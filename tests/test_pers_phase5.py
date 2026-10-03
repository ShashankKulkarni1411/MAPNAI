"""
MAPNAI — tests/test_pers_phase5.py
Phase 5: feedback (all 8 types, section from the last impression), adaptive τ (math, counting, job, digest cache),
exposure proposals (engagement + A4-fact rules, job, accept / reject, API). Pure functions first, then the service
on mongomock with the in-memory Neo4j fake from the profile tests.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from api.app import create_app
from api.personalization_router import get_service
from personalization import explain, jobs
from personalization import feedback as fr
from personalization.service import Conflict, InvalidInput, PersonalizationService, ProposalNotFound
from tests.test_pers_phase2 import CFG, NOW, FakeMongo, FakeVectors
from tests.test_pers_phase4 import dsvc  # noqa: F401  (fixture)
from tests.test_pers_profile import FakeExposureStore


# ── τ (pure) ─────────────────────────────────────────────────

class TestTauMath:
    def test_on_target_is_unchanged(self):
        assert fr.tau_update(0.2, 1, 9, CFG) == {"tau": 0.2, "prev_tau": 0.2, "miss_rate": 0.1}

    def test_all_missed_lowers_by_045(self):
        assert fr.tau_update(0.2, 4, 0, CFG)["tau"] == pytest.approx(0.155)

    def test_all_needed_raises_by_005(self):
        assert fr.tau_update(0.2, 0, 3, CFG)["tau"] == pytest.approx(0.205)

    def test_half_missed(self):
        assert fr.tau_update(0.2, 1, 1, CFG) == {"tau": 0.18, "prev_tau": 0.2, "miss_rate": 0.5}

    def test_clip(self):
        assert fr.tau_update(0.06, 5, 0, CFG)["tau"] == CFG.tau_min
        assert fr.tau_update(0.6, 0, 5, CFG)["tau"] == CFG.tau_max

    def test_no_evidence_is_unchanged(self):
        assert fr.tau_update(0.3, 0, 0, CFG) == {"tau": 0.3, "prev_tau": 0.3, "miss_rate": None}


class TestTauCounts:
    def test_needed_counts_only_when_served_and_everything_once_per_pair(self):
        rows = [{"user_id": "u", "article_id": "a", "type": "needed"},
                {"user_id": "u", "article_id": "a", "type": "needed"},      # duplicate click
                {"user_id": "u", "article_id": "b", "type": "needed"},      # never in must_know
                {"user_id": "v", "article_id": "a", "type": "missed"},
                {"user_id": "v", "article_id": "a", "type": "missed"},
                {"user_id": "v", "article_id": "c", "type": "not_needed"},
                {"user_id": "v", "article_id": "d", "type": "open"}]
        assert fr.tau_counts(rows, {("u", "a")}) == {"needed": 1, "needed_ignored": 1, "missed": 1, "not_needed": 1}


# ── Proposals (pure) ─────────────────────────────────────────

def fb(article_id, keys, type_="open", value=None):
    return {"article_id": article_id, "type": type_, "value": value, "entity_keys": keys}


class TestEngagementProposals:
    BETA = {"entity:acme": [2.5, 1.0], "entity:zeta": [9.0, 1.0], "entity:meh": [1.0, 1.0]}

    def test_three_articles_and_theta(self):
        rows = [fb("a1", ["acme", "meh"]), fb("a2", ["acme", "meh"]), fb("a3", ["x", "y", "acme"]),
                fb("a3", ["x", "y", "acme"], "more"), fb("b1", ["meh"])]
        out = fr.engagement_proposals(rows, self.BETA, set(), set(), CFG)
        assert [p["entity_key"] for p in out] == ["acme"]              # meh: 3 articles but θ .5 < .7
        p = out[0]
        assert p["evidence"] == ["a1", "a2", "a3"] and p["articles"] == 3 and p["theta"] == pytest.approx(2.5 / 3.5)
        assert p["suggested_role"] == "follows" and p["suggested_weight"] == 1 and p["reason"] == "engagement"

    def test_two_articles_are_not_enough(self):
        assert fr.engagement_proposals([fb("a1", ["zeta"]), fb("a2", ["zeta"])], self.BETA, set(), set(), CFG) == []

    def test_medium_weight_from_high_theta(self):
        rows = [fb(f"a{i}", ["zeta"]) for i in range(3)]
        assert fr.engagement_proposals(rows, self.BETA, set(), set(), CFG)[0]["suggested_weight"] == 2

    def test_non_engagement_types_and_short_dwell_dont_count(self):
        rows = [fb("a1", ["zeta"]), fb("a2", ["zeta"], "less"), fb("a3", ["zeta"], "dwell", 5),
                fb("a4", ["zeta"], "needed"), fb("a5", ["zeta"], "missed")]
        assert fr.engagement_proposals(rows, self.BETA, set(), set(), CFG) == []
        rows.append(fb("a6", ["zeta"], "dwell", 40))
        rows.append(fb("a7", ["zeta"], "save"))
        assert fr.engagement_proposals(rows, self.BETA, set(), set(), CFG)[0]["evidence"] == ["a1", "a6", "a7"]

    def test_only_the_top_entities_count(self):
        rows = [fb(f"a{i}", ["p", "q", "r", "zeta"]) for i in range(3)]    # zeta is 4th → not a top entity
        assert fr.engagement_proposals(rows, self.BETA, set(), set(), CFG) == []

    def test_exposures_and_already_proposed_are_skipped(self):
        rows = [fb(f"a{i}", ["zeta", "acme"]) for i in range(3)]
        assert fr.engagement_proposals(rows, self.BETA, {"zeta"}, {"acme"}, CFG) == []

    def test_aliases_merge_spellings(self):
        rows = [fb("a1", ["man city"]), fb("a2", ["manchester city"]), fb("a3", ["man city"])]
        beta = {"entity:man city": [5.0, 1.0]}
        out = fr.engagement_proposals(rows, beta, set(), set(), CFG, {"man city": "manchester city"})
        assert out[0]["entity_key"] == "manchester city" and out[0]["articles"] == 3
        assert out[0]["theta"] == pytest.approx(5 / 6)

    def test_cap_and_order(self):
        beta = {f"entity:e{i}": [9.0, 1.0] for i in range(5)}
        rows = [fb(f"a{j}", [f"e{i}"]) for i in range(5) for j in range(3 + (i == 4))]
        out = fr.engagement_proposals(rows, beta, set(), set(), CFG)
        assert [p["entity_key"] for p in out] == ["e4", "e0", "e1"]        # most articles first, then key


class TestFactProposals:
    ARTS = [
        {"article_id": "a1", "facts": [{"type": "acquisition", "subject": "Acme", "object": "Widget Co"},
                                       {"type": "supplier", "subject": "Parts Ltd", "object": "ACME"},
                                       {"type": "sanction", "subject": "EU", "object": "Nobody"},
                                       {"type": "merger", "subject": "Acme", "object": "Other"}]},
        {"article_id": "a2", "facts": [{"type": "Acquisition", "subject": "acme", "object": "widget co"}]},
    ]

    def test_rules_and_sides(self):
        out = {p["entity_key"]: p for p in fr.fact_proposals(self.ARTS, {"acme"}, set(), CFG)}
        assert set(out) == {"widget co", "parts ltd"}                     # no exposure in the sanction; merger unknown
        assert out["widget co"]["suggested_role"] == "owns" and out["widget co"]["evidence"] == ["a1", "a2"]
        assert out["parts ltd"]["suggested_role"] == "depends_on" and out["parts ltd"]["via"] == "acme"
        assert all(p["reason"] == "a4_fact" and p["suggested_weight"] == 1 for p in out.values())

    def test_wrong_side_and_blocked(self):
        assert fr.fact_proposals(self.ARTS, {"widget co"}, set(), CFG) == []   # the acquired side isn't an anchor
        assert [p["entity_key"] for p in fr.fact_proposals(self.ARTS, {"acme"}, {"widget co"}, CFG)] == ["parts ltd"]


class TestTexts:
    def test_why_proposal(self):
        p = {"entity_key": "england", "suggested_role": "follows", "reason": "engagement", "articles": 3,
             "theta": 0.714}
        assert explain.why_proposal(p, CFG, {"england": "England"}) == \
            "You engaged with 3 articles featuring England in the last 7 days (affinity 71%). " \
            "Add it as something you follow?"
        f = {"entity_key": "parts ltd", "suggested_role": "depends_on", "reason": "a4_fact", "fact_type": "supplier",
             "via": "acme"}
        assert explain.why_proposal(f, CFG) == \
            "A recent article reports a supplier link between parts ltd and acme; you may depend on parts ltd."

    def test_confirmed_exposure_sentence(self):
        exps = [{"name": "England", "role": "follows", "weight_label": "low", "provenance": "confirmed"},
                {"name": "WHO", "role": "follows", "weight_label": "high", "provenance": "declared"}]
        assert explain.profile_sentences(exps, {}, {}, CFG)[:2] == [
            "You follow England (low, from a suggestion you accepted).", "You follow WHO (high)."]


# ── Service on mongomock ─────────────────────────────────────

def art(article_id, ents, topic="sports", hours_ago=3):
    return {"article_id": article_id, "title": f"title {article_id}", "domain": topic, "source_name": "BBC",
            "url": f"u/{article_id}", "published_at": (NOW - timedelta(hours=hours_ago)).isoformat(),
            "entities": [{"name": n, "type": "Location", "salience": 1.0 - i / 10} for i, n in enumerate(ents)]}


ARTICLES = [
    art("e1", ["England", "Manchester City"]), art("e2", ["England"]), art("e3", ["U.S", "England"]),
    art("e4", ["England", "WHO"], topic="health"), art("n1", ["Nowhere Land"]), art("n2", ["Nowhere Land"]),
    art("n3", ["Nowhere Land"]), art("mc", ["Manchester City"]), art("w1", ["WHO"], topic="health"),
]


@pytest.fixture
def svc():
    mongo = FakeMongo()
    mongo.db.processed_articles.insert_many([dict(a) for a in ARTICLES])
    s = PersonalizationService(mongo=mongo, exposures=FakeExposureStore(CFG), vectors=FakeVectors({}), cfg=CFG,
                               clock=lambda: NOW)
    s.user_id = s.create_user("Ana", {"sports": 1.0}, None,
                              [{"key": "manchester city", "role": "owns", "weight": "high"}])["user_id"]
    return s


def impression(svc, article_id, section, t=None, user_id=None):
    svc.logs.log_impressions([{"user_id": user_id or svc.user_id, "article_id": article_id, "section": section,
                               "slot": 1, "digest_id": "d1", "t": t or NOW}])


class TestFeedbackService:
    def test_all_types(self, svc):
        u = svc.user_id
        for t in CFG.feedback_types:
            out = svc.record_feedback(u, "e2", t, value=30 if t == "dwell" else None)
            assert out["type"] == t
            assert bool(out["beta_deltas"]) is (t in ("open", "more", "less", "dwell"))
            assert out["history_added"] is (t in ("open", "more", "save", "dwell"))
        assert svc.mongo.db.feedback.count_documents({"user_id": u, "article_id": "e2"}) == len(CFG.feedback_types)

    def test_theta_is_returned_for_changed_keys(self, svc):
        out = svc.record_feedback(svc.user_id, "e2", "more")
        assert out["beta"]["topic:sports"] == [5.0, 1.0] and out["theta"]["topic:sports"] == pytest.approx(5 / 6)
        out = svc.record_feedback(svc.user_id, "w1", "less")
        assert out["beta"]["topic:health"] == [1.0, 2.0] and out["theta"]["entity:who"] == pytest.approx(1 / 3)

    def test_section_comes_from_the_last_impression(self, svc):
        impression(svc, "e1", "for_you", NOW - timedelta(hours=5))
        impression(svc, "e1", "must_know", NOW - timedelta(hours=1))
        out = svc.record_feedback(svc.user_id, "e1", "needed")
        assert out["section"] == "must_know" and out["served"]["section"] == "must_know"
        assert out["counts_for_tau"] is True
        assert svc.mongo.db.feedback.find_one({"type": "needed"})["section"] == "must_know"
        assert svc.record_feedback(svc.user_id, "e1", "open", section="alert")["section"] == "alert"

    def test_needed_outside_must_know_does_not_count(self, svc):
        impression(svc, "e2", "for_you")
        assert svc.record_feedback(svc.user_id, "e2", "needed")["counts_for_tau"] is False
        assert svc.record_feedback(svc.user_id, "e3", "needed")["served"] is None
        assert svc.record_feedback(svc.user_id, "e3", "missed")["counts_for_tau"] is True


class TestTauService:
    def test_update_writes_a_row_and_moves_tau(self, svc):
        impression(svc, "e1", "must_know")
        svc.record_feedback(svc.user_id, "e1", "needed")
        svc.record_feedback(svc.user_id, "e2", "needed")              # not served in must_know → ignored
        svc.record_feedback(svc.user_id, "e3", "missed")
        row = svc.update_tau()
        assert row["prev_tau"] == 0.2 and row["tau"] == pytest.approx(0.18) and row["miss_rate"] == 0.5
        assert (row["missed"], row["needed"], row["needed_ignored"], row["window_days"]) == (1, 1, 1, 7)
        assert svc.logs.current_tau() == pytest.approx(0.18)
        assert svc.mongo.db.thresholds.count_documents({}) == 1

    def test_old_feedback_and_old_impressions_are_outside_the_window(self, svc):
        old = NOW - timedelta(days=8)
        svc.logs.log_feedback([{"user_id": svc.user_id, "article_id": "e3", "type": "missed", "t": old}])
        impression(svc, "e1", "must_know", old)
        svc.record_feedback(svc.user_id, "e1", "needed")
        row = svc.update_tau()
        assert (row["missed"], row["needed"], row["needed_ignored"]) == (0, 0, 1)
        assert row["tau"] == 0.2 and row["miss_rate"] is None             # no evidence: kept, row still logged
        assert svc.mongo.db.thresholds.count_documents({}) == 1

    def test_job(self, svc):
        svc.record_feedback(svc.user_id, "e3", "missed")
        out = jobs.run_job(svc, "tau")
        assert out["ok"] and out["stats"]["tau"] == pytest.approx(0.155)
        assert svc.mongo.db.job_runs.find_one({"job": "tau"})["ok"] is True

    def test_a_new_tau_invalidates_the_cached_digest(self, dsvc):
        assert dsvc.get_digest("u1")["cached"] is False
        assert dsvc.get_digest("u1")["cached"] is True
        dsvc.logs.push_tau({"t": NOW, "tau": 0.82, "prev_tau": 0.2})
        d = dsvc.get_digest("u1")
        assert d["cached"] is False and d["tau"] == 0.82

    def test_feedback_does_not_invalidate_the_cached_digest(self, dsvc):
        dsvc.get_digest("u1")
        dsvc.record_feedback("u1", "sp1", "more")
        assert dsvc.get_digest("u1")["cached"] is True
        assert "sp1" not in [i["article_id"] for i in dsvc.get_digest("u1", refresh=True)["items"]]   # now read


class TestProposalService:
    def engage(self, svc, ids=("e1", "e2", "e3"), type_="open"):
        for a in ids:
            svc.record_feedback(svc.user_id, a, type_)

    def test_engagement_creates_one_pending_proposal(self, svc):
        self.engage(svc)
        stats = svc.run_proposals()
        assert stats["created"] == 1 and stats["by_reason"] == {"engagement": 1, "a4_fact": 0}
        assert stats["a4_fact_rule"] == "inactive (a4_facts_field unset)"
        [p] = svc.list_proposals(svc.user_id, "pending")
        assert p["entity_key"] == "england" and p["name"] == "England" and p["evidence"] == ["e1", "e2", "e3"]
        assert (p["suggested_role"], p["suggested_weight"], p["suggested_weight_label"]) == ("follows", 1, "low")
        assert p["origin"] == "proposed" and p["signal"]["theta"] == pytest.approx(2.5 / 3.5)
        assert p["why"].startswith("You engaged with 3 articles featuring England")
        # manchester city (in e1) is already an exposure; no graph edge is written by the job
        assert svc.exposures.get_exposures(svc.user_id)[0]["key"] == "manchester city"
        assert len(svc.exposures.get_exposures(svc.user_id)) == 1
        assert svc.get_profile(svc.user_id)["pending_proposals"] == 1

    def test_rerun_does_not_duplicate(self, svc):
        self.engage(svc)
        svc.run_proposals()
        again = svc.run_proposals()
        assert again["created"] == 0 and svc.mongo.db.proposals.count_documents({}) == 1

    def test_entities_missing_from_the_graph_are_not_proposed(self, svc):
        self.engage(svc, ("n1", "n2", "n3"))
        stats = svc.run_proposals()
        assert stats["created"] == 0 and stats["unresolved"] == 1

    def test_old_engagement_is_outside_the_window(self, svc):
        self.engage(svc)
        later = PersonalizationService(mongo=svc.mongo, exposures=svc.exposures, vectors=svc._vectors, cfg=CFG,
                                       clock=lambda: NOW + timedelta(days=8))
        assert later.run_proposals()["created"] == 0

    def test_disabled(self, svc):
        self.engage(svc)
        off = PersonalizationService(mongo=svc.mongo, exposures=svc.exposures, vectors=svc._vectors,
                                     clock=lambda: NOW,
                                     cfg=CFG.model_copy(update={"enable_proposals": False}))
        assert off.run_proposals()["skipped"] and svc.mongo.db.proposals.count_documents({}) == 0

    def test_accept_writes_a_confirmed_edge_and_changes_the_profile(self, svc):
        self.engage(svc)
        svc.run_proposals()
        pid = svc.list_proposals(svc.user_id)[0]["proposal_id"]
        before = svc.get_profile(svc.user_id)
        svc.get_digest(svc.user_id)
        out = svc.accept_proposal(svc.user_id, pid)
        assert out["proposal"]["status"] == "accepted" and out["proposal"]["decided_at"] == NOW
        assert out["exposure"]["provenance"] == "confirmed" and out["exposure"]["role"] == "follows"
        edge = next(e for e in svc.exposures.edges.values() if e["key"] == "england")
        assert edge["provenance"] == "confirmed"
        assert out["persona_version"] == before["persona_version"] + 1
        assert "You follow England (low, from a suggestion you accepted)." in out["sentences"]
        after = svc.get_profile(svc.user_id)
        assert "You follow England (low, from a suggestion you accepted)." in after["sentences"]
        assert after["pending_proposals"] == 0
        assert svc.mongo.db.digests.count_documents({}) == 0             # edit → cached digest dropped
        assert {e["entity"] for e in after["pi_topk"]} == {"manchester city", "england"}
        with pytest.raises(Conflict):
            svc.accept_proposal(svc.user_id, pid)

    def test_accept_with_override(self, svc):
        self.engage(svc)
        svc.run_proposals()
        pid = svc.list_proposals(svc.user_id)[0]["proposal_id"]
        with pytest.raises(InvalidInput):
            svc.accept_proposal(svc.user_id, pid, role="boss")
        assert svc.list_proposals(svc.user_id, "pending")                # a bad override leaves it pending
        out = svc.accept_proposal(svc.user_id, pid, role="covers", weight="high")
        assert out["exposure"]["role"] == "covers" and out["exposure"]["weight"] == 3
        assert out["proposal"]["accepted_role"] == "covers" and out["proposal"]["accepted_weight"] == 3

    def test_reject_changes_nothing(self, svc):
        self.engage(svc)
        svc.run_proposals()
        pid = svc.list_proposals(svc.user_id)[0]["proposal_id"]
        before = svc.get_profile(svc.user_id)
        out = svc.reject_proposal(svc.user_id, pid)
        assert out["proposal"]["status"] == "rejected"
        after = svc.get_profile(svc.user_id)
        assert {k: after[k] for k in ("persona_version", "sentences", "exposures", "beta")} == \
            {k: before[k] for k in ("persona_version", "sentences", "exposures", "beta")}
        with pytest.raises(Conflict):
            svc.reject_proposal(svc.user_id, pid)
        assert svc.run_proposals()["created"] == 0                     # a rejected entity isn't proposed again

    def test_unknown_proposal(self, svc):
        with pytest.raises(ProposalNotFound):
            svc.accept_proposal(svc.user_id, "nope")

    def test_a4_fact_rule(self, svc):
        svc.mongo.db.processed_articles.update_one({"article_id": "mc"}, {"$set": {"event_facts": [
            {"type": "supplier", "subject": "WHO", "object": "Manchester City"}]}})
        on = PersonalizationService(mongo=svc.mongo, exposures=svc.exposures, vectors=svc._vectors,
                                    clock=lambda: NOW, cfg=CFG.model_copy(update={"a4_facts_field": "event_facts"}))
        stats = on.run_proposals()
        assert stats["a4_fact_rule"].startswith("active (event_facts: 1 ")
        [p] = on.list_proposals(svc.user_id)
        assert (p["entity_key"], p["reason"], p["suggested_role"], p["evidence"]) == \
            ("who", "a4_fact", "depends_on", ["mc"])
        assert p["why"] == "A recent article reports a supplier link between WHO and manchester city; " \
                           "you may depend on WHO."


class TestProposalAPI:
    def test_endpoints(self, svc):
        for a, t in [("e1", "more"), ("e2", "more"), ("e3", "more"), ("e4", "more"), ("e1", "open"), ("e2", "open"),
                     ("e3", "open")]:
            svc.record_feedback(svc.user_id, a, t)                    # england [1+4+1.5, 1] → θ .87 → medium
        svc.run_proposals()
        app = create_app()
        app.dependency_overrides[get_service] = lambda: svc
        client = TestClient(app)
        u = svc.user_id

        r = client.get(f"/v1/users/{u}/proposals?status=pending")
        assert r.status_code == 200 and [p["entity_key"] for p in r.json()] == ["england"]
        assert r.json()[0]["suggested_weight_label"] == "medium"
        pid = r.json()[0]["proposal_id"]
        assert client.get(f"/v1/users/{u}/proposals?status=maybe").status_code == 422
        assert client.get("/v1/users/nobody/proposals").status_code == 404
        assert client.post(f"/v1/users/{u}/proposals/nope/accept").status_code == 404

        r = client.post(f"/v1/users/{u}/proposals/{pid}/accept", json={"weight": "low"})
        assert r.status_code == 200 and r.json()["exposure"]["weight_label"] == "low"
        assert client.post(f"/v1/users/{u}/proposals/{pid}/accept").status_code == 409
        assert client.post(f"/v1/users/{u}/proposals/{pid}/reject").status_code == 409
        assert client.get(f"/v1/users/{u}/proposals?status=accepted").json()[0]["proposal_id"] == pid

    def test_feedback_endpoint_types(self, svc):
        app = create_app()
        app.dependency_overrides[get_service] = lambda: svc
        client = TestClient(app)
        for t in CFG.feedback_types:
            body = {"user_id": svc.user_id, "article_id": "e1", "type": t, **({"value": 20} if t == "dwell" else {})}
            assert client.post("/v1/feedback", json=body).status_code == 200
        assert client.post("/v1/feedback", json={"user_id": svc.user_id, "article_id": "e1",
                                                 "type": "like"}).status_code == 422
        assert client.post("/v1/feedback", json={"user_id": svc.user_id, "article_id": "zz",
                                                 "type": "open"}).status_code == 404
