"""
MAPNAI — tests/test_stream_fetch.py
poll_rss_source (agents/rss_fetcher.py): conditional GET, 304, the seen-item filter, prominence rows from top-stories
feeds, signal-only feeds, errors. The HTTP call is patched; feedparser parses a real RSS document.
"""

from unittest.mock import patch

import requests

from agents.rss_fetcher import poll_rss_source
from config.sources import RSSSource
from stream import polling


def rss(*items):
    body = "".join(
        f"<item><title>{t}</title><link>https://news.example/{g}</link><guid>{g}</guid>"
        f"<description>{t}. A long enough description of the story for the article body.</description>"
        f"<pubDate>Tue, 29 Sep 2026 10:00:00 GMT</pubDate></item>"
        for g, t in items)
    return (f'<?xml version="1.0"?><rss version="2.0"><channel><title>Feed</title>{body}</channel></rss>').encode()


class Resp:
    def __init__(self, status=200, content=b"", headers=None):
        self.status_code, self.content, self.headers = status, content, headers or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code}", response=self)


SECTION = RSSSource(name="Sports Feed", url="https://news.example/sports.xml", domain="sports")
TOP = RSSSource(name="Front Page", url="https://news.example/top.xml", domain="general", role="top_stories")
SIGNAL = RSSSource(name="Aggregator", url="https://news.example/agg.xml", domain="general", role="top_stories",
                   store_items=False)
FEED = rss(("g1", "Kohli out of the final"), ("g2", "India win the toss"), ("g3", "Rain delays play"))


def poll(source, state=None, resp=None):
    with patch("agents.rss_fetcher.requests.get", return_value=resp or Resp(200, FEED)) as get:
        result = poll_rss_source(source, state, max_articles=50, seen_keep=500, timeout=5)
    return result, get


class TestPoll:
    def test_first_poll_returns_every_item_and_remembers_the_keys(self):
        r, _ = poll(SECTION, resp=Resp(200, FEED, {"ETag": '"v1"', "Last-Modified": "Tue, 29 Sep 2026 10:00:00 GMT"}))
        assert r.status == polling.OK and r.new_count == 3
        assert [a.title for a in r.articles] == ["Kohli out of the final", "India win the toss", "Rain delays play"]
        assert r.articles[0].raw_metadata.get("feed_role") == "section"
        assert r.seen == ["id:g1", "id:g2", "id:g3"]
        assert r.etag == '"v1"' and r.last_modified.startswith("Tue")
        assert r.prominence == []                                   # a section feed is not a front page

    def test_conditional_headers_and_304(self):
        r, get = poll(SECTION, {"etag": '"v1"', "last_modified": "Tue, 29 Sep 2026 10:00:00 GMT"}, Resp(304))
        headers = get.call_args.kwargs["headers"]
        assert headers["If-None-Match"] == '"v1"' and headers["If-Modified-Since"].startswith("Tue")
        assert r.status == polling.NOT_MODIFIED and r.articles == [] and r.new_count == 0 and r.http_status == 304

    def test_only_unseen_items_are_new(self):
        r, _ = poll(SECTION, {"seen": ["id:g1", "id:g2", "id:old"]})
        assert r.new_count == 1 and [a.title for a in r.articles] == ["Rain delays play"]
        assert r.seen[:3] == ["id:g1", "id:g2", "id:g3"] and "id:old" in r.seen

    def test_top_stories_report_every_current_item_as_prominence(self):
        r, _ = poll(TOP, {"seen": ["id:g1", "id:g2", "id:g3"]})
        assert r.new_count == 0 and r.articles == []
        assert [p["title"] for p in r.prominence] == ["Kohli out of the final", "India win the toss",
                                                     "Rain delays play"]
        assert r.prominence[0] == {"feed": "Front Page", "url": "https://news.example/g1",
                                   "title": "Kohli out of the final", "domain": "general"}

    def test_signal_only_feed_stores_nothing(self):
        r, _ = poll(SIGNAL)
        assert r.new_count == 3 and r.articles == [] and len(r.prominence) == 3

    def test_http_error_and_network_error(self):
        r, _ = poll(SECTION, resp=Resp(503))
        assert r.status == polling.ERROR and r.http_status == 503 and r.articles == []
        with patch("agents.rss_fetcher.requests.get", side_effect=requests.ConnectionError("down")):
            r = poll_rss_source(SECTION, {}, max_articles=5)
        assert r.status == polling.ERROR and "down" in r.error

    def test_unparseable_feed_is_an_error(self):
        r, _ = poll(SECTION, resp=Resp(200, b"<html>not a feed"))
        assert r.status == polling.ERROR and r.error.startswith("unparseable feed")


def test_stream_sources_add_top_stories_and_disable_reuters():
    from config.sources import ALL_RSS_SOURCES, STREAM_RSS_SOURCES, TOP_STORIES_RSS
    assert STREAM_RSS_SOURCES == ALL_RSS_SOURCES + TOP_STORIES_RSS
    assert all(s.role == "top_stories" for s in TOP_STORIES_RSS)
    assert any(not s.store_items for s in TOP_STORIES_RSS)          # Google News: prominence only
    assert all(not s.active for s in ALL_RSS_SOURCES if "reuters" in s.url.lower())
