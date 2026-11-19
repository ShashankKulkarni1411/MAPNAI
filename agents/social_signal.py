"""
MAPNAI — agents/social_signal.py
The optional social component of hotness (continousexplanation.md §5.8, "social"): how many Bluesky posts mention a
story that is already trending or breaking.

  WatchList          the stories worth counting: clusters whose hot.tier is trending / breaking, each with the names
                     of its main entities (lower case). Rebuilt every stream_social_refresh_seconds.
  match_post         a post counts for a story when it names ≥ min(2, #names) of the story's entities (one name
                     alone, e.g. "India", matches far too much).
  Buckets            counts per (cluster, 10-minute bucket), written to `social_signals` with $inc; hotness reads
                     the last hot_social_window_min of them.
  JetstreamCollector a background thread on Bluesky's Jetstream (JSON over a websocket, no auth), filtered to
                     app.bsky.feed.post, reconnecting with back-off.

Off by default (STREAM_SOCIAL_ENABLED). It only counts posts; no post text is stored.
"""

import json
import re
import threading
import time
from datetime import datetime, timezone
from typing import Callable, Dict, Iterable, List, Optional, Set

from utils.logger import logger

_WORD = re.compile(r"[a-z0-9]+")
MAX_NAMES = 6


def normalise(text: str) -> str:
    """Lower case, words separated by single spaces, padded (so ' kohli ' matches whole words only)."""
    return " " + " ".join(_WORD.findall((text or "").lower())) + " "


class WatchList:
    """{cluster_id: [entity names, normalised]} with a first-word index so a post is checked against few stories."""

    def __init__(self, stories: Dict[str, Iterable[str]]):
        self.names: Dict[str, List[str]] = {}
        self._by_word: Dict[str, Set[str]] = {}
        for cid, names in (stories or {}).items():
            clean = []
            for n in names:
                norm = normalise(n).strip()
                if len(norm) >= 3 and norm not in clean:
                    clean.append(norm)
            if not clean:
                continue
            self.names[cid] = clean[:MAX_NAMES]
            for n in self.names[cid]:
                for w in n.split():
                    self._by_word.setdefault(w, set()).add(cid)

    def __len__(self) -> int:
        return len(self.names)

    def candidates(self, words: Set[str]) -> Set[str]:
        out: Set[str] = set()
        for w in words:
            out |= self._by_word.get(w, set())
        return out


def match_post(text: str, watch: WatchList) -> List[str]:
    """The clusters this post counts for."""
    if not text or not len(watch):
        return []
    norm = normalise(text)
    words = set(norm.split())
    hits = []
    for cid in sorted(watch.candidates(words)):
        names = watch.names[cid]
        found = sum(1 for n in names if f" {n} " in norm)
        if found >= min(2, len(names)):
            hits.append(cid)
    return hits


