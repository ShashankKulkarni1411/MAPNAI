"""
MAPNAI — tests/test_hotness.py
Hotness H (personalization/hotness.py) and the hotness job (service.compute_hotness, breaking(), the Big today blend).
"""

import math
from datetime import datetime, timedelta, timezone

import pytest

from personalization import hotness as hot
from personalization.service import PersonalizationService
from tests.fakes import CFG, Clock, FakeMongo, FakeVectors, NamedExposures

HCFG = CFG.model_copy(update={"source_cred": {"ToI": 0.8, "Hindu": 0.8, "NDTV": 0.8, "ESPN": 0.8, "Blog": 0.3},
                              "source_cred_default": 0.5})
NOW = datetime(2026, 9, 29, 12, 0, tzinfo=timezone.utc)


def member(source, mins_ago, now=NOW, **kw):
    return {"article_id": kw.pop("article_id", f"{source}-{mins_ago}"), "source": source,
            "published": (now - timedelta(minutes=mins_ago)).isoformat(), "domain": kw.pop("domain", "sports"),
            "title": kw.pop("title", "Kohli ruled out of the final"), "url": kw.pop("url", None), **kw}


def sat(x, scale):
    return 1 - math.exp(-x / scale)


# ── Pure ────────────────────────────────────────────────────

class TestStripPublisher:
    @pytest.mark.parametrize("title,expected", [
        ("Kohli ruled out of the final - Cricbuzz", "Kohli ruled out of the final"),
        ("Kohli ruled out | The Times of India", "Kohli ruled out"),
        ("Kohli ruled out — ESPNcricinfo", "Kohli ruled out"),
        ("India vs Australia - live", "India vs Australia"),
        ("Twenty-twenty cricket returns", "Twenty-twenty cricket returns"),     # a hyphen inside a word stays
        ("- Cricbuzz", "- Cricbuzz"),
        ("", ""),
    ])
    def test_cases(self, title, expected):
        assert hot.strip_publisher(title) == expected


class TestOutlets:
    def test_articles_and_sightings_earliest_time_per_outlet(self):
        members = [
            member("ToI", 50, sightings=[{"source": "NDTV", "at": NOW - timedelta(minutes=40)},
                                         {"source": "Hindu", "at": NOW - timedelta(minutes=10)}]),
            member("Hindu", 30),
            member("ToI", 20),
        ]
        out = hot.outlets(members, NOW)
        assert out == {"ToI": NOW - timedelta(minutes=50), "NDTV": NOW - timedelta(minutes=40),
                       "Hindu": NOW - timedelta(minutes=30)}

    def test_future_times_are_clamped_to_now(self):
        out = hot.outlets([member("ToI", -60, sightings=[{"source": "ESPN", "at": NOW + timedelta(hours=2)}])], NOW)
        assert out == {"ToI": NOW, "ESPN": NOW}


