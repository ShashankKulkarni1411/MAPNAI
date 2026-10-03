"""
MAPNAI — storage/pers_article_store.py
processed_articles for the personalization engine, plus the `clusters` collection.
Writes are additive and field-scoped (PERSONALIZATION_PLAN.md §2.3): entity_keys, cluster_id, cluster_size,
first_report, materiality, pers_indexed_at. No pipeline field is ever written here.
"""

import re
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from pymongo import ASCENDING, DESCENDING, UpdateMany, UpdateOne

from config.personalization import pers_settings
from personalization.scoring import parse_ts
from storage.mongo_store import MongoStore
from utils.logger import logger


class PersArticleStore:
    def __init__(self, mongo: Optional[MongoStore] = None, cfg=None):
        self.mongo = mongo or MongoStore()
        self.cfg = cfg or pers_settings
        self._indexes_ok = False

    @property
    def articles(self):
        if not self._indexes_ok:
            self._indexes_ok = True
            self.ensure_indexes()
        return self.mongo.db[self.cfg.articles_collection]

    @property
    def clusters(self):
        if not self._indexes_ok:
            self._indexes_ok = True
            self.ensure_indexes()
        return self.mongo.db[self.cfg.clusters_collection]

    def ensure_indexes(self) -> None:
        c, db = self.cfg, self.mongo.db
        arts = db[c.articles_collection]
        arts.create_index([("entity_keys", ASCENDING)])
        arts.create_index([("cluster_id", ASCENDING)])
        arts.create_index([("materiality.m", DESCENDING)])
        arts.create_index([(c.published_field, DESCENDING), ("materiality.m", DESCENDING)])
        clusters = db[c.clusters_collection]
        clusters.create_index([("cluster_id", ASCENDING)], unique=True)
        clusters.create_index([("updated_at", DESCENDING)])
        logger.debug("[PersArticles] Indexes verified.")

    def _projection(self) -> Dict:
        c = self.cfg
        fields = [c.id_field, c.title_field, c.topic_field, c.url_field, c.source_field,
                  c.published_field, c.entities_field, "entity_keys", "cluster_id", "cluster_size",
                  "first_report", "materiality", c.risk_field, "risk_processed_at"]
        return {"_id": 0, **{f: 1 for f in fields}}

    # ── Reads ────────────────────────────────────────────────

    def by_ids(self, ids: List[str], projection: Optional[Dict] = None) -> List[Dict]:
        if not ids:
            return []
        return list(self.articles.find({self.cfg.id_field: {"$in": list(ids)}}, projection or self._projection()))

    def window(self, hours: int, now: datetime, projection: Optional[Dict] = None,
               extra: Optional[Dict] = None) -> List[Dict]:
        """
        Articles published in (now − hours, now] (and matching `extra`). published_at is an ISO string with mixed
        offsets, so Mongo prefilters on the date prefix a day early and the exact cutoff is applied after parsing
        (plan C18).
        """
        c = self.cfg
        cutoff = now - timedelta(hours=hours)
        coarse = (cutoff - timedelta(days=1)).date().isoformat()
        docs = self.articles.find({c.published_field: {"$gte": coarse}, **(extra or {})},
                                  projection or self._projection())
        return [d for d in docs if (ts := parse_ts(d.get(c.published_field))) and cutoff <= ts <= now]

    def alert_scan_pending(self, hours: int, now: datetime, rescan: bool = False) -> List[Dict]:
        """
        Window articles whose current materiality the alerts job hasn't evaluated (rescan: all with materiality).
        set_materiality replaces the whole `materiality` subdoc, so every recompute (cluster growth, A4 rescore)
        clears the scan mark.
        """
        extra: Dict = {"materiality": {"$exists": True}}
        if not rescan:
            extra["materiality.alerts_scanned_at"] = {"$exists": False}
        return self.window(hours, now, extra=extra)

    def all_ids(self) -> List[str]:
        return [d[self.cfg.id_field] for d in self.articles.find({}, {"_id": 0, self.cfg.id_field: 1})]

    def docs_for_embedding(self, ids: List[str]) -> List[Dict]:
        c = self.cfg
        fields = [c.id_field, c.title_field, "body", c.topic_field, c.url_field, c.source_field, c.published_field]
        return self.by_ids(ids, {"_id": 0, **{f: 1 for f in fields}})

    def missing_entity_keys(self) -> List[Dict]:
        c = self.cfg
        return list(self.articles.find({"entity_keys": {"$exists": False}},
                                       {"_id": 0, c.id_field: 1, c.entities_field: 1}))

    def rescore_candidates(self) -> List[Dict]:
        """Clustered articles with no materiality yet, or that A4 has scored (callers compare risk_seen_at)."""
        return list(self.articles.find(
            {"cluster_id": {"$exists": True},
             "$or": [{"materiality": {"$exists": False}}, {"risk_processed_at": {"$exists": True}}]},
            self._projection(),
        ))

    def get_clusters(self, cluster_ids: List[str]) -> Dict[str, Dict]:
        if not cluster_ids:
            return {}
        return {d["cluster_id"]: d for d in self.clusters.find({"cluster_id": {"$in": list(cluster_ids)}}, {"_id": 0})}

    def clusters_with_members(self, ids: List[str]) -> Dict[str, Dict]:
        if not ids:
            return {}
        return {d["cluster_id"]: d for d in self.clusters.find({"members": {"$in": list(ids)}}, {"_id": 0})}

    def ranked_by_topic(self, topic: str, limit: int) -> List[Dict]:
        """One topic's articles by materiality desc, then newest (articles without materiality sort last)."""
        c = self.cfg
        return list(
            self.articles.find({c.topic_field: topic}, self._projection())
            .sort([("materiality.m", DESCENDING), (c.published_field, DESCENDING)])
            .limit(limit)
        )

    def topics(self) -> List[str]:
        return sorted(t for t in self.articles.distinct(self.cfg.topic_field) if t)

    def cluster_members(self, cluster_id: str, projection: Optional[Dict] = None) -> List[Dict]:
        return list(self.articles.find({"cluster_id": cluster_id}, projection or self._projection()))

    def with_entity_keys(self, keys: List[str], limit: int, projection: Optional[Dict] = None) -> List[Dict]:
        """Newest articles mentioning any of the entity keys."""
        return list(self.articles.find({"entity_keys": {"$in": list(keys)}}, projection or self._projection())
                    .sort(self.cfg.published_field, DESCENDING).limit(limit))

    def search(self, terms: List[str], topic: Optional[str], limit: int, projection: Dict) -> List[Dict]:
        """Newest articles whose title, short summary or an entity name contains any of the terms (case-insensitive)."""
        c = self.cfg
        if not terms:
            return []
        pattern = "|".join(re.escape(t) for t in terms)
        query: Dict = {"$or": [{f: {"$regex": pattern, "$options": "i"}}
                               for f in (c.title_field, "summary_short", f"{c.entities_field}.{c.entity_name_key}")]}
        if topic:
            query[c.topic_field] = topic
        return list(self.articles.find(query, projection).sort(c.published_field, DESCENDING).limit(limit))

    # ── Additive writes ──────────────────────────────────────

    def _bulk(self, ops: List) -> int:
        if not ops:
            return 0
        res = self.articles.bulk_write(ops, ordered=False)
        return res.modified_count

    def set_entity_keys(self, keys_by_id: Dict[str, List[str]]) -> int:
        return self._bulk([UpdateOne({self.cfg.id_field: a}, {"$set": {"entity_keys": k}})
                           for a, k in keys_by_id.items()])

    def mark_indexed(self, ids: List[str], now: datetime) -> int:
        if not ids:
            return 0
        return self._bulk([UpdateMany({self.cfg.id_field: {"$in": list(ids)}}, {"$set": {"pers_indexed_at": now}})])

    def apply_clusters(self, clusters: List[Dict], now: datetime) -> int:
        """
        clusters: [{cluster_id, members, first_report, first_published, entity_keys, size}] → upsert each
        `clusters` doc and $set cluster_id / cluster_size / first_report on every member. Returns articles modified.
        """
        ops = []
        for cl in clusters:
            self.clusters.update_one(
                {"cluster_id": cl["cluster_id"]},
                {"$set": {**cl, "updated_at": now}, "$setOnInsert": {"created_at": now}},
                upsert=True,
            )
            ops.append(UpdateMany(
                {self.cfg.id_field: {"$in": cl["members"]}},
                {"$set": {"cluster_id": cl["cluster_id"], "cluster_size": cl["size"],
                          "first_report": cl["first_report"]}},
            ))
        return self._bulk(ops)

    def reset_clusters(self, article_ids: List[str], cluster_ids: List[str]) -> int:
        """Unset the cluster fields and materiality on the articles and delete the cluster docs (recluster)."""
        if cluster_ids:
            self.clusters.delete_many({"cluster_id": {"$in": list(cluster_ids)}})
        if not article_ids:
            return 0
        return self._bulk([UpdateMany(
            {self.cfg.id_field: {"$in": list(article_ids)}},
            {"$unset": {"cluster_id": "", "cluster_size": "", "first_report": "", "materiality": ""}},
        )])

    def set_materiality(self, updates: Dict[str, Dict]) -> int:
        return self._bulk([UpdateOne({self.cfg.id_field: a}, {"$set": {"materiality": m}})
                           for a, m in updates.items()])

    def mark_alert_scanned(self, seen: Dict[str, object], now: datetime) -> int:
        """
        seen: {article_id: the materiality.computed_at that was evaluated}. The mark is written only while that
        materiality is still current, so one recomputed during the scan is picked up by the next run.
        """
        return self._bulk([UpdateOne({self.cfg.id_field: a, "materiality.computed_at": computed_at},
                                     {"$set": {"materiality.alerts_scanned_at": now}})
                           for a, computed_at in seen.items()])
