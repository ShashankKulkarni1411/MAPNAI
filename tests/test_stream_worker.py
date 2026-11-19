"""
MAPNAI — tests/test_stream_worker.py
The stream worker loop (stream_worker.py) with fakes: due-only polling with adaptive intervals stored per source,
prominence, micro-batch flushes (by size and by time), agents on the flushed ids, the fixed-interval API / scraper
polls, FAISS save throttling, the heartbeat, reseeding, and a clean shutdown.
"""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from agents.rss_fetcher import PollResult
from config.settings import Settings
from storage.source_state_store import SourceStateStore
from stream import polling
from stream_worker import StreamWorker
from tests.fakes import FakeMongo

T0 = datetime.now(timezone.utc).replace(microsecond=0)   # prominence has a 3-day TTL index (mongomock applies it)
CFG = Settings(_env_file=None).model_copy(update={"stream_flush_max": 5, "stream_flush_seconds": 120.0,
                                                  "stream_faiss_save_seconds": 600.0, "stream_poll_workers": 2})


def src(name, role="section"):
    return SimpleNamespace(name=name, url=f"https://x/{name}.xml", domain="sports", active=True, role=role,
                           store_items=True)


class Clock:
    def __init__(self):
        self.now = T0

    def __call__(self):
        return self.now

    def advance(self, **kw):
        self.now += timedelta(**kw)


class Harness:
    """A worker over a mongomock source-state store, a scripted poller and recording ingest / agents."""

    def __init__(self, sources, script, **kw):
        self.clock = Clock()
        self.state = SourceStateStore(FakeMongo())
        self.script = script                     # name → list of PollResult (one per poll) or a callable
        self.polls, self.ingested, self.agent_calls, self.saves = [], [], [], 0
        self.seeded = 0
        self.worker = StreamWorker(
            sources=sources, state=self.state, cfg=kw.pop("cfg", CFG), clock=self.clock, sleep=lambda s: None,
            poller=self.poll, ingest=self.ingest, agents=self.agents, api_fetch=kw.pop("api_fetch", None),
            scrape=kw.pop("scrape", None), seed=self.seed, save_faiss=self.save, **kw)

    def poll(self, source, state_doc):
        self.polls.append((source.name, dict(state_doc)))
        queue = self.script[source.name]
        if isinstance(queue, list):
            item = queue.pop(0) if queue else ok(source.name, [])     # script used up: nothing new
        else:
            item = queue
        return item(source, state_doc) if callable(item) else item

    def ingest(self, raw, deduplicator=None, save_faiss=False):
        assert save_faiss is False and deduplicator is self.worker.dedup
        self.ingested.append(list(raw))
        return {"stored": len(raw), "duplicates": 0, "sightings": 0, "article_ids": [f"id-{a}" for a in raw]}

    def agents(self, agents, article_ids=None, limit=None):
        self.agent_calls.append((sorted(agents), article_ids, limit))
        return {"pending_found": len(article_ids or []) or limit, "articles_ok": 1}

    def seed(self):
        self.seeded += 1
        return [{"dedup_hash": "00000000000000ff", "article_id": "old", "source_name": "A"}]

    def save(self):
        self.saves += 1


def ok(name, articles, seen=None, prominence=None):
    return PollResult(name, polling.OK, articles=list(articles), new_count=len(articles), seen=seen or [],
                      prominence=prominence or [], etag='"e"')


