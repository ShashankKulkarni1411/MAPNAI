"""
MAPNAI — tests/test_pers_phase4.py
Phase 4: need, the slate (must_know + more_you_need, MMR, topic caps + calibration, Thompson explore with
propensity), why lines, alias-canonical spread, and the digest service (cache, invalidation, impressions, API).
Pure functions first, then the service on mongomock with in-memory fakes.
"""

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import timedelta

import numpy as np
import pytest
from fastapi.testclient import TestClient

from api.app import create_app
from api.personalization_router import get_service
from personalization import candidates, explain, jobs, slate, spread
from personalization.service import PersonalizationService
from tests.test_pers_phase2 import CFG, NOW, FakeExposures, FakeMongo, FakeVectors


def it(article_id, topic="sports", need=0.0, rel=0.5, m=0.5, cluster=None):
    return {"article_id": article_id, "topic": topic, "need": need, "rel": rel, "m": m, "cluster_id": cluster}


def no_sim(a, b):
    return 0.0


def ids(items):
    return [i["article_id"] for i in items]


def by_topic(items):
    out = {}
    for i in items:
        out[slate.topic_of(i)] = out.get(slate.topic_of(i), 0) + 1
    return out


def persona(topics=None, beta=None):
    return {"topics": topics or {}, "beta": beta or {}}


def rng(seed=7):
    return np.random.default_rng(seed)


PI = {
    "acme": {"entity": "acme", "score": 1.0, "path": {"seed": "acme", "role": "owns", "via": [], "relations": []}},
    "zeta": {"entity": "zeta", "score": 0.1,
             "path": {"seed": "acme", "role": "owns", "via": [], "relations": ["MENTIONED_WITH"]}},
    "beta co": {"entity": "beta co", "score": 0.005,
                "path": {"seed": "acme", "role": "owns", "via": ["zeta"],
                         "relations": ["MENTIONED_WITH", "MENTIONED_WITH"]}},
}


# ── Need ─────────────────────────────────────────────────────

class TestNeed:
    def test_need_is_m_times_the_best_pi(self):
        n, entry = slate.need(["zeta", "acme", "none"], 0.6, PI)
        assert n == pytest.approx(0.6) and entry["entity"] == "acme"
        assert slate.need(["zeta"], 0.6, PI)[0] == pytest.approx(0.06)

    def test_no_hit_or_no_materiality_is_zero(self):
        assert slate.need(["none"], 0.9, PI) == (0.0, None)
        assert slate.need(["acme"], None, PI)[0] == 0.0

    def test_hits_best_first(self):
        assert [h["entity"] for h in slate.pi_hits(["beta co", "zeta", "acme"], PI)] == ["acme", "zeta", "beta co"]

    def test_relevance(self):
        assert slate.relevance(0.4, 0.5, CFG) == pytest.approx(0.4 + 0.3 * 0.5)

    def test_resolve_keys_replaces_aliases(self):
        assert candidates.resolve_keys(["man city", "x", "manchester city"], {"man city": "manchester city"}) == \
            ["manchester city", "x"]


# ── must_know ────────────────────────────────────────────────

class TestMustKnow:
    def test_cap_and_overflow_by_need(self):
        items = [it(f"a{i}", need=0.2 + i / 100) for i in range(8)] + [it("low", need=0.19), it("zero")]
        must, over = slate.pick_must_know(items, 0.2, CFG)
        assert ids(must) == ["a7", "a6", "a5", "a4", "a3"]
        assert ids(over) == ["a2", "a1", "a0"]                  # τ exactly (a0 = 0.20) counts

    def test_slate_keeps_the_overflow_in_more_you_need(self):
        items = [it(f"a{i}", need=0.5 - i / 100, rel=0.1) for i in range(8)] + \
                [it(f"x{i}", topic=f"t{i}", rel=0.9) for i in range(10)]
        out = slate.build_slate(items, 0.2, persona(), no_sim, rng(), CFG)
        sections = [i["section"] for i in out["items"]]
        assert sections[:5] == ["must_know"] * 5 and "must_know" not in sections[5:]
        assert ids(out["more_you_need"]) == ["a5", "a6", "a7"]
        assert all(i["section"] == "more_you_need" for i in out["more_you_need"])
        # overflow is never also in the slate, and nothing above τ is dropped
        assert not set(ids(out["more_you_need"])) & set(ids(out["items"]))
        assert out["stats"]["above_tau"] == 8 and len(out["items"]) == CFG.slate_k

    def test_fewer_than_the_cap(self):
        out = slate.build_slate([it("a", need=0.3), it("b", need=0.1)], 0.2, persona(), no_sim, rng(), CFG)
        assert [i["section"] for i in out["items"]][:1] == ["must_know"] and out["more_you_need"] == []
        assert out["items"][1]["section"] != "must_know"

    def test_tau_is_respected(self):
        items = [it("a", need=0.3), it("b", need=0.25)]
        assert ids(slate.pick_must_know(items, 0.26, CFG)[0]) == ["a"]


