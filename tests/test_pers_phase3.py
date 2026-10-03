"""
MAPNAI — tests/test_pers_phase3.py
Phase 3: two-window late-fusion interest, Beta affinities, the four retrievers + RRF + cluster collapse, and
feedback → Beta + history. Pure functions first, then the service on mongomock with in-memory fakes.
"""

import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from config.personalization import PersonalizationSettings
from personalization import candidates, interest
from personalization.service import InvalidInput, PersonalizationService
from tests.test_pers_phase2 import FakeExposures, FakeMongo, FakeVectors, unit

CFG = PersonalizationSettings(_env_file=None)
NOW = datetime(2026, 9, 29, 12, 0, tzinfo=timezone.utc)
E = np.eye(8, dtype=np.float32)


def hist(article_id, hours_ago, w=1.0, win="both"):
    return {"article_id": article_id, "title": article_id, "t": NOW - timedelta(hours=hours_ago), "w": w, "win": win}


def parts(vec, history, hist_vecs, beta=None, topics=None, article=None):
    persona = {"history": history, "beta": beta or {}, "topics": topics or {}}
    return interest.interest(article or {"topic": "sports", "entity_keys": []}, vec, persona, hist_vecs, NOW, CFG)


# ── Decay ────────────────────────────────────────────────────

class TestDecay:
    @pytest.mark.parametrize("age,expected", [(0, 1.0), (24, 0.5), (48, 0.25), (72, 0.125), (-5, 1.0)])
    def test_half_life(self, age, expected):
        assert interest.decay(age, 24) == pytest.approx(expected)

    def test_monotonic_and_positive(self):
        values = [interest.decay(h, 24) for h in range(0, 24 * 60, 6)]
        assert all(a > b for a, b in zip(values, values[1:])) and values[-1] > 0

    def test_recent_item_dominates_the_fusion(self):
        # sim 1 read now (weight 1), sim 0 read 24h ago (weight 0.5): LF_short = 1 / 1.5
        lf, closest = interest.late_fusion(E[1], [hist("a", 0), hist("b", 24)], {"a": E[1], "b": E[2]}, NOW,
                                           72, 24, include_long_only=False)
        assert lf == pytest.approx(2 / 3) and closest["article_id"] == "a"

    def test_same_items_older_decay_less_in_the_long_window(self):
        # 3 days old vs fresh: in the short window (half-life 24h) the gap is 8x, in the long (21d) it is ~1.1x
        history, vecs = [hist("fresh", 0), hist("old", 72)], {"fresh": E[1], "old": E[2]}
        short, _ = interest.late_fusion(E[2], history, vecs, NOW, 72, 24, include_long_only=False)
        long, _ = interest.late_fusion(E[2], history, vecs, NOW, 60 * 24, 21 * 24, include_long_only=True)
        assert short == pytest.approx(0.125 / 1.125) and long == pytest.approx(0.5 ** (72 / 504) / (1 + 0.5 ** (72 / 504)))

    def test_items_outside_the_window_are_ignored(self):
        lf, closest = interest.late_fusion(E[1], [hist("a", 73)], {"a": E[1]}, NOW, 72, 24, include_long_only=False)
        assert (lf, closest) == (0.0, None)

    def test_history_weight_counts(self):
        lf, _ = interest.late_fusion(E[1], [hist("a", 0, w=2), hist("b", 0, w=1)], {"a": E[1], "b": E[2]}, NOW,
                                     72, 24, include_long_only=False)
        assert lf == pytest.approx(2 / 3)


# ── Two windows ──────────────────────────────────────────────

