"""
MAPNAI — tests/test_pers_app.py
The app views the mobile app reads (mobile/src/api/types.ts): StoryItem fields and explanation_parts on the digest,
the feed pages, Big today, the story page, cluster sources, saved stories, story search, Ask (with a fake Agent 5),
and the app fields added to alerts and proposals. Service on mongomock with the Phase 4 fixture, then the API.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from api.app import create_app
from api.personalization_router import get_service
from personalization.service import ArticleNotFound, InvalidInput
from tests.test_pers_phase2 import NOW
from tests.test_pers_phase4 import dsvc  # noqa: F401  (fixture)


def ids(items):
    return [i["article_id"] for i in items]


class FakeAgent:
    def __init__(self, sources=None, fail=False):
        self.sources, self.fail, self.questions = sources or [], fail, []

    def process(self, query, domain_filter=None, top_k=5):
        self.questions.append(query)
        if self.fail:
            raise RuntimeError("faiss index missing")
        return {"query": query, "answer": "Acme recalled widgets [1].", "sources": self.sources,
                "confidence": 0.8 if self.sources else 0.0}


class TestDigestForTheApp:
    def test_items_carry_story_fields_and_explanation_parts(self, dsvc):
        d = dsvc.get_digest("u1")
        top = d["items"][0]
        assert top["article_id"] == "mk-s1" and top["explanation"] == top["why"]
        assert top["explanation_parts"] == {"kind": "direct", "seed_name": "Acme", "role": "owns", "also": ["Zeta"]}
        assert {"key": "acme", "name": "Acme"} in top["entities"] and top["unscored"] is True
        assert top["another_angle"] == {"article_id": "mk-s1-b", "title": "title mk-s1-b", "source_name": "Reuters",
                                        "url": "u/mk-s1-b"}
        assert d["items"][-1]["explanation_parts"]["kind"] == "explore"
        assert all(i["explanation"] for i in d["more_you_need"])

    def test_cache_keeps_the_engine_shape(self, dsvc):
        dsvc.get_digest("u1")
        cached = dsvc.mongo.db.digests.find_one({}, {"_id": 0})
        assert "explanation" not in cached["items"][0]


class TestFeed:
    def test_pages_are_disjoint_and_one_per_cluster(self, dsvc):
        p1 = dsvc.feed("u1", None, 5, [])
        p2 = dsvc.feed("u1", p1["next_cursor"], 5, [])
        assert p1["next_cursor"] == "5" and not p1["exhausted"] and p1["window_h"] == 48
        assert not set(ids(p1["items"])) & set(ids(p2["items"]))
        assert p1["items"][0]["article_id"] == "mk-s1" and "mk-s1-b" not in ids(p1["items"] + p2["items"])
        assert [i["slot"] for i in p2["items"]] == list(range(5, 10))
        assert all(i["section"] == "feed" and i["explanation"] and i["title"] for i in p1["items"])

    def test_exclude_and_the_last_page(self, dsvc):
        out = dsvc.feed("u1", None, 30, ["mk-s1", "mk-s2"])
        assert "mk-s2" not in ids(out["items"]) and "mk-s1-b" in ids(out["items"])   # its cluster mate fills in
        assert out["exhausted"] is True and out["next_cursor"] is None

    def test_bad_cursor(self, dsvc):
        with pytest.raises(InvalidInput):
            dsvc.feed("u1", "abc", 5, [])


class TestTopStoryClusterSaved:
    def test_top_is_by_materiality_one_per_cluster(self, dsvc):
        out = dsvc.top(24, 3)
        assert ids(out) == ["mk-s1", "mk-s2", "mk-f1"]
        assert out[0]["section"] == "big_today" and out[0]["explanation_parts"] == {"kind": "big_today"}
        assert "mk-s1-b" not in ids(dsvc.top(24, 50))

    def test_story_with_personal_why_and_related(self, dsvc):
        s = dsvc.story("mk-s1", "u1")
        assert s["personal"]["parts"]["kind"] == "direct" and s["personal"]["explanation"].startswith("You own Acme.")
        assert s["related"][0]["article_id"] == "mk-s1-b" and len(s["related"]) == dsvc.cfg.related_max
        assert "mk-s1" not in ids(s["related"]) and s["risk"] is None
        assert dsvc.story("mk-s1")["personal"] is None
        with pytest.raises(ArticleNotFound):
            dsvc.story("nope")

    def test_story_risk_uses_the_app_labels(self, dsvc):
        dsvc.mongo.db.processed_articles.update_one({"article_id": "h1"}, {"$set": {
            "risk_score": 72, "risk_level": "ESCALATE", "action_recommendation": "Watch it",
            "risk_reasoning": {"event_severity": 20, "entity_salience": 18, "temporal_urgency": 19,
                               "domain_criticality": 15}}})
        s = dsvc.story("h1")
        assert s["risk_level"] == "ESCALATE" and s["risk"] == {
            "score": 72, "level": "ESCALATE", "action_recommendation": "Watch it",
            "reasoning": {"severity": 20, "prominence": 18, "urgency": 19, "base_weight": 15}}

    def test_cluster_sources(self, dsvc):
        dsvc.mongo.db.processed_articles.update_many({"cluster_id": "c-mk-s1"}, {"$set": {"first_report": "mk-s1"}})
        out = dsvc.cluster_sources("mk-s1-b")
        assert ids(out) == ["mk-s1", "mk-s1-b"] and [o["first_report"] for o in out] == [True, False]
        assert out[1]["source_name"] == "Reuters" and ids(dsvc.cluster_sources("h1")) == ["h1"]

    def test_saved_follows_the_latest_save_or_unsave(self, dsvc):
        for a, t in [("mk-s2", "save"), ("mk-f1", "save"), ("mk-s2", "unsave"), ("h1", "share")]:
            dsvc.record_feedback("u1", a, t)
        assert ids(dsvc.saved("u1")) == ["mk-f1"]


class TestSearch:
    def test_matches_entities_and_filters_topic(self, dsvc):
        out = dsvc.search("Zeta news")
        assert set(ids(out["items"])) == {"mk-s1", "hop"} and out["items"][0]["matched_terms"] == ["zeta"]
        assert {i["topic"] for i in dsvc.search("acme", "finance")["items"]} == {"finance"}

    def test_stopwords_only(self, dsvc):
        with pytest.raises(InvalidInput):
            dsvc.search("the of")


class TestAsk:
    def test_sources_get_outlet_and_time(self, dsvc):
        dsvc._query_agent = FakeAgent([{"article_id": "mk-s1", "title": "title mk-s1", "domain": "sports",
                                        "relevance_score": 0.9}])
        out = dsvc.ask("What happened to Acme?", context_article_id="mk-s2")
        assert out["answer"] == "Acme recalled widgets [1]." and out["confidence"] == 0.8
        assert out["sources"][0]["source_name"] == "BBC" and out["sources"][0]["published_at"]
        assert dsvc._query_agent.questions == ["What happened to Acme? (about: title mk-s2)"]

    def test_no_sources_means_no_answer(self, dsvc):
        dsvc._query_agent = FakeAgent([])
        assert dsvc.ask("Anything?")["answer"] is None


class TestAlertsAndProposalsForTheApp:
    def test_alert_fields(self, dsvc):
        path = {"seed": "acme", "role": "owns", "via": [], "relations": []}
        dsvc.mongo.db.processed_articles.update_one({"article_id": "mk-s1"}, {"$set": {"cluster_size": 4}})
        dsvc.mongo.db.alerts.insert_many([
            {"alert_id": "a1", "user_id": "u1", "article_id": "mk-s1", "cluster_id": "c-mk-s1", "m": 0.9,
             "entity": "acme", "path": path, "explanation": "why", "created_at": NOW - timedelta(hours=1),
             "deliver_after": NOW - timedelta(hours=1)},
            {"alert_id": "a2", "user_id": "u1", "article_id": "mk-f2", "cluster_id": "c-mk-f2", "m": 0.7,
             "entity": "acme", "path": path, "explanation": "why", "created_at": NOW - timedelta(hours=2),
             "deliver_after": NOW - timedelta(hours=2)},
        ])
        out = {a["alert_id"]: a for a in dsvc.alerts("u1")}
        assert out["a1"]["entity_name"] == "Acme" and out["a1"]["tier"] == "major" and out["a1"]["cluster_size"] == 4
        assert out["a2"]["tier"] == "high" and out["a2"]["cluster_size"] == 1

    def test_proposal_evidence_titles(self, dsvc):
        dsvc.mongo.db.proposals.insert_one({
            "proposal_id": "p1", "user_id": "u1", "entity_key": "zeta", "name": "Zeta", "suggested_role": "follows",
            "suggested_weight": 1, "reason": "engagement", "evidence": ["mk-s1", "gone"], "why": "You read it.",
            "status": "pending", "created_at": NOW, "decided_at": None})
        p = dsvc.list_proposals("u1", "pending")[0]
        assert p["evidence_articles"] == [{"article_id": "mk-s1", "title": "title mk-s1"}]


class TestApi:
    @pytest.fixture
    def client(self, dsvc):
        app = create_app()
        app.dependency_overrides[get_service] = lambda: dsvc
        return TestClient(app)

    def test_routes(self, client, dsvc):
        assert len(client.get("/v1/articles/top", params={"hours": 24, "limit": 2}).json()) == 2
        assert client.get("/v1/articles/mk-s1", params={"user_id": "u1"}).json()["personal"] is not None
        assert client.get("/v1/articles/nope").status_code == 404
        r = client.get("/v1/users/u1/feed", params={"limit": 3, "exclude": "mk-s1,mk-s2"}).json()
        assert len(r["items"]) == 3 and not {"mk-s1", "mk-s2"} & set(ids(r["items"]))
        assert client.get("/v1/users/u1/feed", params={"limit": 99}).status_code == 422
        assert ids(client.get("/v1/clusters/by-article/mk-s1").json()) == ["mk-s1", "mk-s1-b"]
        assert client.get("/v1/search", params={"q": "zeta"}).status_code == 200
        assert client.get("/v1/users/u1/saved").json() == []
        assert client.get("/v1/users/nobody/saved").status_code == 404

    def test_ask(self, client, dsvc):
        dsvc._query_agent = FakeAgent(fail=True)
        assert client.post("/v1/ask", json={"query": "Why?"}).status_code == 503
        dsvc._query_agent = FakeAgent([])
        assert client.post("/v1/ask", json={"query": "Why?"}).json()["answer"] is None
        assert client.post("/v1/ask", json={"query": ""}).status_code == 422


class TestFlashFields:
    """Images, the full summary, engagement counts and comments on the items Flash renders."""

    def test_media_and_summary_long_pass_through(self, dsvc):
        media = {"primary_image": {"url": "https://img.example/hero.jpg", "width": 1200, "height": 630,
                                   "alt": None, "source": "og:image"}, "additional_images": []}
        dsvc.mongo.db.processed_articles.update_one({"article_id": "mk-s1"},
                                                    {"$set": {"media": media, "summary_long": "Long. Summary."}})
        top = dsvc.get_digest("u1")["items"][0]
        assert top["article_id"] == "mk-s1" and top["media"] == media and top["summary_long"] == "Long. Summary."
        assert dsvc.feed("u1", None, 30, [])["items"][1]["media"] is None   # no image ingested: null, not invented

    def test_engagement_counts_leave_the_viewer_out(self, dsvc):
        fb = dsvc.mongo.db.feedback
        rows = [("u2", "more"), ("u3", "more"), ("u4", "less"), ("u3", "unreact"), ("u2", "save"), ("u2", "share"),
                ("u2", "share"), ("u1", "more"), ("u1", "save"), ("u1", "unsave")]
        fb.insert_many([{"user_id": u, "article_id": "mk-s1", "type": t, "t": NOW + timedelta(seconds=i)}
                        for i, (u, t) in enumerate(rows)])
        row = dsvc.logs.engagement(["mk-s1"], "u1")["mk-s1"]
        assert row == {"likes": 1, "dislikes": 1, "comments": 0, "saves": 1, "shares": 1,
                       "viewer": {"reaction": "more", "saved": False}}
        big = next(i for i in dsvc.top(48, 50) if i["article_id"] == "mk-s1")
        assert big["engagement"]["likes"] == 2 and "viewer" not in big   # no viewer: everyone counts
        fb.delete_many({"user_id": "u1"})                                  # (the viewer's more marks it read)
        top = dsvc.get_digest("u1", refresh=True)["items"][0]
        assert top["article_id"] == "mk-s1" and top["engagement"]["likes"] == 1
        assert top["viewer"] == {"reaction": None, "saved": False}

    def test_comments(self, dsvc):
        with pytest.raises(InvalidInput):
            dsvc.add_comment("mk-s1", "u1", "   ")
        with pytest.raises(ArticleNotFound):
            dsvc.add_comment("nope", "u1", "hi")
        first = dsvc.add_comment("mk-s1", "u1", "  Big   news ")
        assert first["text"] == "Big news" and first["author_name"] == "Ana"
        dsvc.clock = lambda: NOW + timedelta(minutes=1)
        dsvc.add_comment("mk-s1", "u1", "Second")
        listed = dsvc.comments("mk-s1")
        assert [c["text"] for c in listed] == ["Second", "Big news"]
        assert all(c["created_at"].tzinfo is not None for c in listed)      # read back from Mongo as UTC
        assert dsvc.get_digest("u1")["items"][0]["engagement"]["comments"] == 2

    def test_unreact_is_feedback_without_beta(self, dsvc):
        out = dsvc.record_feedback("u1", "mk-s1", "unreact")
        assert out["beta_deltas"] == {} and out["history_added"] is False

    def test_comment_routes(self, dsvc):
        app = create_app()
        app.dependency_overrides[get_service] = lambda: dsvc
        client = TestClient(app)
        r = client.post("/v1/articles/mk-s1/comments", json={"user_id": "u1", "text": "Hello"})
        assert r.status_code == 201 and r.json()["author_name"] == "Ana"
        assert [c["text"] for c in client.get("/v1/articles/mk-s1/comments").json()] == ["Hello"]
        assert client.post("/v1/articles/mk-s1/comments", json={"user_id": "u1", "text": "x" * 501}).status_code == 422
        assert client.get("/v1/articles/nope/comments").status_code == 404
