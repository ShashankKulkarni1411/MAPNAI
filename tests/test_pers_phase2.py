"""
MAPNAI — tests/test_pers_phase2.py
Phase 2: clustering, materiality and exposure spread — the pure functions (PERSONALIZATION_PLAN.md §6 Phase 2
verify list plus the calibrated join rule), then the clustering job, recluster and compute_pi end to end on
mongomock with in-memory fakes for the personalization FAISS index and Neo4j.
"""

import math
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

from datetime import datetime, timedelta, timezone

import mongomock
import numpy as np
import pytest

from calibrate_clustering import DEFAULT_FILE, choose, load_pairs, sweep
from config.personalization import PersonalizationSettings
from personalization import clustering, jobs, materiality, spread
from personalization.service import PersonalizationService

CFG = PersonalizationSettings(_env_file=None)
NOW = datetime(2026, 9, 29, 12, 0, tzinfo=timezone.utc)


# ── C. Clustering (pure) ─────────────────────────────────────

def art(article_id, hours_ago=0.0, keys=("acme",), cluster_id=None, title=""):
    meta = {"article_id": article_id, "published": NOW - timedelta(hours=hours_ago), "entity_keys": list(keys),
            "title": title or f"story {article_id}"}
    if cluster_id:
        meta["cluster_id"] = cluster_id
    return meta


@pytest.mark.parametrize("delta", [-0.01, 0.0])
@pytest.mark.parametrize("dt_h", [35, 37])
@pytest.mark.parametrize("shared", [0, 1])
def test_join_rule_grid(delta, dt_h, shared):
    cos = CFG.cos_join + delta
    known = {"old": art("old", dt_h, ["acme"] if shared else ["other"], cluster_id="c-old", title="alpha beta")}
    new = art("new", 0, ["acme"], title="gamma delta")
    op = clustering.assign_clusters([new], {"new": [("old", cos)]}, known, CFG)[0]
    expected = cos >= CFG.cos_join and dt_h <= 36 and shared == 1
    assert (op["cluster_id"] == "c-old") is expected


@pytest.mark.parametrize("dt_h", [5, 47])
def test_strong_similarity_needs_no_evidence(dt_h):
    known = {"old": art("old", dt_h, ["other"], cluster_id="c-old", title="alpha beta")}
    op = clustering.assign_clusters([art("new", 0, ["acme"], title="gamma delta")],
                                    {"new": [("old", CFG.cos_strong)]}, known, CFG)[0]
    assert op["cluster_id"] == "c-old"


class TestFuzzyEntities:
    @pytest.mark.parametrize("a,b", [
        ("Sarapatta 2", "Sarpatta"),                 # sequel number dropped, then ratio 94
        ("Atlético Madrid", "atletico madrid"),       # accents
        ("the asian games 2026", "asian games"),      # leading "the", year
        ("Ranbir Kapoor's", "ranbir kapoor"),         # possessive
        ("Ranbir Kapoor’s", "ranbir kapoor"),         # curly possessive
        ("pa. ranjith", "Pa Ranjith"),                # punctuation
    ])
    def test_match(self, a, b):
        assert clustering.fuzzy_shared_entities([a], [b], CFG.fuzzy_entity_min) == [(a, b)]

    @pytest.mark.parametrize("a,b", [("india", "indiana"), ("us", "uk"), ("sarapatta", "sarpatta parambarai"),
                                     ("2026", "2026")])
    def test_no_match(self, a, b):
        assert clustering.fuzzy_shared_entities([a], [b], CFG.fuzzy_entity_min) == []

    def test_normalize(self):
        assert clustering.normalize_entity("The Asian Games 2026") == "asian games"
        assert clustering.normalize_entity("Sarapatta 2'") == "sarapatta"

    def test_fuzzy_entity_is_join_evidence(self):
        known = {"old": art("old", 3, ["Sarpatta"], cluster_id="c", title="shoot begins")}
        new = art("new", 0, ["Sarapatta 2"], title="arya starts filming")
        op = clustering.assign_clusters([new], {"new": [("old", CFG.cos_join)]}, known, CFG)[0]
        assert op["cluster_id"] == "c"