class TestScore:
    def test_components_without_severity_or_social_are_renormalised(self):
        members = [member("ToI", 50), member("Hindu", 40), member("Blog", 200)]
        h = hot.hotness(members, NOW, HCFG)
        breadth = sat(0.8 + 0.8 + 0.3, 2.0)
        velocity = sat(0.8 + 0.8, 1.5)                             # Blog arrived 200 min ago: not in the hour
        raw = (0.3 * breadth + 0.3 * velocity + 0.2 * 0.0) / 0.8
        decay = 0.5 ** ((40 / 60) / 6.0)                           # the last new outlet arrived 40 min ago
        assert h["components"] == {"breadth": pytest.approx(breadth, abs=1e-6),
                                   "velocity": pytest.approx(velocity, abs=1e-6), "prominence": 0.0}
        assert h["raw"] == pytest.approx(raw, abs=1e-6) and h["score"] == pytest.approx(raw * decay, abs=1e-6)
        assert h["outlets"] == 3 and h["velocity_outlets"] == 2 and h["credible_outlets"] == 2
        assert h["first_seen"] == NOW - timedelta(minutes=200) and h["domain"] == "sports"

    def test_severity_from_risk_else_urgency(self):
        assert hot.severity([{"risk_score": 30}, {"risk_score": 80}], HCFG) == 0.8
        assert hot.severity([{"urgency_flag": True}], HCFG) == 0.7
        assert hot.severity([{"risk_score": None}, {"risk_score": True}], HCFG) is None
        h = hot.hotness([member("ToI", 10, risk_score=90)], NOW, HCFG, social_count=20)
        assert h["components"]["severity"] == 0.9
        assert h["components"]["social"] == pytest.approx(sat(20, 20.0), abs=1e-6)
        total = 0.3 * h["components"]["breadth"] + 0.3 * h["components"]["velocity"] + 0.2 * 0.9 \
            + 0.1 * h["components"]["social"]
        assert h["raw"] == pytest.approx(total / 1.1, abs=1e-6)

    def test_decay_halves_every_half_life_since_the_last_new_outlet(self):
        fresh = hot.hotness([member("ToI", 0)], NOW, HCFG)
        later = hot.hotness([member("ToI", 0)], NOW + timedelta(hours=6), HCFG)
        assert later["decay"] == pytest.approx(0.5) and fresh["decay"] == 1.0

    def test_per_domain_scale(self):
        cfg = HCFG.model_copy(update={"hot_domain_scale": {"sports": 2.0}})
        h = hot.hotness([member("ToI", 5), member("Hindu", 5)], NOW, cfg)
        assert h["components"]["breadth"] == pytest.approx(sat(0.8, 2.0), abs=1e-6)

    def test_empty(self):
        assert hot.hotness([], NOW, HCFG)["tier"] == hot.NORMAL


class TestProminence:
    def test_url_or_title_after_stripping_the_publisher(self):
        index = hot.ProminenceIndex([{"url": "https://toi/1", "title": "Kohli ruled out of the final - Cricbuzz"},
                                     {"url": "", "title": "Markets rally on rate cut"}], 0.5)
        assert index.match("https://toi/1", "anything")
        assert index.match(None, "Kohli ruled out of final")
        assert not index.match(None, "Kohli scores a century in the final")
        assert not index.match("https://other", "") and len(index) == 3

    def test_prominence_lifts_the_score(self):
        index = hot.ProminenceIndex([{"title": "Kohli ruled out of the final - Cricbuzz"}], 0.5)
        members = [member("ToI", 10), member("Hindu", 5)]
        assert hot.hotness(members, NOW, HCFG, index)["components"]["prominence"] == 1.0
        assert hot.hotness(members, NOW, HCFG, index)["score"] > hot.hotness(members, NOW, HCFG)["score"]


