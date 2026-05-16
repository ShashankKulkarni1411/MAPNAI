"""
MAPNAI — agents/ner_agent.py
Agent 1: Named Entity Recognition & Entity Extraction

Reads articles from MongoDB (processed_articles collection written by the
ingestion layer) and writes enriched entities back via MongoStore + Neo4jStore.
All credentials and storage logic come from the ingestion layer modules.
"""

import logging
import time
from datetime import datetime
from typing import Dict, Any, List, Optional, Union

from agents.ner_utils import (
    deduplicate_and_merge_entities,
    extract_entities_fallback,
    SPACY_TO_CUSTOM_MAP,
)
from storage.mongo_store import MongoStore
from storage.neo4j_store import Neo4jStore
from utils.models import ProcessedArticle, Domain, SourceType, SentimentLabel
from utils.logger import logger as mapnai_logger


logger = logging.getLogger(__name__)


def _normalize_domain(domain) -> str:
    if hasattr(domain, "value"):
        return domain.value
    return str(domain) if domain else "general"


def mongo_doc_to_article_input(doc: dict) -> dict:
    """
    Convert a processed_articles MongoDB document (from ingestion) into
    the dict shape expected by NERAgent.process().
    """
    return {
        "article_id": doc["article_id"],
        "title": doc.get("title", ""),
        "body": doc.get("body", ""),
        "domain": _normalize_domain(doc.get("domain", "general")),
        "_mongo_doc": doc,
    }


def mongo_doc_to_processed_article(
    doc: dict,
    entities: List[Dict],
) -> ProcessedArticle:
    """Build a ProcessedArticle for Neo4j upsert from a MongoDB document."""
    domain_val = doc.get("domain", "general")
    source_type_val = doc.get("source_type", "rss")

    published_at = doc.get("published_at")
    if isinstance(published_at, str) and published_at:
        try:
            published_at = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
        except ValueError:
            published_at = None
    elif not isinstance(published_at, datetime):
        published_at = None

    ingested_at = doc.get("ingested_at")
    if isinstance(ingested_at, str) and ingested_at:
        try:
            ingested_at = datetime.fromisoformat(ingested_at.replace("Z", "+00:00"))
        except ValueError:
            ingested_at = datetime.utcnow()
    elif not isinstance(ingested_at, datetime):
        ingested_at = datetime.utcnow()

    sentiment_label_val = doc.get("sentiment_label", "neutral")
    try:
        sentiment_label = SentimentLabel(sentiment_label_val)
    except ValueError:
        sentiment_label = SentimentLabel.NEUTRAL

    return ProcessedArticle(
        article_id=doc["article_id"],
        title=doc.get("title", ""),
        body=doc.get("body", ""),
        url=doc.get("url", ""),
        source_name=doc.get("source_name", "unknown"),
        source_type=SourceType(source_type_val),
        domain=Domain(domain_val),
        raw_source=doc.get("raw_source", ""),
        published_at=published_at,
        ingested_at=ingested_at,
        language=doc.get("language", "en"),
        dedup_hash=doc.get("dedup_hash", ""),
        entities=entities,
        sentiment_score=float(doc.get("sentiment_score", 0.0)),
        sentiment_label=sentiment_label,
        keywords=doc.get("keywords", []),
        topic_tags=doc.get("topic_tags", []),
    )