class TestWindows:
    def test_empty_short_window_uses_long_only(self):
        score, p = parts(E[1], [hist("old", 24 * 5)], {"old": E[1]})
        assert p["lf_short"] == 0.0 and p["lf_long"] > 0 and p["lf"] == p["lf_long"]

    def test_onboarding_items_are_long_window_only(self):
        _, p = parts(E[1], [hist("onb", 1, win="long")], {"onb": E[1]})
        assert p["lf_short"] == 0.0 and p["lf"] == p["lf_long"] == pytest.approx(1.0)

    def test_both_windows_mix_04_06(self):
        history = [hist("recent", 1), hist("old", 24 * 10)]
        _, p = parts(E[1], history, {"recent": E[1], "old": E[2]})
        assert p["lf"] == pytest.approx(0.4 * p["lf_short"] + 0.6 * p["lf_long"], abs=1e-6)
        assert p["lf_short"] == pytest.approx(1.0)

    def test_everything_empty_is_zero(self):
        _, p = parts(E[1], [], {})
        assert p["lf"] == 0.0 and p["closest"] is None

    def test_no_article_vector(self):
        _, p = parts(None, [hist("a", 1)], {"a": E[1]})
        assert p["lf"] == 0.0 and p["has_vector"] is False

    def test_late_fusion_differs_from_the_mean_vector(self):
        history, vecs = [hist("a", 0), hist("b", 0)], {"a": E[1], "b": E[2]}
        lf, _ = interest.late_fusion(E[1], history, vecs, NOW, 72, 24, include_long_only=False)
        mean_vec = (E[1] + E[2]) / 2
        early = float(np.dot(E[1], mean_vec) / np.linalg.norm(mean_vec))
        assert lf == pytest.approx(0.5) and early == pytest.approx(math.sqrt(0.5)) and lf != pytest.approx(early)

    def test_negative_similarity_is_floored(self):
        lf, _ = interest.late_fusion(-E[1], [hist("a", 0)], {"a": E[1]}, NOW, 72, 24, include_long_only=False)
        assert lf == 0.0


# ── Beta affinities ──────────────────────────────────────────

class TestBeta:
    def test_prior(self):
        assert interest.prior(1.0, CFG) == [4.0, 1.0] and interest.prior(0.0, CFG) == [1.0, 4.0]

    def test_topic_theta_learned_declared_default(self):
        assert interest.topic_theta({"topic:sports": [6, 2]}, "sports", {"sports": 0.1}, CFG) == 0.75
        assert interest.topic_theta({}, "sports", {"sports": 1.0}, CFG) == 0.8
        assert interest.topic_theta({}, "finance", {"sports": 1.0}, CFG) == 0.5

    def test_max_entity_theta(self):
        beta = {"entity:acme": [8, 2], "entity:zeta": [1, 9]}
        assert interest.max_entity_theta(beta, ["zeta", "acme"]) == 0.8
        assert interest.max_entity_theta(beta, ["zeta"]) == 0.1
        assert interest.max_entity_theta(beta, ["zeta", "unknown"]) == 0.5   # an unseen entity is the flat prior
        assert interest.max_entity_theta(beta, []) == 0.5

    def test_interest_combines_weights(self):
        score, p = parts(E[1], [hist("a", 1)], {"a": E[1]}, beta={"topic:sports": [3, 1], "entity:acme": [1, 1]},
                         article={"topic": "sports", "entity_keys": ["acme"]})
        assert score == pytest.approx(0.5 * 1.0 + 0.3 * 0.75 + 0.2 * 0.5)


# ── Retrievers, RRF, collapse ────────────────────────────────

def d(article_id, hours_ago=1, topic="sports", keys=("acme",), m=0.5, cluster=None, source="BBC", entities=None):
    doc = {"article_id": article_id, "title": f"t {article_id}", "domain": topic, "source_name": source,
           "published_at": (NOW - timedelta(hours=hours_ago)).isoformat(), "materiality": {"m": m} if m else None,
           "cluster_id": cluster, "entity_keys": list(keys)}
    if entities is not None:
        del doc["entity_keys"]
        doc["entities"] = entities
    return doc