class TestTier:
    def test_breaking_needs_fast_credible_outlets_and_a_fresh_story(self):
        index = hot.ProminenceIndex([{"title": "Kohli ruled out of the final"}], 0.5)
        fast = [member("ToI", 50), member("Hindu", 40), member("NDTV", 30), member("ESPN", 5)]
        h = hot.hotness(fast, NOW, HCFG, index)
        assert h["score"] >= HCFG.hot_breaking_h and h["fast_credible"] == 4 and h["tier"] == hot.BREAKING
        # the same outlets, but the third credible one came 3 hours after the first report
        slow = [member("ToI", 240), member("Hindu", 230), member("NDTV", 30), member("ESPN", 5)]
        h = hot.hotness(slow, NOW, HCFG, index)
        assert h["fast_credible"] == 2 and h["tier"] == hot.TRENDING
        # 13 hours old: never breaking, however hot
        old = [member("ToI", 780), member("Hindu", 775), member("NDTV", 770), member("ESPN", 5)]
        assert hot.hotness(old, NOW, HCFG, index)["tier"] != hot.BREAKING

    def test_trending_needs_two_outlets(self):
        index = hot.ProminenceIndex([{"title": "Kohli ruled out of the final"}], 0.5)
        two = [member("Paper A", 30), member("Paper B", 20)]               # cred 0.5 each: not credible
        h = hot.hotness(two, NOW, HCFG, index)
        assert h["tier"] == hot.TRENDING and h["fast_credible"] == 0
        one = hot.hotness([member("ToI", 1, risk_score=100)], NOW, HCFG, index)
        assert one["score"] >= HCFG.hot_trending_h and one["tier"] == hot.NORMAL

    def test_history_due_and_rank(self):
        assert hot.history_due(None, {"tier": hot.TRENDING, "score": 0.5}, HCFG)
        assert not hot.history_due(None, {"tier": hot.NORMAL, "score": 0.3}, HCFG)
        assert not hot.history_due({"tier": "trending", "score": 0.5}, {"tier": "trending", "score": 0.54}, HCFG)
        assert hot.history_due({"tier": "trending", "score": 0.5}, {"tier": "trending", "score": 0.56}, HCFG)
        assert hot.history_due({"tier": "breaking", "score": 0.7}, {"tier": "trending", "score": 0.7}, HCFG)
        hs = [{"tier": "trending", "score": 0.6}, {"tier": "breaking", "score": 0.66}, {"tier": "normal", "score": .9}]
        assert [h["tier"] for h in sorted(hs, key=hot.rank_key)] == ["breaking", "trending", "normal"]

    def test_explain(self):
        h = {"tier": "breaking", "outlets": 6, "velocity_outlets": 4, "components": {"prominence": 1.0}}
        assert hot.explain(h) == "Breaking · 6 outlets, 4 in the last hour · on front pages"
        assert hot.explain({"tier": "trending", "outlets": 1}) == "Trending · 1 outlet"


# ── Service: the hotness job ────────────────────────────────

RNOW = datetime.now(timezone.utc).replace(microsecond=0)      # prominence has a TTL index (mongomock applies it)


def adoc(aid, source, mins_ago, cluster, domain="sports", m=0.5, title="Kohli ruled out of the final", **kw):
    return {"article_id": aid, "source_name": source, "domain": domain, "title": title,
            "url": f"https://news/{aid}", "published_at": (RNOW - timedelta(minutes=mins_ago)).isoformat(),
            "cluster_id": cluster, "cluster_size": kw.pop("size", 1), "materiality": {"m": m},
            "entities": [{"name": "Virat Kohli", "salience": 0.9}], "entity_keys": ["virat kohli"], **kw}


@pytest.fixture
def svc():
    mongo = FakeMongo()
    db = mongo.db
    db.processed_articles.insert_many([
        # a breaking sports story: four credible outlets within the hour, on a front page
        adoc("k1", "ToI", 50, "k1", m=0.6, size=3, sightings=[{"source": "ESPN", "at": RNOW - timedelta(minutes=5)}]),
        adoc("k2", "Hindu", 40, "k1", m=0.7, size=3),
        adoc("k3", "NDTV", 30, "k1", m=0.5, size=3),
        # a quiet story with a higher materiality
        adoc("q1", "Blog", 300, "q1", m=0.75, title="Stadium renovation plans approved"),
        # a general-domain story that is just as hot (hits are only shown for hot_domains)
        adoc("g1", "ToI", 20, "g1", domain="general", m=0.4, size=3, title="Parliament passes the budget bill"),
        adoc("g2", "Hindu", 15, "g1", domain="general", m=0.4, size=3, title="Parliament passes the budget bill"),
        adoc("g3", "NDTV", 10, "g1", domain="general", m=0.4, size=3, title="Parliament passes the budget bill"),
        # outside the 24 h window, still marked hot from long ago
        adoc("old", "ToI", 60 * 30, "old", hot={"tier": "breaking", "score": 0.9}),
    ])
    db.clusters.insert_many([
        {"cluster_id": "k1", "members": ["k1", "k2", "k3"], "first_report": "k1", "size": 3},
        {"cluster_id": "q1", "members": ["q1"], "first_report": "q1", "size": 1},
        {"cluster_id": "g1", "members": ["g1", "g2", "g3"], "first_report": "g1", "size": 3},
    ])
    db.prominence.insert_many([
        {"feed": "ToI Top Stories", "key": "t1", "url": "", "title": "Kohli ruled out of the final - Cricbuzz",
         "last_seen_at": RNOW - timedelta(minutes=3), "first_seen_at": RNOW - timedelta(minutes=30)},
        {"feed": "ToI Top Stories", "key": "t2", "url": "https://news/g2", "title": "x",
         "last_seen_at": RNOW - timedelta(minutes=3), "first_seen_at": RNOW - timedelta(minutes=30)},
    ])
    return PersonalizationService(mongo=mongo, exposures=NamedExposures([], {}), vectors=FakeVectors({}),
                                  cfg=HCFG, clock=Clock(RNOW))


