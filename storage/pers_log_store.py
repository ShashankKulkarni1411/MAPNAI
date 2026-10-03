"""
MAPNAI — storage/pers_log_store.py
Mongo collections owned by the personalization engine (PERSONALIZATION_PLAN.md §2.2).
Phase 1: entity_aliases and feedback. Phase 2: job_runs. Phase 4: impressions, digests, thresholds (read: current τ).
Phase 5: thresholds (write), feedback/impression windows for τ, proposals. Phase 6: alerts. Phase 7: render_cache.
"""

import re
import uuid
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Set, Tuple

from pymongo import ASCENDING, DESCENDING
from pymongo.errors import DuplicateKeyError

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
        db[self.cfg.job_runs_collection].create_index([("job", ASCENDING), ("started_at", DESCENDING)])
        impressions = db[self.cfg.impressions_collection]
        impressions.create_index([("user_id", ASCENDING), ("t", DESCENDING)])
        impressions.create_index([("section", ASCENDING), ("t", DESCENDING)])
        impressions.create_index([("article_id", ASCENDING)])
        db[self.cfg.thresholds_collection].create_index([("t", DESCENDING)])
        db[self.cfg.digests_collection].create_index([("user_id", ASCENDING), ("date", ASCENDING)], unique=True)
        proposals = db[self.cfg.proposals_collection]
        proposals.create_index([("proposal_id", ASCENDING)], unique=True)
        proposals.create_index([("user_id", ASCENDING), ("status", ASCENDING)])
        # at most one pending proposal per (user, entity)
        proposals.create_index([("user_id", ASCENDING), ("entity_key", ASCENDING)], unique=True,
                               partialFilterExpression={"status": "pending"}, name="one_pending_per_entity")
        alerts = db[self.cfg.alerts_collection]
        alerts.create_index([("alert_id", ASCENDING)], unique=True)
        alerts.create_index([("user_id", ASCENDING), ("deliver_after", DESCENDING)])
        alerts.create_index([("user_id", ASCENDING), ("cluster_id", ASCENDING)], unique=True,
                            name="one_alert_per_cluster")
        db[self.cfg.render_cache_collection].create_index(
            [("article_id", ASCENDING), ("tone", ASCENDING), ("length", ASCENDING), ("jargon", ASCENDING),
             ("prompt_version", ASCENDING)], unique=True, name="one_render_per_style")
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

    def alias_map(self) -> Dict[str, str]:
        """{alias: entity_key} for the whole table (small, hand-seeded)."""
        return {d["alias"]: d["entity_key"]
                for d in self._col(self.cfg.aliases_collection).find({}, {"_id": 0, "alias": 1, "entity_key": 1})}

    def alias_count(self) -> int:
        return self._col(self.cfg.aliases_collection).estimated_document_count()

    # ── Feedback ─────────────────────────────────────────────

    def log_feedback(self, docs: List[Dict]) -> int:
        if not docs:
            return 0
        return len(self._col(self.cfg.feedback_collection).insert_many(docs).inserted_ids)

    def read_ids(self, user_id: str, history: List[Dict]) -> set:
        """Articles the user has consumed: history items ∪ feedback of an engaged type (open/more/save/dwell)."""
        ids = {h.get("article_id") for h in history or [] if h.get("article_id")}
        cursor = self._col(self.cfg.feedback_collection).find(
            {"user_id": user_id, "type": {"$in": list(self.cfg.read_feedback_types)}}, {"_id": 0, "article_id": 1})
        return ids | {d["article_id"] for d in cursor}

    def saved_ids(self, user_id: str) -> List[str]:
        """Articles whose latest save/unsave feedback is a save, most recently saved first."""
        cursor = self._col(self.cfg.feedback_collection).find(
            {"user_id": user_id, "type": {"$in": ["save", "unsave"]}}, {"_id": 0, "article_id": 1, "type": 1}
        ).sort([("t", DESCENDING), ("_id", DESCENDING)])        # _id: insertion order within one timestamp
        latest: Dict[str, str] = {}
        for d in cursor:
            latest.setdefault(d["article_id"], d["type"])
        return [a for a, t in latest.items() if t == "save"]

    def feedback_window(self, since: datetime, types: List[str], user_id: Optional[str] = None) -> List[Dict]:
        """Feedback of the given types from `since` on (one user or all), oldest first."""
        query: Dict = {"type": {"$in": list(types)}, "t": {"$gte": since}}
        if user_id is not None:
            query["user_id"] = user_id
        return list(self._col(self.cfg.feedback_collection).find(query, {"_id": 0}).sort("t", ASCENDING))

    # ── Impressions ──────────────────────────────────────────

    def log_impressions(self, docs: List[Dict]) -> int:
        if not docs:
            return 0
        return len(self._col(self.cfg.impressions_collection).insert_many(docs).inserted_ids)

    def last_impression(self, user_id: str, article_id: str) -> Optional[Dict]:
        """The latest time this article was served to the user (section, slot, digest_id, t), or None."""
        return self._col(self.cfg.impressions_collection).find_one(
            {"user_id": user_id, "article_id": article_id},
            {"_id": 0, "section": 1, "slot": 1, "digest_id": 1, "t": 1}, sort=[("t", DESCENDING)])

    def served_pairs(self, pairs: Set[Tuple[str, str]], section: str, since: datetime) -> Set[Tuple[str, str]]:
        """The (user_id, article_id) pairs among `pairs` that were served in `section` from `since` on."""
        if not pairs:
            return set()
        cursor = self._col(self.cfg.impressions_collection).find(
            {"section": section, "t": {"$gte": since},
             "user_id": {"$in": sorted({u for u, _ in pairs})},
             "article_id": {"$in": sorted({a for _, a in pairs})}},
            {"_id": 0, "user_id": 1, "article_id": 1})
        return {(d["user_id"], d["article_id"]) for d in cursor} & set(pairs)

    # ── Threshold τ ──────────────────────────────────────────

    def current_tau(self) -> float:
        """The latest τ written by the τ job, else tau_init."""
        doc = self._col(self.cfg.thresholds_collection).find_one({}, {"_id": 0, "tau": 1}, sort=[("t", DESCENDING)])
        return float(doc["tau"]) if doc and doc.get("tau") is not None else float(self.cfg.tau_init)

    def push_tau(self, row: Dict) -> None:
        """Append a thresholds row {t, tau, prev_tau, miss_rate, missed, needed, …}; the latest one is current."""
        self._col(self.cfg.thresholds_collection).insert_one(dict(row))

    def tau_history(self, limit: int = 10) -> List[Dict]:
        return list(self._col(self.cfg.thresholds_collection).find({}, {"_id": 0}).sort("t", DESCENDING).limit(limit))

    # ── Proposals ────────────────────────────────────────────

    def add_proposal(self, doc: Dict) -> bool:
        """Insert a pending proposal. False when the user already has a pending one for this entity."""
        try:
            self._col(self.cfg.proposals_collection).insert_one(dict(doc))
            return True
        except DuplicateKeyError:
            return False

    def list_proposals(self, user_id: str, status: Optional[str] = None) -> List[Dict]:
        query: Dict = {"user_id": user_id}
        if status:
            query["status"] = status
        return list(self._col(self.cfg.proposals_collection).find(query, {"_id": 0}).sort("created_at", DESCENDING))

    def get_proposal(self, user_id: str, proposal_id: str) -> Optional[Dict]:
        return self._col(self.cfg.proposals_collection).find_one(
            {"user_id": user_id, "proposal_id": proposal_id}, {"_id": 0})

    def proposal_keys(self, user_id: str) -> Set[str]:
        """Entity keys already proposed to the user, in any status."""
        return set(self._col(self.cfg.proposals_collection).distinct("entity_key", {"user_id": user_id}))

    def decide_proposal(self, user_id: str, proposal_id: str, status: str, now: datetime,
                        extra: Optional[Dict] = None, from_status: str = "pending") -> Optional[Dict]:
        """Atomically move a proposal from `from_status` to `status`. None when it isn't in `from_status`."""
        col = self._col(self.cfg.proposals_collection)
        res = col.update_one({"user_id": user_id, "proposal_id": proposal_id, "status": from_status},
                             {"$set": {"status": status, "decided_at": now, **(extra or {})}})
        return self.get_proposal(user_id, proposal_id) if res.modified_count else None

    # ── Alerts ───────────────────────────────────────────────

    def add_alert(self, doc: Dict) -> bool:
        """Insert an alert. False when the user already has one for this cluster (unique index)."""
        try:
            self._col(self.cfg.alerts_collection).insert_one(dict(doc))
            return True
        except DuplicateKeyError:
            return False

    def count_alerts(self, user_id: str, start: datetime, end: datetime) -> int:
        """The user's alerts delivered (deliver_after) in [start, end): one local day for the per-day cap."""
        return self._col(self.cfg.alerts_collection).count_documents(
            {"user_id": user_id, "deliver_after": {"$gte": start, "$lt": end}})

    def alerted_clusters(self, user_id: str, cluster_ids: List[str]) -> Set[str]:
        """The clusters among `cluster_ids` the user already has an alert for."""
        if not cluster_ids:
            return set()
        return set(self._col(self.cfg.alerts_collection).distinct(
            "cluster_id", {"user_id": user_id, "cluster_id": {"$in": list(cluster_ids)}}))

    def alerts_for(self, user_id: str, since: Optional[datetime], until: Optional[datetime],
                   limit: int) -> List[Dict]:
        """The user's alerts with deliver_after in (since, until], newest first (None: unbounded)."""
        window: Dict = {}
        if since is not None:
            window["$gt"] = since
        if until is not None:
            window["$lte"] = until
        query: Dict = {"user_id": user_id, **({"deliver_after": window} if window else {})}
        return list(self._col(self.cfg.alerts_collection).find(query, {"_id": 0})
                    .sort("deliver_after", DESCENDING).limit(limit))

    # ── Render cache ─────────────────────────────────────────

    def render_get(self, key: Dict) -> Optional[Dict]:
        """key: {article_id, tone, length, jargon, prompt_version}."""
        return self._col(self.cfg.render_cache_collection).find_one(dict(key), {"_id": 0})

    def render_put(self, doc: Dict) -> None:
        """Upsert by the key fields (a changed source text replaces the entry)."""
        key = {k: doc[k] for k in ("article_id", "tone", "length", "jargon", "prompt_version")}
        self._col(self.cfg.render_cache_collection).replace_one(key, dict(doc), upsert=True)

    # ── Digest cache ─────────────────────────────────────────

    def get_digest(self, user_id: str, date: str) -> Optional[Dict]:
        return self._col(self.cfg.digests_collection).find_one({"user_id": user_id, "date": date}, {"_id": 0})

    def put_digest(self, doc: Dict) -> None:
        """Upsert by (user_id, date): one cached digest per user and local day."""
        self._col(self.cfg.digests_collection).replace_one(
            {"user_id": doc["user_id"], "date": doc["date"]}, doc, upsert=True)

    def invalidate_digest(self, user_id: str) -> int:
        return self._col(self.cfg.digests_collection).delete_many({"user_id": user_id}).deleted_count

    def purge_user(self, user_id: str) -> Dict[str, int]:
        """Delete every per-user row (feedback, impressions, digests, proposals, alerts). Returns counts per collection."""
        c = self.cfg
        return {
            name: self._col(name).delete_many({"user_id": user_id}).deleted_count
            for name in (c.feedback_collection, c.impressions_collection, c.digests_collection,
                         c.proposals_collection, c.alerts_collection)
        }

    def drop_tau_since(self, since: datetime) -> int:
        """Delete τ rows written at or after `since` (the smoke test undoes its own τ step)."""
        return self._col(self.cfg.thresholds_collection).delete_many({"t": {"$gte": since}}).deleted_count

    # ── Job runs ─────────────────────────────────────────────

    def job_start(self, job: str, now: datetime) -> Optional[str]:
        """
        Open a run holding a lease of job_lease_s. Returns the run id, or None while another run of the same
        job still holds an unexpired lease (a second worker or an overlapping manual run).
        """
        col = self._col(self.cfg.job_runs_collection)
        if col.find_one({"job": job, "finished_at": None, "lease_until": {"$gt": now}}):
            return None
        run_id = str(uuid.uuid4())
        col.insert_one({"run_id": run_id, "job": job, "started_at": now, "finished_at": None, "ok": None,
                        "stats": None, "error": None, "lease_until": now + timedelta(seconds=self.cfg.job_lease_s)})
        return run_id

    def job_finish(self, run_id: str, now: datetime, ok: bool, stats: Optional[Dict] = None,
                   error: Optional[str] = None) -> None:
        self._col(self.cfg.job_runs_collection).update_one(
            {"run_id": run_id},
            {"$set": {"finished_at": now, "ok": ok, "stats": stats, "error": error, "lease_until": now}},
        )

    def last_runs(self) -> Dict[str, Dict]:
        """The latest run of each job."""
        col = self._col(self.cfg.job_runs_collection)
        out: Dict[str, Dict] = {}
        for doc in col.find({}, {"_id": 0}).sort("started_at", DESCENDING):
            out.setdefault(doc["job"], doc)
        return out
