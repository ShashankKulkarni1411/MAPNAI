"""
MAPNAI — stream_worker.py
The continuous news stream (continousexplanation.md §4–5): a long-running process that

  1. polls each RSS source when it is due — its own adaptive interval (stream/polling.py), a conditional GET and a
     seen-item filter (agents/rss_fetcher.poll_rss_source) — several feeds in parallel;
  2. records front-page items of top-stories feeds as prominence (hotness signal);
  3. polls the quota-limited news APIs and the scrapers on fixed intervals;
  4. buffers the new items and flushes them as a micro-batch through the shared ingestion phases
     (ingestion_pipeline.ingest_batch: preprocess → images → NER → store → sightings), with one in-memory
     duplicate index for its lifetime;
  5. runs Agents 1–2 on every flushed article and Agents 3–4 (LLM) on a bounded number of pending articles,
     hottest stories first, with models loaded once (pipeline.AgentPool);
  6. writes the FAISS index at most every stream_faiss_save_seconds and a heartbeat every tick;
  7. optionally counts Bluesky Jetstream mentions of trending stories (agents/social_signal.py).

Clustering, hotness, alerts and push run in the API process (personalization jobs) and read what this writes.

Usage:
  python stream_worker.py                    # run until Ctrl+C
  python stream_worker.py --once             # poll every source once, flush, run the agents, exit
  python stream_worker.py --no-agents        # ingest only (leave Agents 1-4 to `python pipeline.py --schedule`)
  python stream_worker.py --llm-per-flush 0  # Agents 1-2 only; no LLM calls from the worker
"""

import argparse
import json
import signal
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Callable, Dict, List, Optional

from config.settings import settings
from config.sources import STREAM_RSS_SOURCES, RSSSource
from stream import polling
from utils.logger import logger

API_SOURCE = SimpleNamespace(name="News APIs", url="newsapi+gnews+newsdata", domain="general", active=True,
                             role="section", store_items=True, kind="api")
SCRAPER_SOURCE = SimpleNamespace(name="Scrapers", url="web_scraper.SCRAPER_TARGETS", domain="general", active=True,
                                 role="section", store_items=True, kind="scraper")


DEFAULT = object()      # "use the built-in collaborator" (None disables api_fetch / scrape / social)


def _now() -> datetime:
    return datetime.now(timezone.utc)


