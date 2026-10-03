"""
MAPNAI — tests/test_pers_profile.py
Phase 1 service + API tests: users, profile sentences, Beta priors, PATCH versioning, onboarding,
v1 persona upgrade. Offline: mongomock for Mongo and an in-memory fake for the Neo4j exposure store.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from datetime import datetime, timezone

import mongomock
import pytest
from fastapi.testclient import TestClient

from api.app import create_app
from api.personalization_router import get_service
from config.personalization import PersonalizationSettings
from personalization import explain
from personalization.keys import encode_key, entity_key
from personalization.service import (
    ArticleNotFound, EntityNotFound, InvalidInput, PersonalizationService, UserNotFound,
)

CFG = PersonalizationSettings(_env_file=None)
NOW = datetime(2026, 9, 29, 12, 0, tzinfo=timezone.utc)


class FakeMongo:
    def __init__(self):
        self.db = mongomock.MongoClient().db


class FakeExposureStore:
    """(name, type, frequency) nodes; edges keyed by (user, name, type) — mirrors ExposureStore's contract."""

    def __init__(self, cfg):
        self.cfg = cfg
        self.nodes = [
            ("Manchester City", "Location", 16), ("Manchester city", "Location", 1),
            ("Man City", "Location", 13), ("England", "Location", 31), ("U.S", "Location", 21),
            ("WHO", "Organization", 16),
        ]
        self.edges = {}
        self.users = {}

    def _variants(self, key):
        return [n for n in self.nodes if entity_key(n[0]) == key]

    def upsert_user(self, user_id, name):
        self.users[user_id] = name

    def delete_user(self, user_id):
        self.users.pop(user_id, None)
        self.edges = {k: v for k, v in self.edges.items() if k[0] != user_id}

    def resolve_key(self, key):
        return [{"name": n, "type": t, "frequency": f} for n, t, f in self._variants(key)]

    def search_entities(self, q, alias_keys, limit):
        keys = {entity_key(n) for n, _, _ in self.nodes if q in entity_key(n) or entity_key(n) in alias_keys}
        return [{"key": k, "name": self.resolve_key(k)[0]["name"], "types": [], "mention_count": 0}
                for k in sorted(keys)][:limit]

    def set_exposure(self, user_id, key, role, weight, provenance, proposal_id=None):
        label = {v: k for k, v in self.cfg.weight_levels.items()}[weight]
        for n, t, _ in self._variants(key):
            self.edges[(user_id, n, t)] = {"key": key, "role": role, "weight": weight, "weight_label": label,
                                           "provenance": provenance}
        v = self.resolve_key(key)
        return {"key": key, "name": v[0]["name"], "role": role, "weight": weight, "weight_label": label,
                "provenance": provenance, "nodes": len(v)} if v else {}

    def remove_exposure(self, user_id, key):
        gone = [k for k, e in self.edges.items() if k[0] == user_id and e["key"] == key]
        for k in gone:
            del self.edges[k]
        return len(gone)

    def get_exposures(self, user_id):
        out = {}
        for (u, _, _), e in self.edges.items():
            if u == user_id:
                out[e["key"]] = {**e, "name": self.resolve_key(e["key"])[0]["name"]}
        return sorted(out.values(), key=lambda e: (-e["weight"], e["key"]))

    def get_seeds(self, user_id):
        return [{"key": e["key"], "role": e["role"], "weight": e["weight"]} for e in self.get_exposures(user_id)]

    def neighbours(self, keys, top):
        return {}

    def is_available(self):
        return {"ok": True}


