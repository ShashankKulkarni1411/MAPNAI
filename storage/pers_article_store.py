"""
MAPNAI — storage/pers_article_store.py
Reads of processed_articles for the personalization engine. Read-only in Phase 1; the additive
writes (entity_keys, cluster_*, materiality) and the R1–R4 retrievers come in later phases.
"""

from typing import Dict, List, Optional

from pymongo import DESCENDING

from config.personalization import pers_settings
from storage.mongo_store import MongoStore


class PersArticleStore:
    def __init__(self, mongo: Optional[MongoStore] = None, cfg=None):
        self.mongo = mongo or MongoStore()
        self.cfg = cfg or pers_settings

    @property
    def articles(self):
        return self.mongo.db[self.cfg.articles_collection]

    def _projection(self) -> Dict:
        c = self.cfg
        fields = [c.id_field, c.title_field, c.topic_field, c.url_field, c.source_field,
                  c.published_field, c.entities_field, "cluster_id", "materiality"]
        return {"_id": 0, **{f: 1 for f in fields}}

    def by_ids(self, ids: List[str]) -> List[Dict]:
        if not ids:
            return []
        return list(self.articles.find({self.cfg.id_field: {"$in": list(ids)}}, self._projection()))

    def recent_by_topic(self, topic: str, limit: int) -> List[Dict]:
        """Newest articles of one topic (published_at is an ISO string; callers re-sort after parsing)."""
        return list(
            self.articles.find({self.cfg.topic_field: topic}, self._projection())
            .sort(self.cfg.published_field, DESCENDING)
            .limit(limit)
        )

    def topics(self) -> List[str]:
        return sorted(t for t in self.articles.distinct(self.cfg.topic_field) if t)
