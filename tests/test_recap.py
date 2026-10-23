"""
MAPNAI — tests/test_recap.py
Article timestamps (RSS UTC parsing, scraped page dates, future dates, the BSON date fields and their backfill) and
the daily / weekly recaps: periods in the reader's time zone, undated articles, stories, selection, the overview
check, then the service on mongomock (build once and freeze, limited-coverage rebuild, weekly carry-over, reader
marks, editor overrides, Big today after the recap) and the API.
"""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import json
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import feedparser
import pytest
from bs4 import BeautifulSoup
from fastapi.testclient import TestClient

from agents.preprocessing_agent import PreprocessingAgent
from agents.rss_fetcher import _parse_published
from agents.web_scraper import _page_published
from api.app import create_app
from api.personalization_router import get_service
from backfill_dates import date_fields
from config.personalization import PersonalizationSettings
from personalization import recap
from personalization.service import InvalidInput, PersonalizationService, RecapNotReady
from tests.test_pers_phase2 import FakeMongo
from tests.test_pers_phase4 import NamedExposures
from utils.models import Domain, ProcessedArticle, RawArticle, SourceType

CFG = PersonalizationSettings(_env_file=None)
IST = ZoneInfo("Asia/Kolkata")


def ist(d, h=12, mi=0):
    """A local Asia/Kolkata time on 2026-10-<d> → UTC."""
    return datetime(2026, 10, d, h, mi, tzinfo=IST).astimezone(timezone.utc)


# ══════════════════════════════════════════════════════════════
# Timestamps
# ══════════════════════════════════════════════════════════════

class TestRssTimes:
    def test_parsed_times_are_read_as_utc_whatever_the_machine_zone(self):
        # time.mktime read feedparser's UTC struct_time as local time: 5 h 30 m early on an IST machine
        feed = feedparser.parse("<rss><channel><item><title>x</title>"
                                "<pubDate>Thu, 22 Oct 2026 10:00:00 +0000</pubDate></item></channel></rss>")
        assert _parse_published(feed.entries[0]) == datetime(2026, 10, 22, 10, 0, tzinfo=timezone.utc)

    def test_offsets_are_converted(self):
        feed = feedparser.parse("<rss><channel><item><title>x</title>"
                                "<pubDate>Thu, 22 Oct 2026 15:30:00 +0530</pubDate></item></channel></rss>")
        assert _parse_published(feed.entries[0]) == datetime(2026, 10, 22, 10, 0, tzinfo=timezone.utc)


class TestScrapedPageDates:
    def page(self, head="", body=""):
        return BeautifulSoup(f"<html><head>{head}</head><body>{body}</body></html>", "lxml")

    def test_meta_tag_first(self):
        soup = self.page('<meta property="article:published_time" content="2026-10-22T09:15:00+05:30">'
                         '<script type="application/ld+json">{"datePublished": "2020-01-01"}</script>')
        assert _page_published(soup, "https://x/a") == datetime(2026, 10, 22, 3, 45, tzinfo=timezone.utc)

    def test_json_ld_in_a_graph(self):
        ld = json.dumps({"@graph": [{"@type": "WebPage"}, {"@type": "NewsArticle",
                                                            "datePublished": "2026-10-21T18:00:00Z"}]})
        soup = self.page(f'<script type="application/ld+json">{ld}</script>')
        assert _page_published(soup, "https://x/a") == datetime(2026, 10, 21, 18, 0, tzinfo=timezone.utc)

    def test_time_tag_then_url(self):
        assert _page_published(self.page(body='<time datetime="2026-10-20T08:00:00Z">x</time>'), "") == \
            datetime(2026, 10, 20, 8, 0, tzinfo=timezone.utc)
        assert _page_published(self.page(), "https://x.com/news/2026/10/19/story") == \
            datetime(2026, 10, 19, tzinfo=timezone.utc)

    def test_none_when_the_page_states_none(self):
        assert _page_published(self.page(body="<p>no date</p>"), "https://x.com/story") is None


