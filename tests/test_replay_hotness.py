"""
MAPNAI — tests/test_replay_hotness.py
The replay script's pure core (scripts/replay_hotness.py): only what was known at each step counts, and the summary
reports when a story was first flagged breaking.
"""

from datetime import datetime, timedelta, timezone

from scripts.replay_hotness import as_of, prominence_at, replay_story, steps, summarize
from tests.test_hotness import HCFG

T0 = datetime(2026, 9, 29, 10, 0, tzinfo=timezone.utc)


def m(source, mins, **kw):
    return {"article_id": f"{source}-{mins}", "source": source, "published": (T0 + timedelta(minutes=mins)).isoformat(),
            "title": "Kohli ruled out of the final", "domain": "sports", **kw}


MEMBERS = [m("ToI", 0, sightings=[{"source": "ESPN", "at": T0 + timedelta(minutes=50)}]),
           m("Hindu", 20), m("NDTV", 40)]
FRONT = [{"title": "Kohli ruled out of the final - Cricbuzz", "first_seen_at": T0 + timedelta(minutes=30),
          "last_seen_at": T0 + timedelta(hours=3)}]


def test_as_of_hides_the_future():
    known = as_of(MEMBERS, T0 + timedelta(minutes=30))
    assert [k["source"] for k in known] == ["ToI", "Hindu"] and known[0]["sightings"] == []
    assert len(as_of(MEMBERS, T0 + timedelta(minutes=55))[0]["sightings"]) == 1
    assert as_of(MEMBERS, T0 - timedelta(minutes=1)) == []


def test_prominence_window():
    assert prominence_at(FRONT, T0, 24) == []
    assert len(prominence_at(FRONT, T0 + timedelta(minutes=31), 24)) == 1
    assert prominence_at(FRONT, T0 + timedelta(hours=28), 24) == []


def test_replay_flags_breaking_once_enough_credible_outlets_arrive():
    times = steps(T0 - timedelta(minutes=15), T0 + timedelta(minutes=75), 15)
    rows = replay_story(MEMBERS, FRONT, times, HCFG)
    assert rows[0]["t"] == T0 and rows[0]["tier"] == "normal"                 # one outlet: not hot yet
    tiers = [r["tier"] for r in rows]
    assert tiers.index("breaking") == 3                                      # 45 min: the 3rd credible outlet (NDTV, 40 min)
    out = summarize({"k1": rows}, {"k1": "Kohli ruled out"})
    [b] = out["breaking"]
    assert b["cluster_id"] == "k1" and b["minutes_after_first_report"] == 45 and b["outlets"] == 3
    assert out["days"]["2026-09-29"]["breaking"] == 1