# ── MMR, topic caps, calibration ─────────────────────────────

class TestMMR:
    def test_lambda_one_is_greedy_by_rel(self):
        cfg = CFG.model_copy(update={"mmr_lambda": 1.0, "per_topic_cap": 100})
        items = [it(f"a{i}", rel=r) for i, r in enumerate([0.3, 0.9, 0.5, 0.7, 0.1])]
        sim = lambda a, b: 1.0                                   # would dominate if diversity were on
        assert ids(slate.mmr(items, sim, 5, cfg)) == ["a1", "a3", "a2", "a0", "a4"]

    def test_mmr_off_is_greedy_too(self):
        cfg = CFG.model_copy(update={"enable_mmr": False, "per_topic_cap": 100})
        items = [it("a", rel=0.9), it("b", rel=0.8), it("c", rel=0.5)]
        assert ids(slate.mmr(items, lambda a, b: 1.0, 3, cfg)) == ["a", "b", "c"]

    def test_diversity_demotes_a_near_duplicate(self):
        cfg = CFG.model_copy(update={"per_topic_cap": 100})
        items = [it("a", rel=0.9), it("a-dup", rel=0.85), it("other", rel=0.6)]
        sim = lambda x, y: 1.0 if {x, y} == {"a", "a-dup"} else 0.0
        # a-dup: .7·.85 − .3·1 = .295 < other: .7·.6 = .42
        assert ids(slate.mmr(items, sim, 3, cfg)) == ["a", "other", "a-dup"]

    def test_already_selected_items_count_for_diversity(self):
        cfg = CFG.model_copy(update={"per_topic_cap": 100})
        sim = lambda x, y: 1.0 if {x, y} == {"mk", "b"} else 0.0
        out = slate.mmr([it("b", rel=0.9), it("c", rel=0.7)], sim, 1, cfg, selected=[it("mk")])
        assert ids(out) == ["c"]