class TestComputeHotness:
    def test_tiers_are_written_to_clusters_articles_and_history(self, svc):
        stats = svc.compute_hotness()
        assert stats["clusters"] == 3 and stats["breaking"] == 2 and stats["prominence_items"] == 2
        db = svc.mongo.db
        k1 = db.clusters.find_one({"cluster_id": "k1"})["hot"]
        assert k1["tier"] == "breaking" and k1["outlets"] == 4 and k1["components"]["prominence"] == 1.0
        assert k1["breaking_since"] is not None and k1["domain"] == "sports"
        art = db.processed_articles.find_one({"article_id": "k2"})["hot"]
        assert art["tier"] == "breaking" and art["outlets"] == 4 and art["score"] == k1["score"]
        assert db.processed_articles.find_one({"article_id": "q1"})["hot"]["tier"] == "normal"
        old = db.processed_articles.find_one({"article_id": "old"})["hot"]
        assert old["tier"] == "normal" and stats["cooled"] == 1
        rows = list(db.hot_history.find({}, {"_id": 0}))
        assert sorted(r["cluster_id"] for r in rows) == ["g1", "k1"]
        assert all(r["prev_tier"] == "normal" and r["tier"] == "breaking" for r in rows)

    def test_a_rerun_without_change_adds_no_history_and_keeps_breaking_since(self, svc):
        svc.compute_hotness()
        since = svc.mongo.db.clusters.find_one({"cluster_id": "k1"})["hot"]["breaking_since"]
        svc.clock.now = RNOW + timedelta(minutes=5)
        stats = svc.compute_hotness()
        assert stats["history_rows"] == 0
        assert svc.mongo.db.clusters.find_one({"cluster_id": "k1"})["hot"]["breaking_since"] == since

    def test_breaking_lists_hot_domains_only_with_the_lead_article(self, svc):
        svc.compute_hotness()
        items = svc.breaking()
        assert [i["article_id"] for i in items] == ["k2"]                 # the most material member of k1
        item = items[0]
        assert item["section"] == "breaking" and item["hot"]["tier"] == "breaking" and item["hot"]["outlets"] == 4
        assert item["explanation"].startswith("Breaking · 4 outlets")
        assert svc.breaking(include_trending=False)[0]["article_id"] == "k2"
        assert svc.breaking(hours=0.5) == []                              # first reported 50 min ago

    def test_big_today_blends_hotness_in(self, svc):
        before = [i["article_id"] for i in svc.top(24, 5)]
        assert before.index("q1") < before.index("k2")                   # m 0.75 vs 0.7 before scoring
        svc.compute_hotness()
        after = svc.top(24, 5)
        ids = [i["article_id"] for i in after]
        assert ids.index("k2") < ids.index("q1")
        assert next(i for i in after if i["article_id"] == "k2")["hot"]["tier"] == "breaking"
        assert next(i for i in after if i["article_id"] == "q1")["hot"] is None