class TestPreprocessingDates:
    def raw(self, published_at, **meta):
        return RawArticle(title="Kohli scores a century in the final", body="Virat Kohli scored a century " * 20,
                          url="https://x/a", source_name="Test", source_type=SourceType.SCRAPER,
                          domain=Domain.SPORTS, published_at=published_at, raw_metadata=meta)

    def test_dated_article(self):
        out, status = PreprocessingAgent().process(self.raw("2026-10-20T10:00:00Z"))
        assert status == "ok" and out.date_source == "published" and out.ingested_at.tzinfo is not None

    def test_page_meta_source_is_kept(self):
        out, _ = PreprocessingAgent().process(self.raw("2026-10-20T10:00:00Z", date_source="page_meta"))
        assert out.date_source == "page_meta"

    def test_future_time_is_dropped(self):
        future = (datetime.now(timezone.utc) + timedelta(hours=5)).isoformat()
        out, _ = PreprocessingAgent().process(self.raw(future))
        assert out.published_at is None and out.date_source == "ingested"

    def test_undated(self):
        out, _ = PreprocessingAgent().process(self.raw(None))
        assert out.published_at is None and out.date_source == "ingested"


class TestDateFields:
    def article(self, published):
        return ProcessedArticle(title="t", body="b", source_name="s", source_type=SourceType.RSS,
                                domain=Domain.SPORTS, published_at=published,
                                ingested_at=datetime(2026, 10, 22, 6, 0, tzinfo=timezone.utc))

    def test_mongo_dict_has_bson_dates(self):
        d = self.article(datetime(2026, 10, 21, 20, 0, tzinfo=timezone.utc)).to_mongo_dict()
        assert d["published_ts"] == datetime(2026, 10, 21, 20, 0, tzinfo=timezone.utc)
        assert d["ingested_ts"] == datetime(2026, 10, 22, 6, 0, tzinfo=timezone.utc)
        assert d["date_source"] == "published" and isinstance(d["published_at"], str)

    def test_undated_falls_back_to_ingestion(self):
        d = self.article(None).to_mongo_dict()
        assert d["published_ts"] == d["ingested_ts"] and d["date_source"] == "ingested"

    def test_backfill_fields(self):
        assert date_fields({"published_at": "2026-10-21T20:00:00+00:00", "ingested_at": "2026-10-22T06:00:00"}) == {
            "published_ts": datetime(2026, 10, 21, 20, 0, tzinfo=timezone.utc), "date_source": "published",
            "ingested_ts": datetime(2026, 10, 22, 6, 0, tzinfo=timezone.utc)}
        assert date_fields({"published_at": None, "ingested_at": "2026-10-22T06:00:00"})["date_source"] == "ingested"
        assert date_fields({}) == {}


# ══════════════════════════════════════════════════════════════
# Recap rules (pure)
# ══════════════════════════════════════════════════════════════

