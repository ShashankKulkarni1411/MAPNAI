"""
MAPNAI — tests/test_pers_phase7.py
Phase 7: rendering. The fact check (numbers, dates, entity names; missing or added → fail), the pure render helpers
(source choice, prompt = style only, response parsing), then render on mongomock with a fake OpenAI-style client:
per-style rewrites, the cache (shared across readers with one style), the fact-check fallback, uncached transport
errors, the persona brief, and the endpoint.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import timedelta
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from api.app import create_app
from api.personalization_router import get_service
from personalization import factcheck, render
from personalization.service import ArticleNotFound, PersonalizationService, UserNotFound
from tests.test_pers_phase2 import CFG, NOW, FakeMongo
from tests.test_pers_profile import FakeExposureStore


# ── Fact check (pure) ────────────────────────────────────────

class TestExtract:
    def test_numbers_are_normalized(self):
        assert factcheck.numbers("£1,200,000 in 2026. Up 5 per cent, then 7.5%, 3-1") == \
            {"1200000", "2026", "5%", "7.5%", "3", "1"}

    def test_dates_and_months(self):
        facts = factcheck.extract_facts("Signed on 26 Sept, due 2027-01-05. He may leave in March. The March 3 "
                                        "vote and October.", [])
        assert facts["dates"] == ["2027-01-05"]
        assert facts["months"] == ["march", "october", "september"]      # "may" the verb and a bare "March" skipped
        assert "01" not in facts["numbers"] and "05" not in facts["numbers"]

    def test_only_entities_that_occur_in_the_source(self):
        text = "Manchester City's appeal was backed by the Premier League."
        assert factcheck.entities_in(text, ["Premier League", "Manchester City", "England", "City"]) == \
            ["Premier League", "Manchester City", "City"]
        assert factcheck.entities_in("Cityscape", ["City"]) == []


class TestVerify:
    SRC = ("Manchester City were fined £1,200,000 on 26 September after two hearings, a 5 per cent rise; "
           "the case opened on 2023-02-06.")
    NAMES = ["Manchester City", "Premier League"]

    def test_a_faithful_paraphrase_passes(self):
        ok, missing, added = factcheck.verify(
            self.SRC, "After 2 hearings, Manchester City got a £1200000 fine on September 26 — 5% more. The case "
                      "began on 6 February 2023.", self.NAMES)
        assert (ok, missing, added) == (True, [], [])

    def test_a_dropped_number_fails(self):
        ok, missing, _ = factcheck.verify(
            self.SRC, "Manchester City were fined heavily on 26 September, 5% more, in the case of 2023-02-06.",
            self.NAMES)
        assert not ok and missing == ["number:1200000"]

    def test_dropped_date_month_and_entity(self):
        ok, missing, _ = factcheck.verify(self.SRC, "The club was fined £1,200,000, up 5%, on the 26th.", self.NAMES)
        assert not ok and missing == ["date:2023-02-06", "month:september", "entity:Manchester City"]

    def test_an_invented_number_fails(self):
        rewrite = ("Manchester City were fined £1,200,000 on 26 September, up 5%, after 2 hearings and 3 appeals; "
                   "the case opened 2023-02-06.")
        assert factcheck.verify(self.SRC, rewrite, self.NAMES) == (False, [], ["3"])

    def test_empty_rewrite_misses_everything(self):
        ok, missing, _ = factcheck.verify(self.SRC, "", self.NAMES)
        assert not ok and len(missing) == 6


# ── Render helpers (pure) ────────────────────────────────────

PLAIN = {"tone": "plain", "length": "short", "jargon": "low"}
ANALYST = {"tone": "analyst", "length": "medium", "jargon": "high"}


class TestRenderHelpers:
    def test_source_is_sized_for_the_length(self):
        doc = {"summary_short": "short.", "summary_long": "long.", "body": "body."}
        assert render.source_text(doc, "short", CFG) == ("short.", "summary_short")
        assert render.source_text(doc, "medium", CFG) == ("long.", "summary_long")
        assert render.source_text({"summary_long": "long."}, "short", CFG) == ("long.", "summary_long")
        assert render.source_text({"summary_short": None, "body": ""}, "short", CFG) == ("", None)

    def test_body_is_cut_at_a_sentence_end(self):
        body = "First sentence here. " * 40
        text, field = render.source_text({"body": body}, "short", CFG)
        assert field == "body" and len(text) <= CFG.render_source_chars and text.endswith("here.")

    def test_the_prompt_is_the_style_and_the_text_only(self):
        msgs = render.build_messages("Some text.", ANALYST)
        assert msgs[1] == {"role": "user", "content": "Some text."}
        for field, value in ANALYST.items():
            assert render.STYLE_RULES[field][value] in msgs[0]["content"]
        assert render.build_messages("Some text.", dict(ANALYST)) == msgs

    @pytest.mark.parametrize("content,expected", [
        ('{"text": " Hi. "}', "Hi."), ('{"text": ""}', None), ("Hi.", None), (None, None), ('["x"]', None),
    ])
    def test_parse(self, content, expected):
        assert render.parse_response(content) == expected


# ── Service (mongomock + fake LLM) ───────────────────────────

SHORT = "Manchester City were fined £1,200,000 on 26 September after 2 hearings."
LONG = ("Manchester City were fined £1,200,000 on 26 September after 2 hearings. The club said it will appeal "
        "within 14 days, and England's FA is watching.")
ARTICLE = {
    "article_id": "a1", "title": "City fined", "domain": "sports", "source_name": "BBC Sport", "url": "u/a1",
    "published_at": (NOW - timedelta(hours=2)).isoformat(), "summary_short": SHORT, "summary_long": LONG,
    "body": "Full body text.",
    "entities": [{"name": "Manchester City", "type": "Organization", "salience": 1.0},
                 {"name": "England", "type": "Location", "salience": 0.5},
                 {"name": "Premier League", "type": "Organization", "salience": 0.3}],
    "entity_keys": ["manchester city", "england", "premier league"], "cluster_id": "c1",
    "materiality": {"m": 0.7, "risk_norm": 0.9, "size_score": 0.3, "first_report": 0, "source_cred": 0.8,
                    "unscored": False, "computed_at": NOW},
}
FAITHFUL = {
    "short": "Manchester City got a £1,200,000 fine on 26 September after 2 hearings.",
    "medium": "Manchester City were fined £1,200,000 on 26 September following 2 hearings. It plans to appeal "
              "within 14 days; England's FA is watching.",
}


def faithful(messages):
    return '{"text": "%s"}' % FAITHFUL["short" if "1-2 sentences" in messages[0]["content"] else "medium"]


class FakeLLM:
    """An OpenAI-SDK-shaped client: client.chat.completions.create(...) → choices[0].message.content."""

    def __init__(self, reply=faithful):
        self.reply, self.calls = reply, []
        self.chat = SimpleNamespace(completions=self)

    def create(self, **kwargs):
        self.calls.append(kwargs)
        content = self.reply(kwargs["messages"]) if callable(self.reply) else self.reply
        if isinstance(content, Exception):
            raise content
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])


def make_svc(mongo=None, llm=None, cfg=CFG, exposures=None):
    llm = llm or FakeLLM()
    svc = PersonalizationService(mongo=mongo or FakeMongo(), exposures=exposures or FakeExposureStore(cfg), cfg=cfg,
                                 clock=lambda: NOW, llm_factory=lambda: (llm, "llama-3.3-70b-versatile"))
    svc.llm = llm
    return svc


@pytest.fixture
def svc():
    s = make_svc()
    s.mongo.db.processed_articles.insert_one(dict(ARTICLE))
    s.ana = s.create_user("Ana", {"sports": 1.0}, PLAIN,
                          [{"key": "manchester city", "role": "owns", "weight": "high"}])["user_id"]
    s.ben = s.create_user("Ben", {"sports": 1.0}, ANALYST,
                          [{"key": "england", "role": "follows", "weight": "medium"}])["user_id"]
    s.cai = s.create_user("Cai", {"health": 1.0}, PLAIN,
                          [{"key": "who", "role": "regulated_by", "weight": "high"}])["user_id"]
    return s


class TestRenderPerStyle:
    def test_two_styles_two_rewrites(self, svc):
        a, b = svc.render("a1", svc.ana), svc.render("a1", svc.ben)
        assert (a["text"], b["text"]) == (FAITHFUL["short"], FAITHFUL["medium"])
        assert (a["style"], b["style"]) == (PLAIN, ANALYST)
        assert (a["source_field"], b["source_field"]) == ("summary_short", "summary_long")
        assert not a["cached"] and not b["cached"] and not a["fallback"] and not b["fallback"]
        assert a["llm_call"] and b["llm_call"] and len(svc.llm.calls) == svc.renderer.llm_calls == 2
        assert svc.llm.calls[0]["messages"] == render.build_messages(SHORT, PLAIN)
        assert svc.llm.calls[1]["messages"] == render.build_messages(LONG, ANALYST)

    def test_the_configured_model_and_options(self, svc):
        svc.render("a1", svc.ana)
        call = svc.llm.calls[0]
        assert call["model"] == CFG.render_model != "llama-3.3-70b-versatile"
        assert call["extra_body"] == CFG.render_llm_extra and call["response_format"] == {"type": "json_object"}
        assert call["max_tokens"] == CFG.render_max_tokens

    def test_second_call_is_a_cache_hit(self, svc):
        first = svc.render("a1", svc.ana)
        second = svc.render("a1", svc.ana)
        assert second["cached"] is True and second["llm_call"] is False and second["text"] == first["text"]
        assert len(svc.llm.calls) == 1
        assert svc.mongo.db.render_cache.count_documents({}) == 1

    def test_another_reader_with_the_same_style_reuses_it(self, svc):
        svc.render("a1", svc.ana)
        cai = svc.render("a1", svc.cai)
        assert cai["cached"] is True and cai["text"] == FAITHFUL["short"] and len(svc.llm.calls) == 1
        assert cai["why"] is None and cai["brief"]["exposures"] == []      # the brief stays personal

    def test_the_cache_survives_a_new_service(self, svc):
        svc.render("a1", svc.ana)
        again = make_svc(mongo=svc.mongo, exposures=svc.exposures)
        assert again.render("a1", svc.ana)["cached"] is True and again.llm.calls == []

    def test_refresh_a_new_summary_and_a_new_prompt_version_miss(self, svc):
        svc.render("a1", svc.ana)
        assert svc.render("a1", svc.ana, refresh=True)["cached"] is False
        svc.mongo.db.processed_articles.update_one({"article_id": "a1"}, {"$set": {"summary_short": SHORT + " "
                                                                                    "Fans reacted."}})
        assert svc.render("a1", svc.ana)["cached"] is False
        v2 = make_svc(mongo=svc.mongo, exposures=svc.exposures,
                      cfg=CFG.model_copy(update={"render_prompt_version": CFG.render_prompt_version + "-next"}))
        assert v2.render("a1", svc.ana)["cached"] is False
        assert len(svc.llm.calls) == 3 and svc.mongo.db.render_cache.count_documents({}) == 2


class TestFallback:
    def test_a_rewrite_that_drops_a_number_serves_the_source(self, svc):
        svc.llm.reply = '{"text": "Manchester City were fined a record sum on 26 September after 2 hearings."}'
        out = svc.render("a1", svc.ana)
        assert out["fallback"] is True and out["reason"] == "fact_check" and out["text"] == SHORT
        assert out["missing"] == ["number:1200000"] and out["added"] == []
        row = svc.mongo.db.render_cache.find_one({"article_id": "a1"})
        assert row["fallback"] is True and row["rewrite"].startswith("Manchester City were fined a record")
        # the failure is cached: no second paid call for the same rewrite
        again = svc.render("a1", svc.ana)
        assert again["cached"] is True and again["fallback"] is True and again["text"] == SHORT
        assert len(svc.llm.calls) == 1

    def test_an_invented_number_serves_the_source(self, svc):
        svc.llm.reply = '{"text": "%s"}' % (FAITHFUL["short"][:-1] + " and 3 appeals.")
        out = svc.render("a1", svc.ana)
        assert out["fallback"] is True and out["added"] == ["3"] and out["text"] == SHORT

    def test_an_unparseable_reply_is_cached_as_a_fallback(self, svc):
        svc.llm.reply = "Sure! Here is the rewrite: ..."
        out = svc.render("a1", svc.ana)
        assert out["fallback"] and out["reason"] == "unparseable_response" and out["text"] == SHORT
        assert svc.render("a1", svc.ana)["cached"] is True and len(svc.llm.calls) == 1

    def test_a_transport_error_is_not_cached(self, svc):
        svc.llm.reply = TimeoutError("groq down")
        out = svc.render("a1", svc.ana)
        assert out["fallback"] and out["reason"] == "llm_error: TimeoutError" and out["text"] == SHORT
        assert svc.mongo.db.render_cache.count_documents({}) == 0
        svc.llm.reply = faithful
        assert svc.render("a1", svc.ana)["text"] == FAITHFUL["short"] and len(svc.llm.calls) == 2

    def test_render_off_or_no_client_serves_the_source_without_a_call(self, svc):
        off = make_svc(mongo=svc.mongo, exposures=svc.exposures, cfg=CFG.model_copy(update={"enable_render": False}))
        out = off.render("a1", svc.ana)
        assert (out["text"], out["fallback"], out["reason"], off.llm.calls) == (SHORT, True, "render_disabled", [])
        none = PersonalizationService(mongo=svc.mongo, exposures=svc.exposures, cfg=CFG, clock=lambda: NOW,
                                      llm_factory=lambda: (None, None))
        out = none.render("a1", svc.ana)
        assert (out["text"], out["reason"], out["llm_call"]) == (SHORT, "no_llm_client", False)
        assert svc.mongo.db.render_cache.count_documents({}) == 0

    def test_an_article_without_text(self, svc):
        svc.mongo.db.processed_articles.insert_one({**ARTICLE, "article_id": "empty", "summary_short": None,
                                                    "summary_long": None, "body": ""})
        out = svc.render("empty", svc.ana)
        assert (out["text"], out["reason"], out["llm_call"]) == ("", "no_source_text", False)


class TestBrief:
    def test_why_from_the_exposure_hits(self, svc):
        out = svc.render("a1", svc.ana)
        assert out["why"] == ("You own Manchester City. Need 0.70 = materiality 0.70 × exposure 1.00; "
                              "Manchester City drives 100% of it.")
        assert out["brief"]["why_source"] == "exposure" and out["brief"]["style"] == PLAIN
        assert out["brief"]["exposures"] == [{"entity": "manchester city", "name": "Manchester City", "pi": 1.0,
                                              "why": "You own Manchester City."}]
        ben = svc.render("a1", svc.ben)["brief"]
        assert [e["entity"] for e in ben["exposures"]] == ["england"] and ben["exposures"][0]["pi"] == 0.666667

    def test_why_from_todays_digest_when_it_was_served_there(self, svc):
        svc.logs.put_digest({"user_id": svc.ana, "date": "2026-09-29", "items": [
            {"article_id": "a1", "why": "Served why line."}], "more_you_need": []})
        brief = svc.render("a1", svc.ana)["brief"]
        assert (brief["why"], brief["why_source"]) == ("Served why line.", "digest")

    def test_unknown_user_or_article(self, svc):
        with pytest.raises(UserNotFound):
            svc.render("a1", "nobody")
        with pytest.raises(ArticleNotFound):
            svc.render("zz", svc.ana)


class TestRenderAPI:
    def test_endpoint(self, svc):
        app = create_app()
        app.dependency_overrides[get_service] = lambda: svc
        client = TestClient(app)
        r = client.get("/v1/articles/a1/render", params={"user_id": svc.ana})
        assert r.status_code == 200
        body = r.json()
        assert body["text"] == FAITHFUL["short"] and body["why"].startswith("You own Manchester City.")
        assert {"text", "why", "brief", "cached", "fallback", "missing"} <= set(body)
        assert client.get("/v1/articles/a1/render", params={"user_id": svc.ana}).json()["cached"] is True
        assert client.get("/v1/articles/a1/render", params={"user_id": svc.ana,
                                                            "refresh": True}).json()["cached"] is False
        assert client.get("/v1/articles/zz/render", params={"user_id": svc.ana}).status_code == 404
        assert client.get("/v1/articles/a1/render", params={"user_id": "nobody"}).status_code == 404
        assert client.get("/v1/articles/a1/render").status_code == 422