class TestTitleJaccard:
    def test_tokens_drop_stopwords_and_punctuation(self):
        assert clustering.title_tokens("LIVE: The Giants trade for McCarthy!") == {"giants", "trade", "mccarthy"}

    def test_jaccard(self):
        assert clustering.title_jaccard("Giants trade for McCarthy", "McCarthy trade: Giants react") == \
            pytest.approx(3 / 4)
        assert clustering.title_jaccard("", "anything") == 0.0

    @pytest.mark.parametrize("title_b,joins", [
        ("SpaceX Starship reaches orbit", True),       # jaccard 4/6
        ("Rocket news roundup today", False),         # jaccard 0
    ])
    def test_jaccard_is_join_evidence_without_entities(self, title_b, joins):
        known = {"old": art("old", 1, ["x"], cluster_id="c", title="SpaceX's Starship reaches orbit first time")}
        new = art("new", 0, ["y"], title=title_b)
        ev = clustering.evidence(new, known["old"], CFG)
        assert ev["entities"] == [] and (ev["jaccard"] >= CFG.title_jaccard_min) is joins
        op = clustering.assign_clusters([new], {"new": [("old", CFG.cos_join + 0.01)]}, known, CFG)[0]
        assert (op["cluster_id"] == "c") is joins


class TestAntiChaining:
    def cluster(self):
        return {"a": art("a", 3, ["acme"], cluster_id="c"), "b": art("b", 2, ["acme"], cluster_id="c")}

    def test_mean_guard_blocks_a_chain(self):
        # close to b, far from a: max .85 but mean .60 < cos_join − chain_margin
        sims = {("new", "a"): 0.35}
        op = clustering.assign_clusters([art("new")], {"new": [("b", 0.85)]}, self.cluster(), CFG,
                                        sim=lambda x, y: sims.get((x, y)))[0]
        assert op["created"] is True

    def test_mean_guard_passes_a_coherent_cluster(self):
        sims = {("new", "a"): CFG.cos_join - CFG.chain_margin}
        op = clustering.assign_clusters([art("new")], {"new": [("b", 0.85)]}, self.cluster(), CFG,
                                        sim=lambda x, y: sims.get((x, y)))[0]
        assert op["cluster_id"] == "c" and op["best_cos"] == 0.85

    def test_compares_against_every_member(self):
        # the only NN hit is weak, but another member (reached through sim) is a strong match
        sims = {("new", "a"): 0.90}
        op = clustering.assign_clusters([art("new")], {"new": [("b", 0.70)]}, self.cluster(), CFG,
                                        sim=lambda x, y: sims.get((x, y)))[0]
        assert op["cluster_id"] == "c" and op["best_cos"] == 0.90 and op["mean_cos"] == 0.8


def test_best_cluster_wins_and_merge_is_only_reported():
    known = {"a": art("a", cluster_id="c-a"), "b": art("b", cluster_id="c-b")}
    op = clustering.assign_clusters([art("new")], {"new": [("a", 0.84), ("b", 0.86)]}, known, CFG)[0]
    assert op["cluster_id"] == "c-b" and op["merge_candidates"] == ["c-a"] and op["best_cos"] == 0.86


def test_new_articles_seed_clusters_oldest_first_and_ignore_self():
    new = [art("later", 1), art("earlier", 5)]
    nbrs = {"later": [("later", 1.0), ("earlier", 0.9)], "earlier": [("earlier", 1.0), ("later", 0.9)]}
    ops = {op["article_id"]: op for op in clustering.assign_clusters(new, nbrs, {}, CFG)}
    assert ops["earlier"]["created"] and ops["earlier"]["cluster_id"] == "earlier"
    assert ops["later"]["cluster_id"] == "earlier" and not ops["later"]["created"]


def test_unclustered_or_unknown_neighbours_are_ignored():
    ops = clustering.assign_clusters([art("new")], {"new": [("ghost", 0.99), ("loose", 0.99)]},
                                     {"loose": art("loose")}, CFG)
    assert ops[0]["created"] is True