ARTICLES = [
    {"article_id": "a-sport", "title": "City win the derby", "domain": "sports", "source_name": "BBC",
     "url": "u1", "published_at": "2026-09-28T10:00:00+00:00",
     "entities": [{"name": "Manchester City", "salience": 1.0}, {"name": "England", "salience": 0.5},
                  {"name": "U.S", "salience": 0.4}, {"name": "WHO", "salience": 0.1}]},
    {"article_id": "a-film", "title": "Box office record", "domain": "entertainment_movies",
     "source_name": "Variety", "url": "u2", "published_at": "2026-09-28T09:00:00+05:30",
     "entities": [{"name": "U.S", "salience": 1.0}]},
    {"article_id": "a-other", "title": "Markets wobble", "domain": "other", "source_name": "ET",
     "url": "u3", "published_at": "2026-09-28T11:00:00+00:00", "entities": []},
    {"article_id": "a-sport-2", "title": "Transfer news", "domain": "sports", "source_name": "Sky",
     "url": "u4", "published_at": "2026-09-27T11:00:00+00:00", "entities": []},
]


@pytest.fixture
def svc():
    mongo = FakeMongo()
    mongo.db.processed_articles.insert_many([dict(a) for a in ARTICLES])
    return PersonalizationService(mongo=mongo, exposures=FakeExposureStore(CFG), cfg=CFG, clock=lambda: NOW)


def make_user(svc, **kw):
    args = dict(name="Ana", topics={"sports": 1.0}, style=None,
                exposures=[{"key": "Manchester City", "role": "owns", "weight": "high"}])
    args.update(kw)
    return svc.create_user(**args)


class TestCreateAndProfile:
    def test_profile_sentence_and_version(self, svc):
        uid = make_user(svc)["user_id"]
        prof = svc.get_profile(uid)
        assert prof["sentences"][0] == "You own Manchester City (high)."
        assert prof["persona_version"] == 1
        assert prof["style"] == CFG.style_defaults
        assert prof["exposures"][0]["key"] == "manchester city"
        assert prof["pi_topk"][0]["entity"] == "manchester city" and prof["pi_topk"][0]["score"] == 1.0

    def test_beta_priors_written(self, svc):
        uid = make_user(svc)["user_id"]
        beta = svc.get_profile(uid)["beta"]
        assert beta["topic:sports"] == [4.0, 1.0]
        assert beta["entity:manchester city"] == [4.0, 1.0]

    def test_int_weight_and_medium_prior(self, svc):
        uid = make_user(svc, exposures=[{"key": "england", "role": "follows", "weight": 2}])["user_id"]
        prof = svc.get_profile(uid)
        assert prof["exposures"][0]["weight_label"] == "medium"
        assert prof["beta"]["entity:england"] == [3.0, 2.0]

    def test_dotted_entity_key_is_encoded_in_mongo(self, svc):
        uid = make_user(svc, exposures=[{"key": "u.s", "role": "operates_in", "weight": "low"}])["user_id"]
        raw = svc.mongo.db.personas.find_one({"user_id": uid})
        assert encode_key("entity:u.s") in raw["beta"]
        assert "entity:u.s" in svc.get_profile(uid)["beta"]

    def test_unknown_entity_404_and_nothing_written(self, svc):
        with pytest.raises(EntityNotFound):
            make_user(svc, exposures=[{"key": "acme quantum widgets", "role": "owns", "weight": "high"}])
        assert svc.mongo.db.personas.count_documents({}) == 0

    @pytest.mark.parametrize("kw", [
        {"topics": {"cooking": 1.0}},
        {"topics": {"sports": 1.5}},
        {"style": {"tone": "shouty"}},
        {"exposures": [{"key": "england", "role": "likes", "weight": "high"}]},
        {"exposures": [{"key": "england", "role": "owns", "weight": 7}]},
        {"name": "  "},
    ])
    def test_invalid_input(self, svc, kw):
        with pytest.raises(InvalidInput):
            make_user(svc, **kw)

    def test_unknown_user(self, svc):
        with pytest.raises(UserNotFound):
            svc.get_profile("nope")


