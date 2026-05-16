"""
MAPNAI — agents/ner_agent.py
Agent 1: Named Entity Recognition & Entity Extraction
Uses GLiNER (zero-shot) with spaCy fallback to extract 8 specific entity types.
Wraps as an AutoGen ConversableAgent.
Reads/writes using PostgreSQL and upserts to Neo4j.
"""

import os
import json
import time
import logging
from typing import Dict, Any, List, Tuple

import psycopg2
from psycopg2.extras import Json

from agents.ner_utils import (
    ENTITY_TYPES, 
    deduplicate_and_merge_entities, 
    extract_entities_fallback
)
from agents.neo4j_writer import Neo4jWriter

# GLiNER Thresholds
GLINER_CONFIDENCE_THRESHOLD = 0.5

class NERAgent:
    def __init__(self, db_url: str = None):
        self.db_url = db_url or os.getenv("POSTGRES_URL", "postgresql://user:password@localhost:5432/mapnai")
        self.neo4j_writer = Neo4jWriter()
        self._gliner_model = None

    def _get_gliner(self):
        """Lazy load GLiNER model to save memory if unused."""
        if self._gliner_model is None:
            try:
                from gliner import GLiNER
                # Load the standard model; this downloads weights on first run
                self._gliner_model = GLiNER.from_pretrained("urchade/gliner_medium-v2.1")
            except ImportError:
                logging.error("[NER Agent] GLiNER not installed. Will use fallback exclusively.")
        return self._gliner_model

    def process(self, article: dict) -> dict:
        """
        Main handler for incoming messages.
        Expects a dictionary containing article data.
        """
        required_keys = {"article_id", "title", "body", "domain"}
        if not required_keys.issubset(article.keys()):
            raise ValueError(f"Article missing required keys: {required_keys - set(article.keys())}")
            
        try:
            start_time = time.time()
            
            # Combine title and body
            text = f"{article['title']}\n\n{article['body']}"
            domain = article["domain"]
            article_id = article["article_id"]
            
            # Edge case: empty body
            if not text.strip():
                final_output = self._finalize_output(article_id, [], "none", time.time() - start_time)
                return final_output
                
            entities, model_used = self._extract_entities(text)
            
            # Deduplicate, score salience, stamp domain
            processed_entities = deduplicate_and_merge_entities(entities, len(text), domain)
            
            latency = time.time() - start_time
            
            # Write to databases
            self._write_to_postgres(article_id, processed_entities)
            self.neo4j_writer.upsert_entities(article_id, processed_entities)
            
            # Log stats
            logging.info(
                f"[NER Agent] Processed {article_id[:8]} | "
                f"Entities: {len(processed_entities)} | Model: {model_used} | Latency: {latency:.2f}s"
            )
            
            final_output = self._finalize_output(article_id, processed_entities, model_used, latency)
            return final_output
            
        except Exception as e:
            logging.error(f"[NER Agent] Error processing message: {e}")
            raise

    def _extract_entities(self, text: str) -> Tuple[List[Dict], str]:
        """Runs GLiNER and falls back to spaCy if needed."""
        gliner = self._get_gliner()
        if gliner:
            try:
                # Truncate text to avoid context window issues
                # GLiNER handles moderate length, but we should be safe
                truncated_text = text[:10000]
                
                # Zero-shot extraction using the 8 requested types
                predictions = gliner.predict_entities(
                    truncated_text, 
                    list(ENTITY_TYPES), 
                    flat_ner=True, 
                    threshold=GLINER_CONFIDENCE_THRESHOLD
                )
                
                if predictions:
                    return predictions, "GLiNER"
            except Exception as e:
                logging.warning(f"[NER Agent] GLiNER extraction failed: {e}")
                
        # Fallback to spaCy
        fallback_entities = extract_entities_fallback(text)
        return fallback_entities, "spaCy"

    def _finalize_output(self, article_id: str, entities: List[Dict], model_used: str, latency: float) -> Dict:
        """Formats the final JSON contract."""
        # Note: metadata is added here for logging/debugging, 
        # but the required contract format is maintained at the root.
        return {
            "article_id": article_id,
            "entities": entities,
            "_metadata": {
                "model_used": model_used,
                "latency_seconds": round(latency, 2),
                "entity_count": len(entities)
            }
        }

    def _write_to_postgres(self, article_id: str, entities: List[Dict]):
        """
        Updates the processed_articles table in PostgreSQL.
        Sets the entities JSONB field.
        """
        try:
            conn = psycopg2.connect(self.db_url)
            cursor = conn.cursor()
            
            # Upsert into processed_articles. If it already exists, update entities.
            # Assuming schema has article_id as primary key/unique constraint.
            query = """
                INSERT INTO processed_articles (article_id, entities)
                VALUES (%s, %s)
                ON CONFLICT (article_id) 
                DO UPDATE SET entities = EXCLUDED.entities;
            """
            cursor.execute(query, (article_id, Json(entities)))
            conn.commit()
            
            cursor.close()
            conn.close()
        except psycopg2.Error as e:
            logging.error(f"[NER Agent] PostgreSQL write failed for {article_id}: {e}")

    def __del__(self):
        if hasattr(self, 'neo4j_writer'):
            self.neo4j_writer.close()