class TestPeriods:
    @pytest.mark.parametrize("now,day", [
        (ist(22, 6, 59), date(2026, 10, 20)),        # before 07:00: the day before yesterday
        (ist(22, 7, 0), date(2026, 10, 21)),
        (ist(22, 23, 59), date(2026, 10, 21)),
    ])
    def test_latest_daily(self, now, day):
        assert recap.latest_daily(now, IST, CFG) == day

    def test_daily_bounds_are_local_midnights(self):
        p = recap.daily_period(date(2026, 10, 21), IST, CFG)
        assert p["start"] == ist(21, 0) and p["end"] == ist(22, 0) and p["ready_at"] == ist(22, 7)
        assert p["key"] == "2026-10-21" and p["title"] == "Wednesday, 21 October"

    @pytest.mark.parametrize("now,monday", [
        (ist(25, 21, 59), date(2026, 10, 12)),       # Sunday before 22:00: last week's is the newest
        (ist(25, 22, 0), date(2026, 10, 19)),
        (ist(26, 9), date(2026, 10, 19)),
        (ist(31, 9), date(2026, 10, 19)),            # the next Saturday
    ])
    def test_latest_weekly(self, now, monday):
        assert recap.latest_weekly(now, IST, CFG) == monday

    def test_week_runs_sunday_22_to_sunday_22(self):
        p = recap.weekly_period(date(2026, 10, 19), IST, CFG)
        assert p["start"] == ist(18, 22) and p["end"] == ist(25, 22)
        assert p["key"] == "2026-W43" and recap.parse_week("2026-W43") == date(2026, 10, 19)
        assert p["title"] == "19–25 October" and len(p["days"]) == 7
        # the Sunday-night hours before the week belong to Monday
        assert recap.day_of(ist(18, 23), IST, p) == date(2026, 10, 19)
        assert recap.day_of(ist(25, 21), IST, p) == date(2026, 10, 25)

    def test_week_across_months(self):
        assert recap.weekly_period(date(2026, 9, 28), IST, CFG)["title"] == "28 September–4 October"

    def test_bad_keys(self):
        for bad in ("2026-13-01", "yesterday"):
            with pytest.raises(ValueError):
                recap.parse_day(bad)
        for bad in ("2026-43", "2026-W54"):
            with pytest.raises(ValueError):
                recap.parse_week(bad)


def doc(article_id, topic="sports", m=0.5, t=None, cluster=None, title=None, keys=(), size=1, source="published",
        summary="A summary.", body="", ingested=None):
    """A processed_articles doc as stored (published_ts / ingested_ts BSON dates)."""
    t = t or ist(21, 12)
    ingested = ingested or t + timedelta(minutes=30)
    published = None if source == "ingested" else t
    return {
        "article_id": article_id, "title": title or f"title {article_id}", "domain": topic, "source_name": "BBC",
        "url": f"https://x/{article_id}", "published_at": published.isoformat() if published else None,
        "published_ts": published or ingested, "ingested_ts": ingested, "ingested_at": ingested.isoformat(),
        "date_source": source, "cluster_id": cluster, "cluster_size": size,
        "entities": [{"name": k.title(), "salience": 0.9} for k in keys], "entity_keys": list(keys),
        "materiality": None if m is None else {"m": m, "unscored": True}, "summary_short": summary,
        "summary_long": None, "body": body, "media": {"primary_image": {"url": f"https://img/{article_id}.jpg"},
                                                      "additional_images": []},
    }


class TestTimesAndStories:
    def test_undated_takes_a_dated_siblings_time(self):
        docs = [doc("d", t=ist(20, 23), keys=("kohli",), title="Kohli hits century in Perth"),
                doc("u", source="ingested", ingested=ist(21, 6), keys=("kohli",), title="Kohli century Perth win"),
                doc("x", source="ingested", ingested=ist(21, 6), keys=("messi",), title="Messi signs deal")]
        times = recap.effective_times(docs, CFG)
        assert times["u"] == (ist(20, 23), "sibling")       # so it lands in the 20th's recap, not the 21st's
        assert times["x"] == (ist(21, 6), "ingested")
        assert times["d"] == (ist(20, 23), "published")

    def test_same_cluster_is_a_sibling(self):
        docs = [doc("d", t=ist(21, 1), cluster="c"), doc("u", source="ingested", ingested=ist(21, 5), cluster="c")]
        assert recap.effective_times(docs, CFG)["u"] == (ist(21, 1), "sibling")

    def test_stories_are_clusters_led_by_the_best_article(self):
        docs = [doc("a1", m=0.4, cluster="c1", t=ist(21, 9), size=3), doc("a2", m=0.6, cluster="c1", t=ist(21, 10)),
                doc("b", m=None, t=ist(21, 8))]
        stories = recap.build_stories(docs, recap.effective_times(docs, CFG), CFG)
        c1 = next(s for s in stories if s["story_id"] == "c1")
        assert c1["lead"]["article_id"] == "a2" and c1["m"] == 0.6 and c1["size"] == 3
        assert c1["member_ids"] == ["a1", "a2"] and c1["first_t"] == ist(21, 9)
        b = next(s for s in stories if s["story_id"] == "b")
        assert b["m_fallback"] is True and 0 < b["m"] < 0.5      # computed from the doc's own fields

    def test_near_identical_clusters_merge(self):
        docs = [doc("a", m=0.6, cluster="c1", title="India beat Australia in the final"),
                doc("b", m=0.5, cluster="c2", title="India beat Australia in final"),
                doc("c", m=0.5, cluster="c3", topic="entertainment_movies", title="India beat Australia in final")]
        stories = recap.build_stories(docs, recap.effective_times(docs, CFG), CFG)
        assert [s["story_id"] for s in stories] == ["c1", "c3"]      # another topic stays apart
        assert stories[0]["member_ids"] == ["a", "b"] and stories[0]["size"] == 2


