"""
MAPNAI — agents/neo4j_writer.py
Writer module for the NER & Entity Extraction Agent to upsert entity nodes to Neo4j.
"""

import logging
from typing import List, Dict, Any
from neo4j import GraphDatabase, Driver
from neo4j.exceptions import ServiceUnavailable, AuthError

from config.settings import settings

class Neo4jWriter:
    """
    Dedicated Neo4j writer for Agent 1.
    Upserts entities with schema: Entity(name, type, domain, article_ids[], frequency, last_seen)
    """

    def __init__(self, uri: str = None, user: str = None, password: str = None):
        self.uri = uri or settings.neo4j_uri
        self.user = user or settings.neo4j_user
        self.password = password or settings.neo4j_password
        self._driver = None

    def _connect(self):
        """Lazy connection to Neo4j."""
        if self._driver is None:
            try:
                self._driver = GraphDatabase.driver(
                    self.uri,
                    auth=(self.user, self.password),
                    connection_timeout=10,
                )
                self._driver.verify_connectivity()
                logging.info(f"[Neo4j Writer] Connected to {self.uri}")
                self._ensure_constraints()
            except (ServiceUnavailable, AuthError) as e:
                logging.error(f"[Neo4j Writer] Connection failed: {e}")
                self._driver = None
                raise

    def _ensure_constraints(self):
        """Ensure entity key constraints exist."""
        constraints = [
            "CREATE CONSTRAINT entity_key IF NOT EXISTS FOR (e:Entity) REQUIRE (e.name, e.type) IS NODE KEY",
        ]
        with self._driver.session() as session:
            for constraint in constraints:
                try:
                    session.run(constraint)
                except Exception as e:
                    logging.debug(f"[Neo4j Writer] Constraint issue (may already exist): {e}")

    @property
    def driver(self) -> Driver:
        self._connect()
        return self._driver

    def upsert_entities(self, article_id: str, entities: List[Dict[str, Any]]) -> int:
        """
        Upsert entities for a specific article.
        entities format: [{"name": "RBI", "type": "Organization", "domain": "finance", "mention_count": 4, ...}]
        """
        if not entities:
            return 0

        entity_records = []
        for ent in entities:
            entity_records.append({
                "name": ent["name"],
                "type": ent["type"],
                "domain": ent["domain"],
                "article_id": article_id,
                "mention_count": ent.get("mention_count", 1)
            })

        cypher = """
        UNWIND $entities AS e
        MERGE (node:Entity {name: e.name, type: e.type})
        ON CREATE SET 
            node.domain = e.domain,
            node.article_ids = [e.article_id],
            node.frequency = e.mention_count,
            node.last_seen = timestamp()
        ON MATCH SET 
            node.frequency = coalesce(node.frequency, 0) + e.mention_count,
            node.last_seen = timestamp(),
            node.domain = coalesce(node.domain, e.domain),
            node.article_ids = CASE 
                WHEN NOT e.article_id IN node.article_ids 
                THEN node.article_ids + [e.article_id] 
                ELSE node.article_ids 
            END
        """

        try:
            with self.driver.session() as session:
                session.run(cypher, entities=entity_records)
            return len(entity_records)
        except Exception as e:
            logging.error(f"[Neo4j Writer] Upsert failed for article {article_id}: {e}")
            return 0

    def close(self):
        if self._driver:
            self._driver.close()
            self._driver = None
            logging.debug("[Neo4j Writer] Connection closed.")