class TestPatch:
    def test_each_patch_bumps_version(self, svc):
        uid = make_user(svc)["user_id"]
        assert svc.patch_topics(uid, {"health": 0.5})["persona_version"] == 2
        assert svc.patch_style(uid, {"tone": "analyst"})["persona_version"] == 3
        assert svc.patch_alert_prefs(uid, {"max_per_day": 1})["persona_version"] == 4
        r = svc.patch_exposures(uid, [{"key": "england", "role": "follows", "weight": "low"}], [])
        assert r["persona_version"] == 5
        assert svc.get_profile(uid)["persona_version"] == 5

    def test_topics_merge_and_remove(self, svc):
        uid = make_user(svc)["user_id"]
        out = svc.patch_topics(uid, {"health": 0.5, "sports": None})
        assert out["topics"] == {"health": 0.5}
        assert svc.get_profile(uid)["beta"]["topic:health"] == [2.5, 2.5]

    def test_topic_patch_keeps_learned_beta(self, svc):
        uid = make_user(svc)["user_id"]
        svc.onboarding(uid, ["a-sport"], [])
        svc.patch_topics(uid, {"sports": 0.2})
        assert svc.get_profile(uid)["beta"]["topic:sports"] == [5.0, 1.0]

    def test_exposure_upsert_and_remove(self, svc):
        uid = make_user(svc)["user_id"]
        r = svc.patch_exposures(uid, [{"key": "who", "role": "regulated_by", "weight": "medium"}],
                                ["manchester city"])
        assert r["removed"] == {"manchester city": 2}
        assert [e["key"] for e in r["exposures"]] == ["who"]
        assert svc.get_profile(uid)["sentences"][0] == "You are regulated by WHO (medium)."

    def test_patch_unknown_key_404(self, svc):
        uid = make_user(svc)["user_id"]
        with pytest.raises(EntityNotFound):
            svc.patch_exposures(uid, [{"key": "nothing here", "role": "owns", "weight": 1}], [])

    def test_remove_unlinked_key_is_harmless(self, svc):
        uid = make_user(svc)["user_id"]
        assert svc.patch_exposures(uid, [], ["no such entity"])["removed"] == {"no such entity": 0}

    def test_patch_empty_and_conflict(self, svc):
        uid = make_user(svc)["user_id"]
        with pytest.raises(InvalidInput):
            svc.patch_exposures(uid, [], [])
        with pytest.raises(InvalidInput):
            svc.patch_exposures(uid, [{"key": "england", "role": "owns", "weight": 1}], ["england"])
        with pytest.raises(InvalidInput):
            svc.patch_alert_prefs(uid, {"tz": "Mars/Base"})
        with pytest.raises(InvalidInput):
            svc.patch_alert_prefs(uid, {"quiet_start": "25:00"})


class TestOnboarding:
    def test_like_adds_one_to_topic_alpha(self, svc):
        uid = make_user(svc)["user_id"]
        before = svc.get_profile(uid)["beta"]["topic:sports"]
        out = svc.onboarding(uid, ["a-sport"], ["a-film"])
        after = svc.get_profile(uid)["beta"]
        assert after["topic:sports"] == [before[0] + 1, before[1]]
        # top-3 entities by salience; the seed's prior is the base
        assert after["entity:manchester city"] == [5.0, 1.0]
        assert after["entity:england"] == [2.0, 1.0]
        assert "entity:who" not in after                       # 4th by salience
        # dislike: undeclared topic starts from [1, 1]
        assert after["topic:entertainment_movies"] == [1.0, 2.0]
        assert after["entity:u.s"] == [2.0, 2.0]               # liked via a-sport, disliked via a-film
        assert out["history_added"] == 1 and out["persona_version"] == 2

    def test_history_is_long_window(self, svc):
        uid = make_user(svc)["user_id"]
        svc.onboarding(uid, ["a-sport"], [])
        hist = svc.personas.get(uid)["history"]
        assert hist[0]["article_id"] == "a-sport" and hist[0]["win"] == "long" and hist[0]["src"] == "onboarding"
        fb = list(svc.mongo.db.feedback.find({"user_id": uid}))
        assert [(f["type"], f["section"]) for f in fb] == [("more", "onboarding")]

    def test_errors(self, svc):
        uid = make_user(svc)["user_id"]
        with pytest.raises(ArticleNotFound):
            svc.onboarding(uid, ["missing"], [])
        with pytest.raises(InvalidInput):
            svc.onboarding(uid, ["a-sport"], ["a-sport"])
        with pytest.raises(InvalidInput):
            svc.onboarding(uid, [], [])

    def test_headlines_round_robin_skips_other(self, svc):
        heads = svc.onboarding_headlines()
        assert [h["article_id"] for h in heads] == ["a-film", "a-sport", "a-sport-2"]
        assert all(h["topic"] != "other" for h in heads)


