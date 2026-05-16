"""
MAPNAI — tests/test_fetchers.py
Unit tests for RSS, API, and Reddit fetchers.
All HTTP calls are mocked — no real network requests.
Run with: pytest tests/test_fetchers.py -v
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone

from utils.models import SourceType, Domain


# ══════════════════════════════════════════════════════════════
# RSS Fetcher Tests
# ══════════════════════════════════════════════════════════════

class TestRSSFetcher:

    def _make_mock_feed(self, entries: list) -> MagicMock:
        """Create a mock feedparser result."""
        mock_feed = MagicMock()
        mock_feed.entries = entries
        return mock_feed

    def _make_entry(self, title, summary, link, published="Thu, 19 Apr 2026 10:00:00 +0000"):
        entry = MagicMock()
        entry.get = lambda k, default="": {
            "title": title, "link": link, "published": published
        }.get(k, default)
        entry.title   = title
        entry.summary = summary
        entry.link    = link
        entry.published = published
        entry.published_parsed = None
        entry.updated_parsed   = None
        entry.tags = []
        # No content attribute (use summary path)
        del entry.content
        return entry

    @patch("agents.rss_fetcher.feedparser")
    @patch("agents.rss_fetcher.requests.get")
    def test_fetches_articles_from_feed(self, mock_get, mock_feedparser):
        """Verify RSS fetcher returns RawArticle list from a valid feed."""
        from agents.rss_fetcher import fetch_rss_source
        from config.sources import RSSSource

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = b"<rss/>"
        mock_get.return_value = mock_response

        mock_feed = self._make_mock_feed([
            self._make_entry("RBI cuts rates", "The RBI cut repo rate by 25bps.", "https://a.com/1"),
            self._make_entry("Fed holds rates", "Fed kept rates unchanged.", "https://a.com/2"),
        ])
        mock_feedparser.parse.return_value = mock_feed

        source = RSSSource("Test Source", "https://test.com/feed", "finance")
        articles = fetch_rss_source(source, max_articles=10)

        assert len(articles) == 2
        assert articles[0].source_type == SourceType.RSS
        assert articles[0].domain == Domain.FINANCE
        assert "RBI" in articles[0].title

    @patch("agents.rss_fetcher.feedparser")
    @patch("agents.rss_fetcher.requests.get")
    def test_skips_entries_without_title(self, mock_get, mock_feedparser):
        from agents.rss_fetcher import fetch_rss_source
        from config.sources import RSSSource

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = b"<rss/>"
        mock_get.return_value = mock_response

        entry_no_title = self._make_entry("", "Some content", "https://a.com/3")
        mock_feed = self._make_mock_feed([entry_no_title])
        mock_feedparser.parse.return_value = mock_feed

        source = RSSSource("Test", "https://test.com/feed", "technology")
        articles = fetch_rss_source(source)
        assert articles == []

    @patch("agents.rss_fetcher.requests.get")
    def test_inactive_source_returns_empty(self, mock_get):
        from agents.rss_fetcher import fetch_rss_source
        from config.sources import RSSSource

        source = RSSSource("Inactive", "https://test.com/feed", "finance", active=False)
        articles = fetch_rss_source(source)
        assert articles == []
        mock_get.assert_not_called()

    @patch("agents.rss_fetcher.requests.get")
    def test_network_error_returns_empty_list(self, mock_get):
        """Verify graceful handling of network errors."""
        import requests as req
        from agents.rss_fetcher import fetch_rss_source
        from config.sources import RSSSource

        mock_get.side_effect = req.exceptions.ConnectionError("Network unreachable")

        source = RSSSource("Test", "https://test.com/feed", "finance")
        articles = fetch_rss_source(source)
        assert articles == []

    @patch("agents.rss_fetcher.requests.get")
    def test_http_error_returns_empty_list(self, mock_get):
        import requests as req
        from agents.rss_fetcher import fetch_rss_source
        from config.sources import RSSSource

        mock_response = MagicMock()
        mock_response.status_code = 503
        mock_response.raise_for_status.side_effect = req.exceptions.HTTPError(
            response=mock_response
        )
        mock_get.return_value = mock_response

        source = RSSSource("Test", "https://test.com/feed", "finance")
        articles = fetch_rss_source(source)
        assert articles == []

    @patch("agents.rss_fetcher.requests.get")
    def test_respects_max_articles_limit(self, mock_get):
        from agents.rss_fetcher import fetch_rss_source
        from config.sources import RSSSource
        import feedparser

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = b"<rss/>"
        mock_get.return_value = mock_response

        # Create 20 entries
        with patch("agents.rss_fetcher.feedparser") as mock_fp:
            entries = [
                self._make_entry(f"Article {i}", f"Content {i}", f"https://a.com/{i}")
                for i in range(20)
            ]
            mock_feed = MagicMock()
            mock_feed.entries = entries
            mock_fp.parse.return_value = mock_feed

            source = RSSSource("Test", "https://test.com/feed", "finance")
            articles = fetch_rss_source(source, max_articles=5)
            assert len(articles) <= 5


# ══════════════════════════════════════════════════════════════
# NewsAPI Fetcher Tests
# ══════════════════════════════════════════════════════════════

class TestNewsAPIFetcher:

    def _mock_api_response(self, articles: list) -> dict:
        return {
            "status":       "ok",
            "totalResults": len(articles),
            "articles":     articles,
        }

    def _make_article_item(self, title, content, url, source_name="Reuters"):
        return {
            "title":       title,
            "content":     content,
            "description": content[:100],
            "url":         url,
            "publishedAt": "2026-04-19T10:00:00Z",
            "source":      {"name": source_name},
            "author":      "Reporter Name",
        }

    @patch("agents.api_fetcher.requests.get")
    def test_fetch_returns_articles(self, mock_get):
        from agents.api_fetcher import NewsAPIFetcher

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = self._mock_api_response([
            self._make_article_item("RBI Policy", "RBI cut rates today.", "https://r.com/1"),
            self._make_article_item("Fed Decision", "Fed held rates.", "https://r.com/2"),
        ])
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        fetcher = NewsAPIFetcher(api_key="test_key_12345")
        articles = fetcher.fetch("central bank rates", "finance", max_articles=10)

        assert len(articles) == 2
        assert articles[0].source_type == SourceType.NEWS_API
        assert articles[0].domain == Domain.FINANCE

    @patch("agents.api_fetcher.requests.get")
    def test_skips_removed_articles(self, mock_get):
        """Articles with title '[Removed]' should be filtered out."""
        from agents.api_fetcher import NewsAPIFetcher

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = self._mock_api_response([
            self._make_article_item("[Removed]", "", "https://r.com/1"),
            self._make_article_item("Good Article", "Real content here.", "https://r.com/2"),
        ])
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        fetcher = NewsAPIFetcher(api_key="test_key")
        articles = fetcher.fetch("query", "finance")
        assert len(articles) == 1
        assert articles[0].title == "Good Article"

    def test_unconfigured_key_returns_empty(self):
        from agents.api_fetcher import NewsAPIFetcher
        fetcher = NewsAPIFetcher(api_key="your_newsapi_key_here")
        articles = fetcher.fetch("query", "finance")
        assert articles == []

    @patch("agents.api_fetcher.requests.get")
    def test_api_error_status_returns_empty(self, mock_get):
        from agents.api_fetcher import NewsAPIFetcher

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"status": "error", "message": "API key invalid"}
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        fetcher = NewsAPIFetcher(api_key="test_key")
        articles = fetcher.fetch("query", "finance")
        assert articles == []

    @patch("agents.api_fetcher.requests.get")
    def test_rate_limit_429_raises(self, mock_get):
        """429 should be retried (raised to tenacity)."""
        import requests as req
        from agents.api_fetcher import _get_json

        mock_resp = MagicMock()
        mock_resp.status_code = 429
        http_error = req.exceptions.HTTPError(response=mock_resp)
        mock_resp.raise_for_status.side_effect = http_error
        mock_get.return_value = mock_resp

        # _get_json re-raises on 429 — tenacity will catch it
        # In our test, tenacity is configured to re-raise after max attempts
        result = _get_json("https://api.example.com", {"key": "test"})
        # Should return None after exhausting retries
        assert result is None


# ══════════════════════════════════════════════════════════════
# GNews Fetcher Tests
# ══════════════════════════════════════════════════════════════

class TestGNewsFetcher:

    @patch("agents.api_fetcher.requests.get")
    def test_fetch_returns_articles(self, mock_get):
        from agents.api_fetcher import GNewsFetcher

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "articles": [
                {
                    "title":       "Tech layoffs continue",
                    "description": "Major tech firms continue layoffs.",
                    "content":     "Technology layoffs continue across Silicon Valley.",
                    "url":         "https://gnews.io/a/1",
                    "publishedAt": "2026-04-19T09:00:00Z",
                    "source":      {"name": "TechCrunch"},
                }
            ]
        }
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        fetcher = GNewsFetcher(api_key="gnews_test_key")
        articles = fetcher.fetch("tech layoffs", "technology", max_articles=5)

        assert len(articles) == 1
        assert articles[0].source_type == SourceType.GNEWS
        assert articles[0].domain == Domain.TECHNOLOGY

    def test_unconfigured_key_skipped(self):
        from agents.api_fetcher import GNewsFetcher
        fetcher = GNewsFetcher(api_key="your_gnews_key_here")
        assert fetcher.fetch("query", "finance") == []


# ══════════════════════════════════════════════════════════════
# Source Config Tests
# ══════════════════════════════════════════════════════════════

class TestSourceConfig:
    def test_all_rss_sources_have_required_fields(self):
        from config.sources import ALL_RSS_SOURCES
        for source in ALL_RSS_SOURCES:
            assert source.name, f"Source missing name"
            assert source.url.startswith("http"), f"{source.name}: invalid URL"
            assert source.domain in (
                "finance", "geopolitics", "technology", "health", "supply_chain", "general"
            ), f"{source.name}: invalid domain '{source.domain}'"

    def test_reddit_sources_have_required_fields(self):
        from config.sources import REDDIT_SOURCES
        for source in REDDIT_SOURCES:
            assert source.subreddit
            assert source.post_limit > 0
            assert source.domain in (
                "finance", "geopolitics", "technology", "health", "supply_chain"
            )

    def test_domain_keywords_coverage(self):
        from config.sources import DOMAIN_KEYWORDS
        required_domains = ["finance", "geopolitics", "technology", "health", "supply_chain"]
        for domain in required_domains:
            assert domain in DOMAIN_KEYWORDS
            assert len(DOMAIN_KEYWORDS[domain]) >= 5

    def test_source_counts_are_meaningful(self):
        from config.sources import (
            FINANCE_RSS, GEOPOLITICS_RSS, TECHNOLOGY_RSS,
            HEALTH_RSS, GOVERNMENT_RSS, REDDIT_SOURCES, ALL_RSS_SOURCES,
        )
        assert len(FINANCE_RSS)     >= 5
        assert len(GEOPOLITICS_RSS) >= 5
        assert len(TECHNOLOGY_RSS)  >= 5
        assert len(HEALTH_RSS)      >= 4
        assert len(GOVERNMENT_RSS)  >= 5
        assert len(REDDIT_SOURCES)  >= 8
        assert len(ALL_RSS_SOURCES) >= 25


# ══════════════════════════════════════════════════════════════
# Settings Tests
# ══════════════════════════════════════════════════════════════

class TestSettings:
    def test_settings_have_defaults(self):
        from config.settings import settings
        assert settings.ingestion_interval_minutes > 0
        assert settings.max_articles_per_source > 0
        assert settings.min_article_length > 0
        assert settings.request_timeout_seconds > 0
        assert settings.max_retries > 0
        assert settings.embedding_model

    def test_default_language_is_english(self):
        from config.settings import settings
        assert settings.primary_language == "en"

    def test_mongo_default_uri(self):
        from config.settings import settings
        assert "mongodb" in settings.mongo_uri.lower()

    def test_neo4j_default_uri(self):
        from config.settings import settings
        assert "bolt://" in settings.neo4j_uri or "neo4j://" in settings.neo4j_uri


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