def bucket_start(t: datetime, minutes: int) -> datetime:
    t = t.astimezone(timezone.utc)
    return t.replace(minute=(t.minute // minutes) * minutes, second=0, microsecond=0)


class Buckets:
    """Thread-safe {(cluster_id, bucket start): count}, drained into Mongo rows by flush()."""

    def __init__(self, minutes: int):
        self.minutes = max(1, int(minutes))
        self._counts: Dict[tuple, int] = {}
        self._lock = threading.Lock()

    def add(self, cluster_ids: Iterable[str], t: datetime) -> None:
        b = bucket_start(t, self.minutes)
        with self._lock:
            for cid in cluster_ids:
                self._counts[(cid, b)] = self._counts.get((cid, b), 0) + 1

    def drain(self) -> List[Dict]:
        with self._lock:
            counts, self._counts = self._counts, {}
        return [{"cluster_id": cid, "bucket": b, "count": n} for (cid, b), n in sorted(counts.items())]


def post_text(event: Dict) -> Optional[str]:
    """The text of a Jetstream commit event that creates a post, else None."""
    if event.get("kind") != "commit":
        return None
    commit = event.get("commit") or {}
    if commit.get("operation") != "create" or commit.get("collection") != "app.bsky.feed.post":
        return None
    return (commit.get("record") or {}).get("text")


class JetstreamCollector:
    """
    Counts posts mentioning hot stories. start() runs the websocket loop on a daemon thread; the worker calls
    stats() for its heartbeat and stop() on shutdown. watch_source() → {cluster_id: [entity names]} and sink(rows)
    are injectable; by default they read the hot clusters from Mongo and $inc rows into social_signals.
    """

    def __init__(self, url: Optional[str] = None, bucket_minutes: Optional[int] = None,
                 refresh_seconds: Optional[float] = None, watch_source: Optional[Callable[[], Dict]] = None,
                 sink: Optional[Callable[[List[Dict]], int]] = None, connect: Optional[Callable] = None,
                 clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc)):
        from config.settings import settings
        self.url = url or settings.stream_social_url
        self.buckets = Buckets(bucket_minutes or settings.stream_social_bucket_minutes)
        self.refresh_seconds = float(refresh_seconds or settings.stream_social_refresh_seconds)
        self.watch_source = watch_source or self._default_watch_source
        self.sink = sink or self._default_sink
        self._connect = connect
        self.clock = clock
        self.watch = WatchList({})
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._last_refresh = 0.0
        self._ws = None
        self.counters = {"posts": 0, "matched": 0, "rows_written": 0, "reconnects": 0, "errors": 0}

    # ── Mongo defaults ───────────────────────────────────────

    @staticmethod
    def _default_watch_source() -> Dict[str, List[str]]:
        from config.personalization import pers_settings as c
        from storage.mongo_store import MongoStore
        db = MongoStore().db
        clusters = list(db[c.clusters_collection].find(
            {"hot.tier": {"$in": ["breaking", "trending"]}}, {"_id": 0, "cluster_id": 1, "members": 1}))
        out: Dict[str, List[str]] = {}
        for cl in clusters:
            names: Dict[str, float] = {}
            for d in db[c.articles_collection].find({c.id_field: {"$in": cl.get("members") or []}},
                                                    {"_id": 0, c.entities_field: 1}):
                for e in d.get(c.entities_field) or []:
                    n = (e.get(c.entity_name_key) or "").strip()
                    if n:
                        names[n] = names.get(n, 0.0) + float(e.get(c.entity_salience_key) or 0.1)
            out[cl["cluster_id"]] = [n for n, _ in sorted(names.items(), key=lambda kv: -kv[1])][:MAX_NAMES]
        return out

    @staticmethod
    def _default_sink(rows: List[Dict]) -> int:
        if not rows:
            return 0
        from pymongo import UpdateOne
        from config.personalization import pers_settings as c
        from storage.mongo_store import MongoStore
        ops = [UpdateOne({"cluster_id": r["cluster_id"], "bucket": r["bucket"]}, {"$inc": {"count": r["count"]}},
                         upsert=True) for r in rows]
        MongoStore().db[c.social_collection].bulk_write(ops, ordered=False)
        return len(ops)

    # ── Loop ─────────────────────────────────────────────────

    def refresh(self) -> None:
        """Write the counted buckets, then rebuild the watch list from the current hot stories."""
        try:
            self.counters["rows_written"] += self.sink(self.buckets.drain())
        except Exception as e:
            self.counters["errors"] += 1
            logger.warning(f"[Social] could not write counts: {e}")
        try:
            self.watch = WatchList(self.watch_source() or {})
        except Exception as e:
            self.counters["errors"] += 1
            logger.warning(f"[Social] could not refresh the watch list: {e}")
        self._last_refresh = time.monotonic()

    def handle(self, message: str) -> List[str]:
        """One Jetstream message → the clusters it counted for."""
        try:
            event = json.loads(message)
        except (TypeError, ValueError):
            return []
        text = post_text(event)
        if text is None:
            return []
        self.counters["posts"] += 1
        hits = match_post(text, self.watch)
        if hits:
            self.counters["matched"] += 1
            self.buckets.add(hits, self.clock())
        if time.monotonic() - self._last_refresh >= self.refresh_seconds:
            self.refresh()
        return hits

    def _open(self):
        if self._connect is not None:
            return self._connect(self.url)
        import websocket
        return websocket.create_connection(self.url, timeout=30)

    def _run(self) -> None:
        backoff = 1.0
        self.refresh()
        while not self._stop.is_set():
            try:
                self._ws = self._open()
                backoff = 1.0
                while not self._stop.is_set():
                    msg = self._ws.recv()
                    if not msg:
                        break
                    self.handle(msg)
            except Exception as e:
                if self._stop.is_set():
                    break
                self.counters["errors"] += 1
                logger.warning(f"[Social] Jetstream connection lost ({type(e).__name__}: {e}); retry in {backoff:.0f} s")
            finally:
                self._close_ws()
            if self._stop.wait(backoff):
                break
            self.counters["reconnects"] += 1
            backoff = min(backoff * 2, 300.0)
        self.refresh()

    def _close_ws(self) -> None:
        ws, self._ws = self._ws, None
        if ws is not None:
            try:
                ws.close()
            except Exception:
                pass

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, name="Jetstream", daemon=True)
        self._thread.start()
        logger.info(f"[Social] Counting Bluesky posts about hot stories ({self.url})")

    def stop(self) -> None:
        self._stop.set()
        self._close_ws()
        if self._thread is not None:
            self._thread.join(timeout=10)
            self._thread = None

    def stats(self) -> Dict:
        return {**self.counters, "watching": len(self.watch)}

