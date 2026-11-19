"""
MAPNAI — storage/source_state_store.py
State of the continuous stream (stream_worker.py), in three Mongo collections:

  source_state   one doc per source: polling interval and next poll time, HTTP validators (ETag / Last-Modified),
                 the keys of recently seen items, the last outcome and counters (shown at /v1/admin/sources)
  prominence     items seen on editor-curated front pages (top_stories feeds) — the prominence component of the
                 hotness score. One doc per (feed, item); last_seen_at is refreshed while the item stays on the
                 page; a TTL index drops rows prominence_ttl_days after they were last seen
  stream_status  the worker's heartbeat (one doc)
"""

import re
from datetime import datetime, timedelta, timezone
from typing import Dict, Iterable, List, Optional

from pymongo import ASCENDING, DESCENDING, UpdateOne

from storage.mongo_store import MongoStore
from utils.logger import logger

SOURCE_STATE = "source_state"
PROMINENCE = "prominence"
STREAM_STATUS = "stream_status"
PROMINENCE_TTL_DAYS = 3
SILENT_DAYS = 7          # a feed with no new item for this long is flagged `silent` (likely dead or moved)

_TOKEN = re.compile(r"[a-z0-9]+")


def _aware(t: Optional[datetime]) -> Optional[datetime]:
    """Mongo hands back naive UTC datetimes."""
    if t is None or not isinstance(t, datetime):
        return t
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