class TestPolling:
    def test_due_sources_are_polled_and_their_interval_stored(self):
        h = Harness([src("a"), src("b", "top_stories")], {
            "a": [ok("a", ["a1", "a2"], seen=["k1"])],
            "b": [ok("b", [], prominence=[{"feed": "b", "url": "https://x/1", "title": "Big story", "domain": "x"}])],
        })
        h.worker.start()
        out = h.worker.tick()
        assert out["polled"] == 2 and sorted(n for n, _ in h.polls) == ["a", "b"]
        a, b = h.state.get("a"), h.state.get("b")
        assert a["interval_s"] == pytest.approx(900 * 0.8) and a["seen"] == ["k1"] and a["etag"] == '"e"'
        assert b["interval_s"] == pytest.approx(900 * 1.25)
        assert len(h.state.prominence_since(T0 - timedelta(hours=1))) == 1
        assert h.worker.totals["new_items"] == 2 and h.worker.totals["prominence"] == 1

        h.clock.advance(seconds=15)
        assert h.worker.tick()["polled"] == 0                    # nothing due 15 s later
        h.clock.advance(seconds=720)
        assert h.worker.tick()["polled"] == 1                    # a (12 min) is due, b (18.75 min) is not
        assert h.polls[-1][0] == "a" and h.polls[-1][1]["seen"] == ["k1"]

    def test_a_failing_poller_backs_off_and_does_not_stop_the_tick(self):
        def boom(source, state_doc):
            raise RuntimeError("feed exploded")
        h = Harness([src("bad"), src("good")], {"bad": boom, "good": [ok("good", ["g1"])]})
        h.worker.start()
        assert h.worker.tick()["polled"] == 2
        bad = h.state.get("bad")
        assert bad["last_status"] == polling.ERROR and "feed exploded" in bad["last_error"]
        assert bad["interval_s"] == pytest.approx(1200.0) and bad["consecutive_failures"] == 1   # 900 × 2, capped
        assert h.worker.totals["poll_errors"] == 1

    def test_a_source_dropped_from_config_is_never_polled(self):
        h = Harness([src("a")], {"a": [ok("a", [])]})
        h.state.ensure_sources([src("a"), src("gone")], T0)
        h.worker.start()
        h.worker.tick()
        assert [n for n, _ in h.polls] == ["a"] and h.state.get("gone")["active"] is False


class TestFlush:
    def test_flush_by_size_and_by_time_then_agents(self):
        h = Harness([src("a")], {"a": [ok("a", ["x1", "x2", "x3"]), ok("a", ["x4", "x5"]), ok("a", ["x6"])]})
        h.worker.start()
        h.worker.tick()                                          # first tick: buffer 3, flush timer starts
        assert h.ingested == [["x1", "x2", "x3"]]                # the first items go out at once
        assert h.agent_calls[0] == ([1, 2], ["id-x1", "id-x2", "id-x3"], None)
        assert h.agent_calls[1] == ([3, 4], None, CFG.stream_llm_per_flush)

        h.clock.advance(seconds=720)
        h.worker.tick()                                          # 2 items, 12 min after the last flush → flush
        assert h.ingested[-1] == ["x4", "x5"]
        h.clock.advance(seconds=30)
        h.state.record_poll("a", status=polling.OK, new_count=1, interval_s=300, now=h.clock.now - timedelta(hours=1))
        h.worker.tick()                                          # 1 item, 30 s after the last flush → buffered
        assert h.ingested[-1] == ["x4", "x5"] and h.worker.buffer == ["x6"]
        h.worker.shutdown()                                      # shutdown flushes what is buffered
        assert h.ingested[-1] == ["x6"] and h.worker.buffer == []

    def test_size_trigger(self):
        h = Harness([src("a")], {"a": [ok("a", ["y1", "y2"]), ok("a", [f"z{i}" for i in range(6)])]})
        h.worker.start()
        h.worker.tick()
        h.state.record_poll("a", status=polling.OK, new_count=1, interval_s=300, now=T0 - timedelta(hours=1))
        h.clock.advance(seconds=20)
        h.worker.tick()                                          # 6 ≥ flush_max (5) → flushed at 20 s
        assert len(h.ingested) == 2 and len(h.ingested[-1]) == 6

    def test_no_agents_and_no_llm(self):
        h = Harness([src("a")], {"a": [ok("a", ["x1"])]}, run_agents=False)
        h.worker.start()
        h.worker.tick()
        assert h.ingested and h.agent_calls == []
        h2 = Harness([src("a")], {"a": [ok("a", ["x1"])]}, llm_per_flush=0)
        h2.worker.start()
        h2.worker.tick()
        assert [c[0] for c in h2.agent_calls] == [[1, 2]]

    def test_agent_failure_is_reported_not_raised(self):
        h = Harness([src("a")], {"a": [ok("a", ["x1"])]})
        h.agents = None
        h.worker.agents = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("model OOM"))
        h.worker.start()
        out = h.worker.tick()
        assert "model OOM" in out["flushed"]["agents_1_2"]["error"]