def stories_of(docs):
    return recap.build_stories(docs, recap.effective_times(docs, CFG), CFG)


class TestSelectDaily:
    def test_domain_minimum_then_by_m(self):
        docs = [doc(f"s{i}", "sports", 0.9 - i * 0.01) for i in range(12)]
        docs += [doc(f"f{i}", "entertainment_movies", 0.5 - i * 0.01) for i in range(5)]
        picks = recap.select_daily(stories_of(docs), CFG)
        assert len(picks) == 10 and [p["rank"] for p in picks] == list(range(1, 11))
        assert sum(p["topic"] == "entertainment_movies" for p in picks) == 3
        assert [p["m"] for p in picks] == sorted((p["m"] for p in picks), reverse=True)

    def test_quality_floor_and_scope(self):
        docs = [doc("s1", m=0.6), doc("weak", m=0.1), doc("fin", "finance", 0.9),
                doc("f1", "entertainment_movies", 0.3)]
        assert [p["lead"]["article_id"] for p in recap.select_daily(stories_of(docs), CFG)] == ["s1", "f1"]

    def test_pins_go_first_even_below_the_floor(self):
        docs = [doc("s1", m=0.6), doc("weak", m=0.1)]
        picks = recap.select_daily(stories_of(docs), CFG, pinned=["weak"])
        assert [p["lead"]["article_id"] for p in picks] == ["weak", "s1"]

    def test_excluded_story_leaves_whole(self):
        docs = [doc("a", cluster="c"), doc("b", cluster="c"), doc("z")]
        assert [s["story_id"] for s in recap.drop_excluded(stories_of(docs), ["b"])] == ["z"]


class TestSelectWeekly:
    def period(self):
        return recap.weekly_period(date(2026, 10, 19), IST, CFG)

    def test_top_then_days_without_repeats(self):
        docs = []
        for d in range(19, 26):        # every day: two sports, one film story
            docs += [doc(f"s{d}a", "sports", 0.5 + d / 100, t=ist(d, 10)),
                     doc(f"s{d}b", "sports", 0.45, t=ist(d, 11)),
                     doc(f"f{d}", "entertainment_movies", 0.40, t=ist(d, 12))]
        # a story that ran three days: lower m, but the span bonus lifts it into the top
        docs += [doc("run1", "entertainment_movies", 0.60, t=ist(19, 9), cluster="run"),
                 doc("run2", "entertainment_movies", 0.55, t=ist(20, 9), cluster="run"),
                 doc("run3", "entertainment_movies", 0.55, t=ist(21, 9), cluster="run")]
        picks = recap.select_weekly(stories_of(docs), IST, self.period(), CFG)
        top = [p for p in picks if p["group"] == "top"]
        assert len(top) == 5 and sum(p["topic"] == "entertainment_movies" for p in top) >= 2
        assert any(p["story_id"] == "run" and p["span_days"] == 3 for p in top)
        ids = [p["story_id"] for p in picks]
        assert len(ids) == len(set(ids)) and len(picks) <= CFG.recap_weekly_max
        groups = [p["group"] for p in picks if p["group"] != "top"]
        assert groups == sorted(groups) and set(groups) <= {f"2026-10-{d}" for d in range(19, 26)}
        # a day's second story prefers the other domain
        assert [p["topic"] for p in picks if p["group"] == "2026-10-22"] == ["sports", "entertainment_movies"]

    def test_quiet_day_keeps_one_and_the_cap_holds(self):
        cfg = CFG.model_copy(update={"recap_weekly_max": 7})
        docs = [doc(f"t{i}", "sports", 0.9, t=ist(19, 1 + i)) for i in range(5)]
        docs += [doc("q1", "sports", 0.5, t=ist(20, 10)), doc("q2", "sports", 0.3, t=ist(20, 11))]   # q2 < 0.35
        docs += [doc(f"w{i}", "sports", 0.6, t=ist(21, 10 + i)) for i in range(2)]
        picks = recap.select_weekly(stories_of(docs), IST, self.period(), cfg)
        assert [p["story_id"] for p in picks if p["group"] == "2026-10-20"] == ["q1"]
        assert len(picks) == 7

    def test_sections(self):
        items = [{"group": "top"}, {"group": "2026-10-19"}, {"group": "2026-10-19"}, {"group": "2026-10-23"}]
        assert recap.sections("weekly", items, self.period()) == [
            {"key": "top", "title": "Stories of the week", "count": 1},
            {"key": "2026-10-19", "title": "Monday 19 Oct", "count": 2},
            {"key": "2026-10-23", "title": "Friday 23 Oct", "count": 1}]