class TestRetrievers:
    def test_r1_ranks_by_pi_then_m_and_reads_entities_when_keys_are_missing(self):
        pi = [{"entity": "acme", "score": 1.0}, {"entity": "zeta", "score": 0.1}]
        docs = [d("z", keys=["zeta"], m=0.9), d("a1", keys=["acme"], m=0.3), d("a2", keys=["x", "acme"], m=0.6),
                d("none", keys=["other"]), d("raw", entities=[{"name": "ACME", "salience": 1.0}], m=0.1)]
        assert candidates.r1_exposure(docs, pi, CFG) == ["a2", "a1", "raw", "z"]

    def test_r1_canonicalizes_article_keys_through_aliases(self):
        pi = [{"entity": "manchester city", "score": 1.0}, {"entity": "man city", "score": 0.1}]
        docs = [d("alias", keys=["man city"]), d("poss", keys=["manchester city's"]), d("other", keys=["x"])]
        aliases = {"man city": "manchester city", "manchester city's": "manchester city"}
        assert candidates.r1_exposure(docs, pi, CFG) == ["alias"]                    # only the weak hop hit
        assert candidates.r1_exposure(docs, pi, CFG, aliases) == ["alias", "poss"]  # both are direct now
        assert candidates.canonical_keys(["man city", "x"], aliases) == ["man city", "manchester city", "x"]

    def test_r2_window_and_top(self):
        cfg = CFG.model_copy(update={"r2_top": 2})
        docs = [d("old", hours_ago=30, m=0.99), d("a", m=0.4), d("b", m=0.8), d("c", m=0.6), d("none", m=None)]
        assert candidates.r2_material(docs, NOW, cfg) == ["b", "c"]

    def test_r4_recency_times_m(self):
        docs = [d("new-low", hours_ago=1, m=0.3), d("old-high", hours_ago=40, m=0.9), d("mid", hours_ago=5, m=0.6),
                d("film", topic="entertainment_movies", m=1.0)]
        # 0.5^(1/24)*.3 = .29, 0.5^(40/24)*.9 = .28, 0.5^(5/24)*.6 = .52
        assert candidates.r4_topic(docs, "sports", NOW, CFG) == ["mid", "new-low", "old-high"]

    def test_r3_restricts_to_window_and_drops_the_item(self):
        hits = {"h1": [("h1", 1.0), ("a", 0.9), ("outside", 0.8), ("b", 0.7)]}
        assert candidates.r3_similar(hits, {"a", "b", "h1"}, CFG) == [["a", "b"]]

    def test_rrf_order(self):
        fused = dict(candidates.rrf([["a", "b", "c"], ["c", "b"]], k=60))
        assert fused == pytest.approx({"c": 1 / 63 + 1 / 61, "b": 2 / 62, "a": 1 / 61})
        assert [a for a, _ in candidates.rrf([["a", "b", "c"], ["c", "b"]], k=60)] == ["c", "b", "a"]
        assert [a for a, _ in candidates.rrf([["y"], ["x"]], k=60)] == ["x", "y"]      # ties → article_id

    def test_r1_and_r2_bypass_the_fused_cut(self):
        cfg = CFG.model_copy(update={"fused_top": 2})
        r3 = [["x1", "x2", "x3"], ["x1", "x2", "x3"]]
        fused, sources = candidates.merge_candidates(["exp"], ["mat"], r3, [], cfg)
        kept = [a for a, _ in fused]
        assert {"exp", "mat"} <= set(kept) and "x3" not in kept and len(kept) == 4
        assert sources["exp"] == {"R1"} and sources["x1"] == {"R3"}

    def test_drop_read(self):
        assert candidates.drop_read([("a", 1.0), ("b", 0.5)], {"a"}) == [("b", 0.5)]

    def test_collapse_keeps_best_and_another_angle_from_a_different_source(self):
        scored = [
            {"article_id": "a", "cluster_id": "c", "source_name": "BBC", "score": 0.9, "title": "A"},
            {"article_id": "b", "cluster_id": "c", "source_name": "BBC", "score": 0.8, "title": "B"},
            {"article_id": "c", "cluster_id": "c", "source_name": "Reuters", "score": 0.5, "title": "C"},
            {"article_id": "s", "cluster_id": None, "source_name": "X", "score": 0.95, "title": "S"},
        ]
        out = candidates.collapse_clusters(scored)
        assert [o["article_id"] for o in out] == ["s", "a"]
        assert out[1]["another_angle"] == {"article_id": "c", "title": "C", "source_name": "Reuters"}
        assert out[1]["cluster_members"] == 3 and out[0]["another_angle"] is None