class SourceStateStore:
    def __init__(self, mongo: Optional[MongoStore] = None):
        self.mongo = mongo or MongoStore()
        self._indexes_ok = False

    def _col(self, name: str):
        if not self._indexes_ok:
            self._indexes_ok = True
            self.ensure_indexes()
        return self.mongo.db[name]

    def ensure_indexes(self) -> None:
        db = self.mongo.db
        db[SOURCE_STATE].create_index([("name", ASCENDING)], unique=True)
        db[SOURCE_STATE].create_index([("next_poll_at", ASCENDING)])
        prom = db[PROMINENCE]
        prom.create_index([("feed", ASCENDING), ("key", ASCENDING)], unique=True)
        prom.create_index([("last_seen_at", DESCENDING)])
        prom.create_index([("url", ASCENDING)])
        try:
            prom.create_index([("last_seen_at", ASCENDING)], name="prominence_ttl",
                              expireAfterSeconds=PROMINENCE_TTL_DAYS * 86400)
        except Exception as e:   # an index on the same key with other options already exists
            logger.debug(f"[SourceState] TTL index not created: {e}")

    # ── Sources ──────────────────────────────────────────────

    def ensure_sources(self, sources: Iterable, now: datetime) -> int:
        """
        One state doc per configured source (static fields refreshed from config on every start; polling state
        kept). Sources no longer in the config are marked inactive. Returns the number of configured sources.
        """
        col = self._col(SOURCE_STATE)
        names, ops = [], []
        for s in sources:
            names.append(s.name)
            ops.append(UpdateOne(
                {"name": s.name},
                {"$set": {"url": s.url, "domain": s.domain, "role": getattr(s, "role", "section"),
                          "store_items": getattr(s, "store_items", True), "active": bool(s.active),
                          "kind": getattr(s, "kind", "rss")},
                 "$setOnInsert": {"created_at": now, "interval_s": None, "next_poll_at": None, "seen": [],
                                  "counters": {"polls": 0, "not_modified": 0, "errors": 0, "new_items": 0},
                                  "consecutive_failures": 0}},
                upsert=True,
            ))
        if ops:
            col.bulk_write(ops, ordered=False)
        col.update_many({"name": {"$nin": names}}, {"$set": {"active": False}})
        return len(names)

    def all(self) -> List[Dict]:
        rows = list(self._col(SOURCE_STATE).find({}, {"_id": 0}))
        for r in rows:
            for f in ("next_poll_at", "last_polled_at", "last_new_at", "created_at"):
                r[f] = _aware(r.get(f))
        return rows

    def get(self, name: str) -> Optional[Dict]:
        row = self._col(SOURCE_STATE).find_one({"name": name}, {"_id": 0})
        if row:
            for f in ("next_poll_at", "last_polled_at", "last_new_at", "created_at"):
                row[f] = _aware(row.get(f))
        return row

    def record_poll(self, name: str, *, status: str, new_count: int, interval_s: float, now: datetime,
                    etag: Optional[str] = None, last_modified: Optional[str] = None,
                    seen: Optional[List[str]] = None, error: Optional[str] = None) -> None:
        """Write one poll's outcome: next poll time, validators, seen keys, counters."""
        sets: Dict = {"last_polled_at": now, "last_status": status, "interval_s": float(interval_s),
                      "next_poll_at": now + timedelta(seconds=float(interval_s)), "last_error": error}
        inc: Dict = {"counters.polls": 1}
        if status == "error":
            inc["counters.errors"] = 1
            inc["consecutive_failures"] = 1
        else:
            sets["consecutive_failures"] = 0
            if etag is not None:
                sets["etag"] = etag
            if last_modified is not None:
                sets["last_modified"] = last_modified
            if seen is not None:
                sets["seen"] = list(seen)
            if status == "not_modified":
                inc["counters.not_modified"] = 1
            if new_count:
                inc["counters.new_items"] = int(new_count)
                sets["last_new_at"] = now
        self._col(SOURCE_STATE).update_one({"name": name}, {"$set": sets, "$inc": inc})

    def health(self, now: datetime) -> List[Dict]:
        """Per-source health for /v1/admin/sources, the worst first (failing, then silent, then the rest)."""
        out = []
        for r in self.all():
            c = r.get("counters") or {}
            polls = int(c.get("polls") or 0)
            last_new = r.get("last_new_at")
            silent = bool(r.get("active")) and polls > 0 and (
                last_new is None and r.get("created_at") is not None
                and now - r["created_at"] > timedelta(days=SILENT_DAYS)
                or last_new is not None and now - last_new > timedelta(days=SILENT_DAYS))
            out.append({
                "name": r["name"], "url": r.get("url"), "kind": r.get("kind", "rss"), "role": r.get("role"),
                "domain": r.get("domain"), "active": r.get("active"), "store_items": r.get("store_items", True),
                "interval_min": round(r["interval_s"] / 60, 1) if r.get("interval_s") else None,
                "next_poll_at": r.get("next_poll_at"), "last_polled_at": r.get("last_polled_at"),
                "last_status": r.get("last_status"), "last_error": r.get("last_error"),
                "last_new_at": last_new, "consecutive_failures": r.get("consecutive_failures", 0),
                "polls": polls, "new_items": int(c.get("new_items") or 0),
                "not_modified_share": round(int(c.get("not_modified") or 0) / polls, 3) if polls else None,
                "error_share": round(int(c.get("errors") or 0) / polls, 3) if polls else None,
                "silent": silent,
                "conditional_get": bool(r.get("etag") or r.get("last_modified")),
            })
        rank = lambda h: (0 if h["consecutive_failures"] else 1 if h["silent"] else 2, h["name"])  # noqa: E731
        return sorted(out, key=rank)

    # ── Prominence ───────────────────────────────────────────

    @staticmethod
    def title_tokens(title: str) -> List[str]:
        from personalization.hotness import strip_publisher
        return sorted(set(_TOKEN.findall(strip_publisher(title or "").lower())))

    def add_prominence(self, rows: List[Dict], now: datetime) -> int:
        """rows: [{feed, url, title, domain}] seen on a front page now. Returns the rows written."""
        ops = []
        for r in rows:
            key = (r.get("url") or "").strip() or (r.get("title") or "").strip().lower()
            if not key:
                continue
            ops.append(UpdateOne(
                {"feed": r["feed"], "key": key},
                {"$set": {"url": r.get("url") or "", "title": r.get("title") or "", "domain": r.get("domain"),
                          "title_tokens": self.title_tokens(r.get("title") or ""), "last_seen_at": now},
                 "$setOnInsert": {"first_seen_at": now}},
                upsert=True,
            ))
        if not ops:
            return 0
        res = self._col(PROMINENCE).bulk_write(ops, ordered=False)
        return res.upserted_count + res.modified_count

    def prominence_since(self, since: datetime) -> List[Dict]:
        rows = list(self._col(PROMINENCE).find({"last_seen_at": {"$gte": since}}, {"_id": 0}))
        for r in rows:
            r["first_seen_at"], r["last_seen_at"] = _aware(r.get("first_seen_at")), _aware(r.get("last_seen_at"))
        return rows

    # ── Heartbeat ────────────────────────────────────────────

    def heartbeat(self, doc: Dict) -> None:
        self._col(STREAM_STATUS).update_one({"_id": "worker"}, {"$set": dict(doc)}, upsert=True)

    def status(self) -> Optional[Dict]:
        doc = self._col(STREAM_STATUS).find_one({"_id": "worker"}, {"_id": 0})
        if doc:
            for f in ("last_tick_at", "last_flush_at", "started_at"):
                doc[f] = _aware(doc.get(f))
        return doc