class TestTopicCaps:
    def test_per_topic_cap_3(self):
        items = [it(f"s{i}", rel=0.9 - i / 100) for i in range(8)] + \
                [it(f"o{i}", topic=f"t{i}", rel=0.1) for i in range(8)]
        cfg = CFG.model_copy(update={"enable_calibration": False, "enable_explore": False})
        out = slate.build_slate(items, 0.2, persona({"sports": 1.0}), no_sim, rng(), cfg)
        assert by_topic(out["items"])["sports"] == 3 and len(out["items"]) == 10

    def test_must_know_counts_towards_the_cap_but_is_never_cut(self):
        items = [it(f"mk{i}", need=0.5, rel=0.1) for i in range(4)] + \
                [it(f"s{i}", rel=0.9) for i in range(5)] + [it(f"o{i}", topic=f"t{i}", rel=0.2) for i in range(8)]
        cfg = CFG.model_copy(update={"enable_calibration": False, "enable_explore": False})
        out = slate.build_slate(items, 0.2, persona(), no_sim, rng(), cfg)
        assert by_topic(out["items"])["sports"] == 4                 # 4 must_know, 0 more sports
        assert all(i["section"] == "must_know" for i in out["items"] if i["topic"] == "sports")

    def test_calibration_caps_formula(self):
        caps = slate.calibration_caps({"sports": 1.0, "finance": 0.5}, 10, CFG)
        assert caps == {"sports": 8, "finance": 4}                  # round(10·2/3)+1, round(10·1/3)+1
        assert slate.calibration_caps({"sports": 1.0, "finance": 0.05}, 10, CFG)["finance"] == 1
        assert slate.calibration_caps({}, 10, CFG) == {}

    def test_effective_cap_is_min_of_calibration_and_per_topic(self):
        caps = {"sports": 8, "finance": 2}
        assert slate.topic_cap("sports", caps, CFG) == 3
        assert slate.topic_cap("finance", caps, CFG) == 2
        assert slate.topic_cap("film", caps, CFG) == 1                # undeclared
        assert slate.topic_cap("film", None, CFG) == 3                # calibration off

    def test_calibration_limits_a_small_share_and_undeclared_topics(self):
        items = [it(f"f{i}", topic="finance", rel=0.95) for i in range(4)] + \
                [it(f"o{i}", topic="other", rel=0.9) for i in range(4)] + \
                [it(f"s{i}", rel=0.5) for i in range(4)] + [it(f"x{i}", topic=f"t{i}", rel=0.2) for i in range(6)]
        p = persona({"sports": 1.0, "finance": 0.05})
        cfg = CFG.model_copy(update={"enable_explore": False})
        out = slate.build_slate(items, 0.2, p, no_sim, rng(), cfg)
        counts = by_topic(out["items"])
        assert counts["finance"] == 1 and counts["other"] == 1 and counts["sports"] == 3
        assert out["stats"]["caps_relaxed"] is False and len(out["items"]) == 10

    def test_calibration_relaxes_back_to_the_per_topic_cap_when_short(self):
        items = [it(f"s{i}", rel=0.9) for i in range(5)] + [it(f"o{i}", topic="other", rel=0.5) for i in range(5)]
        cfg = CFG.model_copy(update={"enable_explore": False})
        out = slate.build_slate(items, 0.2, persona({"sports": 1.0}), no_sim, rng(), cfg)
        counts = by_topic(out["items"])
        assert counts == {"sports": 3, "other": 3} and out["stats"]["caps_relaxed"] is True

    def test_calibration_off_or_no_declared_topics(self):
        items = [it(f"o{i}", topic="other", rel=0.9) for i in range(5)]
        cfg = CFG.model_copy(update={"enable_explore": False})
        assert by_topic(slate.build_slate(items, 0.2, persona(), no_sim, rng(), cfg)["items"])["other"] == 3


class TestNoDuplicateClusters:
    def test_one_item_per_cluster(self):
        items = [it("a", cluster="c1", rel=0.9), it("b", cluster="c1", rel=0.8, need=0.9),
                 it("c", cluster="c2", rel=0.7), it("d", cluster="c2", topic="other", rel=0.6),
                 it("e", rel=0.5), it("f", topic="film", rel=0.4, cluster="c3"), it("g", topic="film", cluster="c3")]
        out = slate.build_slate(items, 0.2, persona(), no_sim, rng(), CFG)
        served = out["items"] + out["more_you_need"]
        keys = [slate.cluster_key(i) for i in served]
        assert len(keys) == len(set(keys)) == 4                      # c1, c2, e, c3

    @pytest.mark.parametrize("seed", range(20))
    def test_random_slates_never_repeat_a_cluster(self, seed):
        r = np.random.default_rng(seed)
        items = [it(f"a{i}", topic=f"t{r.integers(6)}", need=float(r.uniform(0, 0.5)), rel=float(r.uniform()),
                    m=float(r.uniform()), cluster=f"c{r.integers(15)}") for i in range(40)]
        out = slate.build_slate(items, 0.2, persona({"t0": 1.0}), no_sim, rng(seed), CFG)
        served = out["items"] + out["more_you_need"]
        assert len({slate.cluster_key(i) for i in served}) == len(served)


# ── Thompson explore ─────────────────────────────────────────

