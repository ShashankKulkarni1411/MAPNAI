"""
MAPNAI — agents/neo4j_writer.py
Backward-compatible wrapper around storage.neo4j_store.Neo4jStore.

The ingestion layer owns Neo4j connectivity and schema. Agent 1 should use
NERAgent (which calls Neo4jStore directly). This module remains for imports
that expect Neo4jWriter.
"""

import logging
from typing import List, Dict, Any

from storage.neo4j_store import Neo4jStore
from agents.ner_agent import mongo_doc_to_processed_article


class Neo4jWriter:
    """Delegates entity upserts to the ingestion layer Neo4jStore."""

    def __init__(self, uri: str = None, user: str = None, password: str = None):
        self._store = Neo4jStore(uri=uri, user=user, password=password)

    def upsert_entities(self, article_id: str, entities: List[Dict[str, Any]]) -> int:
        if not entities:
            return 0

        doc = {"article_id": article_id, "domain": entities[0].get("domain", "general")}
        processed = mongo_doc_to_processed_article(doc, entities)
        self._store.upsert_articles([processed])
        return self._store.upsert_entities([processed])

    def close(self):
        self._store.close()
        logging.debug("[Neo4j Writer] Connection closed (via Neo4jStore).")