# ── Service ──────────────────────────────────────────────────

@pytest.fixture
def svc():
    mongo = FakeMongo()
    mongo.db.processed_articles.insert_many([
        d("acme-1", 2, keys=["acme"], m=0.7, cluster="c1", source="BBC"),
        d("acme-2", 3, keys=["acme", "x"], m=0.5, cluster="c1", source="Reuters"),
        d("film", 4, topic="entertainment_movies", keys=["zeta"], m=0.9, cluster="c2"),
        d("sport", 5, keys=["team"], m=0.2, cluster="c3"),
        d("read-one", 6, keys=["acme"], m=0.4, cluster="c4"),
        d("old", 24 * 4, keys=["acme"], m=0.9, cluster="c5"),
    ])
    mongo.db.personas.insert_one({
        "user_id": "u1", "name": "Ana", "topics": {"sports": 1.0}, "beta": {},
        "history": [hist("read-one", 1)],
        "pi_topk": [{"entity": "acme", "score": 1.0, "path": {"seed": "acme", "role": "owns", "via": [],
                                                              "relations": []}}],
    })
    vecs = {"acme-1": unit(8, 0.9, 1), "acme-2": unit(8, 0.9, 2), "film": unit(8, 0.0, 3), "sport": unit(8, 0.5, 4),
            "read-one": unit(8, 1.0, 5), "old": unit(8, 1.0, 6)}
    fake = FakeVectors(vecs)
    fake.rows = dict(vecs)
    return PersonalizationService(mongo=mongo, exposures=FakeExposures([{"key": "acme", "role": "owns",
                                                                         "weight": 3}], {}),
                                  vectors=fake, cfg=CFG, clock=lambda: NOW)


class TestServiceCandidates:
    def test_retrievers_fusion_read_filter_and_collapse(self, svc):
        out = svc.candidates("u1")
        st = out["stats"]
        assert out["retrieved"]["R1"] == ["acme-1", "acme-2", "read-one"]
        assert st["retrievers"]["R2"] == 5 and st["r4_topics"] == ["sports"]
        assert st["read_dropped"] == 1 and "read-one" not in [i["article_id"] for i in out["items"]]
        assert "old" not in {a for s in out["retrieved"].values() for a in s}      # outside the 48h window
        top = {i["cluster_id"]: i for i in out["items"]}
        assert top["c1"]["cluster_members"] == 2 and top["c1"]["another_angle"]["source_name"] != \
            top["c1"]["source_name"]
        assert st["vector_coverage"] == 1.0
        acme = next(i for i in out["items"] if i["cluster_id"] == "c1")
        assert "R1" in acme["sources"] and acme["interest_parts"]["closest"]["article_id"] == "read-one"

    def test_feedback_updates_beta_and_history(self, svc):
        out = svc.record_feedback("u1", "sport", "more")
        assert out["beta"]["topic:sports"] == [5.0, 1.0]            # declared prior [4, 1] + more
        assert out["beta"]["entity:team"] == [2.0, 1.0] and out["history_added"]
        assert svc.personas.get("u1")["history"][-1]["article_id"] == "sport"
        assert "sport" in svc.logs.read_ids("u1", svc.personas.get("u1")["history"])

    def test_short_dwell_changes_nothing_but_is_logged(self, svc):
        out = svc.record_feedback("u1", "film", "dwell", value=5)
        assert out["beta_deltas"] == {} and out["history_added"] is False
        assert svc.mongo.db.feedback.count_documents({"type": "dwell"}) == 1

    def test_logged_only_types_and_validation(self, svc):
        assert svc.record_feedback("u1", "film", "needed")["beta_deltas"] == {}
        with pytest.raises(InvalidInput):
            svc.record_feedback("u1", "film", "like")
        with pytest.raises(InvalidInput):
            svc.record_feedback("u1", "film", "dwell")
