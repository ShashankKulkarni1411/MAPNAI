"""
MAPNAI — storage/persona_store.py
MongoDB storage for reader personas (PERSONALIZATION_PLAN.md §2.2):
  {user_id, name, topics: {topic: 0–1}, style: {tone, length, jargon},
   beta: {enc("topic:x") | enc("entity:y"): [α, β]},
   history: [{article_id, title, t, w, win, src}], pi_topk: [...], alert_prefs: {...},
   persona_version, updated_at, created_at}
Beta keys are stored encoded (keys.encode_key) and decoded on read. v1 docs are upgraded lazily on read.
Reuses the lazy connection of the existing MongoStore.
"""

import copy
from datetime import datetime, timezone
from typing import Dict, List, Optional

from pymongo import ASCENDING, ReturnDocument

from config.personalization import pers_settings
from personalization.keys import decode_key, encode_key
from storage.mongo_store import MongoStore
from utils.logger import logger


def _now() -> datetime:
    return datetime.now(timezone.utc)


class PersonaStore:
    def __init__(self, mongo: Optional[MongoStore] = None, cfg=None):
        self.mongo = mongo or MongoStore()
        self.cfg = cfg or pers_settings
        self._indexes_ok = False

    @property
    def personas(self):
        col = self.mongo.db[self.cfg.personas_collection]
        if not self._indexes_ok:
            self._indexes_ok = True
            self.ensure_indexes()
        return col

    def ensure_indexes(self) -> None:
        self.mongo.db[self.cfg.personas_collection].create_index([("user_id", ASCENDING)], unique=True)
        logger.debug("[Personas] Indexes verified.")

    def _defaults(self) -> Dict:
        """v2 fields and their defaults; also used to upgrade v1 docs."""
        return {
            "topics": {},
            "style": dict(self.cfg.style_defaults),
            "beta": {},
            "history": [],
            "pi_topk": [],
            "alert_prefs": copy.deepcopy(self.cfg.alert_prefs_default),
            "persona_version": 1,
        }

    @staticmethod
    def _decode(doc: Dict) -> Dict:
        doc["beta"] = {decode_key(k): v for k, v in (doc.get("beta") or {}).items()}
        return doc

    # ── Create / read ────────────────────────────────────────

    def create(
        self,
        user_id: str,
        name: str,
        topics: Dict[str, float],
        style: Dict[str, str],
        beta: Dict[str, List[float]],
    ) -> Dict:
        now = _now()
        doc = {
            **self._defaults(),
            "user_id": user_id,
            "name": name,
            "topics": topics,
            "style": style,
            "beta": {encode_key(k): v for k, v in beta.items()},
            "created_at": now,
            "updated_at": now,
        }
        self.personas.insert_one(doc)
        doc.pop("_id", None)
        return self._decode(doc)

    def get(self, user_id: str) -> Optional[Dict]:
        """The persona with decoded Beta keys. A v1 doc gets its missing v2 fields written once."""
        doc = self.personas.find_one({"user_id": user_id}, {"_id": 0})
        if doc is None:
            return None
        missing = {k: v for k, v in self._defaults().items() if k not in doc}
        if missing:
            missing["updated_at"] = doc.get("updated_at") or doc.get("created_at") or _now()
            # $set only fields that are still absent, so a concurrent writer is never overwritten
            for field, value in missing.items():
                self.personas.update_one(
                    {"user_id": user_id, field: {"$exists": False}}, {"$set": {field: value}}
                )
            doc.update(missing)
            logger.info(f"[Personas] Upgraded v1 persona {user_id}: added {sorted(missing)}")
        return self._decode(doc)

    def delete(self, user_id: str) -> None:
        self.personas.delete_one({"user_id": user_id})

    # ── Updates ──────────────────────────────────────────────

    def patch(self, user_id: str, set_fields: Dict, unset_fields: Optional[List[str]] = None) -> Optional[int]:
        """$set / $unset fields, bump persona_version and updated_at. Returns the new version (None: no user)."""
        update: Dict = {"$set": {**set_fields, "updated_at": _now()}, "$inc": {"persona_version": 1}}
        if unset_fields:
            update["$unset"] = {f: "" for f in unset_fields}
        doc = self.personas.find_one_and_update(
            {"user_id": user_id}, update,
            projection={"_id": 0, "persona_version": 1}, return_document=ReturnDocument.AFTER,
        )
        return doc["persona_version"] if doc else None

    def init_beta(self, user_id: str, priors: Dict[str, List[float]]) -> List[str]:
        """Set Beta priors for keys that have no Beta yet (learned values are never overwritten). Returns keys set."""
        added = []
        for key, ab in priors.items():
            path = f"beta.{encode_key(key)}"
            res = self.personas.update_one({"user_id": user_id, path: {"$exists": False}}, {"$set": {path: list(ab)}})
            if res.modified_count:
                added.append(key)
        return added

    def inc_beta(self, user_id: str, deltas: Dict[str, List[float]], base: Dict[str, List[float]]) -> None:
        """
        Add [Δα, Δβ] to each Beta. A key without a Beta starts from base[key] (its prior, default [1, 1]);
        the increment itself is a single atomic $inc.
        """
        if not deltas:
            return
        self.init_beta(user_id, {k: base.get(k, [1.0, 1.0]) for k in deltas})
        inc: Dict[str, float] = {}
        for key, (da, db) in deltas.items():
            path = f"beta.{encode_key(key)}"
            if da:
                inc[f"{path}.0"] = da
            if db:
                inc[f"{path}.1"] = db
        if inc:
            self.personas.update_one({"user_id": user_id}, {"$inc": inc})

    def push_history(self, user_id: str, items: List[Dict]) -> None:
        """Append history items, keeping the newest history_keep."""
        if items:
            self.personas.update_one(
                {"user_id": user_id},
                {"$push": {"history": {"$each": items, "$slice": -self.cfg.history_keep}}},
            )

    def set_pi_topk(self, user_id: str, pi: List[Dict]) -> None:
        """pi_topk is derived from the exposures, so it doesn't bump persona_version."""
        self.personas.update_one(
            {"user_id": user_id}, {"$set": {"pi_topk": pi[: self.cfg.pi_topk_max], "pi_computed_at": _now()}}
        )

    # ── Admin ────────────────────────────────────────────────

    def all_ids(self) -> List[str]:
        return [d["user_id"] for d in self.personas.find({}, {"_id": 0, "user_id": 1})]

    def pi_rows(self) -> List[Dict]:
        """{user_id, pi_topk, alert_prefs, persona_version} of every persona with a pi_topk (the alerts index)."""
        return list(self.personas.find(
            {"pi_topk.0": {"$exists": True}},
            {"_id": 0, "user_id": 1, "pi_topk": 1, "alert_prefs": 1, "persona_version": 1}))

    def count(self) -> int:
        return self.personas.estimated_document_count()