def test_missing_published_does_not_crash():
    new = [{"article_id": "x", "published": None, "entity_keys": []}]
    assert clustering.assign_clusters(new, {}, {}, CFG)[0]["cluster_id"] == "x"
    assert clustering.cluster_summary(new)["first_report"] == "x"


def test_cluster_summary_uses_earliest_article_and_entity_union():
    members = [
        {"article_id": "b", "published": "2026-09-29T02:00:00Z", "entity_keys": ["x"]},
        {"article_id": "a", "published": "2026-09-29T07:00:00+05:00", "entity_keys": ["y", "x"]},
        {"article_id": "c", "published": "2026-09-29T02:00:00+00:00", "entity_keys": []},
    ]
    # all three are the same instant (07:00+05:00 = 02:00Z), so the smallest article_id wins
    assert clustering.cluster_summary(members) == {
        "size": 3, "first_report": "a", "first_published": "2026-09-29T07:00:00+05:00", "entity_keys": ["x", "y"],
    }
    assert clustering.cluster_summary(members[:1] + [
        {"article_id": "z", "published": "2026-09-29T06:00:00+05:00", "entity_keys": []}])["first_report"] == "z"


class TestCalibration:
    """Regression guard on the labelled pairs (tests/data/cluster_pairs.jsonl, labelled 2026-09-29)."""

    def test_labelled_set_shape(self):
        rows = load_pairs(DEFAULT_FILE)
        assert len(rows) >= 50 and all(isinstance(r["same_event"], bool) for r in rows)
        assert all(0.68 <= r["cos"] <= 0.90 and r["dt_h"] <= 36 for r in rows)

    def test_default_is_the_calibrated_choice(self):
        results = sweep(load_pairs(DEFAULT_FILE), CFG)
        chosen, _ = choose(results, 0.95)
        assert CFG.cos_join == chosen
        at_default = next(r for r in results if r["t"] == chosen)
        assert at_default["precision"] >= 0.9 and at_default["recall"] >= 0.5

    def test_choose_falls_back_to_highest_precision(self):
        results = [{"t": 0.7, "precision": 0.8}, {"t": 0.75, "precision": 0.9}, {"t": 0.8, "precision": 0.9}]
        assert choose(results, 0.95) == (0.75, False)
        assert choose(results, 0.85) == (0.75, True)


# ── D. Materiality (pure) ────────────────────────────────────

def test_size_score():
    assert materiality.size_score(10, CFG) == 1.0
    assert materiality.size_score(50, CFG) == 1.0
    assert materiality.size_score(0, CFG) == 0.0
    assert materiality.size_score(1, CFG) == pytest.approx(math.log(2) / math.log(11))


def test_unscored_is_renormalized_over_present_components():
    cfg = CFG.model_copy(update={"source_cred": {"wire": 0.8}})
    r = materiality.materiality({"risk_score": None, "source_name": "wire"}, 11, True, cfg)
    assert r == {"m": round((0.2 * 1.0 + 0.15 * 1 + 0.15 * 0.8) / 0.5, 6), "risk_norm": None, "size_score": 1.0,
                 "first_report": 1, "source_cred": 0.8, "unscored": True}
    assert r["m"] == 0.94


def test_singleton_gets_no_first_report():
    single = materiality.materiality({"risk_score": None, "source_name": "x"}, 1, True, CFG)
    pair = materiality.materiality({"risk_score": None, "source_name": "x"}, 2, True, CFG)
    assert single["first_report"] == 0 and pair["first_report"] == 1
    assert single["m"] == pytest.approx((0.2 * math.log(2) / math.log(11) + 0.15 * 0.5) / 0.5, abs=1e-6)