class TestOverviewRules:
    def test_check_rejects_added_numbers_only(self):
        source = "1. [Sports] India win by 5 wickets — Kohli made 82."
        assert recap.overview_check(source, "India won by 5 wickets.") == (True, [])
        assert recap.overview_check(source, "India won by 7 wickets.") == (False, ["7"])
        assert recap.overview_check(source, None) == (False, [])

    def test_source_lines(self):
        items = [{"rank": 1, "topic": "sports", "title": "T1", "summary_short": "S1"},
                 {"rank": 2, "topic": "entertainment_movies", "title": "T2", "summary_short": None}]
        assert recap.overview_source(items, CFG) == "1. [Sports] T1 — S1\n2. [Film] T2"


# ══════════════════════════════════════════════════════════════
# Service + API (mongomock)
# ══════════════════════════════════════════════════════════════

class FakeLLM:
    def __init__(self, reply):
        self.reply, self.calls = reply, []
        self.chat = SimpleNamespace(completions=self)

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if isinstance(self.reply, Exception):
            raise self.reply
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=self.reply))])


class Clock:
    def __init__(self, now):
        self.now = now

    def __call__(self):
        return self.now


def make_svc(now, llm=None, docs=()):
    mongo = FakeMongo()
    if docs:
        mongo.db.processed_articles.insert_many([dict(d) for d in docs])
    clock = Clock(now)
    svc = PersonalizationService(mongo=mongo, exposures=NamedExposures([{"key": "kohli", "role": "follows",
                                                                         "weight": 3}], {}),
                                 cfg=CFG, clock=clock, llm_factory=lambda: (llm, "m") if llm else (None, None))
    svc.clock_obj = clock
    return svc


def day21(n_sports=12, n_film=6):
    docs = [doc(f"s{i}", "sports", 0.9 - i * 0.02, t=ist(21, 9 + i % 12)) for i in range(n_sports)]
    docs += [doc(f"f{i}", "entertainment_movies", 0.6 - i * 0.02, t=ist(21, 8 + i)) for i in range(n_film)]
    return docs


