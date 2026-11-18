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

import pytest
from fastapi.testclient import TestClient

from api.app import create_app
from api.personalization_router import get_service
from personalization import factcheck, render
from personalization.service import ArticleNotFound, PersonalizationService, UserNotFound
from tests.fakes import CFG, NOW, FakeExposureStore, FakeLLM, FakeMongo


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


class TestMonthBoundary:
    """F1: after a number, a month must be a whole word ("65 markets" is not March)."""

    @pytest.mark.parametrize("text", [
        "65 markets reopened.", "His 1981 novel sold well.", "12 junior players.", "5 decades later.",
        "3 marathons in a row.", "2 augmented teams.", "4 octopus sightings.", "8 septic tanks.",
    ])
    def test_a_word_that_starts_like_a_month_is_not_a_month(self, text):
        assert factcheck.months(text, strict=True) == set()

    @pytest.mark.parametrize("text,month", [
        ("Signed on 26 Sept.", "september"), ("Due 26 Sept. 2027.", "september"), ("On 5 Mar. he left.", "march"),
        ("The 3rd March vote.", "march"), ("From 10 Dec, prices rise.", "december"), ("The March 3 vote.", "march"),
        ("Back on 1 May.", "may"),
    ])
    def test_a_month_after_a_number_is_still_found(self, text, month):
        assert factcheck.months(text, strict=True) == {month}

    @pytest.mark.parametrize("src", [
        "Stocks fell in 65 markets on Friday.",
        "The 1981 novel by Anne Tyler was reissued on 3 May.",
    ])
    def test_an_identical_rewrite_passes(self, src):
        assert factcheck.verify(src, src, ["Anne Tyler"]) == (True, [], [])


class TestEntityNormalization:
    """F2: gate v2-norm compares entity names after normalizing possessives, punctuation, case, a leading "the" and
    whitespace. v1 (the default) is unchanged."""

    @pytest.mark.parametrize("name,norm", [
        ("Formula 1's", "formula 1"), ("Formula 1’s", "formula 1"), ("Saints'", "saints"),
        ("Arsenal's.", "arsenal"), ("The Beatles", "beatles"), ("the  Premier   League", "premier league"),
        ("U.S.", "us"), ("U.S", "us"), ("  Arsenal, ", "arsenal"), ("Rolls-Royce", "rolls royce"),
        ('"Barbie"', "barbie"), ("The Who", "the who"), ("...", ""), ("", ""),
    ])
    def test_normalize_name(self, name, norm):
        assert factcheck.normalize_name(name) == norm

    def test_possessive_fragment_v1_rejects_v2_norm_accepts(self):
        src, rw = "Formula 1's new rules start in Baku.", "New Formula 1 rules start in Baku."
        names = ["Formula 1's", "Baku"]
        assert factcheck.verify(src, rw, names) == (False, ["entity:Formula 1's"], [])
        assert factcheck.verify(src, rw, names, **factcheck.GATE_VERSIONS["v2-norm"]) == (True, [], [])

    def test_leading_the_and_acronym_dots(self):
        src, rw = "The Beatles toured the U.S. in 1964.", "In 1964 Beatles toured the US."
        names = ["The Beatles", "U.S."]
        assert not factcheck.verify(src, rw, names)[0]
        assert factcheck.verify(src, rw, names, normalize_entities=True) == (True, [], [])

    def test_v2_norm_still_rejects_a_missing_entity(self):
        src = "Bukayo Saka's goal beat Chelsea."
        ok, missing, _ = factcheck.verify(src, "A late goal beat Chelsea.", ["Bukayo Saka's", "Chelsea"],
                                          normalize_entities=True)
        assert not ok and missing == ["entity:Bukayo Saka's"]

    def test_v2_norm_still_rejects_a_substituted_entity(self):
        src = "Arsenal beat Chelsea 2-1."
        ok, missing, _ = factcheck.verify(src, "Arsenal beat Spurs 2-1.", ["Arsenal", "Chelsea"],
                                          normalize_entities=True)
        assert not ok and missing == ["entity:Chelsea"]

    def test_v2_norm_reports_a_duplicate_name_once(self):
        src = "Saka scored. Saka's run won it."
        ok, missing, _ = factcheck.verify(src, "A run won it.", ["Saka", "Saka's"], normalize_entities=True)
        assert not ok and missing == ["entity:Saka"]

    def test_v2_norm_ignores_names_not_in_the_source_and_empty_names(self):
        assert factcheck.verify("Arsenal won.", "Arsenal won.", ["Chelsea", "...", ""], normalize_entities=True) \
            == (True, [], [])

    def test_v2_norm_identity_passes(self):
        src = "Formula 1’s chief met the U.S. team; Saints' fans cheered."
        assert factcheck.verify(src, src, ["Formula 1’s", "U.S.", "Saints'"], normalize_entities=True) == \
            (True, [], [])

    def test_the_default_is_v1(self):
        src, rw, names = "Formula 1's rules.", "Formula 1 rules.", ["Formula 1's"]
        assert factcheck.verify(src, rw, names) == factcheck.verify(src, rw, names, **factcheck.GATE_VERSIONS["v1"])
        assert CFG.render_gate_version == "v1"

    def test_cache_key_is_unchanged_for_v1_and_versioned_otherwise(self):
        style = {"tone": "plain", "length": "short", "jargon": "low"}
        assert "gate_version" not in render.cache_key("a1", style, CFG)
        v2 = CFG.model_copy(update={"render_gate_version": "v2-norm"})
        assert render.cache_key("a1", style, v2)["gate_version"] == "v2-norm"