def test_scored_risk_uses_all_weights_and_clamps():
    cfg = CFG.model_copy(update={"source_cred": {"odd": 2.0}})
    r = materiality.materiality({"risk_score": 140, "source_name": "odd"}, 1, False, cfg)
    assert (r["risk_norm"], r["source_cred"], r["unscored"], r["first_report"]) == (1.0, 1.0, False, 0)
    r = materiality.materiality({"risk_score": 40, "source_name": "unknown"}, 1, False, CFG)
    assert r["risk_norm"] == 0.4 and r["source_cred"] == 0.5
    assert r["m"] == pytest.approx(0.5 * 0.4 + 0.2 * math.log(2) / math.log(11) + 0.15 * 0.5, abs=1e-6)


@pytest.mark.parametrize("bad", [None, "n/a", True, float("nan")])
def test_unusable_risk_is_unscored(bad):
    r = materiality.materiality({"risk_score": bad}, 1, False, CFG)
    assert r["unscored"] is True and r["risk_norm"] is None


def test_source_credibility_table_is_loaded():
    table = PersonalizationSettings(_env_file=None).source_cred
    assert table["Reuters"] == 0.8 and table["Mint"] == 0.6 and table["Pinkvilla"] == 0.4
    assert all(v in (0.4, 0.5, 0.6, 0.8) for v in table.values())


# ── B. Spread (pure) ─────────────────────────────────────────

def nbr(key, strength, rel="MENTIONED_WITH", freq=0):
    return {"key": key, "rel_type": rel, "strength": strength, "freq": freq}


def by_entity(pi):
    return {e["entity"]: e for e in pi}


@pytest.mark.parametrize("weight,score", [(1, 1 / 3), (2, 2 / 3), (3, 1.0)])
def test_seed_score(weight, score):
    assert spread.seed_score(weight, CFG) == pytest.approx(score)


def test_rel_weight_mapping():
    assert spread.rel_weight("MENTIONED_WITH", CFG) == 0.1
    assert spread.rel_weight("SUBSIDIARY_OF", CFG) == 0.5
    assert spread.rel_weight("SOMETHING_NEW", CFG) == 0.1


def test_hop1_normalised_by_the_seeds_strongest_neighbour():
    pi = by_entity(spread.spread([{"key": "s", "role": "owns", "weight": 3}],
                                 {"s": [nbr("a", 4), nbr("b", 2)]}, None, CFG))
    assert pi["s"]["score"] == 1.0
    assert pi["a"]["score"] == 0.1 and pi["b"]["score"] == 0.05
    assert pi["a"]["path"] == {"seed": "s", "role": "owns", "via": [], "relations": ["MENTIONED_WITH"]}


def test_hop2_decay_and_path():
    pi = by_entity(spread.spread([{"key": "s", "role": "owns", "weight": 3}],
                                 {"s": [nbr("sup", 4, "SUPPLIES")]},
                                 {"sup": [nbr("region", 2, "LOCATED_IN")]}, CFG))
    assert pi["sup"]["score"] == 0.3
    assert pi["region"]["score"] == pytest.approx(0.3 * 0.15 * 0.5)
    assert pi["region"]["path"] == {"seed": "s", "role": "owns", "via": ["sup"],
                                    "relations": ["SUPPLIES", "LOCATED_IN"]}


def test_hop2_disabled():
    cfg = CFG.model_copy(update={"enable_hop2": False})
    pi = spread.spread([{"key": "s", "role": "follows", "weight": 3}], {"s": [nbr("one", 1)]},
                       {"one": [nbr("two", 1)]}, cfg)
    assert {e["entity"] for e in pi} == {"s", "one"}


def test_max_merge_keeps_best_path():
    seeds = [{"key": "low", "role": "follows", "weight": 1}, {"key": "high", "role": "owns", "weight": 3}]
    pi = by_entity(spread.spread(seeds, {"low": [nbr("x", 1)], "high": [nbr("x", 1)]}, None, CFG))
    assert pi["x"]["score"] == 0.1 and pi["x"]["path"]["seed"] == "high"


