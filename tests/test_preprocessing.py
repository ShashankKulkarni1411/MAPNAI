"""
MAPNAI — tests/test_preprocessing.py
Unit tests for preprocessing agent, text cleaner, and deduplicator.
Run with: pytest tests/test_preprocessing.py -v
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest
from datetime import datetime, timezone

from utils.text_cleaner import (
    strip_html, remove_urls, normalize_whitespace, clean_text,
    detect_language, normalize_timestamp, to_iso8601,
    classify_domain, passes_quality_gates,
)
from utils.deduplicator import (
    compute_simhash, simhash_distance, ArticleDeduplicator,
)
from utils.models import RawArticle, SourceType, Domain
from agents.preprocessing_agent import (
    PreprocessingAgent, lexicon_sentiment, extract_keywords,
)


# ══════════════════════════════════════════════════════════════
# Text Cleaner Tests
# ══════════════════════════════════════════════════════════════

class TestStripHTML:
    def test_removes_basic_tags(self):
        assert strip_html("<p>Hello <b>world</b></p>") == "Hello world"

    def test_removes_nested_tags(self):
        result = strip_html("<div><p>Text <span>here</span></p></div>")
        assert "Text here" in result
        assert "<" not in result

    def test_decodes_entities(self):
        result = strip_html("&lt;script&gt; &amp; &#39;")
        assert "<script>" in result
        assert "&" in result

    def test_empty_string(self):
        assert strip_html("") == ""

    def test_no_html(self):
        assert strip_html("plain text") == "plain text"


class TestRemoveURLs:
    def test_removes_https(self):
        result = remove_urls("Visit https://www.reuters.com/article for more")
        assert "https://" not in result
        assert "Visit" in result

    def test_removes_http(self):
        result = remove_urls("See http://example.com/path?q=1")
        assert "http://" not in result

    def test_removes_www(self):
        result = remove_urls("Go to www.bbc.com today")
        assert "www.bbc.com" not in result

    def test_keeps_non_url_text(self):
        result = remove_urls("The RBI raised rates by 25bps.")
        assert "The RBI raised rates by 25bps." == result


class TestNormalizeWhitespace:
    def test_collapses_spaces(self):
        assert normalize_whitespace("hello   world") == "hello world"

    def test_collapses_newlines(self):
        assert normalize_whitespace("line1\n\nline2") == "line1 line2"

    def test_strips_edges(self):
        assert normalize_whitespace("  text  ") == "text"

    def test_tabs(self):
        assert normalize_whitespace("a\t\tb") == "a b"


class TestCleanText:
    def test_full_pipeline(self):
        raw = "<p>The Fed <b>raised</b> rates. Visit https://fed.gov for more.  </p>"
        result = clean_text(raw)
        assert "<" not in result
        assert "https://" not in result
        assert result == result.strip()
        assert "  " not in result

    def test_empty_input(self):
        assert clean_text("") == ""

    def test_none_safe(self):
        assert clean_text(None) == ""


class TestLanguageDetection:
    def test_english(self):
        text = "The Federal Reserve raised interest rates by 25 basis points on Wednesday."
        assert detect_language(text) == "en"

    def test_short_text_returns_unknown(self):
        assert detect_language("hi") == "unknown"

    def test_empty_returns_unknown(self):
        assert detect_language("") == "unknown"


class TestTimestampNormalization:
    def test_iso_string(self):
        dt = normalize_timestamp("2026-04-19T14:30:00Z")
        assert dt is not None
        assert dt.tzinfo is not None
        assert dt.year == 2026

    def test_rfc2822_string(self):
        dt = normalize_timestamp("Thu, 19 Apr 2026 14:30:00 +0530")
        assert dt is not None
        # Should be converted to UTC (offset -05:30 from +05:30)
        assert dt.tzinfo == timezone.utc or str(dt.tzinfo) == "UTC"

    def test_unix_epoch(self):
        dt = normalize_timestamp(1713534600)
        assert dt is not None
        assert dt.year in (2024, 2025, 2026)

    def test_none_input(self):
        assert normalize_timestamp(None) is None

    def test_invalid_string(self):
        assert normalize_timestamp("not-a-date") is None

    def test_to_iso8601_format(self):
        dt = normalize_timestamp("2026-04-19T14:30:00Z")
        iso = to_iso8601(dt)
        assert iso == "2026-04-19T14:30:00Z"


class TestDomainClassification:
    def test_finance(self):
        text = "The RBI governor announced new interest rate policy today."
        assert classify_domain(text) == "finance"

    def test_technology(self):
        text = "OpenAI released a new large language model with improved reasoning."
        assert classify_domain(text) == "technology"

    def test_health(self):
        text = "WHO declared a new outbreak of mpox virus in several African nations."
        assert classify_domain(text) == "health"

    def test_no_match_returns_general(self):
        text = "abc xyz foo bar baz"
        assert classify_domain(text) == "general"


class TestQualityGates:
    def test_passes_valid_article(self):
        ok, reason = passes_quality_gates(
            title="Fed raises rates",
            body="The Federal Reserve raised interest rates by 25 basis points on Wednesday, citing persistent inflation concerns in the economy.",
            language="en",
            min_length=50,
        )
        assert ok is True
        assert reason == ""

    def test_fails_empty_title(self):
        ok, reason = passes_quality_gates("", "Some body text here.", "en")
        assert ok is False
        assert "title" in reason.lower()

    def test_fails_empty_body(self):
        ok, reason = passes_quality_gates("Title here", "", "en")
        assert ok is False

    def test_fails_short_body(self):
        ok, reason = passes_quality_gates("Title", "Too short.", "en", min_length=100)
        assert ok is False
        assert "short" in reason.lower()


# ══════════════════════════════════════════════════════════════
# Deduplicator Tests
# ══════════════════════════════════════════════════════════════

class TestSimHash:
    def test_same_text_same_hash(self):
        h1 = compute_simhash("RBI raises rates", "The RBI raised interest rates today.")
        h2 = compute_simhash("RBI raises rates", "The RBI raised interest rates today.")
        assert h1 == h2

    def test_completely_different_texts(self):
        h1 = compute_simhash("Apple releases iPhone", "Apple has released a new iPhone model.")
        h2 = compute_simhash("WHO declares outbreak", "The WHO declared a new disease outbreak.")
        distance = simhash_distance(h1, h2)
        assert distance > 6   # should be very different

    def test_near_duplicate_texts(self):
        # Same story, slight rewording
        h1 = compute_simhash(
            "Fed raises interest rates",
            "The Federal Reserve raised interest rates by 25 basis points Wednesday."
        )
        h2 = compute_simhash(
            "Fed hikes interest rates",
            "The Federal Reserve hiked interest rates by 25 basis points on Wednesday."
        )
        distance = simhash_distance(h1, h2)
        assert distance <= 10   # near-duplicate

    def test_returns_hex_string(self):
        h = compute_simhash("test title", "test body content here")
        assert len(h) == 16
        int(h, 16)   # should not raise


class TestArticleDeduplicator:
    def setup_method(self):
        self.deduper = ArticleDeduplicator(simhash_threshold=3)

    def test_first_article_not_duplicate(self):
        title = "ECB cuts rates amid recession fears"
        body  = "The European Central Bank cut interest rates by 50 basis points on Thursday."
        h = self.deduper.compute_hash(title, body)
        assert not self.deduper.is_duplicate("art-001", title, body, h)
        self.deduper.register(h)

    def test_exact_duplicate_detected(self):
        title = "RBI holds rates steady"
        body  = "The Reserve Bank of India held the repo rate steady at 6.5 percent on Friday."
        h = self.deduper.compute_hash(title, body)
        self.deduper.register(h)
        # Same article again
        assert self.deduper.is_duplicate("art-002", title, body, h)

    def test_distinct_articles_not_duplicates(self):
        art1_h = self.deduper.compute_hash("AI chip demand surges", "NVIDIA reported record revenues.")
        self.deduper.register(art1_h)
        art2_h = self.deduper.compute_hash("Monsoon forecast", "IMD predicts normal monsoon season.")
        assert not self.deduper.is_duplicate("art-003", "Monsoon forecast", "IMD predicts normal monsoon season.", art2_h)

    def test_seed_from_existing_hashes(self):
        existing = [compute_simhash("Existing article", "This article was already in the database.")]
        deduper = ArticleDeduplicator()
        deduper.load_existing_hashes(existing)
        # Same article should be a duplicate
        h = compute_simhash("Existing article", "This article was already in the database.")
        assert deduper.is_duplicate("new-id", "Existing article", "This article was already in the database.", h)


# ══════════════════════════════════════════════════════════════
# Preprocessing Agent Tests
# ══════════════════════════════════════════════════════════════

class TestLexiconSentiment:
    def test_positive_text(self):
        score, label = lexicon_sentiment("Strong growth and profit surge drives bullish market recovery.")
        assert label.value == "positive"
        assert score > 0

    def test_negative_text(self):
        score, label = lexicon_sentiment("Market crash and recession risk threaten economic loss.")
        assert label.value == "negative"
        assert score < 0

    def test_neutral_text(self):
        score, label = lexicon_sentiment("The committee met on Tuesday to discuss quarterly results.")
        assert label.value == "neutral"


class TestExtractKeywords:
    def test_returns_list(self):
        keywords = extract_keywords("The Federal Reserve raised interest rates today amid inflation concerns.")
        assert isinstance(keywords, list)
        assert len(keywords) > 0

    def test_excludes_stopwords(self):
        keywords = extract_keywords("The the the a an in on at to for of")
        assert "the" not in keywords

    def test_top_n_limit(self):
        text = " ".join(["word"] * 50 + ["apple"] * 30 + ["banana"] * 20)
        keywords = extract_keywords(text, top_n=5)
        assert len(keywords) <= 5


class TestPreprocessingAgent:
    def _make_raw(self, title, body, domain="general"):
        return RawArticle(
            title=title,
            body=body,
            url="https://example.com/article",
            source_name="Test Source",
            source_type=SourceType.RSS,
            domain=Domain(domain),
            published_at=None,
            language="en",
        )

    def test_processes_valid_article(self):
        agent = PreprocessingAgent()
        raw = self._make_raw(
            "Fed raises rates by 25bps",
            "The Federal Reserve raised interest rates by 25 basis points on Wednesday, "
            "citing persistent inflation. The move was widely expected by markets and analysts.",
        )
        result, status = agent.process(raw)
        assert status == "ok"
        assert result is not None
        assert result.title == "Fed raises rates by 25bps"
        assert result.dedup_hash != ""
        assert result.sentiment_label is not None

    def test_drops_empty_body(self):
        agent = PreprocessingAgent()
        raw = self._make_raw("Title only", "")
        result, status = agent.process(raw)
        assert result is None
        assert "quality" in status

    def test_drops_short_body(self):
        agent = PreprocessingAgent()
        raw = self._make_raw("Title", "Too short.")
        result, status = agent.process(raw)
        assert result is None

    def test_cleans_html_in_body(self):
        agent = PreprocessingAgent()
        raw = self._make_raw(
            "Breaking News",
            "<p>The <b>RBI</b> announced <a href='#'>new policy</a> today. "
            "The decision was unanimous and affects all scheduled commercial banks "
            "across India. More details are expected in the press conference tomorrow.",
        )
        result, status = agent.process(raw)
        assert result is not None
        assert "<" not in result.body
        assert "<b>" not in result.body

    def test_deduplicates_same_article(self):
        agent = PreprocessingAgent()
        body = (
            "The Reserve Bank of India kept the repo rate unchanged at 6.5 percent "
            "during its Monetary Policy Committee meeting held in Mumbai on Friday, "
            "as expected by most economists and financial analysts surveyed."
        )
        raw1 = self._make_raw("RBI holds rates", body)
        raw2 = self._make_raw("RBI holds rates", body)

        result1, status1 = agent.process(raw1)
        result2, status2 = agent.process(raw2)

        assert status1 == "ok"
        assert result1 is not None
        assert status2 == "duplicate"
        assert result2 is None

    def test_batch_processing(self):
        agent = PreprocessingAgent()
        articles = [
            self._make_raw(
                f"Article {i}: Market update",
                f"This is article number {i} about the financial markets. "
                f"The stock market showed mixed signals today with technology stocks "
                f"leading gains while energy sector lagged behind. Investors remain cautious."
            )
            for i in range(5)
        ]
        results = agent.process_batch(articles)
        assert len(results) == 5
        stats = agent.get_stats()
        assert stats["total_input"] == 5
        assert stats["processed"] == 5

    def test_timestamp_normalization(self):
        agent = PreprocessingAgent()
        raw = self._make_raw(
            "Inflation data released",
            "The government released CPI inflation data for March 2026. "
            "Headline inflation came in at 4.2 percent, slightly below expectations "
            "of 4.5 percent according to Bloomberg survey of economists.",
        )
        raw.published_at = "Thu, 19 Apr 2026 10:30:00 +0530"
        result, status = agent.process(raw)
        assert result is not None
        assert result.published_at is not None
        assert result.published_at.tzinfo is not None   # UTC-aware


# ══════════════════════════════════════════════════════════════
# Integration-style smoke test (no external services)
# ══════════════════════════════════════════════════════════════

class TestEndToEndPreprocessing:
    """
    Simulates a realistic ingestion batch — no DB, no API calls.
    Tests the full preprocessing pipeline on synthetic articles.
    """

    SAMPLE_ARTICLES = [
        ("RBI cuts repo rate by 25bps",
         "The Reserve Bank of India's Monetary Policy Committee voted 4-2 to cut the repo rate "
         "by 25 basis points to 6.25 percent, the first cut in two years. Governor Shaktikanta Das "
         "said the move was aimed at supporting growth amid slowing global demand.", "finance"),

        ("OpenAI releases GPT-5 with multimodal capabilities",
         "OpenAI announced the release of GPT-5, its most capable language model to date. "
         "The model shows significant improvements in reasoning, coding, and multimodal tasks. "
         "CEO Sam Altman described it as a major leap forward for AI safety and capability.", "technology"),

        ("WHO declares mpox public health emergency",
         "The World Health Organization declared mpox a public health emergency of international "
         "concern for the second time after a new clade emerged in Central Africa. Director-General "
         "Tedros Adhanom Ghebreyesus urged countries to accelerate vaccine deployment.", "health"),

        # Near-duplicate of first article (should be deduplicated)
        ("RBI reduces repo rate 25bps in surprise move",
         "The Reserve Bank of India Monetary Policy Committee voted 4-2 to reduce the repo rate "
         "by 25 basis points to 6.25 percent, marking the first reduction in two years. Governor "
         "Das said the cut aimed to support growth amid slowing global demand pressure.", "finance"),

        ("China imposes new tariffs on US semiconductor exports",
         "China announced new retaliatory tariffs on US semiconductor exports, escalating the "
         "ongoing trade war between the two largest economies. The tariffs affect over 150 products "
         "and take effect immediately, according to the Ministry of Commerce statement.", "geopolitics"),
    ]

    def test_batch_with_duplicate(self):
        from utils.models import RawArticle, SourceType, Domain

        raw_articles = [
            RawArticle(
                title=title,
                body=body,
                url=f"https://news.example.com/{i}",
                source_name="Test News",
                source_type=SourceType.RSS,
                domain=Domain(domain),
                published_at="2026-04-19T10:00:00Z",
                language="en",
            )
            for i, (title, body, domain) in enumerate(self.SAMPLE_ARTICLES)
        ]

        agent = PreprocessingAgent()
        results = agent.process_batch(raw_articles)

        stats = agent.get_stats()
        assert stats["total_input"] == 5
        assert stats["processed"] == 4        # one duplicate dropped
        assert stats["duplicates"] >= 1

        # Verify all processed articles have required fields
        for art in results:
            assert art.article_id
            assert art.title
            assert art.body
            assert art.dedup_hash
            assert art.sentiment_label
            assert isinstance(art.keywords, list)
            assert isinstance(art.topic_tags, list)


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
