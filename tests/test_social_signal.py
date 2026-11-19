"""
MAPNAI — tests/test_social_signal.py
The optional Bluesky social signal (agents/social_signal.py): watch list, post matching, buckets, Jetstream events,
the collector's refresh and its reconnecting loop (with a fake connection).
"""

import json
import threading
from datetime import datetime, timezone

from agents.social_signal import (Buckets, JetstreamCollector, WatchList, bucket_start, match_post, normalise,
                                  post_text)

T = datetime(2026, 9, 29, 12, 7, 30, tzinfo=timezone.utc)
STORIES = {"k1": ["Virat Kohli", "India", "World Cup Final"], "p1": ["RBI"], "x": ["", "a"]}


def event(text, op="create", collection="app.bsky.feed.post", kind="commit"):
    return json.dumps({"did": "did:plc:x", "kind": kind,
                       "commit": {"operation": op, "collection": collection, "record": {"text": text}}})


class TestMatching:
    def test_normalise_whole_words(self):
        assert normalise("Kohli's 100!") == " kohli s 100 "

    def test_needs_two_names_unless_the_story_has_one(self):
        watch = WatchList(STORIES)
        assert len(watch) == 2                                            # "x" has no usable name
        assert match_post("Virat Kohli out before the World Cup final!", watch) == ["k1"]
        assert match_post("India win again", watch) == []                 # one name of three: too loose
        assert match_post("RBI holds rates", watch) == ["p1"]
        assert match_post("The RBIs are out", watch) == []                # whole words only
        assert match_post("", watch) == [] and match_post("RBI", WatchList({})) == []


class TestBuckets:
    def test_counts_per_cluster_and_ten_minute_bucket(self):
        b = Buckets(10)
        assert bucket_start(T, 10) == datetime(2026, 9, 29, 12, 0, tzinfo=timezone.utc)
        b.add(["k1"], T)
        b.add(["k1", "p1"], T)
        b.add(["k1"], T.replace(minute=12))
        rows = b.drain()
        assert rows == [
            {"cluster_id": "k1", "bucket": datetime(2026, 9, 29, 12, 0, tzinfo=timezone.utc), "count": 2},
            {"cluster_id": "k1", "bucket": datetime(2026, 9, 29, 12, 10, tzinfo=timezone.utc), "count": 1},
            {"cluster_id": "p1", "bucket": datetime(2026, 9, 29, 12, 0, tzinfo=timezone.utc), "count": 1},
        ]
        assert b.drain() == []


class TestEvents:
    def test_only_created_posts(self):
        assert post_text(json.loads(event("hello"))) == "hello"
        assert post_text(json.loads(event("hello", op="delete"))) is None
        assert post_text(json.loads(event("hello", collection="app.bsky.feed.like"))) is None
        assert post_text(json.loads(event("hello", kind="identity"))) is None


class FakeWS:
    def __init__(self, messages, done):
        self.messages, self.done, self.closed = list(messages), done, False

    def recv(self):
        if self.messages:
            return self.messages.pop(0)
        self.done.set()
        raise ConnectionError("server closed")

    def close(self):
        self.closed = True


class TestCollector:
    def collector(self, **kw):
        self.written = []
        return JetstreamCollector(url="wss://test", bucket_minutes=10, refresh_seconds=3600,
                                  watch_source=lambda: STORIES, sink=lambda rows: self.written.extend(rows) or len(rows),
                                  clock=lambda: T, **kw)

    def test_handle_counts_matches_and_refresh_writes_them(self):
        c = self.collector()
        c.refresh()
        assert c.handle(event("Virat Kohli and India lose the World Cup Final")) == ["k1"]
        assert c.handle(event("nothing here")) == []
        assert c.handle("not json") == [] and c.handle(event("RBI", op="delete")) == []
        assert c.stats() == {"posts": 2, "matched": 1, "rows_written": 0, "reconnects": 0, "errors": 0,
                             "watching": 2}
        c.refresh()
        assert self.written == [{"cluster_id": "k1", "bucket": bucket_start(T, 10), "count": 1}]
        assert c.stats()["rows_written"] == 1

    def test_a_failing_watch_source_keeps_the_old_list(self):
        c = self.collector()
        c.refresh()
        c.watch_source = lambda: (_ for _ in ()).throw(RuntimeError("mongo down"))
        c.refresh()
        assert len(c.watch) == 2 and c.stats()["errors"] == 1

    def test_loop_reads_reconnects_and_stops(self):
        done = threading.Event()
        sockets = []

        def connect(url):
            ws = FakeWS([event("RBI cuts rates"), event("RBI again")] if not sockets else [], done)
            sockets.append(ws)
            return ws
        c = self.collector(connect=connect)
        c.start()
        assert done.wait(5)
        c.stop()
        assert c.counters["posts"] == 2 and c.counters["matched"] == 2 and sockets[0].closed
        assert c.counters["errors"] >= 1
        assert {r["cluster_id"] for r in self.written} == {"p1"}           # flushed on stop
        assert sum(r["count"] for r in self.written) == 2