class TestExplore:
    def test_topic_is_outside_the_slate_and_highest_m_is_picked(self):
        pool = [it("s", rel=0.9), it("f1", topic="finance", m=0.4), it("f2", topic="finance", m=0.8)]
        pick, p = slate.thompson_explore(pool, {"sports"}, {}, {}, rng(), CFG)
        assert pick["article_id"] == "f2" and p == 1.0               # one topic → always picked

    def test_empty_pool(self):
        assert slate.thompson_explore([it("s")], {"sports"}, {}, {}, rng(), CFG) == (None, 0.0)

    @pytest.mark.parametrize("seed", range(30))
    def test_propensity_in_zero_one(self, seed):
        pool = [it(f"x{i}", topic=f"t{i}") for i in range(5)]
        beta = {"topic:t0": [50, 1], "topic:t4": [1, 50]}
        _, p = slate.thompson_explore(pool, set(), beta, {}, rng(seed), CFG)
        assert 0.0 < p <= 1.0

    def test_propensity_is_never_zero_for_an_unlikely_pick(self):
        # t1 ~ Beta(1, 400) almost never beats t0 ~ Beta(400, 1); if it is picked it still has p = 1/201 > 0
        pool = [it("a", topic="t0"), it("b", topic="t1")]
        beta = {"topic:t0": [400, 1], "topic:t1": [1, 400]}
        for seed in range(50):
            pick, p = slate.thompson_explore(pool, set(), beta, {}, rng(seed), CFG)
            assert p >= 1 / (CFG.propensity_sims + 1)
            assert pick["article_id"] == "a" and p == 1.0

    def test_propensity_estimates_the_pick_probability(self):
        pool = [it("a", topic="t0"), it("b", topic="t1")]
        props = [slate.thompson_explore(pool, set(), {}, {}, rng(s), CFG)[1] for s in range(20)]
        assert all(0.35 < p < 0.65 for p in props)                  # two flat Betas: ≈ 0.5

    def test_reproducible_under_a_seed(self):
        pool = [it(f"x{i}", topic=f"t{i}") for i in range(4)]
        a = slate.thompson_explore(pool, set(), {}, {}, np.random.default_rng(slate.rng_seed("u1", "2026-09-29")), CFG)
        b = slate.thompson_explore(pool, set(), {}, {}, np.random.default_rng(slate.rng_seed("u1", "2026-09-29")), CFG)
        assert a == b and slate.rng_seed("u1", "2026-09-29") != slate.rng_seed("u1", "2026-09-30")

    def test_declared_prior_is_used_for_topics_without_a_beta(self):
        assert slate.topic_beta({}, "sports", {"sports": 1.0}, CFG) == [4.0, 1.0]
        assert slate.topic_beta({"topic:sports": [2, 3]}, "sports", {"sports": 1.0}, CFG) == [2.0, 3.0]
        assert slate.topic_beta({}, "film", {}, CFG) == [1.0, 1.0]

    @pytest.mark.parametrize("seed", range(25))
    def test_explore_is_never_must_know_or_overflow(self, seed):
        # six items above τ: the sixth (in its own topic, highest m) is overflow and must not come back as explore
        items = [it(f"mk{i}", need=0.9 - i / 100, rel=0.5) for i in range(5)] + \
                [it("over", topic="health", need=0.5, m=0.99, rel=0.4)] + \
                [it(f"s{i}", rel=0.6) for i in range(10)] + \
                [it("fin", topic="finance", m=0.3, rel=0.1), it("geo", topic="geopolitics", m=0.2, rel=0.1)]
        cfg = CFG.model_copy(update={"per_topic_cap": 100, "enable_calibration": False})
        out = slate.build_slate(items, 0.2, persona(), no_sim, rng(seed), cfg)
        explore = [i for i in out["items"] if i["section"] == "explore"]
        assert len(explore) == 1 and explore[0]["article_id"] in {"fin", "geo"}
        must = [i for i in out["items"] if i["section"] == "must_know"]
        assert explore[0]["article_id"] not in ids(must) + ids(out["more_you_need"])
        others = {slate.topic_of(i) for i in out["items"] if i["section"] != "explore"}
        assert explore[0]["topic"] not in others
        assert 0 < explore[0]["propensity"] <= 1 and explore[0]["slot"] == 10
        assert all(i["propensity"] == 1.0 for i in out["items"] if i["section"] != "explore")

    def test_empty_explore_pool_gives_the_slot_to_mmr(self):
        items = [it(f"s{i}", rel=0.9 - i / 100) for i in range(12)]
        cfg = CFG.model_copy(update={"per_topic_cap": 100})
        out = slate.build_slate(items, 0.2, persona({"sports": 1.0}), no_sim, rng(), cfg)
        assert out["stats"]["explore_skipped"] is True and len(out["items"]) == 10
        assert {i["section"] for i in out["items"]} == {"for_you"}

    def test_explore_off(self):
        items = [it(f"s{i}") for i in range(4)] + [it("f", topic="finance")]
        cfg = CFG.model_copy(update={"enable_explore": False})
        out = slate.build_slate(items, 0.2, persona(), no_sim, rng(), cfg)
        assert "explore" not in {i["section"] for i in out["items"]}