class TestDailyService:
    def test_built_once_then_frozen(self):
        llm = FakeLLM(json.dumps({"text": "India won and a film opened."}))
        svc = make_svc(ist(22, 8), llm, day21())
        r = svc.get_recap("daily", "Asia/Kolkata")
        assert r["period"] == "2026-10-21" and r["version"] == 1 and r["latest"] is True
        assert len(r["items"]) == 10 and r["items"][0]["section"] == "recap"
        assert r["items"][0]["media"]["primary_image"]["url"].startswith("https://img/")
        assert r["overview"]["text"] == "India won and a film opened." and len(llm.calls) == 1
        assert r["coverage"]["articles"] == 18 and r["coverage"]["limited"] is False
        assert r["sections"] == [{"key": "day", "title": "Wednesday, 21 October", "count": 10}]
        assert r["start"] == ist(21, 0) and r["next_at"] == ist(23, 7)
        assert "excluded" not in r
        # a new article for the day doesn't change a frozen recap
        svc.mongo.db.processed_articles.insert_one(doc("late", "sports", 0.99, t=ist(21, 23),
                                                       ingested=ist(22, 9)))
        again = svc.get_recap("daily", "Asia/Kolkata")
        assert again["version"] == 1 and "late" not in [i["article_id"] for i in again["items"]]
        assert len(llm.calls) == 1

    def test_limited_coverage_is_rebuilt_when_articles_arrive(self):
        svc = make_svc(ist(22, 8), None, day21(3, 1))
        first = svc.get_recap("daily", "Asia/Kolkata")
        assert first["coverage"]["limited"] is True and first["overview"]["reason"] == "no_llm_client"
        svc.mongo.db.processed_articles.insert_many([doc(f"n{i}", "sports", 0.7, t=ist(21, 15),
                                                         ingested=ist(22, 9)) for i in range(12)])
        svc.clock_obj.now = ist(22, 10)
        again = svc.get_recap("daily", "Asia/Kolkata")
        assert again["version"] == 2 and again["coverage"]["articles"] == 16

    def test_day_boundaries_follow_the_time_zone(self):
        # 21 Oct 23:50 IST (18:20 UTC) is still the 21st in Kolkata
        late = doc("late", "sports", 0.9, t=ist(21, 23, 50))
        svc = make_svc(ist(22, 8), None, day21() + [late])
        assert "late" in [i["article_id"] for i in svc.get_recap("daily", "Asia/Kolkata")["items"]]
        early = doc("early", "sports", 0.95, t=ist(22, 1))      # 21 Oct 19:30 UTC → the 21st in London
        svc.mongo.db.processed_articles.insert_one(early)
        svc.clock_obj.now = ist(22, 16)
        london = svc.get_recap("daily", "Europe/London", "2026-10-21")
        assert "early" in [i["article_id"] for i in london["items"]]
        assert "early" not in [i["article_id"] for i in svc.get_recap("daily", "Asia/Kolkata")["items"]]

    def test_not_ready_bad_zone_bad_date(self):
        svc = make_svc(ist(22, 6), None, day21())
        assert svc.get_recap("daily", "Asia/Kolkata")["period"] == "2026-10-20"
        with pytest.raises(RecapNotReady):
            svc.get_recap("daily", "Asia/Kolkata", "2026-10-21")
        with pytest.raises(InvalidInput):
            svc.get_recap("daily", "Mars/Olympus")
        with pytest.raises(InvalidInput):
            svc.get_recap("daily", "Asia/Kolkata", "21-10-2026")
        with pytest.raises(InvalidInput):
            svc.get_recap("monthly", "Asia/Kolkata")

    def test_overview_with_a_new_number_is_dropped(self):
        llm = FakeLLM(json.dumps({"text": "India won by 900 runs."}))
        r = make_svc(ist(22, 8), llm, day21()).get_recap("daily", "Asia/Kolkata")
        assert r["overview"]["text"] is None and r["overview"]["reason"] == "fact_check"
        assert r["overview"]["added"] == ["900"]

    def test_overview_error_keeps_the_recap(self):
        r = make_svc(ist(22, 8), FakeLLM(RuntimeError("down")), day21()).get_recap("daily", "Asia/Kolkata")
        assert r["overview"]["text"] is None and r["overview"]["reason"] == "llm_error: RuntimeError"
        assert len(r["items"]) == 10

    def test_missing_summary_is_filled_from_the_body(self):
        body = ("Virat Kohli scored a century in the final at Perth. " * 3 +
                "India won the series three to one after the match. The crowd was large and loud today.")
        docs = day21() + [doc("nosum", "sports", 0.99, summary=None, body=body)]
        item = make_svc(ist(22, 8), None, docs).get_recap("daily", "Asia/Kolkata")["items"][0]
        assert item["article_id"] == "nosum" and item["summary_fallback"] is True
        assert "Kohli" in item["summary_short"]

    def test_reader_marks(self):
        docs = day21()
        docs[0] = doc("s0", "sports", 0.95, keys=("kohli",))
        svc = make_svc(ist(22, 8), None, docs)
        svc.mongo.db.personas.insert_one({"user_id": "u1", "name": "Ana", "topics": {"entertainment_movies": 1.0},
                                          "history": [], "persona_version": 1})
        svc.mongo.db.feedback.insert_one({"user_id": "u1", "article_id": "s1", "type": "open", "t": ist(21, 20)})
        items = {i["article_id"]: i for i in svc.get_recap("daily", "Asia/Kolkata", user_id="u1")["items"]}
        assert items["s0"]["marks"]["follows"] == "Kohli" and items["s0"]["explanation"] == "You follow Kohli"
        assert items["s0"]["explanation_parts"] == {"kind": "direct", "seed_name": "Kohli", "role": "follows"}
        assert items["s1"]["marks"]["seen"] is True and items["s2"]["marks"]["seen"] is False
        assert items["f0"]["marks"]["in_your_topics"] is True
        assert items["f0"]["explanation"].startswith("In your topics · ")
        # the stored recap holds no reader's marks
        stored = svc.mongo.db.recaps.find_one({}, {"_id": 0})
        assert "marks" not in stored["items"][0] and stored["items"][0]["explanation_parts"] == {"kind": "recap"}

    def test_reader_zone_is_the_default(self):
        svc = make_svc(ist(22, 8), None, day21())
        svc.mongo.db.personas.insert_one({"user_id": "u1", "name": "Ana", "history": [], "persona_version": 1,
                                          "alert_prefs": {"tz": "Europe/London"}})
        assert svc.get_recap("daily", user_id="u1")["tz"] == "Europe/London"
        assert svc.get_recap("daily")["tz"] == CFG.tz

    def test_editor_rebuild_excludes_and_pins(self):
        svc = make_svc(ist(22, 8), None, day21())
        first = svc.get_recap("daily", "Asia/Kolkata")
        assert first["items"][0]["article_id"] == "s0"
        r = svc.rebuild_recap("daily", None, "Asia/Kolkata", exclude=["s0"], pin=["f5"])
        assert r["version"] == 2 and r["items"][0]["article_id"] == "f5"
        assert "s0" not in [i["article_id"] for i in r["items"]]
        # a later rebuild keeps the editor's lists unless new ones are given
        assert svc.rebuild_recap("daily", None, "Asia/Kolkata")["items"][0]["article_id"] == "f5"
        assert svc.get_recap("daily", "Asia/Kolkata")["version"] == 3

    def test_job_builds_once(self):
        svc = make_svc(ist(22, 8), None, day21())
        assert svc.run_recap("daily")["built"] is True
        out = svc.run_recap("daily")
        assert out["built"] is False and out["version"] == 1 and out["items"] == 10