class StreamWorker:
    """
    One worker per database. Every collaborator is injectable (tests run it with fakes):
      state      SourceStateStore (source_state, prominence, stream_status)
      poller     (source, state_doc) → PollResult             default agents.rss_fetcher.poll_rss_source
      ingest     (raw, deduplicator=…, save_faiss=…) → dict   default ingestion_pipeline.ingest_batch
      agents     (agents, article_ids=None, limit=None) → dict  default pipeline.run_agent_pipeline with a pool
      api_fetch  () → [RawArticle]                            default agents.api_fetcher.fetch_all_apis; None: off
      scrape     () → [RawArticle]                            default agents.web_scraper.scrape_all_targets; None: off
      seed       () → [{dedup_hash, article_id, source_name}] default MongoStore.get_recent_hash_docs
      save_faiss () → None                                    default the ingestion FAISS store's save()
    """

    def __init__(self, sources: Optional[List[RSSSource]] = None, state=None, cfg=None,
                 clock: Callable[[], datetime] = _now, sleep: Callable[[float], None] = time.sleep,
                 poller=None, ingest=None, agents=None, api_fetch=DEFAULT, scrape=DEFAULT, seed=None,
                 save_faiss=None,
                 run_agents: Optional[bool] = None, llm_per_flush: Optional[int] = None, social=None):
        self.cfg = cfg or settings
        self.sources = list(sources if sources is not None else STREAM_RSS_SOURCES)
        self.by_name = {s.name: s for s in self.sources}
        self.clock, self.sleep = clock, sleep
        self._state = state
        self.poller = poller or self._default_poller
        self.ingest = ingest or self._default_ingest
        self.agents = agents or self._default_agents
        self.api_fetch = self._default_api_fetch if api_fetch is DEFAULT else api_fetch
        self.scrape = self._default_scrape if scrape is DEFAULT else scrape
        self.seed = seed or self._default_seed
        self.save_faiss = save_faiss or self._default_save_faiss
        self.run_agents = self.cfg.stream_run_agents if run_agents is None else run_agents
        self.llm_per_flush = self.cfg.stream_llm_per_flush if llm_per_flush is None else llm_per_flush
        self.social = social

        self.buffer: List = []
        self.dedup = None
        self._pool = None
        self._stop = False
        self._seeded_at: Optional[datetime] = None
        self._last_flush: Optional[datetime] = None
        self._last_save: Optional[datetime] = None
        self._faiss_dirty = False
        self._last_api: Optional[datetime] = None
        self._last_scrape: Optional[datetime] = None
        self.started_at: Optional[datetime] = None
        self.ticks = 0
        self.flushes = 0
        self.totals: Dict[str, int] = {"polls": 0, "not_modified": 0, "poll_errors": 0, "new_items": 0,
                                       "prominence": 0, "stored": 0, "duplicates": 0, "sightings": 0,
                                       "agent_articles": 0, "llm_articles": 0}
        self.last_flush_stats: Optional[Dict] = None

    # ── Collaborators ────────────────────────────────────────

    @property
    def state(self):
        if self._state is None:
            from storage.source_state_store import SourceStateStore
            from ingestion_pipeline import _get_mongo
            self._state = SourceStateStore(_get_mongo())
        return self._state

    @staticmethod
    def _default_poller(source, state_doc):
        from agents.rss_fetcher import poll_rss_source
        return poll_rss_source(source, state_doc)

    @staticmethod
    def _default_ingest(raw, deduplicator=None, save_faiss=False):
        from ingestion_pipeline import ingest_batch
        return ingest_batch(raw, deduplicator=deduplicator, save_faiss=save_faiss)

    def _default_agents(self, agents, article_ids=None, limit=None):
        from pipeline import AgentPool, run_agent_pipeline
        if self._pool is None:
            from ingestion_pipeline import _get_faiss, _get_mongo
            try:
                faiss_store = _get_faiss()
            except Exception as e:
                logger.warning(f"[Stream] FAISS unavailable for the agents: {e}")
                faiss_store = None
            self._pool = AgentPool(mongo=_get_mongo(), faiss_store=faiss_store)
        return run_agent_pipeline(limit=limit or max(1, len(article_ids or [])), agents=set(agents),
                                  pool=self._pool, article_ids=article_ids)

    @staticmethod
    def _default_api_fetch():
        from agents.api_fetcher import fetch_all_apis
        return fetch_all_apis(max_per_domain=settings.max_articles_per_source)

    @staticmethod
    def _default_scrape():
        from agents.web_scraper import scrape_all_targets
        return scrape_all_targets(max_per_target=10)

    @staticmethod
    def _default_seed():
        from ingestion_pipeline import _get_mongo
        return _get_mongo().get_recent_hash_docs(settings.dedup_seed_days)

    @staticmethod
    def _default_save_faiss():
        from ingestion_pipeline import _get_faiss
        _get_faiss().save()

    # ── Lifecycle ────────────────────────────────────────────

    def start(self) -> None:
        now = self.clock()
        self.started_at = now
        configured = list(self.sources)
        if self.api_fetch:
            configured.append(API_SOURCE)
        if self.scrape:
            configured.append(SCRAPER_SOURCE)
        n = self.state.ensure_sources(configured, now)
        logger.info(f"[Stream] Started with {n} sources (tick {self.cfg.stream_tick_seconds:.0f} s, "
                    f"flush every {self.cfg.stream_flush_seconds:.0f} s or {self.cfg.stream_flush_max} items)")
        self._reseed(now)
        if self.social is not None:
            self.social.start()

    def stop(self, *_args) -> None:
        self._stop = True

    def shutdown(self) -> None:
        """Flush what is buffered, write the FAISS index, stop the social collector, close the agents."""
        now = self.clock()
        try:
            if self.buffer:
                self.flush(now)
            self._save_faiss(now, force=True)
        finally:
            if self.social is not None:
                self.social.stop()
            if self._pool is not None:
                self._pool.close()
                self._pool = None
            self._heartbeat(now, running=False)
            logger.info(f"[Stream] Stopped after {self.ticks} ticks, {self.flushes} flushes: {self.totals}")

    def run(self, max_ticks: Optional[int] = None) -> Dict:
        self.start()
        try:
            while not self._stop and (max_ticks is None or self.ticks < max_ticks):
                self.tick()
                if self._stop or (max_ticks is not None and self.ticks >= max_ticks):
                    break
                self.sleep(self.cfg.stream_tick_seconds)
        finally:
            self.shutdown()
        return self.status()

    def run_once(self) -> Dict:
        """Poll every source now (ignoring their schedule), flush, run the agents, exit."""
        self.start()
        try:
            self.tick(force_all=True)
            if self.buffer:
                self.flush(self.clock())
        finally:
            self.shutdown()
        return self.status()

    # ── One tick ─────────────────────────────────────────────

    def tick(self, force_all: bool = False) -> Dict:
        now = self.clock()
        self.ticks += 1
        if self._seeded_at is None or now - self._seeded_at >= timedelta(hours=self.cfg.stream_reseed_hours):
            self._reseed(now)

        polled = self.poll_due(now, force_all=force_all)
        fixed = self.poll_fixed(now, force_all=force_all)

        flushed = None
        if self.buffer and (len(self.buffer) >= self.cfg.stream_flush_max or self._last_flush is None
                            or (now - self._last_flush).total_seconds() >= self.cfg.stream_flush_seconds):
            flushed = self.flush(now)
        elif not self.buffer and self._last_flush is None:
            self._last_flush = now          # nothing yet: the flush timer starts now
        self._save_faiss(now)
        self._heartbeat(now)
        return {"polled": polled, "fixed": fixed, "flushed": flushed, "buffer": len(self.buffer)}

    def poll_due(self, now: datetime, force_all: bool = False) -> int:
        """Poll every due RSS source (in parallel), record each outcome, buffer the new articles."""
        states = {s["name"]: s for s in self.state.all() if s["name"] in self.by_name}
        rows = [s for s in states.values() if s.get("active", True)] if force_all else polling.due(states.values(), now)
        if not rows:
            return 0
        sources = [self.by_name[r["name"]] for r in rows]
        workers = max(1, min(int(self.cfg.stream_poll_workers), len(sources)))
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="Poll") as pool:
            results = list(pool.map(lambda src: self._safe_poll(src, states.get(src.name) or {}), sources))

        prominence = []
        for source, result in zip(sources, results):
            prev = (states.get(source.name) or {}).get("interval_s")
            interval = polling.next_interval(prev, result.status, result.new_count, source.role, self.cfg)
            self.state.record_poll(source.name, status=result.status, new_count=result.new_count,
                                   interval_s=interval, now=now, etag=result.etag,
                                   last_modified=result.last_modified, seen=result.seen, error=result.error)
            self.totals["polls"] += 1
            self.totals["not_modified"] += result.status == polling.NOT_MODIFIED
            self.totals["poll_errors"] += result.status == polling.ERROR
            self.totals["new_items"] += result.new_count
            self.buffer.extend(result.articles)
            prominence.extend(result.prominence)
        if prominence:
            try:
                self.totals["prominence"] += self.state.add_prominence(prominence, now)
            except Exception as e:
                logger.warning(f"[Stream] Prominence not recorded: {e}")
        return len(sources)

    def _safe_poll(self, source, state_doc):
        try:
            return self.poller(source, state_doc)
        except Exception as e:     # a poller must not take the tick down
            from agents.rss_fetcher import PollResult
            return PollResult(source.name, polling.ERROR, error=f"{type(e).__name__}: {e}"[:300])

    def poll_fixed(self, now: datetime, force_all: bool = False) -> Dict[str, int]:
        """News APIs and scrapers: fixed intervals (quotas), recorded in source_state like the feeds."""
        out = {}
        jobs = [("api", self.api_fetch, API_SOURCE, self.cfg.stream_api_interval_minutes),
                ("scraper", self.scrape, SCRAPER_SOURCE, self.cfg.stream_scraper_interval_minutes)]
        for kind, fn, source, minutes in jobs:
            if not fn:
                continue
            last = self._last_api if kind == "api" else self._last_scrape
            if not force_all and last is not None and now - last < timedelta(minutes=minutes):
                continue
            if kind == "api":
                self._last_api = now
            else:
                self._last_scrape = now
            try:
                articles = list(fn() or [])
                status, error = polling.OK, None
            except Exception as e:
                articles, status, error = [], polling.ERROR, f"{type(e).__name__}: {e}"[:300]
                logger.warning(f"[Stream] {source.name} failed: {error}")
            self.buffer.extend(articles)
            self.totals["new_items"] += len(articles)
            self.state.record_poll(source.name, status=status, new_count=len(articles),
                                   interval_s=float(minutes) * 60, now=now, error=error)
            out[kind] = len(articles)
        return out

    # ── Flush ────────────────────────────────────────────────

    def flush(self, now: datetime) -> Dict:
        """The buffered items through the ingestion phases, then the agents."""
        raw, self.buffer = self.buffer, []
        self._last_flush = now
        started = time.perf_counter()
        result = self.ingest(raw, deduplicator=self.dedup, save_faiss=False)
        ids = list(result.get("article_ids") or [])
        stats: Dict = {"at": now, "items": len(raw), "stored": result.get("stored", 0),
                       "duplicates": result.get("duplicates", 0), "sightings": result.get("sightings", 0),
                       "quality_failed": result.get("quality_failed", 0), "errors": list(result.get("errors") or [])}
        if ids:
            self._faiss_dirty = True
        if self.run_agents and ids:
            stats["agents_1_2"] = self._run_agents({1, 2}, article_ids=ids)
            self.totals["agent_articles"] += len(ids)
        if self.run_agents and self.llm_per_flush > 0:
            llm = self._run_agents({3, 4}, limit=self.llm_per_flush)
            stats["agents_3_4"] = llm
            self.totals["llm_articles"] += int((llm or {}).get("pending_found", 0) or 0)
        stats["seconds"] = round(time.perf_counter() - started, 2)
        self.flushes += 1
        self.totals["stored"] += stats["stored"]
        self.totals["duplicates"] += stats["duplicates"]
        self.totals["sightings"] += stats["sightings"]
        self.last_flush_stats = stats
        logger.info(f"[Stream] Flush {self.flushes}: {stats['items']} items → stored {stats['stored']}, "
                    f"duplicates {stats['duplicates']}, sightings {stats['sightings']} ({stats['seconds']} s)")
        return stats

    def _run_agents(self, agents, article_ids=None, limit=None) -> Optional[Dict]:
        try:
            out = self.agents(agents, article_ids=article_ids, limit=limit)
        except Exception as e:
            logger.error(f"[Stream] Agents {sorted(agents)} failed: {e}")
            return {"error": f"{type(e).__name__}: {e}"}
        keys = ("pending_found", "articles_ok", "failed", "ner_processed", "classified", "summarized",
                "risk_scored", "risk_shared", "out_of_scope")
        return {k: out.get(k) for k in keys if k in (out or {})}

    # ── Housekeeping ─────────────────────────────────────────

    def _reseed(self, now: datetime) -> None:
        """A fresh duplicate index from the recent stored fingerprints (old stories age out of it)."""
        from utils.deduplicator import ArticleDeduplicator
        dedup = ArticleDeduplicator(simhash_threshold=3, minhash_threshold=0.5)
        try:
            dedup.load_existing_hashes(self.seed() or [])
        except Exception as e:
            logger.warning(f"[Stream] Could not seed the duplicate index: {e}")
        self.dedup, self._seeded_at = dedup, now

    def _save_faiss(self, now: datetime, force: bool = False) -> None:
        if not self._faiss_dirty:
            return
        if not force and self._last_save is not None and \
                (now - self._last_save).total_seconds() < self.cfg.stream_faiss_save_seconds:
            return
        try:
            self.save_faiss()
            self._faiss_dirty = False
        except Exception as e:
            logger.warning(f"[Stream] FAISS save failed: {e}")
        self._last_save = now

    def status(self) -> Dict:
        return {"started_at": self.started_at, "ticks": self.ticks, "flushes": self.flushes,
                "buffer": len(self.buffer), "totals": dict(self.totals), "last_flush": self.last_flush_stats,
                "last_flush_at": self._last_flush, "dedup_size": len(self.dedup) if self.dedup else 0}

    def _heartbeat(self, now: datetime, running: bool = True) -> None:
        try:
            self.state.heartbeat({**self.status(), "running": running, "last_tick_at": now,
                                  "tick_seconds": self.cfg.stream_tick_seconds,
                                  "social": self.social.stats() if self.social is not None else None})
        except Exception as e:
            logger.debug(f"[Stream] Heartbeat not written: {e}")


def build_worker(args) -> StreamWorker:
    social = None
    if settings.stream_social_enabled:
        from agents.social_signal import JetstreamCollector
        social = JetstreamCollector()
    return StreamWorker(run_agents=False if args.no_agents else None, llm_per_flush=args.llm_per_flush,
                        social=social)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="MAPNAI continuous news stream")
    parser.add_argument("--once", action="store_true", help="poll every source once, flush, run the agents, exit")
    parser.add_argument("--max-ticks", type=int, default=None, help="stop after this many ticks")
    parser.add_argument("--no-agents", action="store_true", help="ingest only; no Agents 1-4 in the worker")
    parser.add_argument("--llm-per-flush", type=int, default=None,
                        help=f"Agents 3-4 articles per flush (default {settings.stream_llm_per_flush}; 0 = none)")
    args = parser.parse_args(argv)

    from ingestion_pipeline import _get_mongo
    if not _get_mongo().is_available():
        logger.error("[Stream] MongoDB is unavailable; the stream needs it (source state, articles).")
        return 1
    worker = build_worker(args)
    signal.signal(signal.SIGINT, worker.stop)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, worker.stop)
    result = worker.run_once() if args.once else worker.run(max_ticks=args.max_ticks)
    print(json.dumps(result, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
