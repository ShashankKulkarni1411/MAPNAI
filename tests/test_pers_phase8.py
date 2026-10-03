"""
MAPNAI — tests/test_pers_phase8.py
Phase 8: the scheduler (six cron jobs in PERS_TZ, an empty cron unschedules a job, the lifespan starts and stops
it), the metric blocks (pure) and their collection on mongomock, delete_user, and the admin endpoints
(metrics, job list, manual runs with their error codes) plus the scheduler state in health.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from api.app import create_app
from api.personalization_router import get_service
from config.personalization import pers_settings
from personalization import jobs, metrics
from personalization.service import InvalidInput, PersonalizationService, UserNotFound
from tests.test_pers_phase2 import CFG, NOW, FakeMongo
from tests.test_pers_phase6 import Clock
from tests.test_pers_profile import FakeExposureStore


@pytest.fixture
def svc():
    s = PersonalizationService(mongo=FakeMongo(), exposures=FakeExposureStore(CFG), cfg=CFG, clock=Clock(NOW))
    s.ana = s.create_user("Ana", {"sports": 1.0},
                          None, [{"key": "manchester city", "role": "owns", "weight": "high"}])["user_id"]
    return s


# ── Scheduler ────────────────────────────────────────────────

class TestScheduler:
    def test_six_jobs_on_their_crons_in_the_configured_tz(self, svc):
        sched = jobs.build_scheduler(svc, CFG)
        by_id = {j.id: j for j in sched.get_jobs()}
        assert sorted(by_id) == ["alerts", "cluster", "digests", "pi_topk", "proposals", "tau"]
        assert str(by_id["alerts"].trigger.timezone) == "Asia/Kolkata"
        assert "minute='*/5'" in str(by_id["alerts"].trigger)
        assert "day_of_week='mon'" in str(by_id["proposals"].trigger)
        assert "hour='5'" in str(by_id["digests"].trigger) and "minute='30'" in str(by_id["digests"].trigger)
        # every fire goes through run_job (lease + job_runs row) with the service and the job name
        assert by_id["tau"].func is jobs.run_job and by_id["tau"].args == (svc, "tau")
        assert by_id["cluster"].max_instances == 1 and by_id["cluster"].coalesce is True

    def test_empty_cron_unschedules_a_job(self, svc):
        cfg = CFG.model_copy(update={"job_alerts": "", "job_proposals": "  "})
        assert sorted(jobs.schedule_table(cfg)) == ["cluster", "digests", "pi_topk", "tau"]
        assert sorted(j.id for j in jobs.build_scheduler(svc, cfg).get_jobs()) == \
            ["cluster", "digests", "pi_topk", "tau"]

    def test_status_before_start_and_without_scheduler(self, svc):
        status = jobs.scheduler_status(jobs.build_scheduler(svc, CFG))
        assert status["running"] is False and len(status["jobs"]) == 6
        assert all(j["next_run"] is None for j in status["jobs"].values())
        assert jobs.scheduler_status(None) == {"running": False, "jobs": {}}

    def test_a_scheduled_fire_records_a_job_run(self, svc):
        sched = jobs.build_scheduler(svc, CFG)
        job = next(j for j in sched.get_jobs() if j.id == "tau")
        job.func(*job.args)
        assert svc.logs.last_runs()["tau"]["ok"] is True
        assert svc.mongo.db.thresholds.count_documents({}) == 1

    def test_lifespan_starts_and_stops_the_scheduler(self, svc, monkeypatch):
        monkeypatch.setattr(pers_settings, "scheduler_enabled", True)
        monkeypatch.setattr(svc, "health", lambda hours=None: {"ok": True})      # no FAISS / Neo4j here
        app = create_app()
        app.dependency_overrides[get_service] = lambda: svc
        with TestClient(app) as client:
            sched = app.state.scheduler
            assert sched is not None and sched.running
            h = client.get("/v1/personalization/health").json()["scheduler"]
            assert h["running"] is True and len(h["jobs"]) == 6
            assert all(j["next_run"] for j in h["jobs"].values())
            assert all(job.args[0] is svc for job in sched.get_jobs())     # jobs share the endpoints' service
        assert not sched.running

    def test_lifespan_respects_the_toggle(self, svc, monkeypatch):
        monkeypatch.setattr(pers_settings, "scheduler_enabled", False)
        monkeypatch.setattr(svc, "health", lambda hours=None: {"ok": True})
        app = create_app()
        app.dependency_overrides[get_service] = lambda: svc
        with TestClient(app) as client:
            assert app.state.scheduler is None
            assert client.get("/v1/personalization/health").json()["scheduler"] == {"running": False, "jobs": {}}


# ── Metrics (pure) ───────────────────────────────────────────

class TestMetricBlocks:
    def test_rate_and_summary(self):
        assert metrics.rate(1, 3) == 0.3333 and metrics.rate(1, 0) is None
        assert metrics.summary([None]) is None
        assert metrics.summary([0.1, 0.5, 0.9, None, 0.3]) == \
            {"n": 4, "mean": 0.45, "p50": 0.5, "p90": 0.9, "max": 0.9}

    def test_engagement_reads_per_section(self):
        imp = [{"user_id": "u", "article_id": a, "section": s, "digest_id": "d"}
               for a, s in (("a", "must_know"), ("b", "must_know"), ("c", "for_you"), ("d", "explore"))]
        fb = [{"user_id": "u", "article_id": "a", "type": "open", "section": "must_know"},
              {"user_id": "u", "article_id": "a", "type": "more", "section": "must_know"},   # same pair once
              {"user_id": "u", "article_id": "c", "type": "less", "section": "for_you"},     # not a read
              {"user_id": "u", "article_id": "x", "type": "open", "section": "explore"}]     # never served there
        out = metrics.engagement(fb, imp, CFG.read_feedback_types)
        assert out["read_rate_by_section"] == {"must_know": 0.5, "for_you": 0.0, "explore": 0.0,
                                               "more_you_need": None}
        assert out["by_type"] == {"less": 1, "more": 1, "open": 2} and out["less_rate"] == 0.25
        assert metrics.serving(imp)["by_section"] == {"must_know": 2, "for_you": 1, "explore": 1,
                                                      "more_you_need": 0}

    def test_must_know_precision_and_miss_rate(self):
        fb = [{"type": t} for t in ["needed"] * 3 + ["not_needed"] + ["missed"]]
        out = metrics.must_know(fb, [], 0.2)
        assert (out["precision"], out["miss_rate"], out["tau"]) == (0.75, 0.25, 0.2)

    def test_articles_block(self):
        docs = [{"cluster_id": "c1", "materiality": {"m": 0.5, "unscored": True}},
                {"cluster_id": "c1", "materiality": {"m": 0.7, "unscored": False}},
                {"cluster_id": "c2", "materiality": {"m": 0.3, "unscored": True}},
                {}]
        out = metrics.articles(docs, 48)
        assert (out["articles"], out["clusters"], out["multi_article_clusters"]) == (4, 2, 1)
        assert out["clustered_share"] == 0.75 and out["unscored_share"] == 0.6667 and out["m"]["max"] == 0.7

    def test_jobs_block_keeps_the_latest_run(self):
        runs = [{"job": "tau", "started_at": NOW - timedelta(days=1), "ok": False, "error": "boom"},
                {"job": "tau", "started_at": NOW, "ok": True, "error": None}]
        assert metrics.jobs(runs)["tau"] == {"runs": 2, "failed": 1, "last_started": NOW, "last_ok": True,
                                             "last_error": None}


# ── Service ──────────────────────────────────────────────────

class TestServiceMetrics:
    def test_collects_every_block_over_the_window(self, svc):
        db = svc.mongo.db
        svc.logs.log_impressions([
            {"digest_id": "d1", "user_id": svc.ana, "article_id": "a", "section": "must_know", "t": NOW},
            {"digest_id": "d1", "user_id": svc.ana, "article_id": "b", "section": "explore", "propensity": 0.4,
             "t": NOW},
            {"digest_id": "old", "user_id": svc.ana, "article_id": "z", "section": "for_you",
             "t": NOW - timedelta(days=30)}])                                       # outside the 7-day window
        svc.logs.log_feedback([{"user_id": svc.ana, "article_id": "a", "type": "needed", "section": "must_know",
                                "t": NOW}])
        db.render_cache.insert_many([{"article_id": "a", "fallback": True, "reason": "fact_check", "model": "m",
                                      "created_at": NOW},
                                     {"article_id": "b", "fallback": False, "reason": None, "model": "m",
                                      "created_at": NOW}])
        svc.update_tau(NOW)
        out = svc.metrics(7)
        assert out["serving"]["impressions"] == 2 and out["serving"]["digests_served"] == 1
        assert out["serving"]["explore_propensity"]["mean"] == 0.4
        assert out["must_know"]["needed"] == 1 and len(out["must_know"]["tau_history"]) == 1
        assert out["render"]["fallback_share"] == 0.5 and out["render"]["fallback_reasons"] == {"fact_check": 1}
        assert out["users"]["personas"] == 1 and out["jobs"] == {}
        assert out["articles"]["articles"] == 0

    def test_days_must_be_positive(self, svc):
        with pytest.raises(InvalidInput):
            svc.metrics(0)


class TestDeleteUser:
    def test_removes_persona_edges_and_logs(self, svc):
        svc.logs.log_feedback([{"user_id": svc.ana, "article_id": "a", "type": "open", "t": NOW}])
        svc.logs.log_impressions([{"user_id": svc.ana, "article_id": "a", "t": NOW}])
        out = svc.delete_user(svc.ana)
        assert out["purged"]["feedback"] == 1 and out["purged"]["impressions"] == 1
        assert svc.personas.get(svc.ana) is None and svc.ana not in svc.exposures.users
        with pytest.raises(UserNotFound):
            svc.delete_user(svc.ana)

    def test_drop_tau_since(self, svc):
        svc.update_tau(NOW - timedelta(hours=1))
        svc.update_tau(NOW)
        assert svc.logs.drop_tau_since(NOW) == 1 and svc.mongo.db.thresholds.count_documents({}) == 1


# ── Admin API ────────────────────────────────────────────────

@pytest.fixture
def client(svc):
    app = create_app()
    app.dependency_overrides[get_service] = lambda: svc
    return TestClient(app)


class TestAdminAPI:
    def test_metrics(self, client):
        r = client.get("/v1/admin/metrics", params={"days": 3})
        assert r.status_code == 200 and r.json()["window"]["days"] == 3
        assert client.get("/v1/admin/metrics", params={"days": 0}).status_code == 422

    def test_job_list(self, client, svc):
        jobs.run_job(svc, "tau")
        body = client.get("/v1/admin/jobs").json()
        assert body["scheduler"] == {"running": False, "jobs": {}}          # no lifespan in this client
        assert body["jobs"]["tau"]["cron"] == "30 2 * * *" and body["jobs"]["tau"]["last_run"]["ok"] is True
        assert body["jobs"]["recluster"]["cron"] is None and body["jobs"]["pi_topk"]["per_user"] is True

    def test_run_a_job(self, client, svc):
        r = client.post("/v1/admin/jobs/pi_topk/run", params={"user": [svc.ana]})
        assert r.status_code == 200 and r.json()["stats"] == {"users": 1, "failed": {}}
        assert client.post("/v1/admin/jobs/tau/run").json()["ok"] is True

    def test_run_errors(self, client, svc):
        assert client.post("/v1/admin/jobs/nope/run").status_code == 404
        assert client.post("/v1/admin/jobs/tau/run", params={"user": ["x"]}).status_code == 422
        assert client.post("/v1/admin/jobs/tau/run", params={"rescan": True}).status_code == 422
        svc.logs.job_start("tau", NOW)                                      # a run holding the lease
        assert client.post("/v1/admin/jobs/tau/run").status_code == 409

    def test_a_failing_job_is_a_500_with_the_error(self, client, svc, monkeypatch):
        monkeypatch.setattr(svc, "update_tau", lambda: (_ for _ in ()).throw(RuntimeError("db down")))
        r = client.post("/v1/admin/jobs/tau/run")
        assert r.status_code == 500 and "db down" in r.json()["detail"]["error"]
        assert svc.logs.last_runs()["tau"]["ok"] is False