# ── Why lines ────────────────────────────────────────────────

NAMES = {"acme": "Acme", "zeta": "Zeta Corp", "beta co": "Beta Co"}


class TestTemplates:
    def test_direct(self):
        assert explain.why_direct(PI["acme"]["path"], CFG, NAMES) == "You own Acme."
        path = {"seed": "who", "role": "regulated_by", "via": [], "relations": []}
        assert explain.why_direct(path, CFG) == "You are regulated by who."

    def test_hop1_and_hop2(self):
        assert explain.why_hop(PI["zeta"], CFG, NAMES) == \
            "It mentions Zeta Corp, often mentioned with Acme, which you own."
        assert explain.why_hop(PI["beta co"], CFG, NAMES) == \
            "It mentions Beta Co, often mentioned with Zeta Corp, often mentioned with Acme, which you own."
        typed = {"entity": "sub", "score": 0.5,
                 "path": {"seed": "acme", "role": "owns", "via": [], "relations": ["SUBSIDIARY_OF"]}}
        assert explain.why_hop(typed, CFG) == "It mentions sub, subsidiary of acme, which you own."

    def test_why_exposure_dispatch(self):
        assert explain.why_exposure(PI["acme"], CFG, NAMES) == "You own Acme."
        assert explain.why_exposure(PI["zeta"], CFG, NAMES).startswith("It mentions Zeta Corp")

    def test_need_share(self):
        assert explain.need_share(1.0, 1.0) == 1.0 and explain.need_share(0.22, 1.0) == 0.22
        assert explain.need_share(0.1, 0.0) == 0.0

    def test_why_need_with_also(self):
        hits = slate.pi_hits(["zeta", "acme", "beta co"], PI)
        assert explain.why_need(0.6, 0.6, hits, CFG, NAMES) == \
            "Need 0.60 = materiality 0.60 × exposure 1.00; Acme drives 100% of it (also: Zeta Corp 0.10, Beta Co 0.01)."

    def test_also_skips_shares_that_round_to_zero_and_caps_the_list(self):
        pi = {k: {"entity": k, "score": s, "path": PI["acme"]["path"]}
              for k, s in {"a": 1.0, "b": 0.5, "c": 0.004, "d": 0.3, "e": 0.2}.items()}
        hits = slate.pi_hits(list(pi), pi)
        assert [h["entity"] for h in explain.also_hits(hits, CFG)] == ["b", "d"]
        assert explain.also_hits(slate.pi_hits(["a", "c"], pi), CFG) == []
        assert explain.why_need(0.3, 0.3, slate.pi_hits(["a", "c"], pi), CFG).endswith("drives 100% of it.")

    def test_why_interest_branches(self):
        base = {"lf": 0.0, "theta_topic": 0.5, "theta_entity": 0.5, "closest": None, "theta_entity_key": None}
        closest = {"article_id": "h", "title": "Old story"}
        assert explain.why_interest({**base, "lf": 0.8, "closest": closest}, "sports", CFG) == \
            "Similar to “Old story”, which you read."
        assert explain.why_interest({**base, "lf": 0.2, "closest": closest}, "sports", CFG, m=0.3) == \
            "A notable sports story (materiality 0.30)."               # weak similarity isn't claimed
        assert explain.why_interest({**base, "theta_topic": 0.8}, "entertainment_movies", CFG) == \
            "Matches your interest in entertainment movies (affinity 80%)."
        assert explain.why_interest({**base, "theta_entity": 0.9, "theta_entity_key": "zeta"}, "x", CFG, NAMES) == \
            "Features Zeta Corp, which you engage with."
        assert explain.why_interest({**base, "theta_entity": 0.9, "theta_entity_key": "zeta"}, "sports", CFG,
                                    NAMES, m=0.5, skip_entity="zeta") == "A notable sports story (materiality 0.50)."
        assert explain.why_interest(base, "other", CFG) == "A notable other story."

    def test_why_explore(self):
        assert explain.why_explore("supply_chain") == \
            "Something different: a top supply chain story, outside the topics in your digest."


