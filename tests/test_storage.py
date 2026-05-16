"""
MAPNAI — tests/test_storage.py
Unit tests for storage layers using mocks.
No real MongoDB / FAISS / Neo4j required to run these tests.
Run with: pytest tests/test_storage.py -v
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest
from unittest.mock import MagicMock, patch, PropertyMock
from datetime import datetime, timezone

from utils.models import ProcessedArticle, SourceType, Domain, SentimentLabel


# ── Shared fixture ───────────────────────────────────────────

def make_article(article_id="art-001", domain="finance", title="Test Article"):
    return ProcessedArticle(
        article_id=article_id,
        title=title,
        body="The Federal Reserve raised interest rates by 25 basis points on Wednesday. "
             "The decision was unanimous and markets reacted positively to the announcement.",
        url="https://example.com/article",
        source_name="Reuters",
        source_type=SourceType.RSS,
        domain=Domain(domain),
        published_at=datetime(2026, 4, 19, 10, 0, 0, tzinfo=timezone.utc),
        ingested_at=datetime(2026, 4, 19, 10, 5, 0, tzinfo=timezone.utc),
        language="en",
        dedup_hash="abcd1234abcd1234",
        sentiment_score=0.3,
        sentiment_label=SentimentLabel.POSITIVE,
        keywords=["federal", "reserve", "rates"],
        topic_tags=["Finance", "Interest Rates"],
        entities=[
            {"name": "Federal Reserve", "type": "ORG", "salience": 1.0},
            {"name": "United States",   "type": "GPE", "salience": 0.7},
        ],
    )


# ══════════════════════════════════════════════════════════════
# MongoDB Store Tests (mocked)
# ══════════════════════════════════════════════════════════════

class TestMongoStore:
    @patch("storage.mongo_store.MongoClient")
    def test_upsert_articles_calls_bulk_write(self, mock_client_class):
        """Verify upsert_articles calls bulk_write with correct operations."""
        from storage.mongo_store import MongoStore

        # Mock chain: MongoClient() → db → collection → bulk_write
        mock_client  = MagicMock()
        mock_db      = MagicMock()
        mock_col     = MagicMock()
        mock_result  = MagicMock()

        mock_client_class.return_value = mock_client
        mock_client.__getitem__.return_value = mock_db
        mock_db.__getitem__.return_value = mock_col
        mock_result.upserted_count = 2
        mock_result.modified_count = 0
        mock_col.bulk_write.return_value = mock_result
        mock_client.admin.command.return_value = {"ok": 1}

        store = MongoStore()
        store._client = mock_client
        store._db     = mock_db

        articles = [make_article("a1"), make_article("a2")]
        result = store.upsert_articles(articles)

        mock_col.bulk_write.assert_called_once()
        assert result["inserted"] == 2

    @patch("storage.mongo_store.MongoClient")
    def test_get_existing_hashes_returns_list(self, mock_client_class):
        """Verify get_existing_hashes returns list of hash strings."""
        from storage.mongo_store import MongoStore

        mock_client = MagicMock()
        mock_db     = MagicMock()
        mock_col    = MagicMock()
        mock_client_class.return_value = mock_client
        mock_client.__getitem__.return_value = mock_db
        mock_db.__getitem__.return_value = mock_col

        mock_cursor = iter([
            {"dedup_hash": "hash001"},
            {"dedup_hash": "hash002"},
            {"dedup_hash": "hash003"},
        ])
        mock_col.find.return_value.limit.return_value = mock_cursor

        store = MongoStore()
        store._client = mock_client
        store._db     = mock_db

        hashes = store.get_existing_hashes()
        assert isinstance(hashes, list)
        assert "hash001" in hashes
        assert len(hashes) == 3

    @patch("storage.mongo_store.MongoClient")
    def test_upsert_empty_list_returns_zeros(self, mock_client_class):
        from storage.mongo_store import MongoStore
        store = MongoStore()
        store._client = MagicMock()
        store._db     = MagicMock()
        result = store.upsert_articles([])
        assert result == {"inserted": 0, "updated": 0, "errors": 0}

    def test_to_mongo_dict_serializes_correctly(self):
        """Verify ProcessedArticle.to_mongo_dict() produces correct structure."""
        article = make_article()
        d = article.to_mongo_dict()
        assert d["article_id"] == "art-001"
        assert d["domain"] == "finance"
        assert d["source_type"] == "rss"
        assert d["sentiment_label"] == "positive"
        assert isinstance(d["published_at"], str)
        assert d["published_at"] == "2026-04-19T10:00:00+00:00"


# ══════════════════════════════════════════════════════════════
# FAISS Store Tests
# ══════════════════════════════════════════════════════════════

class TestFAISSStore:
    @patch("storage.faiss_store._get_model")
    @patch("storage.faiss_store._get_faiss")
    def test_add_articles_calls_index_add(self, mock_faiss_fn, mock_model_fn):
        """Verify add_articles calls faiss index.add with correct shape."""
        import numpy as np
        from storage.faiss_store import FAISSStore

        # Mock model
        mock_model = MagicMock()
        mock_model.encode.return_value = np.random.rand(2, 384).astype(np.float32)
        mock_model_fn.return_value = mock_model

        # Mock faiss module
        mock_faiss = MagicMock()
        mock_index = MagicMock()
        mock_index.ntotal = 0
        mock_faiss.IndexFlatIP.return_value = mock_index
        mock_faiss.read_index.side_effect = Exception("no file")
        mock_faiss_fn.return_value = mock_faiss

        store = FAISSStore(index_path="/tmp/test.faiss", metadata_path="/tmp/test.pkl")
        store._index    = mock_index
        store._metadata = []

        articles = [make_article("a1"), make_article("a2")]
        added = store.add_articles(articles)

        mock_index.add.assert_called_once()
        call_args = mock_index.add.call_args[0][0]
        assert call_args.shape == (2, 384)
        assert added == 2

    @patch("storage.faiss_store._get_model")
    @patch("storage.faiss_store._get_faiss")
    def test_add_empty_articles_returns_zero(self, mock_faiss_fn, mock_model_fn):
        import numpy as np
        from storage.faiss_store import FAISSStore

        mock_model = MagicMock()
        mock_model_fn.return_value = mock_model
        mock_faiss = MagicMock()
        mock_faiss_fn.return_value = mock_faiss

        store = FAISSStore(index_path="/tmp/t.faiss", metadata_path="/tmp/t.pkl")
        store._index = MagicMock()
        store._metadata = []

        assert store.add_articles([]) == 0

    @patch("storage.faiss_store._get_model")
    @patch("storage.faiss_store._get_faiss")
    def test_search_returns_sorted_results(self, mock_faiss_fn, mock_model_fn):
        """Verify search returns results ordered by similarity score."""
        import numpy as np
        from storage.faiss_store import FAISSStore

        mock_model = MagicMock()
        mock_model.encode.return_value = np.random.rand(1, 384).astype(np.float32)
        mock_model_fn.return_value = mock_model

        mock_faiss = MagicMock()
        mock_faiss_fn.return_value = mock_faiss

        store = FAISSStore(index_path="/tmp/t2.faiss", metadata_path="/tmp/t2.pkl")

        # Fake pre-built index
        mock_index       = MagicMock()
        mock_index.ntotal = 3
        # Return scores [0.9, 0.7, 0.5] for indices [0, 1, 2]
        mock_index.search.return_value = (
            np.array([[0.9, 0.7, 0.5]]),
            np.array([[0, 1, 2]])
        )
        store._index    = mock_index
        store._metadata = [
            {"faiss_idx": 0, "article_id": "a1", "title": "Fed raises rates",   "domain": "finance"},
            {"faiss_idx": 1, "article_id": "a2", "title": "RBI policy update",  "domain": "finance"},
            {"faiss_idx": 2, "article_id": "a3", "title": "WHO health warning", "domain": "health"},
        ]

        results = store.search("central bank interest rate policy", top_k=3)
        assert len(results) == 3
        assert results[0]["similarity_score"] == pytest.approx(0.9)
        assert results[0]["article_id"] == "a1"

    @patch("storage.faiss_store._get_model")
    @patch("storage.faiss_store._get_faiss")
    def test_search_domain_filter(self, mock_faiss_fn, mock_model_fn):
        """Verify domain_filter correctly excludes non-matching domains."""
        import numpy as np
        from storage.faiss_store import FAISSStore

        mock_model = MagicMock()
        mock_model.encode.return_value = np.random.rand(1, 384).astype(np.float32)
        mock_model_fn.return_value = mock_model
        mock_faiss = MagicMock()
        mock_faiss_fn.return_value = mock_faiss

        store = FAISSStore(index_path="/tmp/t3.faiss", metadata_path="/tmp/t3.pkl")
        mock_index        = MagicMock()
        mock_index.ntotal = 3
        mock_index.search.return_value = (
            np.array([[0.9, 0.8, 0.7]]),
            np.array([[0, 1, 2]])
        )
        store._index    = mock_index
        store._metadata = [
            {"faiss_idx": 0, "article_id": "a1", "domain": "finance"},
            {"faiss_idx": 1, "article_id": "a2", "domain": "health"},
            {"faiss_idx": 2, "article_id": "a3", "domain": "finance"},
        ]

        results = store.search("test query", top_k=5, domain_filter="finance")
        domains = [r["domain"] for r in results]
        assert all(d == "finance" for d in domains)
        assert len(results) == 2


# ══════════════════════════════════════════════════════════════
# Neo4j Store Tests (mocked)
# ══════════════════════════════════════════════════════════════

class TestNeo4jStore:
    @patch("storage.neo4j_store.GraphDatabase")
    def test_upsert_articles_runs_cypher(self, mock_gdb):
        """Verify upsert_articles calls session.run with UNWIND cypher."""
        from storage.neo4j_store import Neo4jStore

        mock_driver  = MagicMock()
        mock_session = MagicMock().__enter__.return_value
        mock_gdb.driver.return_value = mock_driver
        mock_driver.verify_connectivity.return_value = None
        mock_driver.session.return_value.__enter__ = lambda s: mock_session
        mock_driver.session.return_value.__exit__  = MagicMock(return_value=False)

        store = Neo4jStore()
        store._driver = mock_driver

        articles = [make_article("a1"), make_article("a2")]
        count = store.upsert_articles(articles)
        assert count == 2
        mock_session.run.assert_called()

    @patch("storage.neo4j_store.GraphDatabase")
    def test_upsert_entities_skips_articles_without_entities(self, mock_gdb):
        from storage.neo4j_store import Neo4jStore

        mock_driver  = MagicMock()
        mock_session = MagicMock()
        mock_gdb.driver.return_value = mock_driver
        mock_driver.verify_connectivity.return_value = None
        mock_driver.session.return_value.__enter__ = lambda s: mock_session
        mock_driver.session.return_value.__exit__  = MagicMock(return_value=False)

        store = Neo4jStore()
        store._driver = mock_driver

        # Articles with no entities
        article = make_article()
        article.entities = []
        count = store.upsert_entities([article])
        assert count == 0

    def test_to_neo4j_dict_structure(self):
        """Verify to_neo4j_dict() produces correct Neo4j-compatible dict."""
        article = make_article()
        d = article.to_neo4j_dict()
        assert set(d.keys()) == {
            "article_id", "title", "domain", "source_name",
            "published_at", "ingested_at", "url"
        }
        assert d["domain"] == "finance"
        assert d["article_id"] == "art-001"


# ══════════════════════════════════════════════════════════════
# ProcessedArticle model tests
# ══════════════════════════════════════════════════════════════

class TestProcessedArticleModel:
    def test_valid_article_creation(self):
        art = make_article()
        assert art.article_id == "art-001"
        assert art.domain == Domain.FINANCE
        assert art.sentiment_label == SentimentLabel.POSITIVE

    def test_empty_body_raises_validation_error(self):
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            ProcessedArticle(
                title="Title",
                body="",
                source_name="Test",
                source_type=SourceType.RSS,
                domain=Domain.FINANCE,
            )

    def test_auto_generates_article_id(self):
        art = ProcessedArticle(
            title="Test",
            body="Some article body content here.",
            source_name="Test",
            source_type=SourceType.NEWS_API,
            domain=Domain.TECHNOLOGY,
        )
        assert art.article_id is not None
        assert len(art.article_id) == 36   # UUID format

    def test_serialization_roundtrip(self):
        art = make_article()
        d = art.to_mongo_dict()
        # Verify all required fields are present
        required = ["article_id", "title", "body", "source_name", "domain",
                    "ingested_at", "language", "dedup_hash"]
        for field in required:
            assert field in d, f"Missing field: {field}"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