class TestV1Upgrade:
    def test_v1_doc_gets_v2_fields(self, svc):
        svc.mongo.db.personas.insert_one({"user_id": "v1", "name": "Old", "topics": {"sports": 1.0},
                                          "history": [], "created_at": datetime(2026, 9, 28)})
        prof = svc.get_profile("v1")
        assert prof["persona_version"] == 1 and prof["style"] == CFG.style_defaults and prof["beta"] == {}
        raw = svc.mongo.db.personas.find_one({"user_id": "v1"})
        assert "alert_prefs" in raw and "pi_topk" in raw
        assert svc.patch_style("v1", {"length": "medium"})["persona_version"] == 2


class TestAliases:
    def test_alias_prefix_lookup(self, svc):
        svc.logs.alias_upsert([{"alias": "Man City", "entity_key": "manchester city"},
                               {"alias": "man utd", "entity_key": "manchester united"}], source="seed")
        assert svc.logs.alias_lookup("man c") == ["manchester city"]
        assert svc.logs.alias_lookup("MAN") == ["manchester city", "manchester united"]


class TestExplain:
    def test_profile_sentences(self):
        exps = [{"role": "owns", "name": "Manchester City", "weight_label": "high"},
                {"role": "regulated_by", "name": "WHO", "weight_label": "low"}]
        s = explain.profile_sentences(exps, {"sports": 1.0, "health": 1.0}, CFG.style_defaults, CFG)
        assert s == [
            "You own Manchester City (high).",
            "You are regulated by WHO (low).",
            "You are interested in health (50%), sports (50%).",
            "You prefer short, plain summaries with low jargon.",
        ]


class TestAPI:
    @pytest.fixture
    def client(self, svc):
        app = create_app()
        app.dependency_overrides[get_service] = lambda: svc
        return TestClient(app)

    def test_flow(self, client):
        r = client.get("/v1/entities/search", params={"q": "manch"})
        assert r.status_code == 200 and r.json()[0]["key"] == "manchester city"
        r = client.post("/v1/users", json={"name": "Ana", "topics": {"sports": 1},
                                           "exposures": [{"key": "manchester city", "role": "owns", "weight": "high"}]})
        assert r.status_code == 201
        uid = r.json()["user_id"]
        assert client.post(f"/v1/users/{uid}/onboarding", json={"likes": ["a-sport"]}).status_code == 200
        assert client.patch(f"/v1/users/{uid}/style", json={"tone": "analyst"}).json()["persona_version"] == 3
        prof = client.get(f"/v1/users/{uid}/profile").json()
        assert prof["sentences"][0] == "You own Manchester City (high)." and prof["persona_version"] == 3

    def test_status_codes(self, client):
        assert client.get("/v1/users/nope/profile").status_code == 404
        r = client.post("/v1/users", json={"name": "X", "exposures": [{"key": "zzz", "role": "owns", "weight": 1}]})
        assert r.status_code == 404
        assert client.post("/v1/users", json={"name": "X", "topics": {"cooking": 1}}).status_code == 422
        assert client.get("/v1/entities/search", params={"q": ""}).status_code == 422
