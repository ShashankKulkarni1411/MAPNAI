"""
MAPNAI — storage/neo4j_store.py
Neo4j Knowledge Graph Storage Layer
Stores articles as nodes, entities as nodes, and relationships between them.
GraphRAG (Edge et al. 2024) queries this graph for global/thematic sensemaking.

Node types:
  (:Article)  — article metadata
  (:Entity)   — named entities (ORG, GPE, PERSON, PRODUCT, EVENT)
  (:Domain)   — domain classification node

Relationship types:
  (Article)-[:BELONGS_TO]->(Domain)
  (Article)-[:MENTIONS {salience}]->(Entity)
  (Entity)-[:MENTIONED_WITH {count}]->(Entity)    ← co-occurrence graph
  (Article)-[:PUBLISHED_BY]->(Source)
"""

from typing import List, Dict, Optional
from neo4j import GraphDatabase, Driver
from neo4j.exceptions import ServiceUnavailable, AuthError

from config.settings import settings
from utils.models import ProcessedArticle
from utils.logger import logger


class Neo4jStore:
    """
    Neo4j interface for MAPNAI knowledge graph.
    Uses bolt:// protocol with native driver.
    Batches writes for efficiency using UNWIND Cypher.
    """

    def __init__(
        self,
        uri: str = None,
        user: str = None,
        password: str = None,
    ):
        self.uri      = uri or settings.neo4j_uri
        self.user     = user or settings.neo4j_user
        self.password = password or settings.neo4j_password
        self._driver: Optional[Driver] = None

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
                logger.info(f"[Neo4j] Connected to {self.uri}")
                self._ensure_constraints()
            except ServiceUnavailable as e:
                logger.error(f"[Neo4j] Service unavailable: {e}")
                self._driver = None
                raise
            except AuthError as e:
                logger.error(f"[Neo4j] Auth error: {e}")
                self._driver = None
                raise

    def _ensure_constraints(self):
        """Create uniqueness constraints and indexes."""
        constraints = [
            "CREATE CONSTRAINT article_id IF NOT EXISTS FOR (a:Article) REQUIRE a.article_id IS UNIQUE",
            "CREATE CONSTRAINT entity_key IF NOT EXISTS FOR (e:Entity) REQUIRE (e.name, e.type) IS NODE KEY",
            "CREATE CONSTRAINT domain_name IF NOT EXISTS FOR (d:Domain) REQUIRE d.name IS UNIQUE",
            "CREATE CONSTRAINT source_name IF NOT EXISTS FOR (s:Source) REQUIRE s.name IS UNIQUE",
        ]
        with self._driver.session() as session:
            for constraint in constraints:
                try:
                    session.run(constraint)
                except Exception as e:
                    logger.debug(f"[Neo4j] Constraint (may already exist): {e}")
        logger.debug("[Neo4j] Constraints verified.")

    @property
    def driver(self) -> Driver:
        self._connect()
        return self._driver

    # ── Write Operations ─────────────────────────────────────

    def upsert_articles(self, articles: List[ProcessedArticle]) -> int:
        """
        Upsert articles into Neo4j as :Article nodes.
        Creates/merges :Domain and :Source nodes.
        Returns number of articles processed.
        """
        if not articles:
            return 0

        article_dicts = [a.to_neo4j_dict() for a in articles]

        cypher = """
        UNWIND $articles AS data
        MERGE (a:Article {article_id: data.article_id})
        SET
            a.title       = data.title,
            a.domain      = data.domain,
            a.source_name = data.source_name,
            a.published_at= data.published_at,
            a.ingested_at = data.ingested_at,
            a.url         = data.url

        MERGE (d:Domain {name: data.domain})
        MERGE (a)-[:BELONGS_TO]->(d)

        MERGE (s:Source {name: data.source_name})
        MERGE (a)-[:PUBLISHED_BY]->(s)
        """

        try:
            with self.driver.session() as session:
                session.run(cypher, articles=article_dicts)
            logger.info(f"[Neo4j] Upserted {len(articles)} article nodes.")
            return len(articles)
        except Exception as e:
            logger.error(f"[Neo4j] Article upsert error: {e}")
            return 0

    def upsert_entities(self, articles: List[ProcessedArticle]) -> int:
        """
        Create :Entity nodes and (Article)-[:MENTIONS]->(Entity) edges.
        Also builds co-occurrence (Entity)-[:MENTIONED_WITH]->(Entity) edges.
        """
        if not articles:
            return 0

        mention_records = []
        for article in articles:
            if not article.entities:
                continue
            for entity in article.entities:
                mention_records.append({
                    "article_id": article.article_id,
                    "entity_name": entity.get("name", ""),
                    "entity_type": entity.get("type", "MISC"),
                    "salience":    float(entity.get("salience", 0.0)),
                })

        if not mention_records:
            return 0

        # ── Create entity nodes and MENTIONS edges ────────────
        mentions_cypher = """
        UNWIND $mentions AS m
        MERGE (e:Entity {name: m.entity_name, type: m.entity_type})
        ON CREATE SET e.first_seen = timestamp(), e.frequency = 1
        ON MATCH  SET e.frequency  = e.frequency + 1,
                      e.last_seen  = timestamp()

        WITH e, m
        MATCH (a:Article {article_id: m.article_id})
        MERGE (a)-[r:MENTIONS]->(e)
        SET r.salience = m.salience
        """

        try:
            with self.driver.session() as session:
                session.run(mentions_cypher, mentions=mention_records)
        except Exception as e:
            logger.error(f"[Neo4j] Entity upsert error: {e}")
            return 0

        # ── Build co-occurrence edges (entities in same article) ──
        self._build_cooccurrence(articles)

        logger.info(
            f"[Neo4j] Upserted entities for {len([a for a in articles if a.entities])} articles."
        )
        return len(mention_records)

    def _build_cooccurrence(self, articles: List[ProcessedArticle]):
        """
        For each article, create MENTIONED_WITH edges between all entity pairs.
        This is the foundation of the entity co-occurrence graph used by GraphRAG.
        """
        cooccurrence_records = []
        for article in articles:
            entities = article.entities
            if len(entities) < 2:
                continue
            # All pairs in this article
            names_types = [(e["name"], e["type"]) for e in entities]
            for i in range(len(names_types)):
                for j in range(i + 1, len(names_types)):
                    cooccurrence_records.append({
                        "name_a": names_types[i][0],
                        "type_a": names_types[i][1],
                        "name_b": names_types[j][0],
                        "type_b": names_types[j][1],
                        "article_id": article.article_id,
                    })

        if not cooccurrence_records:
            return

        # Limit to avoid Cartesian explosion on entity-dense articles
        cooccurrence_records = cooccurrence_records[:5000]

        cooccurrence_cypher = """
        UNWIND $pairs AS p
        MATCH (ea:Entity {name: p.name_a, type: p.type_a})
        MATCH (eb:Entity {name: p.name_b, type: p.type_b})
        MERGE (ea)-[r:MENTIONED_WITH]-(eb)
        ON CREATE SET r.count = 1, r.article_ids = [p.article_id]
        ON MATCH  SET r.count      = r.count + 1,
                      r.article_ids = r.article_ids + p.article_id
        """

        try:
            with self.driver.session() as session:
                # Batch in chunks of 500 to avoid memory pressure
                batch_size = 500
                for i in range(0, len(cooccurrence_records), batch_size):
                    batch = cooccurrence_records[i:i + batch_size]
                    session.run(cooccurrence_cypher, pairs=batch)
        except Exception as e:
            logger.warning(f"[Neo4j] Co-occurrence build error: {e}")

    # ── Read Operations ──────────────────────────────────────

    def get_entity_neighbors(
        self, entity_name: str, depth: int = 2, limit: int = 20
    ) -> List[Dict]:
        """
        Get entities connected to a given entity name.
        Used by GraphRAG for neighborhood context.
        """
        cypher = """
        MATCH (e:Entity {name: $name})-[r:MENTIONED_WITH*1..{depth}]-(neighbor:Entity)
        RETURN neighbor.name AS name, neighbor.type AS type, neighbor.frequency AS frequency
        ORDER BY frequency DESC
        LIMIT $limit
        """.replace("{depth}", str(depth))

        try:
            with self.driver.session() as session:
                result = session.run(cypher, name=entity_name, limit=limit)
                return [dict(record) for record in result]
        except Exception as e:
            logger.error(f"[Neo4j] get_entity_neighbors error: {e}")
            return []

    def get_articles_by_entity(self, entity_name: str, limit: int = 20) -> List[Dict]:
        """Get all articles that mention a specific entity."""
        cypher = """
        MATCH (a:Article)-[:MENTIONS]->(e:Entity {name: $name})
        RETURN a.article_id AS article_id, a.title AS title,
               a.domain AS domain, a.published_at AS published_at, a.url AS url
        ORDER BY a.published_at DESC
        LIMIT $limit
        """
        try:
            with self.driver.session() as session:
                result = session.run(cypher, name=entity_name, limit=limit)
                return [dict(record) for record in result]
        except Exception as e:
            logger.error(f"[Neo4j] get_articles_by_entity error: {e}")
            return []

    def get_top_entities(self, domain: str = None, limit: int = 20) -> List[Dict]:
        """Get most frequently mentioned entities, optionally filtered by domain."""
        if domain:
            cypher = """
            MATCH (a:Article)-[:BELONGS_TO]->(d:Domain {name: $domain})
            MATCH (a)-[:MENTIONS]->(e:Entity)
            RETURN e.name AS name, e.type AS type, COUNT(*) AS mention_count
            ORDER BY mention_count DESC
            LIMIT $limit
            """
            params = {"domain": domain, "limit": limit}
        else:
            cypher = """
            MATCH (e:Entity)
            RETURN e.name AS name, e.type AS type, e.frequency AS mention_count
            ORDER BY mention_count DESC
            LIMIT $limit
            """
            params = {"limit": limit}

        try:
            with self.driver.session() as session:
                result = session.run(cypher, **params)
                return [dict(record) for record in result]
        except Exception as e:
            logger.error(f"[Neo4j] get_top_entities error: {e}")
            return []

    def get_graph_stats(self) -> Dict:
        """Return basic stats about the knowledge graph."""
        cypher = """
        MATCH (a:Article) WITH count(a) AS articles
        MATCH (e:Entity)  WITH articles, count(e) AS entities
        MATCH ()-[r:MENTIONS]->() WITH articles, entities, count(r) AS mention_rels
        MATCH ()-[c:MENTIONED_WITH]-() WITH articles, entities, mention_rels, count(c)/2 AS cooccurrence_rels
        RETURN articles, entities, mention_rels, cooccurrence_rels
        """
        try:
            with self.driver.session() as session:
                result = session.run(cypher)
                record = result.single()
                return dict(record) if record else {}
        except Exception as e:
            logger.error(f"[Neo4j] get_graph_stats error: {e}")
            return {}

    def close(self):
        if self._driver:
            self._driver.close()
            self._driver = None
            logger.debug("[Neo4j] Connection closed.")