class NERAgent:
    """
    Agent 1 — NER & entity extraction.

    Typical usage after ingestion:
        agent = NERAgent()
        for doc in mongo.get_articles_pending_ner():
            agent.process(doc)
        agent.close()
    """

    def __init__(
        self,
        mongo_store: Optional[MongoStore] = None,
        neo4j_store: Optional[Neo4jStore] = None,
    ):
        self.mongo = mongo_store or MongoStore()
        self.neo4j = neo4j_store or Neo4jStore()
        self._nlp = None

    def _get_nlp(self):
        """Lazy-load spaCy model (trf preferred, sm fallback)."""
        if self._nlp is None:
            try:
                import spacy
                try:
                    self._nlp = spacy.load("en_core_web_trf")
                    logger.info("[NER Agent] Loaded spaCy model: en_core_web_trf")
                except OSError:
                    logger.warning(
                        "[NER Agent] 'en_core_web_trf' not found. "
                        "Falling back to 'en_core_web_sm'."
                    )
                    self._nlp = spacy.load("en_core_web_sm")
                    logger.info("[NER Agent] Loaded spaCy model: en_core_web_sm")
            except ImportError:
                logger.error("[NER Agent] spaCy is not installed.")
        return self._nlp

    def process(self, article: Union[dict, ProcessedArticle]) -> dict:
        """
        Run NER on one article. Accepts either:
          - A MongoDB document from processed_articles (preferred)
          - A minimal dict with article_id, title, body, domain
          - A ProcessedArticle from the ingestion layer
        """
        if isinstance(article, ProcessedArticle):
            article_input = {
                "article_id": article.article_id,
                "title": article.title,
                "body": article.body,
                "domain": article.domain.value,
                "_mongo_doc": article.model_dump(),
            }
        elif "article_id" in article and "title" in article and "body" in article:
            if "_mongo_doc" not in article:
                article_input = mongo_doc_to_article_input(article)
            else:
                article_input = article
        else:
            article_input = mongo_doc_to_article_input(article)

        required_keys = {"article_id", "title", "body", "domain"}
        missing = required_keys - set(article_input.keys())
        if missing:
            raise ValueError(f"[NER Agent] Article missing required keys: {missing}")

        start_time = time.time()
        article_id = article_input["article_id"]
        domain_str = _normalize_domain(article_input["domain"])
        text = f"{article_input['title']}\n\n{article_input['body']}"

        if not text.strip():
            logger.warning(f"[NER Agent] Empty text for article {article_id[:8]}. Skipping.")
            return self._build_output(article_id, [], "none", time.time() - start_time)

        raw_entities, model_used = self._extract(text)
        processed_entities = deduplicate_and_merge_entities(
            raw_entities, len(text), domain_str
        )
        latency = time.time() - start_time
        metadata = {
            "model_used": model_used,
            "latency_seconds": round(latency, 3),
            "entity_count": len(processed_entities),
        }

        self._persist(article_input, processed_entities, metadata)

        mapnai_logger.info(
            f"[NER Agent] {article_id[:8]} | "
            f"Entities: {len(processed_entities)} | "
            f"Model: {model_used} | "
            f"Latency: {latency:.2f}s"
        )

        return self._build_output(article_id, processed_entities, model_used, latency)

    def process_batch(
        self,
        articles: List[Union[dict, ProcessedArticle]],
    ) -> List[dict]:
        """Process multiple articles; returns list of NER output contracts."""
        results = []
        for article in articles:
            try:
                results.append(self.process(article))
            except Exception as e:
                aid = article.get("article_id", "?") if isinstance(article, dict) else getattr(article, "article_id", "?")
                logger.error(f"[NER Agent] Failed on {aid}: {e}")
        return results

    def _extract(self, text: str):
        nlp = self._get_nlp()
        if nlp is None:
            logger.warning("[NER Agent] Primary spaCy load failed. Using ner_utils fallback.")
            return extract_entities_fallback(text), "spacy-fallback"

        try:
            doc = nlp(text[:100_000])
            raw_entities = []
            for ent in doc.ents:
                mapped_type = SPACY_TO_CUSTOM_MAP.get(ent.label_)
                if mapped_type:
                    raw_entities.append({
                        "text": ent.text,
                        "label": mapped_type,
                        "start": ent.start_char,
                        "end": ent.end_char,
                        "score": 1.0,
                    })
            model_name = nlp.meta.get("name", "spacy")
            return raw_entities, model_name
        except Exception as e:
            logger.error(f"[NER Agent] spaCy inference error: {e}. Trying fallback.")
            return extract_entities_fallback(text), "spacy-fallback"

    def _persist(
        self,
        article_input: dict,
        entities: List[Dict],
        metadata: Dict,
    ) -> None:
        article_id = article_input["article_id"]
        mongo_doc = article_input.get("_mongo_doc") or article_input

        self.mongo.update_ner_results(article_id, entities, metadata)

        try:
            processed = mongo_doc_to_processed_article(mongo_doc, entities)
            self.neo4j.upsert_articles([processed])
            self.neo4j.upsert_entities([processed])
        except Exception as e:
            logger.error(f"[NER Agent] Neo4j persist failed for {article_id[:8]}: {e}")

    @staticmethod
    def _build_output(
        article_id: str,
        entities: List[Dict],
        model_used: str,
        latency: float,
    ) -> Dict:
        return {
            "article_id": article_id,
            "entities": entities,
            "_metadata": {
                "model_used": model_used,
                "latency_seconds": round(latency, 3),
                "entity_count": len(entities),
            },
        }

    def close(self):
        self.neo4j.close()
        self.mongo.close()
        logger.debug("[NER Agent] Storage connections closed.")

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass
