"""
MAPNAI — tests/test_breaking_alerts.py
Hit news for the user (service._breaking_alerts via run_alerts): breaking_for_you on the reader's pi map,
opt-in breaking_global with its own daily cap, the shared rules (one per cluster, max_per_day, quiet hours),
the alert prefs, and alerts() for alerts without an exposure path.
"""

from datetime import timedelta

import pytest

from personalization.service import InvalidInput, PersonalizationService
from tests.fakes import Clock, FakeMongo, FakeVectors, NamedExposures
from tests.test_hotness import HCFG, RNOW, adoc

NO_QUIET = {"quiet_start": "00:00", "quiet_end": "00:00", "tz": "Asia/Kolkata"}


def pi(entity, score):
    return {"entity": entity, "score": score, "path": {"seed": entity, "role": "follows", "via": [], "relations": []}}


def persona(user_id, entries, **prefs):
    return {"user_id": user_id, "name": user_id, "topics": {}, "beta": {}, "history": [], "persona_version": 1,
            "pi_topk": entries, "alert_prefs": {**NO_QUIET, **prefs}}


@pytest.fixture
def svc():
    mongo = FakeMongo()
    db = mongo.db
    db.processed_articles.insert_many([
        adoc("k1", "ToI", 50, "k1", m=0.6, size=3, sightings=[{"source": "ESPN", "at": RNOW - timedelta(minutes=5)}]),
        adoc("k2", "Hindu", 40, "k1", m=0.7, size=3),
        adoc("k3", "NDTV", 30, "k1", m=0.5, size=3),
    ])
    db.clusters.insert_one({"cluster_id": "k1", "members": ["k1", "k2", "k3"], "first_report": "k1", "size": 3})
    db.prominence.insert_one({"feed": "ToI Top Stories", "key": "t1", "url": "",
                              "title": "Kohli ruled out of the final - Cricbuzz",
                              "last_seen_at": RNOW - timedelta(minutes=3), "first_seen_at": RNOW})
    db.personas.insert_many([
        persona("fan", [pi("virat kohli", 0.5)]),                               # breaking_for_you
        persona("weak", [pi("virat kohli", 0.1)]),                              # below breaking_min_pi
        persona("off", [pi("virat kohli", 0.6)], breaking_for_you=False),       # turned it off (need .42: no exposure alert)
        persona("global", [pi("rohit sharma", 0.9)], breaking_global=True),     # opted in to major news
        {**persona("newbie", [], breaking_global=True), "pi_topk": []},          # no pi map yet, opted in
        persona("capped", [pi("virat kohli", 0.5)], max_per_day=0),
    ])
    s = PersonalizationService(mongo=mongo, exposures=NamedExposures([], {}), vectors=FakeVectors({}),
                               cfg=HCFG.model_copy(update={"enable_push": False}), clock=Clock(RNOW))
    s.compute_hotness()
    return s


def alerts_of(svc, user_id):
    return list(svc.mongo.db.alerts.find({"user_id": user_id}, {"_id": 0}))


class TestBreakingAlerts:
    def test_who_gets_what(self, svc):
        h = svc.mongo.db.clusters.find_one({"cluster_id": "k1"})["hot"]
        assert h["tier"] == "breaking" and h["score"] >= HCFG.breaking_global_min_h
        stats = svc.run_alerts()["breaking"]
        assert stats["clusters"] == 1 and stats["for_you"] == 1 and stats["global"] == 2
        assert stats["dropped"]["capped"] == 1
        [fan] = alerts_of(svc, "fan")
        assert fan["kind"] == "breaking_for_you" and fan["cluster_id"] == "k1" and fan["article_id"] == "k2"
        assert fan["entity"] == "virat kohli" and fan["path"]["seed"] == "virat kohli"
        assert fan["explanation"].startswith("Breaking · 4 outlets") and fan["hot"]["tier"] == "breaking"
        assert fan["deferred"] is False and fan["need"] is None
        for user in ("global", "newbie"):
            [a] = alerts_of(svc, user)
            assert a["kind"] == "breaking_global" and a["path"] is None and a["entity"] is None
        for user in ("weak", "off", "capped"):
            assert alerts_of(svc, user) == []

    def test_one_alert_per_cluster_across_runs(self, svc):
        svc.run_alerts()
        svc.clock.now = RNOW + timedelta(minutes=5)
        stats = svc.run_alerts()["breaking"]
        assert stats["for_you"] == 0 and stats["global"] == 0 and stats["dropped"]["already_alerted"] == 3
        assert len(alerts_of(svc, "fan")) == 1

    def test_an_exposure_alert_for_the_story_blocks_a_breaking_one(self, svc):
        svc.mongo.db.alerts.insert_one({"alert_id": "x", "kind": "exposure", "user_id": "fan", "cluster_id": "k1",
                                        "deliver_after": RNOW})
        svc.run_alerts()
        assert [a["kind"] for a in alerts_of(svc, "fan")] == ["exposure"]

    def test_breaking_global_has_its_own_daily_cap(self, svc):
        svc.mongo.db.alerts.insert_many([
            {"alert_id": f"g{i}", "kind": "breaking_global", "user_id": "global", "cluster_id": f"other{i}",
             "deliver_after": RNOW} for i in range(HCFG.breaking_global_max_per_day)])
        stats = svc.run_alerts()["breaking"]
        assert stats["dropped"]["global_capped"] == 1 and stats["global"] == 1          # newbie still gets it
        assert [a for a in alerts_of(svc, "global") if a["cluster_id"] == "k1"] == []

    def test_only_hot_domains(self, svc):
        svc.mongo.db.clusters.update_one({"cluster_id": "k1"}, {"$set": {"hot.domain": "general"}})
        assert svc.run_alerts()["breaking"]["clusters"] == 0

    def test_quiet_hours_defer(self, svc):
        local = RNOW.astimezone(__import__("zoneinfo").ZoneInfo("Asia/Kolkata"))
        start = (local - timedelta(minutes=30)).strftime("%H:%M")
        end = (local + timedelta(hours=2)).strftime("%H:%M")
        svc.mongo.db.personas.update_one({"user_id": "fan"}, {"$set": {"alert_prefs.quiet_start": start,
                                                                       "alert_prefs.quiet_end": end}})
        svc.run_alerts()
        [a] = alerts_of(svc, "fan")
        assert a["deferred"] is True and a["deliver_after"] > RNOW.replace(tzinfo=None)

    def test_alerts_view_handles_alerts_without_a_path(self, svc):
        svc.run_alerts()
        [g] = svc.alerts("global")
        assert g["kind"] == "breaking_global" and g["entity_name"] is None and g["tier"] == "major"
        assert "push" not in g
        [f] = svc.alerts("fan")
        assert f["kind"] == "breaking_for_you" and f["entity_name"]


class TestPrefs:
    def test_booleans_accepted_and_validated(self, svc):
        out = svc.patch_alert_prefs("weak", {"breaking_global": True, "breaking_for_you": False})
        prefs = out.get("alert_prefs", out)
        assert prefs["breaking_global"] is True and prefs["breaking_for_you"] is False
        with pytest.raises(InvalidInput):
            svc.patch_alert_prefs("weak", {"breaking_global": "yes"})
        with pytest.raises(InvalidInput):
            svc.patch_alert_prefs("weak", {"breaking_everything": True})

    def test_defaults(self):
        assert HCFG.alert_prefs_default["breaking_for_you"] is True
        assert HCFG.alert_prefs_default["breaking_global"] is False