def test_seeds_are_never_changed_by_a_hop():
    seeds = [{"key": "parent", "role": "owns", "weight": 3}, {"key": "child", "role": "follows", "weight": 1}]
    pi = by_entity(spread.spread(seeds, {"parent": [nbr("child", 1, "SUBSIDIARY_OF")]},
                                 {"child": [nbr("grandchild", 1)]}, CFG))
    assert pi["child"]["score"] == pytest.approx(1 / 3, abs=1e-6)
    assert pi["child"]["path"]["relations"] == []
    assert "grandchild" not in pi        # hop 2 expands only non-seed hop-1 entities; child is a seed


def test_top_cuts_and_frequency_tie_break():
    hop1 = {"s": [nbr(f"h{i:02d}", 30 - i) for i in range(25)]}
    hop2 = {f"h{i:02d}": [nbr(f"x{i:02d}-{j:02d}", 20 - j) for j in range(15)] for i in range(25)}
    pi = spread.spread([{"key": "s", "role": "owns", "weight": 3}], hop1, hop2, CFG)
    hop1_hits = [e for e in pi if len(e["path"]["relations"]) == 1]
    hop2_hits = [e for e in pi if len(e["path"]["relations"]) == 2]
    assert len(hop1_hits) == 20 and len(hop2_hits) == 20 * 10
    assert spread.hop1_keys(pi) == [f"h{i:02d}" for i in range(20)]

    tied = spread.spread([{"key": "s", "role": "owns", "weight": 3}],
                         {"s": [nbr("rare", 1, freq=1), nbr("common", 1, freq=9)]},
                         None, CFG.model_copy(update={"hop1_top": 1}))
    assert [e["entity"] for e in tied] == ["s", "common"]


def test_pi_topk_max_and_order():
    hop1 = {"s": [nbr(f"n{i}", 1) for i in range(10)]}
    pi = spread.spread([{"key": "s", "role": "owns", "weight": 3}], hop1, None,
                       CFG.model_copy(update={"pi_topk_max": 4}))
    assert [e["entity"] for e in pi] == ["s", "n0", "n1", "n2"]


# ── Service: clustering job, recluster, compute_pi (mongomock + fakes) ──

class FakeMongo:
    def __init__(self):
        self.db = mongomock.MongoClient().db


def unit(dim, base_cos, k):
    """A unit vector with cosine base_cos to e0 and its remainder on axis k (so two such vectors on different
    axes have cosine base_cos_1 · base_cos_2)."""
    v = np.zeros(dim, dtype=np.float32)
    v[0] = base_cos
    v[k] = math.sqrt(max(0.0, 1 - base_cos ** 2))
    return v


class FakeVectors:
    """The PersVectorStore contract over a dict of preset vectors."""

    def __init__(self, preset):
        self.preset, self.rows = preset, {}

    def indexed_article_ids(self):
        return set(self.rows)

    def sync_from_mongo(self, docs):
        added = [d["article_id"] for d in docs if d["article_id"] in self.preset and d["article_id"] not in self.rows]
        for a in added:
            self.rows[a] = self.preset[a]
        return len(added)

    def vectors_for(self, ids):
        return {a: self.rows[a] for a in ids if a in self.rows}

    def search_vector(self, vec, k):
        hits = sorted(((a, float(np.dot(vec, v))) for a, v in self.rows.items()), key=lambda h: -h[1])
        return hits[:k]

    @property
    def total_vectors(self):
        return len(self.rows)


class FakeExposures:
    def __init__(self, seeds, graph):
        self.seeds, self.graph = seeds, graph

    def sync_name_lower(self):
        return 0

    def get_seeds(self, user_id):
        return self.seeds

    def get_exposures(self, user_id):
        return [{"key": s["key"], "role": s["role"], "weight": s["weight"]} for s in self.seeds]

    def neighbours(self, keys, top):
        return {k: self.graph[k][:top] for k in keys if k in self.graph}


def doc(article_id, hours_ago, ents, title, source="BBC", domain="sports"):
    return {"article_id": article_id, "title": title, "body": "body", "domain": domain,
            "source_name": source, "url": f"u/{article_id}", "risk_score": None,
            "published_at": (NOW - timedelta(hours=hours_ago)).isoformat(),
            "entities": [{"name": n, "type": "Organization", "salience": 1.0 - i / 10} for i, n in enumerate(ents)]}


