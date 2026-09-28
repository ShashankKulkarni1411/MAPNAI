"""
MAPNAI — agents/ner_agent.py
Agent 1: Named Entity Recognition & Entity Extraction

Uses fine-tuned BERT model (models/mapnai-ner-bert) to extract entities.

Reads/writes using MongoDB (primary store) and upserts to Neo4j.
All credentials come from config.settings (loaded from .env).
"""

import logging
import os
import time
from typing import Dict, Any, List

from transformers import AutoTokenizer, pipeline

from agents.ner_utils import deduplicate_and_merge_entities
from agents.neo4j_writer import Neo4jWriter
from storage.mongo_store import MongoStore


logger = logging.getLogger(__name__)

LABEL_MAP = {
    "PER": "Person",
    "ORG": "Organization",
    "LOC": "Location",
    "MISC": "Product"
}


class NERAgent:
    """
    Standalone NER Agent.
    Call  agent.process(article_dict) → returns the NER output contract dict.

    Expected article dict keys:
        article_id  (str)
        title       (str)
        body        (str)
        domain      (str)  — e.g. "finance", "geopolitics"
    """

    def __init__(self, model_path: str = "models/mapnai-ner-bert", mongo_store=None):
        self.mongo_store = mongo_store or MongoStore()
        self._owns_mongo_store = mongo_store is None

        # ── Neo4j ────────────────────────────────────────────
        self.neo4j_writer = Neo4jWriter()

        # ── BERT Pipeline ────────────────────────────────────
        resolved_path = model_path
        if not os.path.exists(resolved_path):
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            alt_path = os.path.join(base_dir, model_path)
            if os.path.exists(alt_path):
                resolved_path = alt_path

        logger.info(f"[NER Agent] Loading fine-tuned BERT model from: {resolved_path}")
        self.ner_pipeline = None
        try:
            tokenizer = AutoTokenizer.from_pretrained(resolved_path)
            # Some saved tokenizers report a huge default max length, which disables chunking
            if tokenizer.model_max_length > 512:
                tokenizer.model_max_length = 512
            self.ner_pipeline = pipeline(
                "token-classification",
                model=resolved_path,
                tokenizer=tokenizer,
                aggregation_strategy="first",
                stride=128,   # chunk long articles instead of truncating at 512 tokens
            )
            logger.info(f"[NER Agent] Loaded BERT model: {resolved_path}")
        except Exception as e:
            logger.warning(
                f"[NER Agent] Fine-tuned BERT not loaded from '{resolved_path}' ({e}). "
                "Falling back to spaCy entities from ingestion — place the model in "
                "models/mapnai-ner-bert to use it."
            )

    # ── Public API ───────────────────────────────────────────

    def process(self, article: dict) -> dict:
        """
        Main entry point.  Accepts an article dict, returns the NER contract:

            {
                "article_id": str,
                "entities":   [ { name, type, domain, salience, mention_count } ],
                "_metadata":  { model_used, latency_seconds, entity_count }
            }
        """
        required_keys = {"article_id", "title", "body", "domain"}
        missing = required_keys - set(article.keys())
        if missing:
            raise ValueError(f"[NER Agent] Article missing required keys: {missing}")

        start_time = time.time()
        article_id = article["article_id"]
        domain = article["domain"]
        # Accept Domain enum or plain string
        domain_str = domain.value if hasattr(domain, "value") else str(domain)
        text = f"{article['title']}\n\n{article['body']}"

        # ── Edge case: empty text ────────────────────────────
        if not text.strip():
            logger.warning(f"[NER Agent] Empty text for article {article_id[:8]}. Skipping.")
            return self._build_output(article_id, [], "none", time.time() - start_time)

        # ── Entity extraction ────────────────────────────────
        if self.ner_pipeline is None:
            processed_entities = article.get("entities", [])
            model_used = "ingestion-enrichment-fallback"
        else:
            raw_entities, model_used = self._extract(text)
            if raw_entities:
                processed_entities = deduplicate_and_merge_entities(
                    raw_entities, len(text), domain_str
                )
            else:
                processed_entities = article.get("entities", [])
                model_used = "ingestion-enrichment-fallback"

        # Ingestion (spaCy) entities carry only name/type/salience; the NER contract and
        # the Neo4j writer also need each entity's domain.
        processed_entities = [{**e, "domain": e.get("domain", domain_str)} for e in processed_entities]

        latency = time.time() - start_time

        # ── Persist ──────────────────────────────────────────
        self._write_to_mongo(article_id, processed_entities, model_used)
        upserted = self.neo4j_writer.upsert_entities(article_id, processed_entities)

        logger.info(
            f"[NER Agent] {article_id[:8]} | "
            f"Entities: {len(processed_entities)} | "
            f"Neo4j upserted: {upserted} | "
            f"Model: {model_used} | "
            f"Latency: {latency:.2f}s"
        )

        return self._build_output(article_id, processed_entities, model_used, latency)

    # ── Internal helpers ─────────────────────────────────────

    def _extract(self, text: str):
        """
        Run fine-tuned BERT NER pipeline.

        Returns (raw_entities: list[dict], model_used: str).
        """
        model_used = "BERT-finetuned"
        try:
            raw_output = self.ner_pipeline(text)
            raw_entities = []
            for ent in raw_output:
                group = ent.get("entity_group") or ent.get("entity") or ""
                clean_group = group.replace("B-", "").replace("I-", "")
                mapped_type = LABEL_MAP.get(clean_group, LABEL_MAP.get(group))
                if mapped_type:
                    raw_entities.append({
                        "text": ent.get("word", "").strip(),
                        "label": mapped_type,
                        "start": ent.get("start", 0),
                        "end": ent.get("end", 0),
                        "score": float(ent.get("score", 1.0)),
                    })
            return raw_entities, model_used
        except Exception as e:
            logger.error(f"[NER Agent] BERT inference error: {e}")
            return [], model_used

    def _write_to_mongo(self, article_id: str, entities: List[Dict], model_used: str) -> None:
        """
        Sets the entities field on the processed_articles document, recording which
        model produced them (BERT vs the spaCy ingestion fallback).
        """
        self.mongo_store.update_ner_results(
            article_id, entities, metadata={"model_used": model_used}
        )

    @staticmethod
    def _build_output(
        article_id: str,
        entities: List[Dict],
        model_used: str,
        latency: float,
    ) -> Dict:
        """Constructs the standard NER output contract."""
        return {
            "article_id": article_id,
            "entities": entities,
            "_metadata": {
                "model_used": model_used,
                "latency_seconds": round(latency, 3),
                "entity_count": len(entities),
            },
        }

    # ── Cleanup ──────────────────────────────────────────────

    def close(self):
        """Release all external connections."""
        self.neo4j_writer.close()
        if self._owns_mongo_store:
            self.mongo_store.close()

    def __del__(self):
        # Best-effort cleanup — avoid raising inside __del__
        try:
            self.close()
        except Exception:
            pass
