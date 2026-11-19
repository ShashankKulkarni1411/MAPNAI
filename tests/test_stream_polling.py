"""
MAPNAI — tests/test_stream_polling.py
Adaptive polling rules (stream/polling.py): interval factors and bounds, item keys, the seen list, due order.
"""

import math
from datetime import datetime, timedelta, timezone

import pytest

from config.settings import Settings
from stream import polling

CFG = Settings(_env_file=None)
NOW = datetime(2026, 9, 29, 12, 0, tzinfo=timezone.utc)


class TestNextInterval:
    @pytest.mark.parametrize("status,new,factor", [
        (polling.ERROR, 0, 2.0), (polling.ERROR, 9, 2.0),             # an error backs off whatever it returned
        (polling.NOT_MODIFIED, 0, 1.25), (polling.OK, 0, 1.25),
        (polling.OK, 1, 0.8), (polling.OK, 4, 0.8),
        (polling.OK, 5, 0.5), (polling.OK, 40, 0.5),
    ])
    def test_factors(self, status, new, factor):
        assert polling.next_interval(600.0, status, new, "section", CFG) == pytest.approx(600.0 * factor)

    def test_first_poll_starts_from_the_initial_interval(self):
        assert polling.next_interval(None, polling.OK, 1, "section", CFG) == pytest.approx(900 * 0.8)
        assert polling.initial_interval("section", CFG) == 900.0

    def test_bounds_per_role(self):
        assert polling.bounds("top_stories", CFG) == (120.0, 1200.0)
        assert polling.bounds("section", CFG) == (300.0, 1200.0)
        assert polling.next_interval(130.0, polling.OK, 9, "top_stories", CFG) == 120.0
        assert polling.next_interval(310.0, polling.OK, 9, "section", CFG) == 300.0
        assert polling.next_interval(1000.0, polling.ERROR, 0, "section", CFG) == 1200.0

    def test_equilibrium_is_half_the_polls_finding_something(self):
        # ln 1.25 = -ln 0.8: one slow-down and one speed-up cancel, so alternating outcomes keep the interval
        assert math.log(polling.SLOWER) == pytest.approx(-math.log(polling.FASTER))
        t = 600.0
        for i in range(20):
            t = polling.next_interval(t, polling.OK, i % 2, "section", CFG)
        assert t == pytest.approx(600.0)

    def test_a_dead_feed_backs_off_to_the_maximum(self):
        t = None
        for _ in range(30):
            t = polling.next_interval(t, polling.NOT_MODIFIED, 0, "section", CFG)
        assert t == CFG.stream_max_interval_s == 1200.0


class TestKeysAndSeen:
    def test_item_key_prefers_the_guid(self):
        assert polling.item_key({"id": "g1", "link": "https://x/1", "title": "T"}) == "id:g1"
        assert polling.item_key({"guid": " g2 ", "link": "https://x/2"}) == "guid:g2"
        assert polling.item_key({"link": "https://x/3", "title": "T"}) == "link:https://x/3"
        assert polling.item_key({"title": "Only a title"}) == "title:Only a title"
        assert polling.item_key({"title": "  "}) == ""

    def test_item_key_reads_attributes(self):
        class Entry:
            link = "https://x/4"
        assert polling.item_key(Entry()) == "link:https://x/4"

    def test_remember_seen_newest_first_unique_capped(self):
        assert polling.remember_seen(["a", "b", "c"], ["d", "a"], 4) == ["d", "a", "b", "c"]
        assert polling.remember_seen(["a", "b", "c"], ["d", "e"], 3) == ["d", "e", "a"]
        assert polling.remember_seen(None, ["x", "", "x"], 5) == ["x"]


class TestDue:
    def test_never_polled_first_then_most_overdue(self):
        states = [
            {"name": "late", "next_poll_at": NOW - timedelta(minutes=10)},
            {"name": "new", "next_poll_at": None},
            {"name": "later", "next_poll_at": NOW - timedelta(minutes=30)},
            {"name": "future", "next_poll_at": NOW + timedelta(minutes=1)},
            {"name": "off", "next_poll_at": None, "active": False},
        ]
        assert [s["name"] for s in polling.due(states, NOW)] == ["new", "later", "late"]

    def test_naive_mongo_datetimes(self):
        naive_past = (NOW - timedelta(minutes=1)).replace(tzinfo=None)
        naive_future = (NOW + timedelta(minutes=1)).replace(tzinfo=None)
        assert polling.is_due({"next_poll_at": naive_past}, NOW)
        assert not polling.is_due({"next_poll_at": naive_future}, NOW)
        mixed = [{"name": "a", "next_poll_at": naive_past}, {"name": "b", "next_poll_at": NOW - timedelta(hours=1)}]
        assert [s["name"] for s in polling.due(mixed, NOW)] == ["b", "a"]
