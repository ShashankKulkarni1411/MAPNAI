"""
MAPNAI — storage/pers_log_store.py
Mongo collections owned by the personalization engine (PERSONALIZATION_PLAN.md §2.2).
Phase 1: entity_aliases and feedback. Impressions, thresholds, proposals, alerts, digests,
render_cache and job_runs are added by later phases.
"""

import re
from typing import Dict, List, Optional

from pymongo import ASCENDING, DESCENDING

from config.personalization import pers_settings
from personalization.keys import entity_key
from storage.mongo_store import MongoStore
from utils.logger import logger


class PersLogStore:
    def __init__(self, mongo: Optional[MongoStore] = None, cfg=None):
        self.mongo = mongo or MongoStore()
        self.cfg = cfg or pers_settings
        self._indexes_ok = False

    def _col(self, name: str):
        if not self._indexes_ok:
            self._indexes_ok = True
            self.ensure_indexes()
        return self.mongo.db[name]

    def ensure_indexes(self) -> None:
        db = self.mongo.db
        aliases = db[self.cfg.aliases_collection]
        aliases.create_index([("alias", ASCENDING)], unique=True)
        aliases.create_index([("entity_key", ASCENDING)])
        feedback = db[self.cfg.feedback_collection]
        feedback.create_index([("user_id", ASCENDING), ("t", DESCENDING)])
        feedback.create_index([("type", ASCENDING), ("t", DESCENDING)])
        logger.debug("[PersLog] Indexes verified.")

    # ── Entity aliases ───────────────────────────────────────

    def alias_lookup(self, q: str) -> List[str]:
        """Entity keys whose alias equals q or starts with it (q is normalised with entity_key)."""
        q = entity_key(q)
        if not q:
            return []
        cursor = self._col(self.cfg.aliases_collection).find(
            {"alias": {"$regex": f"^{re.escape(q)}"}}, {"_id": 0, "entity_key": 1}
        )
        return sorted({d["entity_key"] for d in cursor})

    def alias_upsert(self, rows: List[Dict], source: str) -> int:
        """rows: [{alias, entity_key}] → upsert by alias. Returns upserted + modified."""
        col = self._col(self.cfg.aliases_collection)
        changed = 0
        for r in rows:  # a hand-written seed list: small, so one round trip per row is fine
            res = col.update_one(
                {"alias": entity_key(r["alias"])},
                {"$set": {"entity_key": entity_key(r["entity_key"]), "source": source}},
                upsert=True,
            )
            changed += int(res.upserted_id is not None) + res.modified_count
        return changed

    def alias_count(self) -> int:
        return self._col(self.cfg.aliases_collection).estimated_document_count()

    # ── Feedback ─────────────────────────────────────────────

    def log_feedback(self, docs: List[Dict]) -> int:
        if not docs:
            return 0
        return len(self._col(self.cfg.feedback_collection).insert_many(docs).inserted_ids)