# ── Spread: alias-canonical ──────────────────────────────────

class TestAliasSpread:
    ALIASES = {"man city": "manchester city", "manchester city's": "manchester city"}

    def test_alias_is_not_its_own_neighbour_and_spellings_merge(self):
        nbrs = {"manchester city": [{"key": "man city", "rel_type": "MENTIONED_WITH", "strength": 9, "freq": 5},
                                    {"key": "haaland", "rel_type": "MENTIONED_WITH", "strength": 2, "freq": 1}],
                "man city": [{"key": "haaland", "rel_type": "MENTIONED_WITH", "strength": 3, "freq": 2},
                             {"key": "manchester city's", "rel_type": "MENTIONED_WITH", "strength": 1, "freq": 1}]}
        out = spread.canonicalize_nbrs(nbrs, self.ALIASES)
        assert out == {"manchester city": [{"key": "haaland", "rel_type": "MENTIONED_WITH", "strength": 5.0,
                                            "freq": 3}]}

    def test_with_alias_sources(self):
        assert spread.with_alias_sources(["manchester city", "x"], self.ALIASES) == \
            ["manchester city", "x", "man city", "manchester city's"]

    def test_compute_pi_uses_aliases(self):
        mongo = FakeMongo()
        mongo.db.personas.insert_one({"user_id": "u", "name": "U", "topics": {}, "beta": {}, "history": []})
        mongo.db.entity_aliases.insert_many([{"alias": a, "entity_key": t} for a, t in self.ALIASES.items()])
        graph = {"manchester city": [{"key": "man city", "rel_type": "MENTIONED_WITH", "strength": 9, "freq": 5},
                                     {"key": "england", "rel_type": "MENTIONED_WITH", "strength": 3, "freq": 5}],
                 "man city": [{"key": "haaland", "rel_type": "MENTIONED_WITH", "strength": 6, "freq": 5}]}
        svc = PersonalizationService(mongo=mongo, exposures=FakeExposures(
            [{"key": "manchester city", "role": "owns", "weight": 3}], graph), vectors=FakeVectors({}), cfg=CFG,
            clock=lambda: NOW)
        pi = {e["entity"]: e["score"] for e in svc.compute_pi("u")}
        assert "man city" not in pi and pi["manchester city"] == 1.0
        # haaland (6, reached through the alias's node) is now the strongest neighbour: 0.1, england 3/6 → 0.05
        assert pi["haaland"] == pytest.approx(0.1) and pi["england"] == pytest.approx(0.05)


# ── Service: digest on mongomock ─────────────────────────────

class NamedExposures(FakeExposures):
    def get_exposures(self, user_id):
        return [{**e, "name": e["key"].title()} for e in super().get_exposures(user_id)]

    def display_names(self, keys):
        return {k: k.upper() for k in keys}


def adoc(article_id, topic, m, keys, cluster=None, hours_ago=2, source="BBC"):
    return {"article_id": article_id, "title": f"title {article_id}", "domain": topic, "source_name": source,
            "url": f"u/{article_id}", "published_at": (NOW - timedelta(hours=hours_ago)).isoformat(),
            "materiality": {"m": m, "risk_norm": None, "size_score": 0.29, "first_report": 0, "source_cred": 0.5,
                            "unscored": True},
            "cluster_id": cluster or f"c-{article_id}", "entity_keys": list(keys),
            "entities": [{"name": k.title(), "type": "Organization", "salience": 1.0} for k in keys]}


