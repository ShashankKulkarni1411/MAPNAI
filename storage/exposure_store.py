"""
MAPNAI — storage/exposure_store.py
Neo4j storage for user exposures:
  (:User {user_id, name, created_at})
    -[:EXPOSED_TO {role, weight:int 1..3, weight_label, provenance, valid_from, updated_at, proposal_id?}]->(:Entity)

Entities are addressed by their canonical key `name_lower` (PERSONALIZATION_PLAN.md C1). An exposure links
the user to every (name, type) variant with that key; unknown keys are never created here.
`name_lower` is an additive property filled by sync_name_lower(); until a node has it, queries fall back
to toLower(trim(name)).
Reuses the lazy driver of the existing Neo4jStore.
"""

import re
from typing import Dict, List, Optional

from config.personalization import pers_settings
from personalization.keys import entity_key
from storage.neo4j_store import Neo4jStore
from utils.logger import logger

_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _ident(name: str) -> str:
    """Labels/relationship types can't be Cypher parameters — only allow plain identifiers."""
    if not _IDENT.match(name):
        raise ValueError(f"Invalid Neo4j identifier in config: {name!r}")
    return name


class ExposureStore:
    def __init__(self, neo4j: Optional[Neo4jStore] = None, cfg=None):
        self.neo4j = neo4j or Neo4jStore()
        self.cfg = cfg or pers_settings
        self._user = _ident(self.cfg.user_label)
        self._entity = _ident(self.cfg.entity_label)
        self._rel = _ident(self.cfg.exposure_rel)
        self._name = _ident(self.cfg.entity_name_prop)
        # canonical key of node `e`, with the fallback for nodes sync_name_lower hasn't reached yet
        self._key = f"coalesce(e.name_lower, toLower(trim(e.{self._name})))"
        # v1 created :Entity nodes from free-text exposures; they were never ingested, so they aren't linkable
        self._ingested = "coalesce(e.created_by, '') <> 'user_exposure'"
        self._schema_ok = False

    def _session(self):
        if not self._schema_ok:
            self._schema_ok = True
            self.ensure_schema()
        return self.neo4j.driver.session()

    def ensure_schema(self) -> None:
        """User constraint, name_lower index, then fill name_lower / migrate v1 edges (idempotent)."""
        statements = [
            f"CREATE CONSTRAINT user_id IF NOT EXISTS FOR (u:{self._user}) REQUIRE u.user_id IS UNIQUE",
            f"CREATE INDEX entity_name_lower IF NOT EXISTS FOR (e:{self._entity}) ON (e.name_lower)",
        ]
        with self.neo4j.driver.session() as session:
            for cypher in statements:
                try:
                    session.run(cypher)
                except Exception as e:
                    logger.debug(f"[Exposures] Schema (may already exist): {e}")
        self.sync_name_lower()

    def sync_name_lower(self) -> int:
        """
        Set name_lower on entities that lack it (or whose name changed), and migrate v1 EXPOSED_TO edges
        (weight stored as a label string, no provenance). Returns the number of entities updated.
        """
        with self.neo4j.driver.session() as session:
            rows = session.run(
                f"MATCH (e:{self._entity}) RETURN elementId(e) AS id, e.{self._name} AS name, "
                f"e.name_lower AS current"
            ).data()
            updates = [
                {"id": r["id"], "key": entity_key(r["name"])}
                for r in rows
                if r["name"] is not None and r["current"] != entity_key(r["name"])
            ]
            for i in range(0, len(updates), 1000):
                session.run(
                    f"UNWIND $rows AS row MATCH (e:{self._entity}) WHERE elementId(e) = row.id "
                    f"SET e.name_lower = row.key",
                    rows=updates[i:i + 1000],
                )
            migrated = session.run(
                f"""
                MATCH (:{self._user})-[r:{self._rel}]->(:{self._entity})
                WHERE r.weight IS :: STRING OR r.provenance IS NULL
                WITH r, CASE WHEN r.weight IS :: STRING THEN r.weight ELSE r.weight_label END AS label
                SET r.weight_label = label,
                    r.weight = coalesce($levels[label], r.weight),
                    r.provenance = coalesce(r.provenance, 'declared'),
                    r.valid_from = coalesce(r.valid_from, r.updated_at)
                RETURN count(r) AS c
                """,
                levels=self.cfg.weight_levels,
            ).single()["c"]
        if updates or migrated:
            logger.info(f"[Exposures] name_lower set on {len(updates)} entities; {migrated} v1 edges migrated")
        return len(updates)

    # ── Users ────────────────────────────────────────────────

    def upsert_user(self, user_id: str, name: str) -> None:
        cypher = f"""
        MERGE (u:{self._user} {{user_id: $user_id}})
        ON CREATE SET u.created_at = timestamp()
        SET u.name = $name
        """
        with self._session() as session:
            session.run(cypher, user_id=user_id, name=name)

    def delete_user(self, user_id: str) -> None:
        """Remove the :User node and its EXPOSED_TO edges (entity nodes are kept)."""
        with self._session() as session:
            session.run(f"MATCH (u:{self._user} {{user_id: $user_id}}) DETACH DELETE u", user_id=user_id)

    # ── Entities ─────────────────────────────────────────────

    def search_entities(self, q: str, alias_keys: List[str], limit: int) -> List[Dict]:
        """
        Entities whose key contains q, or whose key is an alias target. Grouped per key.
        Ranked exact > alias > prefix > word prefix > substring, then by total mentions.
        Returns [{key, name, types, mention_count}].
        """
        cypher = f"""
        MATCH (e:{self._entity})
        WITH e, {self._key} AS k
        WHERE (k CONTAINS $q OR k IN $alias_keys) AND {self._ingested}
        WITH k, collect({{name: e.{self._name}, type: e.type, freq: coalesce(e.frequency, 0)}}) AS variants,
             sum(coalesce(e.frequency, 0)) AS mentions
        WITH k, variants, mentions,
             CASE WHEN k = $q THEN 0
                  WHEN k IN $alias_keys THEN 1
                  WHEN k STARTS WITH $q THEN 2
                  WHEN k CONTAINS (' ' + $q) THEN 3
                  ELSE 4 END AS rank
        RETURN k AS key, variants, mentions
        ORDER BY rank, mentions DESC, k
        LIMIT $limit
        """
        with self._session() as session:
            rows = session.run(cypher, q=q, alias_keys=alias_keys, limit=limit).data()
        return [
            {
                "key": r["key"],
                "name": self._display_name(r["variants"]),
                "types": sorted({v["type"] for v in r["variants"] if v["type"]}),
                "mention_count": r["mentions"],
            }
            for r in rows
        ]

    def resolve_key(self, key: str) -> List[Dict]:
        """Ingested variant nodes of a canonical key: [{name, type, frequency}]. [] means unknown."""
        cypher = f"""
        MATCH (e:{self._entity}) WHERE {self._key} = $key AND {self._ingested}
        RETURN e.{self._name} AS name, e.type AS type, coalesce(e.frequency, 0) AS frequency
        ORDER BY frequency DESC, name
        """
        with self._session() as session:
            return session.run(cypher, key=key).data()

    def display_names(self, keys: List[str]) -> Dict[str, str]:
        """{key: most-mentioned spelling} for the keys that exist (one query; uses the name_lower index)."""
        if not keys:
            return {}
        cypher = f"""
        MATCH (e:{self._entity}) WHERE e.name_lower IN $keys
        RETURN e.name_lower AS key, collect({{name: e.{self._name}, freq: coalesce(e.frequency, 0)}}) AS variants
        """
        with self._session() as session:
            rows = session.run(cypher, keys=list(keys)).data()
        return {r["key"]: self._display_name(r["variants"]) for r in rows if r["variants"]}

    @staticmethod
    def _display_name(variants: List[Dict]) -> str:
        """Most-mentioned spelling of the key (ties → alphabetical)."""
        best = sorted(variants, key=lambda v: (-(v.get("freq") or v.get("frequency") or 0), v["name"]))
        return best[0]["name"]

    # ── Exposures ────────────────────────────────────────────

    def set_exposure(
        self,
        user_id: str,
        key: str,
        role: str,
        weight: int,
        provenance: str,
        proposal_id: Optional[str] = None,
    ) -> Dict:
        """
        MERGE the user's EXPOSED_TO edge to every variant of `key` and set its properties.
        valid_from is kept when the edge already exists. Returns the grouped exposure, or {} if the key is unknown.
        """
        label = {v: k for k, v in self.cfg.weight_levels.items()}[weight]
        cypher = f"""
        MERGE (u:{self._user} {{user_id: $user_id}})
        WITH u
        MATCH (e:{self._entity}) WHERE {self._key} = $key AND {self._ingested}
        MERGE (u)-[r:{self._rel}]->(e)
        ON CREATE SET r.valid_from = timestamp()
        SET r.role = $role, r.weight = $weight, r.weight_label = $label, r.provenance = $provenance,
            r.proposal_id = $proposal_id, r.updated_at = timestamp()
        RETURN e.{self._name} AS name, e.type AS type, coalesce(e.frequency, 0) AS frequency
        """
        with self._session() as session:
            nodes = session.execute_write(
                lambda tx: tx.run(
                    cypher, user_id=user_id, key=key, role=role, weight=weight, label=label,
                    provenance=provenance, proposal_id=proposal_id,
                ).data()
            )
        if not nodes:
            return {}
        return {
            "key": key,
            "name": self._display_name(nodes),
            "types": sorted({n["type"] for n in nodes if n["type"]}),
            "role": role,
            "weight": weight,
            "weight_label": label,
            "provenance": provenance,
            "nodes": len(nodes),
        }

    def remove_exposure(self, user_id: str, key: str) -> int:
        """Delete the user's EXPOSED_TO edges to every variant of `key`. Returns edges deleted."""
        cypher = f"""
        MATCH (u:{self._user} {{user_id: $user_id}})-[r:{self._rel}]->(e:{self._entity})
        WHERE {self._key} = $key
        DELETE r
        RETURN count(*) AS removed
        """
        with self._session() as session:
            record = session.run(cypher, user_id=user_id, key=key).single()
        return int(record["removed"]) if record else 0

    def get_exposures(self, user_id: str) -> List[Dict]:
        """
        The user's exposures grouped per entity key (max weight across variants):
        [{key, name, types, role, weight, weight_label, provenance, valid_from, updated_at, nodes}].
        """
        cypher = f"""
        MATCH (u:{self._user} {{user_id: $user_id}})-[r:{self._rel}]->(e:{self._entity})
        RETURN {self._key} AS key, e.{self._name} AS name, e.type AS type,
               coalesce(e.frequency, 0) AS frequency, properties(r) AS r
        """
        with self._session() as session:
            rows = session.run(cypher, user_id=user_id).data()

        grouped: Dict[str, List[Dict]] = {}
        for row in rows:
            grouped.setdefault(row["key"], []).append(row)
        out = []
        for key, variants in grouped.items():
            edges = [self._edge(v["r"]) for v in variants]
            best = max(edges, key=lambda e: (e["weight"], e["updated_at"] or 0))
            out.append({
                "key": key,
                "name": self._display_name(variants),
                "types": sorted({v["type"] for v in variants if v["type"]}),
                **best,
                "nodes": len(variants),
            })
        out.sort(key=lambda e: (-e["weight"], -(e["updated_at"] or 0), e["key"]))
        return out

    def get_seeds(self, user_id: str) -> List[Dict]:
        """[{key, role, weight}] — the spread seeds."""
        return [{"key": e["key"], "role": e["role"], "weight": e["weight"]} for e in self.get_exposures(user_id)]

    def neighbours(self, keys: List[str], top: int) -> Dict[str, List[Dict]]:
        """
        Entity–entity neighbours of each key, grouped per (key, neighbour key, relationship type):
        {key: [{key, rel_type, strength, freq}]}, the `top` strongest per key (ties → higher freq, then key).
        strength = Σ coalesce(r.count, r.weight, 1) across the type variants of both ends (plan C4);
        MENTIONED_WITH was MERGEd without a direction, so the match is undirected.
        """
        if not keys:
            return {}
        n_key = f"coalesce(n.name_lower, toLower(trim(n.{self._name})))"
        cypher = f"""
        MATCH (s:{self._entity}) WHERE s.name_lower IN $keys
        MATCH (s)-[r]-(n:{self._entity})
        WHERE type(r) <> $exposure AND coalesce(n.created_by, '') <> 'user_exposure'
        WITH s.name_lower AS src, {n_key} AS dst, type(r) AS rel, r, n
        WHERE dst <> src
        WITH src, dst, rel, sum(coalesce(r.count, r.weight, 1)) AS strength, collect(DISTINCT n) AS ns
        RETURN src, dst, rel, strength, reduce(f = 0, x IN ns | f + coalesce(x.frequency, 0)) AS freq
        """
        with self._session() as session:
            rows = session.run(cypher, keys=list(keys), exposure=self._rel).data()
        out: Dict[str, List[Dict]] = {}
        for r in rows:
            out.setdefault(r["src"], []).append(
                {"key": r["dst"], "rel_type": r["rel"], "strength": float(r["strength"]), "freq": int(r["freq"])}
            )
        for src, nbrs in out.items():
            nbrs.sort(key=lambda n: (-n["strength"], -n["freq"], n["key"]))
            del nbrs[top:]
        return out

    def _edge(self, r: Dict) -> Dict:
        """Edge properties, tolerating v1 edges that sync_name_lower hasn't migrated yet."""
        weight = r.get("weight")
        label = r.get("weight_label")
        if isinstance(weight, str):
            label, weight = weight, self.cfg.weight_levels.get(weight, 1)
        return {
            "role": r.get("role"),
            "weight": int(weight or 1),
            "weight_label": label,
            "provenance": r.get("provenance") or "declared",
            "valid_from": r.get("valid_from", r.get("updated_at")),
            "updated_at": r.get("updated_at"),
            **({"proposal_id": r["proposal_id"]} if r.get("proposal_id") else {}),
        }

    # ── Health ───────────────────────────────────────────────

    def is_available(self) -> Dict:
        """{ok, users, entities, name_lower_coverage} — never raises."""
        try:
            with self._session() as session:
                users = session.run(f"MATCH (u:{self._user}) RETURN count(u) AS c").single()["c"]
                row = session.run(
                    f"MATCH (e:{self._entity}) RETURN count(e) AS c, count(e.name_lower) AS k"
                ).single()
            return {
                "ok": True,
                "users": users,
                "entities": row["c"],
                "name_lower_coverage": round(row["k"] / row["c"], 4) if row["c"] else 1.0,
            }
        except Exception as e:
            logger.error(f"[Exposures] Neo4j not available: {e}")
            return {"ok": False, "error": type(e).__name__}