class TestHousekeeping:
    def test_faiss_saved_at_most_every_interval_and_on_shutdown(self):
        h = Harness([src("a")], {"a": [ok("a", ["x1"]), ok("a", ["x2"]), ok("a", ["x3"])]})
        h.worker.start()
        h.worker.tick()
        assert h.saves == 1                                      # first save right after the first stored batch
        h.clock.advance(seconds=720)
        h.worker.tick()
        assert h.saves == 2
        h.state.record_poll("a", status=polling.OK, new_count=1, interval_s=300, now=T0)
        h.clock.advance(seconds=200)
        h.worker.tick()                                          # stored again but < 600 s since the last save
        assert h.saves == 2
        h.worker.shutdown()
        assert h.saves == 3

    def test_heartbeat_and_status(self):
        h = Harness([src("a")], {"a": [ok("a", ["x1"])]})
        h.worker.start()
        h.worker.tick()
        hb = h.state.status()
        assert hb["running"] is True and hb["ticks"] == 1 and hb["flushes"] == 1 and hb["dedup_size"] == 1
        assert hb["last_tick_at"] == T0 and hb["totals"]["stored"] == 1
        h.worker.shutdown()
        assert h.state.status()["running"] is False

    def test_reseed_daily(self):
        h = Harness([src("a")], {"a": ok("a", [])})
        h.worker.start()
        assert h.seeded == 1
        h.clock.advance(hours=23)
        h.worker.tick()
        assert h.seeded == 1
        h.clock.advance(hours=2)
        h.worker.tick()
        assert h.seeded == 2

    def test_apis_and_scrapers_on_fixed_intervals(self):
        calls = {"api": 0, "scraper": 0}

        def api():
            calls["api"] += 1
            return ["api1"]

        def scrape():
            calls["scraper"] += 1
            raise RuntimeError("site down")
        h = Harness([src("a")], {"a": ok("a", [])}, api_fetch=api, scrape=scrape)
        h.worker.start()
        h.worker.tick()
        assert calls == {"api": 1, "scraper": 1} and h.ingested == [["api1"]]
        h.clock.advance(minutes=31)
        h.worker.tick()
        assert calls == {"api": 1, "scraper": 2}
        h.clock.advance(minutes=30)
        h.worker.tick()
        assert calls == {"api": 2, "scraper": 3}
        assert h.state.get("Scrapers")["last_status"] == polling.ERROR
        assert h.state.get("News APIs")["kind"] == "api"

    def test_run_stops_after_max_ticks_and_run_once_polls_everything(self):
        h = Harness([src("a"), src("b")], {"a": ok("a", ["x"]), "b": ok("b", [])})
        out = h.worker.run(max_ticks=3)
        assert out["ticks"] == 3 and h.state.status()["running"] is False
        h2 = Harness([src("a"), src("b")], {"a": ok("a", ["x"]), "b": ok("b", [])})
        h2.state.ensure_sources([src("a"), src("b")], T0)
        h2.state.record_poll("a", status=polling.OK, new_count=0, interval_s=3600, now=T0)   # not due
        out = h2.worker.run_once()
        assert sorted(n for n, _ in h2.polls) == ["a", "b"] and out["flushes"] == 1