ARTICLES = [
    # 7 above τ (need = m × 1.0): 5 must_know + 2 more_you_need
    adoc("mk-s1", "sports", 0.90, ["acme", "zeta"]), adoc("mk-s2", "sports", 0.85, ["acme"]),
    adoc("mk-f1", "finance", 0.80, ["acme"]), adoc("mk-s3", "sports", 0.75, ["acme"]),
    adoc("mk-f2", "finance", 0.70, ["acme"]), adoc("ov-s4", "sports", 0.65, ["acme"]),
    adoc("ov-f3", "finance", 0.60, ["acme"]),
    adoc("mk-s1-b", "sports", 0.50, ["acme"], cluster="c-mk-s1", source="Reuters"),   # same story, other source
    adoc("hop", "sports", 0.50, ["zeta"]),                                           # need .05 < τ
    adoc("sp1", "sports", 0.30, ["team"]), adoc("sp2", "sports", 0.30, ["team"]),
    adoc("h1", "health", 0.30, ["who"]), adoc("o1", "other", 0.30, ["x"]), adoc("t1", "technology", 0.30, ["y"]),
    adoc("g1", "geopolitics", 0.30, ["z"]), adoc("e1", "entertainment_movies", 0.30, ["w"]),
    adoc("sc1", "supply_chain", 0.40, ["v"]), adoc("sc2", "supply_chain", 0.20, ["v"]),
]


@pytest.fixture
def dsvc():
    mongo = FakeMongo()
    mongo.db.processed_articles.insert_many([dict(a) for a in ARTICLES])
    mongo.db.personas.insert_one({
        "user_id": "u1", "name": "Ana", "topics": {"sports": 1.0}, "beta": {}, "history": [], "persona_version": 1,
        "pi_topk": [PI["acme"], PI["zeta"]], "alert_prefs": {"tz": "Asia/Kolkata"},
    })
    eye = np.eye(32, dtype=np.float32)
    vecs = {a["article_id"]: eye[i] for i, a in enumerate(ARTICLES)}
    fake = FakeVectors(vecs)
    fake.rows = dict(vecs)
    return PersonalizationService(mongo=mongo, exposures=NamedExposures([{"key": "acme", "role": "owns",
                                                                          "weight": 3}], {}),
                                  vectors=fake, cfg=CFG, clock=lambda: NOW)


def served(d):
    return d["items"] + d["more_you_need"]


