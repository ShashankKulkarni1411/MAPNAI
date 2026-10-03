"""
MAPNAI — tests/test_pers_phase6.py
Phase 6: alerts. The pure rules first (quiet hours across midnight in Asia/Kolkata, local-day bounds, the inverted
index, selection), then the job on mongomock with the in-memory Neo4j fake: a simulated high-materiality article on a
user's exposure, the per-day cap, one alert per cluster, quiet-hour deferral, and that users the article's entities
don't reach are never scored.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from api.app import create_app
from api.personalization_router import get_service
from personalization import alerts, jobs
from personalization.keys import entity_key
from personalization.scoring import parse_ts
from personalization.service import PersonalizationService, UserNotFound
from tests.test_pers_phase2 import CFG, NOW, FakeMongo
from tests.test_pers_profile import FakeExposureStore

IST = ZoneInfo("Asia/Kolkata")
UTC = timezone.utc
PREFS = {"max_per_day": 3, "quiet_start": "22:00", "quiet_end": "07:00", "tz": "Asia/Kolkata"}


def ist(y, mo, d, h, mi=0):
    return datetime(y, mo, d, h, mi, tzinfo=IST).astimezone(UTC)


# ── Quiet hours (pure) ───────────────────────────────────────

class TestQuietHours:
    @pytest.mark.parametrize("local,expected", [
        ((2026, 9, 29, 23, 30), (2026, 9, 30, 7, 0)),     # late evening → next morning
        ((2026, 9, 30, 2, 0), (2026, 9, 30, 7, 0)),       # after midnight → same morning
        ((2026, 9, 29, 22, 0), (2026, 9, 30, 7, 0)),      # quiet_start is inside
        ((2026, 9, 30, 6, 59), (2026, 9, 30, 7, 0)),
        ((2026, 12, 31, 23, 15), (2027, 1, 1, 7, 0)),     # across a year boundary
    ])
    def test_deferred_across_midnight_in_kolkata(self, local, expected):
        deliver, deferred = alerts.deliver_after(ist(*local), PREFS, CFG.tz)
        assert deferred is True and deliver == ist(*expected)
        assert deliver.astimezone(IST).time().isoformat() == "07:00:00"

    @pytest.mark.parametrize("local", [(2026, 9, 29, 7, 0), (2026, 9, 29, 12, 0), (2026, 9, 29, 21, 59)])
    def test_outside_quiet_hours_is_immediate(self, local):
        assert alerts.deliver_after(ist(*local), PREFS, CFG.tz) == (ist(*local), False)

    def test_the_utc_view_of_the_kolkata_window(self):
        # 22:00–07:00 IST = 16:30–01:30 UTC: 18:00 UTC is quiet, 15:00 UTC is not
        assert alerts.deliver_after(datetime(2026, 9, 29, 18, 0, tzinfo=UTC), PREFS, CFG.tz)[0] == \
            datetime(2026, 9, 30, 1, 30, tzinfo=UTC)
        assert alerts.deliver_after(datetime(2026, 9, 29, 15, 0, tzinfo=UTC), PREFS, CFG.tz)[1] is False

    def test_same_day_window_and_no_window(self):
        noon = {**PREFS, "quiet_start": "13:00", "quiet_end": "15:00"}
        assert alerts.deliver_after(ist(2026, 9, 29, 14, 0), noon, CFG.tz) == (ist(2026, 9, 29, 15, 0), True)
        assert alerts.deliver_after(ist(2026, 9, 29, 23, 0), noon, CFG.tz)[1] is False
        off = {**PREFS, "quiet_start": "00:00", "quiet_end": "00:00"}
        assert alerts.deliver_after(ist(2026, 9, 29, 3, 0), off, CFG.tz)[1] is False

    def test_the_users_own_zone(self):
        london = {**PREFS, "tz": "Europe/London"}
        now = datetime(2026, 9, 29, 18, 0, tzinfo=UTC)          # 23:30 IST but 19:00 BST
        assert alerts.deliver_after(now, london, CFG.tz)[1] is False
        now = datetime(2026, 9, 29, 23, 30, tzinfo=UTC)         # 00:30 BST → 07:00 BST = 06:00 UTC
        assert alerts.deliver_after(now, london, CFG.tz)[0] == datetime(2026, 9, 30, 6, 0, tzinfo=UTC)

    def test_prefs_defaults_and_bad_zone(self):
        assert alerts.prefs({"max_per_day": 1, "tz": None}, CFG) == {**CFG.alert_prefs_default, "max_per_day": 1}
        assert alerts.zone("Mars/Olympus", CFG.tz) == IST

    def test_day_bounds_are_the_local_day(self):
        start, end = alerts.day_bounds(datetime(2026, 9, 29, 20, 0, tzinfo=UTC), IST)   # 01:30 IST on the 30th
        assert (start, end) == (datetime(2026, 9, 29, 18, 30, tzinfo=UTC), datetime(2026, 9, 30, 18, 30, tzinfo=UTC))


# ── Index and selection (pure) ───────────────────────────────

class TestIndex:
    def test_entries_that_can_never_fire_are_pruned(self):
        rows = [{"user_id": "a", "pi_topk": [{"entity": "x", "score": 1.0}, {"entity": "hop", "score": 0.1}]},
                {"user_id": "b", "pi_topk": [{"entity": "x", "score": 0.5}]},
                {"user_id": "c", "pi_topk": [{"entity": "x", "score": 0.49}]},
                {"user_id": "d", "pi_topk": []}]
        index = alerts.build_index(rows, CFG.alert_min_need)
        assert index == {"x": {"a", "b"}}
        assert alerts.users_for(["x", "y"], index) == {"a", "b"} and alerts.users_for(["hop"], index) == set()
        assert alerts.users_for([], index) == set()


def cand(article_id, cluster, need, m=0.8):
    return {"article_id": article_id, "cluster_id": cluster, "need": need, "m": m}


class TestSelect:
    def test_cap_keeps_the_highest_need(self):
        cands = [cand("a", "c1", 0.6), cand("b", "c2", 0.9), cand("c", "c3", 0.7), cand("d", "c4", 0.8)]
        chosen, dropped = alerts.select(cands, set(), 3)
        assert [c["article_id"] for c in chosen] == ["b", "d", "c"] and dropped["capped"] == 1

    def test_one_per_cluster_and_already_alerted(self):
        cands = [cand("a", "c1", 0.6), cand("b", "c1", 0.9), cand("c", "c2", 0.7), cand("d", "c3", 0.8)]
        chosen, dropped = alerts.select(cands, {"c3"}, 3)
        assert [c["article_id"] for c in chosen] == ["b", "c"]
        assert dropped == {"already_alerted": 1, "same_cluster": 1, "capped": 0}

    def test_nothing_left_today(self):
        assert alerts.select([cand("a", "c1", 0.9)], set(), 0)[0] == []
        assert alerts.select([cand("a", "c1", 0.9)], set(), -2)[1]["capped"] == 1


# ── The job (mongomock + Neo4j fake) ─────────────────────────

MAT = {"risk_norm": 0.9, "size_score": 0.289, "first_report": 0, "source_cred": 0.8, "unscored": False}


def mart(article_id, ents, m, cluster=None, hours_ago=2.0, computed_at=NOW, **extra):
    """A clustered article whose materiality the clustering job has written."""
    return {"article_id": article_id, "title": f"title {article_id}", "domain": "sports", "source_name": "BBC",
            "url": f"u/{article_id}", "published_at": (NOW - timedelta(hours=hours_ago)).isoformat(),
            "entities": [{"name": n, "type": "Location", "salience": 1.0 - i / 10} for i, n in enumerate(ents)],
            "entity_keys": [entity_key(n) for n in ents], "cluster_id": cluster or f"c-{article_id}",
            "materiality": {"m": m, **MAT, "computed_at": computed_at}, **extra}


class Clock:
    def __init__(self, now):
        self.now = now

    def __call__(self):
        return self.now


@pytest.fixture
def svc():
    s = PersonalizationService(mongo=FakeMongo(), exposures=FakeExposureStore(CFG), cfg=CFG, clock=Clock(NOW))
    make = lambda name, exps: s.create_user(name, {"sports": 1.0}, None, exps)["user_id"]    # noqa: E731
    s.ana = make("Ana", [{"key": "manchester city", "role": "owns", "weight": "high"}])       # pi 1.0
    s.ben = make("Ben", [{"key": "who", "role": "regulated_by", "weight": "high"}])           # other exposure
    s.cai = make("Cai", [])                                                                    # no exposures
    return s


def add(svc, *docs):
    svc.mongo.db.processed_articles.insert_many([dict(d) for d in docs])


def user_alerts(svc, user_id):
    """The raw alert docs, best first, with their times made UTC-aware (Mongo hands back naive UTC)."""
    docs = list(svc.mongo.db.alerts.find({"user_id": user_id}, {"_id": 0}).sort("need", -1))
    for d in docs:
        d["created_at"], d["deliver_after"] = parse_ts(d["created_at"]), parse_ts(d["deliver_after"])
    return docs


class TestSimulatedArticle:
    def test_a_high_materiality_article_on_an_exposure_alerts_that_user(self, svc):
        add(svc, mart("sim", ["Manchester City", "England"], m=0.82))
        stats = jobs.run_job(svc, "alerts")["stats"]
        assert (stats["articles_scanned"], stats["articles_material"], stats["pairs_scored"], stats["created"]) == \
            (1, 1, 1, 1)
        [a] = user_alerts(svc, svc.ana)
        assert (a["article_id"], a["cluster_id"], a["entity"]) == ("sim", "c-sim", "manchester city")
        assert a["need"] == pytest.approx(0.82) and a["m"] == 0.82 and a["m_parts"] == MAT
        assert a["deferred"] is False and a["deliver_after"] == a["created_at"]
        assert a["explanation"] == ("You own Manchester City. Need 0.82 = materiality 0.82 × exposure 1.00; "
                                    "Manchester City drives 100% of it.")
        assert a["path"] == {"seed": "manchester city", "role": "owns", "via": [], "relations": []}
        assert user_alerts(svc, svc.ben) == [] and user_alerts(svc, svc.cai) == []
        assert svc.mongo.db.job_runs.find_one({"job": "alerts"})["ok"] is True
        [served] = svc.alerts(svc.ana)
        assert served["article_id"] == "sim" and served["delivered"] is True

    def test_thresholds(self, svc):
        svc.patch_exposures(svc.ben, [{"key": "england", "role": "follows", "weight": "medium"}], [])
        add(svc, mart("low-m", ["Manchester City"], m=0.59),              # need .59 but m < .6
            mart("low-need", ["England"], m=0.7))                         # Ben: m .7 × pi .667 = .467 < .5
        stats = svc.run_alerts()
        assert stats["articles_material"] == 1 and stats["pairs_scored"] == 1 and stats["created"] == 0
        # the test mode of the plan: PERS_ALERT_MIN_M=0.3 (the marks don't block a rescan)
        loose = PersonalizationService(mongo=svc.mongo, exposures=svc.exposures, cfg=CFG.model_copy(
            update={"alert_min_m": 0.3}), clock=svc.clock)
        assert loose.run_alerts()["articles_scanned"] == 0
        stats = loose.run_alerts(rescan=True)
        assert stats["created"] == 1 and user_alerts(svc, svc.ana)[0]["article_id"] == "low-m"

    def test_disabled(self, svc):
        add(svc, mart("sim", ["Manchester City"], m=0.9))
        off = PersonalizationService(mongo=svc.mongo, exposures=svc.exposures, clock=svc.clock,
                                     cfg=CFG.model_copy(update={"enable_alerts": False}))
        assert off.run_alerts() == {"skipped": "enable_alerts=false"}
        assert svc.mongo.db.alerts.count_documents({}) == 0

    def test_articles_outside_the_lookback_are_ignored(self, svc):
        add(svc, mart("old", ["Manchester City"], m=0.9, hours_ago=CFG.alert_lookback_h + 1))
        assert svc.run_alerts()["articles_scanned"] == 0

    def test_an_article_is_evaluated_again_only_when_its_materiality_changes(self, svc):
        add(svc, mart("a1", ["Manchester City"], m=0.55, cluster="cl"))
        assert svc.run_alerts()["articles_scanned"] == 1
        assert svc.run_alerts()["articles_scanned"] == 0                  # marked: nothing new
        # the cluster grew and the clustering job rewrote the materiality → evaluated again, now above .6
        svc.articles.set_materiality({"a1": {"m": 0.66, **MAT, "computed_at": NOW + timedelta(hours=1)}})
        stats = svc.run_alerts()
        assert stats["articles_scanned"] == 1 and stats["created"] == 1

    def test_the_mark_is_not_written_over_a_newer_materiality(self, svc):
        add(svc, mart("a1", ["Manchester City"], m=0.55))
        docs = svc.articles.alert_scan_pending(CFG.alert_lookback_h, NOW)
        svc.articles.set_materiality({"a1": {"m": 0.7, **MAT, "computed_at": NOW + timedelta(minutes=1)}})
        svc.articles.mark_alert_scanned({"a1": docs[0]["materiality"]["computed_at"]}, NOW)
        assert svc.run_alerts()["created"] == 1


class TestPerDayCap:
    def test_three_per_day_by_need_then_nothing_until_the_next_local_day(self, svc):
        add(svc, *[mart(f"a{i}", ["Manchester City"], m=0.6 + i / 20) for i in range(5)])   # 5 clusters
        stats = svc.run_alerts()
        assert stats["eligible"] == 5 and stats["created"] == 3 and stats["dropped"]["capped"] == 2
        assert [a["article_id"] for a in user_alerts(svc, svc.ana)] == ["a4", "a3", "a2"]

        # later the same local day: a new, even more material story is still capped
        svc.clock.now = ist(2026, 9, 29, 21, 30)
        add(svc, mart("b1", ["Manchester City"], m=0.95, hours_ago=-2))
        stats = svc.run_alerts()
        assert stats["created"] == 0 and stats["dropped"]["capped"] == 1

        # the next local day (after quiet hours) the counter starts again
        svc.clock.now = ist(2026, 9, 30, 9, 0)
        add(svc, mart("c1", ["Manchester City"], m=0.9, hours_ago=-15))      # NOW + 15.5h
        assert svc.run_alerts()["created"] == 1

    def test_the_users_own_cap(self, svc):
        svc.patch_alert_prefs(svc.ana, {"max_per_day": 1})
        add(svc, *[mart(f"a{i}", ["Manchester City"], m=0.7 + i / 20) for i in range(3)])
        assert svc.run_alerts()["created"] == 1
        assert [a["article_id"] for a in user_alerts(svc, svc.ana)] == ["a2"]
        svc.patch_alert_prefs(svc.ana, {"max_per_day": 0})               # 0 turns alerts off for the user
        add(svc, mart("z", ["Manchester City"], m=0.9))
        assert svc.run_alerts()["created"] == 0

    def test_deferred_alerts_count_towards_their_delivery_day(self, svc):
        svc.clock.now = ist(2026, 9, 29, 23, 0)                          # quiet: delivered 07:00 on the 30th
        add(svc, *[mart(f"n{i}", ["Manchester City"], m=0.7 + i / 20, hours_ago=-5) for i in range(3)])
        assert svc.run_alerts()["deferred"] == 3
        svc.clock.now = ist(2026, 9, 30, 10, 0)                          # the 30th: the 3 deferred used it up
        add(svc, mart("d1", ["Manchester City"], m=0.9, hours_ago=-16))
        assert svc.run_alerts()["dropped"]["capped"] == 1

    def test_the_cap_is_per_user(self, svc):
        svc.patch_exposures(svc.ben, [{"key": "manchester city", "role": "covers", "weight": "high"}], [])
        add(svc, *[mart(f"a{i}", ["Manchester City"], m=0.7 + i / 20) for i in range(4)])
        stats = svc.run_alerts()
        assert stats["created"] == 6 and len(user_alerts(svc, svc.ana)) == len(user_alerts(svc, svc.ben)) == 3


class TestOnePerCluster:
    def test_three_articles_of_one_story_give_one_alert(self, svc):
        add(svc, mart("s1", ["Manchester City"], m=0.7, cluster="story"),
            mart("s2", ["Manchester City"], m=0.9, cluster="story"),
            mart("s3", ["Manchester City"], m=0.8, cluster="story"))
        stats = svc.run_alerts()
        assert stats["eligible"] == 3 and stats["created"] == 1 and stats["dropped"]["same_cluster"] == 2
        [a] = user_alerts(svc, svc.ana)
        assert (a["article_id"], a["cluster_id"]) == ("s2", "story")     # the most material report

    def test_a_later_report_of_the_same_story_never_alerts_again(self, svc):
        add(svc, mart("s1", ["Manchester City"], m=0.7, cluster="story"))
        assert svc.run_alerts()["created"] == 1
        svc.clock.now = NOW + timedelta(days=1)                          # even on another day
        add(svc, mart("s2", ["Manchester City"], m=0.95, cluster="story", hours_ago=-20))
        stats = svc.run_alerts()
        assert stats["created"] == 0 and stats["dropped"]["already_alerted"] == 1
        assert len(user_alerts(svc, svc.ana)) == 1

    def test_the_unique_index_blocks_a_concurrent_duplicate(self, svc):
        add(svc, mart("s1", ["Manchester City"], m=0.7, cluster="story"))
        svc.run_alerts()
        assert svc.logs.add_alert({"alert_id": "x", "user_id": svc.ana, "cluster_id": "story"}) is False
        assert svc.logs.add_alert({"alert_id": "y", "user_id": svc.ben, "cluster_id": "story"}) is True

    def test_other_users_still_get_the_story(self, svc):
        svc.patch_exposures(svc.ben, [{"key": "manchester city", "role": "covers", "weight": "high"}], [])
        add(svc, mart("s1", ["Manchester City"], m=0.7, cluster="story"),
            mart("s2", ["Manchester City"], m=0.8, cluster="story"))
        assert svc.run_alerts()["created"] == 2
        assert [a["cluster_id"] for a in user_alerts(svc, svc.ben)] == ["story"]


class TestQuietHourDeferral:
    @pytest.mark.parametrize("local,deliver", [
        ((2026, 9, 29, 23, 30), (2026, 9, 30, 7, 0)),
        ((2026, 9, 30, 2, 15), (2026, 9, 30, 7, 0)),
    ])
    def test_created_in_quiet_hours_delivered_at_seven_ist(self, svc, local, deliver):
        now = ist(*local)
        svc.clock.now = now
        add(svc, mart("q1", ["Manchester City"], m=0.8, hours_ago=(NOW - now).total_seconds() / 3600 + 1))
        stats = svc.run_alerts()
        assert stats["created"] == 1 and stats["deferred"] == 1
        [a] = user_alerts(svc, svc.ana)
        assert a["deferred"] is True and a["created_at"] == now and a["deliver_after"] == ist(*deliver)

        assert svc.alerts(svc.ana) == []                                  # held back during quiet hours
        [pending] = svc.alerts(svc.ana, include_pending=True)
        assert pending["delivered"] is False
        svc.clock.now = ist(*deliver) - timedelta(minutes=1)
        assert svc.alerts(svc.ana) == []
        svc.clock.now = ist(*deliver)
        [out] = svc.alerts(svc.ana)
        assert out["delivered"] is True and out["deliver_after"] == ist(*deliver)
        # a client polling since its last poll (before 07:00) sees the released alert
        assert len(svc.alerts(svc.ana, since=ist(*deliver) - timedelta(minutes=5))) == 1
        assert svc.alerts(svc.ana, since=ist(*deliver)) == []

    def test_each_user_in_their_own_zone(self, svc):
        svc.patch_exposures(svc.ben, [{"key": "manchester city", "role": "covers", "weight": "high"}], [])
        svc.patch_alert_prefs(svc.ben, {"tz": "Europe/London"})
        svc.clock.now = ist(2026, 9, 29, 23, 30)                         # 19:00 in London
        add(svc, mart("q1", ["Manchester City"], m=0.8, hours_ago=-5))
        svc.run_alerts()
        assert user_alerts(svc, svc.ana)[0]["deferred"] is True
        ben = user_alerts(svc, svc.ben)[0]
        assert ben["deferred"] is False and ben["deliver_after"] == svc.clock.now


class TestUnexposedUsersAreNeverScored:
    def spy(self, svc, monkeypatch):
        scored = []
        real = svc._score_alert

        def record(user_id, *args):
            scored.append(user_id)
            return real(user_id, *args)
        monkeypatch.setattr(svc, "_score_alert", record)
        return scored

    def test_only_users_the_articles_entities_reach(self, svc, monkeypatch):
        # a crowd exposed only elsewhere, and a user reaching Manchester City only through a weak hop
        crowd = [svc.create_user(f"U{i}", {"sports": 1.0}, None,
                                 [{"key": "who", "role": "follows", "weight": "high"}])["user_id"] for i in range(40)]
        hop = svc.create_user("Hop", {"sports": 1.0}, None, [])["user_id"]
        svc.personas.set_pi_topk(hop, [{"entity": "manchester city", "score": 0.1, "path": {
            "seed": "england", "role": "follows", "via": [], "relations": ["MENTIONED_WITH"]}}])
        scored = self.spy(svc, monkeypatch)

        add(svc, mart("mc", ["Manchester City", "England", "U.S"], m=0.9))
        stats = svc.run_alerts()
        assert scored == [svc.ana]
        assert stats["pairs_scored"] == 1 and stats["users"] == 43 and stats["users_indexed"] == 42
        assert svc.mongo.db.alerts.distinct("user_id") == [svc.ana]
        assert set(svc.mongo.db.personas.distinct("user_id")) - set(scored) >= {svc.ben, svc.cai, hop, *crowd}

    def test_an_article_nobody_is_exposed_to_scores_nobody(self, svc, monkeypatch):
        scored = self.spy(svc, monkeypatch)
        add(svc, mart("x", ["Nowhere Land"], m=0.99), mart("y", [], m=0.99))
        stats = svc.run_alerts()
        assert scored == [] and stats["articles_material"] == 2 and stats["pairs_scored"] == 0
        assert svc.mongo.db.alerts.count_documents({}) == 0

    def test_aliases_reach_the_canonical_exposure(self, svc, monkeypatch):
        svc.logs.alias_upsert([{"alias": "man city", "entity_key": "manchester city"}], "seed")
        scored = self.spy(svc, monkeypatch)
        add(svc, mart("alias", ["Man City"], m=0.8))
        assert svc.run_alerts()["created"] == 1 and scored == [svc.ana]


class TestAlertsAPI:
    def test_endpoint(self, svc):
        add(svc, mart("sim", ["Manchester City"], m=0.8))
        svc.run_alerts()
        app = create_app()
        app.dependency_overrides[get_service] = lambda: svc
        client = TestClient(app)

        r = client.get(f"/v1/users/{svc.ana}/alerts")
        assert r.status_code == 200 and [a["article_id"] for a in r.json()] == ["sim"]
        assert r.json()[0]["explanation"].startswith("You own Manchester City.")
        assert client.get(f"/v1/users/{svc.ana}/alerts", params={"since": NOW.isoformat()}).json() == []
        naive = (NOW - timedelta(minutes=1)).replace(tzinfo=None).isoformat()            # naive = UTC
        assert len(client.get(f"/v1/users/{svc.ana}/alerts", params={"since": naive}).json()) == 1
        assert client.get(f"/v1/users/{svc.ben}/alerts").json() == []
        assert client.get("/v1/users/nobody/alerts").status_code == 404
        assert client.get(f"/v1/users/{svc.ana}/alerts", params={"limit": 0}).status_code == 422

    def test_unknown_user(self, svc):
        with pytest.raises(UserNotFound):
            svc.alerts("nobody")
