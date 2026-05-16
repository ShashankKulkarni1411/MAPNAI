"""
MAPNAI — storage/mongo_store.py
MongoDB Storage Layer
Handles all read/write operations to the Articles and ProcessedArticles collections.
Provides:
  - Bulk insert with upsert (idempotent)
  - Existing hash retrieval (for deduplication seeding)
  - Index management
  - Query interface for downstream agents
"""

from typing import List, Optional, Dict, Any
from pymongo import MongoClient, UpdateOne, ASCENDING, DESCENDING
from pymongo.errors import BulkWriteError, ConnectionFailure, ServerSelectionTimeoutError

from config.settings import settings
from utils.models import ProcessedArticle
from utils.logger import logger


class MongoStore:
    """
    MongoDB interface for MAPNAI article storage.
    Collections:
      - articles:           raw articles (pre-processing, kept for audit)
      - processed_articles: enriched, clean articles (primary working set)
      - ingestion_runs:     run stats for monitoring
    """

    def __init__(self, uri: str = None, db_name: str = None):
        self.uri     = uri or settings.mongo_uri
        self.db_name = db_name or settings.mongo_db_name
        self._client: Optional[MongoClient] = None
        self._db = None

    def _connect(self):
        """Lazy connection — connect on first use."""
        if self._client is None:
            try:
                self._client = MongoClient(
                    self.uri,
                    serverSelectionTimeoutMS=5000,
                    connectTimeoutMS=5000,
                )
                self._db = self._client[self.db_name]
                # Verify connection
                self._client.admin.command("ping")
                logger.info(f"[MongoDB] Connected to {self.uri} / {self.db_name}")
                self._ensure_indexes()
            except (ConnectionFailure, ServerSelectionTimeoutError) as e:
                logger.error(f"[MongoDB] Connection failed: {e}")
                self._client = None
                raise

    def _ensure_indexes(self):
        """Create indexes for fast lookups and deduplication queries."""
        col = self._db["processed_articles"]
        col.create_index([("article_id", ASCENDING)], unique=True)
        col.create_index([("dedup_hash", ASCENDING)])
        col.create_index([("domain", ASCENDING)])
        col.create_index([("published_at", DESCENDING)])
        col.create_index([("ingested_at", DESCENDING)])
        col.create_index([("source_name", ASCENDING)])
        col.create_index([("language", ASCENDING)])
        # Text index for full-text search (backup to vector store)
        col.create_index([("title", "text"), ("body", "text")])
        logger.debug("[MongoDB] Indexes verified.")

    @property
    def db(self):
        self._connect()
        return self._db

    # ── Write Operations ─────────────────────────────────────

    def upsert_articles(
        self, articles: List[ProcessedArticle]
    ) -> Dict[str, int]:
        """
        Bulk upsert processed articles.
        Uses article_id as the idempotency key.
        Returns {inserted, updated, errors} counts.
        """
        if not articles:
            return {"inserted": 0, "updated": 0, "errors": 0}

        operations = []
        for article in articles:
            doc = article.to_mongo_dict()
            operations.append(
                UpdateOne(
                    {"article_id": article.article_id},
                    {"$set": doc},
                    upsert=True,
                )
            )

        try:
            result = self.db["processed_articles"].bulk_write(
                operations, ordered=False
            )
            stats = {
                "inserted": result.upserted_count,
                "updated":  result.modified_count,
                "errors":   0,
            }
            logger.info(
                f"[MongoDB] Upserted {stats['inserted']} new + "
                f"{stats['updated']} updated articles."
            )
            return stats
        except BulkWriteError as e:
            error_count = len(e.details.get("writeErrors", []))
            logger.error(f"[MongoDB] BulkWriteError: {error_count} write errors")
            return {"inserted": 0, "updated": 0, "errors": error_count}
        except Exception as e:
            logger.error(f"[MongoDB] Upsert error: {e}")
            return {"inserted": 0, "updated": 0, "errors": len(articles)}

    def log_ingestion_run(self, stats: dict):
        """Store ingestion run statistics for monitoring."""
        try:
            self.db["ingestion_runs"].insert_one(stats)
        except Exception as e:
            logger.warning(f"[MongoDB] Could not log run stats: {e}")

    def update_article_classification(self, article_id: str, classification_data: dict) -> bool:
        """
        Agent 2 (Event Classifier) updates specific classification 
        fields to the processed_articles table.
        """
        try:
            result = self.db["processed_articles"].update_one(
                {"article_id": article_id},
                {"$set": classification_data}
            )
            if result.modified_count > 0:
                logger.debug(f"[MongoDB] Classification updated for article {article_id}")
                return True
            else:
                logger.debug(f"[MongoDB] Article {article_id} not found or data identical")
                return False
        except Exception as e:
            logger.error(f"[MongoDB] Classification update failed for {article_id}: {e}")
            return False

    def update_article_summaries(self, article_id: str, summary_data: dict) -> bool:
        """
        Agent 3 (Summarization) updates specific text summaries
        (`summary_short` and `summary_long`) to the processed_articles table.
        """
        # Ensure we only update permitted fields
        allowed_keys = {"summary_short", "summary_long"}
        filtered_data = {k: v for k, v in summary_data.items() if k in allowed_keys}
        
        if not filtered_data:
            return False

        try:
            result = self.db["processed_articles"].update_one(
                {"article_id": article_id},
                {"$set": filtered_data}
            )
            if result.modified_count > 0:
                logger.debug(f"[MongoDB] Summaries updated for article {article_id}")
                return True
            else:
                logger.debug(f"[MongoDB] Article {article_id} not found or summaries identical")
                return False
        except Exception as e:
            logger.error(f"[MongoDB] Summary update failed for {article_id}: {e}")
            return False

    # ── Read Operations ──────────────────────────────────────

    def get_existing_hashes(self, limit: int = 100_000) -> List[str]:
        """
        Retrieve existing dedup_hash values from DB.
        Used to seed ArticleDeduplicator on startup.
        """
        try:
            cursor = (
                self.db["processed_articles"]
                .find({}, {"dedup_hash": 1, "_id": 0})
                .limit(limit)
            )
            hashes = [doc["dedup_hash"] for doc in cursor if doc.get("dedup_hash")]
            logger.info(f"[MongoDB] Loaded {len(hashes)} existing hashes for deduplication.")
            return hashes
        except Exception as e:
            logger.warning(f"[MongoDB] Could not load existing hashes: {e}")
            return []

    def get_articles_by_domain(
        self,
        domain: str,
        limit: int = 50,
        skip: int = 0,
    ) -> List[Dict]:
        """Retrieve recent articles for a specific domain."""
        try:
            cursor = (
                self.db["processed_articles"]
                .find({"domain": domain}, {"_id": 0, "body": 0})  # exclude large body field
                .sort("published_at", DESCENDING)
                .skip(skip)
                .limit(limit)
            )
            return list(cursor)
        except Exception as e:
            logger.error(f"[MongoDB] get_articles_by_domain error: {e}")
            return []

    def get_article_by_id(self, article_id: str) -> Optional[Dict]:
        """Retrieve full article by article_id."""
        try:
            return self.db["processed_articles"].find_one(
                {"article_id": article_id}, {"_id": 0}
            )
        except Exception as e:
            logger.error(f"[MongoDB] get_article_by_id error: {e}")
            return None

    def get_recent_articles(
        self,
        hours: int = 24,
        domain: str = None,
        limit: int = 100,
    ) -> List[Dict]:
        """Get articles ingested within the last N hours."""
        from datetime import datetime, timedelta, timezone
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
        query: Dict = {"ingested_at": {"$gte": cutoff.isoformat()}}
        if domain:
            query["domain"] = domain
        try:
            cursor = (
                self.db["processed_articles"]
                .find(query, {"_id": 0, "body": 0})
                .sort("ingested_at", DESCENDING)
                .limit(limit)
            )
            return list(cursor)
        except Exception as e:
            logger.error(f"[MongoDB] get_recent_articles error: {e}")
            return []

    def count_articles(self, domain: str = None) -> int:
        """Count total articles, optionally filtered by domain."""
        query = {"domain": domain} if domain else {}
        try:
            return self.db["processed_articles"].count_documents(query)
        except Exception as e:
            logger.error(f"[MongoDB] count_articles error: {e}")
            return 0

    def close(self):
        if self._client:
            self._client.close()
            self._client = None
            logger.debug("[MongoDB] Connection closed.")