class TestDigestService:
    def test_slate_sections_and_invariants(self, dsvc):
        d = dsvc.compute_digest("u1")
        secs = [i["section"] for i in d["items"]]
        assert len(d["items"]) == CFG.slate_k and [i["slot"] for i in d["items"]] == list(range(1, 11))
        assert secs[:5] == ["must_know"] * 5 and secs[-1] == "explore"
        assert ids(d["items"][:5]) == ["mk-s1", "mk-s2", "mk-f1", "mk-s3", "mk-f2"]
        assert ids(d["more_you_need"]) == ["ov-s4", "ov-f3"]
        clusters = [i["cluster_id"] for i in served(d)]
        assert len(clusters) == len(set(clusters))
        assert by_topic(d["items"])["sports"] <= 3                    # 3 must_know sports, no more
        assert all(i["need"] >= d["tau"] for i in d["items"] if i["section"] == "must_know")
        assert all(i["why"] for i in served(d))

    def test_explore_item(self, dsvc):
        d = dsvc.compute_digest("u1")
        ex = d["items"][-1]
        assert ex["topic"] not in {i["topic"] for i in d["items"][:-1]}
        assert ex["article_id"] not in ids(d["items"][:5]) + ids(d["more_you_need"])
        assert 0 < ex["propensity"] <= 1 and ex["why"].startswith("Something different")
        assert d["stats"]["explore_skipped"] is False
        assert dsvc.compute_digest("u1")["items"][-1] == ex             # same user + day → same draw

    def test_cluster_rep_and_another_angle(self, dsvc):
        top = dsvc.compute_digest("u1")["items"][0]
        assert top["article_id"] == "mk-s1" and top["cluster_members"] == 2
        assert top["another_angle"]["article_id"] == "mk-s1-b" and top["another_angle"]["source_name"] == "Reuters"

    def test_must_know_why_matches_its_path_share(self, dsvc):
        d = dsvc.compute_digest("u1")
        for item in d["items"][:5]:
            wp = item["why_parts"]
            assert wp["kind"] == "direct" and wp["entity"] == "acme" and wp["share"] == 1.0
            assert item["need"] == pytest.approx(item["m"] * wp["pi"])
            nums = re.search(r"Need ([\d.]+) = materiality ([\d.]+) × exposure ([\d.]+); (.+?) drives (\d+)%",
                             item["why"]).groups()
            assert float(nums[0]) == round(item["need"], 2) and float(nums[2]) == round(wp["pi"], 2)
            assert nums[3] == "Acme" and int(nums[4]) == round(wp["share"] * 100)
            assert item["why"].startswith("You own Acme.")
        first = d["items"][0]                                          # mentions acme and zeta
        assert first["why_parts"]["also"] == [{"entity": "zeta", "pi": 0.1, "share": 0.1}]
        assert first["why"].endswith("(also: ZETA 0.10).") or first["why"].endswith("(also: Zeta 0.10).")

    def test_tau_comes_from_thresholds(self, dsvc):
        dsvc.mongo.db.thresholds.insert_many([{"t": NOW - timedelta(days=1), "tau": 0.1}, {"t": NOW, "tau": 0.82}])
        d = dsvc.compute_digest("u1")                                  # latest row wins: only .90 and .85 ≥ .82
        assert d["tau"] == 0.82 and ids(d["items"][:2]) == ["mk-s1", "mk-s2"]
        assert [i["section"] for i in d["items"]].count("must_know") == 2

    def test_cache_impressions_and_invalidation(self, dsvc):
        imp = dsvc.mongo.db.impressions
        first = dsvc.get_digest("u1")
        assert first["cached"] is False and dsvc.mongo.db.digests.count_documents({}) == 1
        assert imp.count_documents({}) == len(served(first)) == 12
        row = imp.find_one({"article_id": "mk-s1"})
        assert row["section"] == "must_know" and row["slot"] == 1 and row["digest_id"] == first["digest_id"]
        assert {"need", "m", "m_parts", "interest", "interest_parts", "tau", "propensity", "policy_version",
                "persona_version", "impression_id", "cluster_id", "t"} <= set(row)

        second = dsvc.get_digest("u1")
        assert second["cached"] is True and second["digest_id"] != first["digest_id"]
        assert ids(served(second)) == ids(served(first))
        assert imp.count_documents({}) == 24 and imp.count_documents({"digest_id": second["digest_id"]}) == 12

        dsvc.patch_topics("u1", {"finance": 0.5})
        assert dsvc.mongo.db.digests.count_documents({}) == 0
        third = dsvc.get_digest("u1")
        assert third["cached"] is False and third["persona_version"] == 2

        assert dsvc.get_digest("u1", refresh=True)["cached"] is False

    def test_stale_persona_version_recomputes(self, dsvc):
        dsvc.get_digest("u1")
        dsvc.mongo.db.personas.update_one({"user_id": "u1"}, {"$inc": {"persona_version": 1}})
        assert dsvc.get_digest("u1")["cached"] is False

    def test_digest_date_is_the_users_local_day(self, dsvc):
        late = PersonalizationService(mongo=dsvc.mongo, exposures=dsvc.exposures, vectors=dsvc._vectors, cfg=CFG,
                                      clock=lambda: NOW.replace(hour=20))      # 20:00 UTC = 01:30 IST next day
        assert late.compute_digest("u1")["date"] == "2026-09-30"
        assert dsvc.compute_digest("u1")["date"] == "2026-09-29"

    def test_job_digests_precomputes_without_impressions(self, dsvc):
        out = jobs.run_job(dsvc, "digests")
        assert out["ok"] and out["stats"]["users"] == 1 and dsvc.mongo.db.impressions.count_documents({}) == 0
        assert dsvc.get_digest("u1")["cached"] is True

    def test_api(self, dsvc):
        app = create_app()
        app.dependency_overrides[get_service] = lambda: dsvc
        client = TestClient(app)
        r = client.get("/v1/users/u1/digest")
        assert r.status_code == 200 and len(r.json()["items"]) == 10
        assert client.get("/v1/users/u1/digest").json()["cached"] is True
        assert client.get("/v1/users/u1/digest?refresh=true").json()["cached"] is False
        assert client.get("/v1/users/nobody/digest").status_code == 404