VECS = {
    "a1": unit(8, 1.0, 1), "a2": unit(8, 0.9, 2), "a3": unit(8, 0.82, 3), "b1": unit(8, 0.0, 4),
    "c1": unit(8, 0.85, 5), "old": unit(8, 1.0, 6), "a4": unit(8, 0.95, 7),
}


@pytest.fixture
def svc():
    mongo = FakeMongo()
    mongo.db.processed_articles.insert_many([
        doc("a1", 10, ["Acme", "X Corp"], "Acme recalls widgets"),
        doc("a2", 8, ["ACME"], "Widget recall widens"),          # cos .90 with a1 ≥ cos_strong
        doc("a3", 7, ["acme"], "Regulators probe faulty parts"),  # cos .82 with a1, shares "acme", Δt 3h
        doc("b1", 9, ["Zeta"], "Film festival opens", domain="entertainment_movies"),
        doc("c1", 6, ["Other"], "Markets rally on data"),         # cos .85 with a1, no entity, no title overlap
        doc("old", 24 * 5, ["Acme"], "Acme annual report"),       # outside the 48h window
    ])
    return PersonalizationService(mongo=mongo, exposures=FakeExposures([], {}), vectors=FakeVectors(VECS),
                                  cfg=CFG, clock=lambda: NOW)


def articles(svc):
    return {d["article_id"]: d for d in svc.mongo.db.processed_articles.find({}, {"_id": 0})}


def unscored_m(size, first, cred=0.5):
    return (0.2 * math.log1p(size) / math.log(11) + 0.15 * first + 0.15 * cred) / 0.5