class TestWeeklyService:
    def week_docs(self):
        docs = []
        for d in range(19, 26):
            docs += [doc(f"s{d}", "sports", 0.5 + (d - 19) / 50, t=ist(d, 10)),
                     doc(f"f{d}", "entertainment_movies", 0.45, t=ist(d, 11))]
        docs.append(doc("sun_night", "sports", 0.99, t=ist(18, 23)))      # before Monday, after the cut
        docs.append(doc("after_cut", "sports", 0.99, t=ist(25, 22, 30)))   # next week's
        return docs

    def test_week_window_and_shape(self):
        svc = make_svc(ist(25, 22, 5), None, self.week_docs())
        r = svc.get_recap("weekly", "Asia/Kolkata")
        ids = [i["article_id"] for i in r["items"]]
        assert r["period"] == "2026-W43" and r["title"] == "19–25 October"
        assert "sun_night" in ids and "after_cut" not in ids
        assert r["sections"][0] == {"key": "top", "title": "Stories of the week", "count": 5}
        assert len(ids) == len(set(ids)) and len(ids) <= CFG.recap_weekly_max
        assert {i["group"] for i in r["items"]} - {"top"} <= {f"2026-10-{d}" for d in range(19, 26)}

    def test_late_arrivals_carry_over_to_next_week(self):
        svc = make_svc(ist(25, 22, 5), None, self.week_docs())
        svc.get_recap("weekly", "Asia/Kolkata")
        # published Sunday 21:50, ingested after the recap was built: missed by week 43 …
        svc.mongo.db.processed_articles.insert_one(doc("late", "sports", 0.99, t=ist(25, 21, 50),
                                                       ingested=ist(25, 23)))
        svc.clock_obj.now = ist(1, 22, 5).replace(month=11)    # Sunday 1 Nov, 22:05 IST
        r = svc.get_recap("weekly", "Asia/Kolkata")
        # … so week 44 takes it in, under Monday
        assert r["period"] == "2026-W44" and r["coverage"]["carried_over"] == 1
        late = next(i for i in r["items"] if i["article_id"] == "late")
        assert late["happened_at"] == ist(25, 21, 50)
        assert [i["article_id"] for i in r["items"]].count("late") == 1