class TestAddedNames:
    """F5: gate v2 also rejects a capitalized name the source never uses (factcheck.new_names). v1 does not check."""

    SRC = "Ravi Dubey and Sargun Mehta launched the show in Mumbai on Friday."
    NAMES = ["Ravi Dubey", "Sargun Mehta", "Mumbai"]

    def test_v1_does_not_check_added_names(self):
        assert factcheck.verify(self.SRC, self.SRC + " Karan Johar attended.", self.NAMES) == (True, [], [])

    def test_an_added_name_is_rejected(self):
        ok, missing, added = factcheck.verify(self.SRC, self.SRC + " Karan Johar attended.", self.NAMES,
                                              check_added_names=True)
        assert not ok and missing == [] and added == ["name:Johar"]      # "Karan" opens a sentence: not checked

    def test_a_misspelled_name_is_rejected(self):
        rw = "On Friday, Rabi Dubey and Sargun Mehta launched the show in Mumbai."
        ok, missing, added = factcheck.verify(self.SRC, rw, self.NAMES, **factcheck.GATE_VERSIONS["v2"])
        assert not ok and missing == ["entity:Ravi Dubey"] and added == ["name:Rabi"]

    def test_a_misspelling_that_extends_a_source_word_is_a_known_blind_spot(self):
        """new_names allows a word that extends a source word (≥ 4 letters: "India" → "Indian"), so the audit's
        real "Ravi" → "Ravie" misspelling is not caught (PROJECT_AUDIT.md §6.1). Kept visible here."""
        rw = "Ravi Dubey and Sargun Mehta launched the show in Mumbai on Friday, and Ravie Dubey hosted."
        assert factcheck.verify(self.SRC, rw, self.NAMES, check_added_names=True) == (True, [], [])

    def test_a_substitution_hidden_by_another_spelling_is_caught_by_v2(self):
        src = "The World Cup final drew crowds; the World Cup trophy toured Delhi."
        rw = "The World Cup final drew crowds, and the Pant trophy toured Delhi."
        names = ["the World Cup", "World Cup", "Delhi"]
        assert factcheck.verify(src, rw, names, **factcheck.GATE_VERSIONS["v2-norm"])[0]      # the F2 blind spot
        assert factcheck.verify(src, rw, names, **factcheck.GATE_VERSIONS["v2"]) == (False, [], ["name:Pant"])

    def test_a_single_new_name_opening_a_sentence_is_a_known_blind_spot(self):
        """factcheck.new_names skips sentence-initial words (after . ! ? : ;) so ordinary openers aren't flagged;
        a one-word name there is therefore missed. Kept visible here, measured in E02."""
        src = "The World Cup final drew crowds; the World Cup trophy toured Delhi."
        rw = "The World Cup final drew crowds; Pant trophy toured Delhi."
        assert factcheck.verify(src, rw, ["the World Cup", "World Cup", "Delhi"], **factcheck.GATE_VERSIONS["v2"])             == (True, [], [])

    @pytest.mark.parametrize("rw", [
        "However, Ravi Dubey and Sargun Mehta launched the show in Mumbai on Friday.",       # sentence opener
        "On Friday, Dubey's and Mehta's show launched in Mumbai.",                           # possessives, surnames
        "Ravi Dubey and Sargun Mehta launched the show in MUMBAI on Friday.",                # case
        "The show opened in Mumbai in October on Friday, with Ravi Dubey and Sargun Mehta.",  # month word
    ])
    def test_no_false_added_name(self, rw):
        assert factcheck.verify(self.SRC, rw, self.NAMES, check_added_names=True)[2] == []

    @pytest.mark.parametrize("src", [
        "Ronnie O'Sullivan's career began early.", "Cricket's O'Shea and Jack scored.",
        "Genelia D'Souza and Ravi Dubey starred.", "Ronnie O’Sullivan won in Sheffield.",
    ])
    def test_apostrophe_names_are_not_added(self, src):
        """factcheck.new_names stripped "'s" anywhere ("O'Sullivan" → "oullivan"); v2 strips it only at the end."""
        assert factcheck.verify(src, src, [], **factcheck.GATE_VERSIONS["v2"]) == (True, [], [])

    def test_a_demonym_of_a_source_place_is_allowed(self):
        assert factcheck.verify("Teams from India met.", "Indian teams met.", ["India"], check_added_names=True)[2] \
            == []

    def test_a_new_acronym_is_rejected(self):
        assert factcheck.verify("Leaders met in Paris.", "NATO leaders met in Paris.", ["Paris"],
                                check_added_names=True)[2] == ["name:NATO"]

    def test_added_numbers_keep_their_format(self):
        ok, _, added = factcheck.verify("Arsenal won 2-1.", "Arsenal won 3-1 against Fulham.", ["Arsenal"],
                                        **factcheck.GATE_VERSIONS["v2"])
        assert not ok and added == ["3", "name:Fulham"]

    def test_v2_is_normalization_plus_added_names_and_identity_passes(self):
        assert factcheck.GATE_VERSIONS["v2"] == {"normalize_entities": True, "check_added_names": True}
        src = "Formula 1’s chief met the U.S. team in Baku; NATO watched."
        assert factcheck.verify(src, src, ["Formula 1’s", "U.S.", "Baku"], **factcheck.GATE_VERSIONS["v2"]) == \
            (True, [], [])


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


def make_svc(mongo=None, llm=None, cfg=CFG, exposures=None):
    llm = llm or FakeLLM(faithful)
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