class TestClusterJob:
    def test_every_window_article_gets_cluster_and_materiality(self, svc):
        stats = svc.cluster_articles()
        docs = articles(svc)
        assert stats["window_articles"] == 5 and stats["new_clusters"] == 3 and stats["joined"] == 2
        assert {a: docs[a]["cluster_id"] for a in ["a1", "a2", "a3", "b1", "c1"]} == {
            "a1": "a1", "a2": "a1", "a3": "a1", "b1": "b1", "c1": "c1"}
        assert "cluster_id" not in docs["old"] and "materiality" not in docs["old"]
        assert docs["old"]["entity_keys"] == ["acme"]          # entity_keys are written for every article
        assert docs["a2"]["cluster_size"] == 3 and docs["a2"]["first_report"] == "a1"
        m1, m2, mb = docs["a1"]["materiality"], docs["a2"]["materiality"], docs["b1"]["materiality"]
        assert m1["first_report"] == 1 and m2["first_report"] == 0 and m1["unscored"] and m1["risk_norm"] is None
        assert mb["first_report"] == 0                          # singleton
        assert m1["m"] == pytest.approx(unscored_m(3, 1), abs=1e-6)
        assert mb["m"] == pytest.approx(unscored_m(1, 0), abs=1e-6)
        cl = svc.mongo.db.clusters.find_one({"cluster_id": "a1"})
        assert cl["members"] == ["a1", "a2", "a3"] and cl["size"] == 3 and cl["entity_keys"] == ["acme", "x corp"]

    def test_rerun_is_idempotent_and_growth_rewrites_members(self, svc):
        svc.cluster_articles()
        assert svc.cluster_articles()["new_articles"] == 0
        svc.mongo.db.processed_articles.insert_one(doc("a4", 1, ["Acme"], "Acme widget recall costs"))
        stats = svc.cluster_articles()
        assert stats["new_articles"] == 1 and stats["joined"] == 1 and stats["vectors_added"] == 1
        docs = articles(svc)
        assert docs["a4"]["cluster_id"] == "a1"
        assert all(docs[a]["cluster_size"] == 4 for a in ["a1", "a2", "a3", "a4"])
        assert docs["a2"]["materiality"]["size_score"] == pytest.approx(math.log(5) / math.log(11), abs=1e-6)

    def test_a4_score_triggers_rescore(self, svc):
        svc.cluster_articles()
        svc.mongo.db.processed_articles.update_one(
            {"article_id": "b1"}, {"$set": {"risk_score": 80, "risk_processed_at": "2026-09-29T11:00:00+00:00"}})
        assert svc.cluster_articles()["rescored"] == 1
        m = articles(svc)["b1"]["materiality"]
        assert m["risk_norm"] == 0.8 and m["unscored"] is False and m["risk_seen_at"] == "2026-09-29T11:00:00+00:00"
        assert m["m"] == pytest.approx(0.5 * 0.8 + 0.2 * math.log(2) / math.log(11) + 0.15 * 0.5, abs=1e-6)
        assert svc.cluster_articles()["rescored"] == 0

    def test_recluster_is_stable_and_keeps_members_outside_the_window(self, svc):
        svc.cluster_articles()
        again = svc.recluster_window()
        assert again["reset"] == {"articles": 5, "clusters_dropped": 3, "clusters_kept_outside_window": 0}
        assert {a: d.get("cluster_id") for a, d in articles(svc).items()} == {
            "a1": "a1", "a2": "a1", "a3": "a1", "b1": "b1", "c1": "c1", "old": None}
        # 39h later a1 has left the window: its cluster keeps only a1, now a singleton
        later = svc.recluster_window(NOW + timedelta(hours=39))
        assert later["reset"]["clusters_kept_outside_window"] == 1
        docs = articles(svc)
        assert svc.mongo.db.clusters.find_one({"cluster_id": "a1"})["members"] == ["a1"]
        assert docs["a1"]["cluster_size"] == 1 and docs["a1"]["materiality"]["first_report"] == 0
        assert docs["a2"]["cluster_id"] == "a2" and docs["a3"]["cluster_id"] == "a3"   # .738 < cos_join

    def test_job_run_is_recorded_and_leased(self, svc):
        out = jobs.run_job(svc, "cluster")
        assert out["ok"] and out["stats"]["new_clusters"] == 3
        run = svc.mongo.db.job_runs.find_one({"job": "cluster"})
        assert run["ok"] is True and run["finished_at"] is not None
        assert svc.logs.job_start("cluster", NOW) is not None           # finished runs release the lease
        assert jobs.run_job(svc, "cluster") == {"job": "cluster", "skipped": True}

    def test_headlines_one_per_cluster_by_materiality(self, svc):
        svc.cluster_articles()
        heads = svc.onboarding_headlines()
        sports = [h["article_id"] for h in heads if h["topic"] == "sports"]
        # a1 (first report of the size-3 cluster) leads; a2/a3 share a1's cluster, so c1 comes next
        assert sports[:2] == ["a1", "c1"] and "a2" not in sports and "a3" not in sports
        assert len({h["cluster_id"] for h in heads}) == len(heads)


class TestComputePi:
    def test_seed_first_then_hops_stored_on_persona(self):
        mongo = FakeMongo()
        mongo.db.personas.insert_one({"user_id": "u1", "name": "Ana", "topics": {}})
        graph = {"manchester city": [nbr("england", 4), nbr("pep guardiola", 2)],
                 "england": [nbr("wembley", 3)], "pep guardiola": [nbr("barcelona", 1)]}
        exposures = FakeExposures([{"key": "manchester city", "role": "owns", "weight": 3}], graph)
        svc = PersonalizationService(mongo=mongo, exposures=exposures, vectors=FakeVectors({}), cfg=CFG,
                                     clock=lambda: NOW)
        pi = svc.compute_pi("u1")
        assert pi[0] == {"entity": "manchester city", "score": 1.0,
                         "path": {"seed": "manchester city", "role": "owns", "via": [], "relations": []}}
        assert all(e["score"] <= 0.1 for e in pi[1:])
        scores = {e["entity"]: e["score"] for e in pi}
        assert scores == {"manchester city": 1.0, "england": 0.1, "pep guardiola": 0.05,
                          "wembley": 0.005, "barcelona": 0.0025}
        assert svc.personas.get("u1")["pi_topk"] == pi
        assert jobs.run_job(svc, "pi_topk")["stats"] == {"users": 1, "failed": {}}