class TestBigTodayAfterRecap:
    def test_since_the_recap_ended(self):
        docs = [doc("y", "sports", 0.9, t=ist(21, 20)), doc("t", "sports", 0.8, t=ist(22, 9))]
        svc = make_svc(ist(22, 10), None, docs)
        for d in docs:     # top() reads published_at windows; give both articles a cluster
            svc.mongo.db.processed_articles.update_one({"article_id": d["article_id"]},
                                                       {"$set": {"cluster_id": d["article_id"]}})
        assert [i["article_id"] for i in svc.top(after_recap=True, tz="Asia/Kolkata")] == ["t"]
        svc.clock_obj.now = ist(22, 6)       # before 07:00 the 21st isn't recapped yet: Big today covers it
        assert [i["article_id"] for i in svc.top(after_recap=True, tz="Asia/Kolkata")] == ["y"]


class TestApi:
    @pytest.fixture
    def client(self):
        svc = make_svc(ist(22, 8), None, day21())
        app = create_app()
        app.dependency_overrides[get_service] = lambda: svc
        return TestClient(app)

    def test_daily_and_weekly(self, client):
        r = client.get("/v1/recaps/daily", params={"tz": "Asia/Kolkata"})
        assert r.status_code == 200
        body = r.json()
        assert body["period"] == "2026-10-21" and len(body["items"]) == 10
        assert body["start"].endswith("+00:00") and body["items"][0]["happened_at"].endswith("+00:00")
        assert client.get("/v1/recaps/weekly", params={"tz": "Asia/Kolkata"}).json()["period"] == "2026-W42"

    def test_errors(self, client):
        assert client.get("/v1/recaps/daily", params={"tz": "Asia/Kolkata", "date": "2026-10-22"}).status_code == 404
        assert client.get("/v1/recaps/daily", params={"tz": "Nowhere/City"}).status_code == 422
        assert client.get("/v1/recaps/weekly", params={"week": "2026-43"}).status_code == 422

    def test_admin_rebuild(self, client):
        client.get("/v1/recaps/daily", params={"tz": "Asia/Kolkata"})
        r = client.post("/v1/admin/recaps/daily/rebuild", params={"tz": "Asia/Kolkata"}, json={"exclude": ["s0"]})
        assert r.status_code == 200 and r.json()["version"] == 2
        assert "s0" not in [i["article_id"] for i in r.json()["items"]]

    def test_top_after_recap(self, client):
        assert client.get("/v1/articles/top", params={"after_recap": True, "tz": "Asia/Kolkata"}).status_code == 200
