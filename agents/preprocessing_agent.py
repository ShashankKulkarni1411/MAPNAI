"""
MAPNAI — agents/preprocessing_agent.py
Agent 2: Preprocessing Agent
Receives raw articles from all fetchers and applies:
  1. Text cleaning (HTML, URLs, whitespace, encoding)
  2. Language detection + filtering
  3. Deduplication (SimHash + MinHash)
  4. Timestamp normalization (ISO 8601 UTC)
  5. Domain classification (keyword fallback)
  6. Metadata tagging
  7. Lightweight enrichment (sentiment, keywords)
Produces: List[ProcessedArticle] — ready for storage.
"""

from typing import List, Tuple
from datetime import datetime

from utils.models import RawArticle, ProcessedArticle, SourceType, Domain, SentimentLabel
from utils.text_cleaner import (
    clean_text, detect_language, normalize_timestamp,
    classify_domain, passes_quality_gates, is_english,
)
from utils.deduplicator import ArticleDeduplicator
from utils.logger import logger
from config.settings import settings


# ── Lightweight sentiment scoring (no LLM needed here) ───────
# We use a simple lexicon approach. The LLM-based sentiment
# (Agent 2 in the main AI pipeline) will supersede this later.

POSITIVE_WORDS = {
    "growth", "surge", "gain", "profit", "bullish", "rise", "boost",
    "recovery", "milestone", "breakthrough", "positive", "strong",
    "approved", "success", "innovation", "opportunity", "upbeat",
}
NEGATIVE_WORDS = {
    "crash", "decline", "loss", "bearish", "fall", "drop", "crisis",
    "recession", "risk", "threat", "conflict", "war", "sanction",
    "outbreak", "failure", "concern", "warning", "cut", "negative",
}


def lexicon_sentiment(text: str) -> Tuple[float, SentimentLabel]:
    """
    Simple lexicon-based sentiment scorer.
    Returns (score: float -1.0 to +1.0, label: SentimentLabel).
    Replaced by LLM-based scoring in Agent 2 of the main pipeline.
    """
    words = set(text.lower().split())
    pos   = len(words & POSITIVE_WORDS)
    neg   = len(words & NEGATIVE_WORDS)
    total = pos + neg
    if total == 0:
        return 0.0, SentimentLabel.NEUTRAL
    score = (pos - neg) / total
    if score > 0.1:
        return score, SentimentLabel.POSITIVE
    if score < -0.1:
        return score, SentimentLabel.NEGATIVE
    return score, SentimentLabel.NEUTRAL


def extract_keywords(text: str, top_n: int = 10) -> List[str]:
    """
    Extract top-N keywords by term frequency (excluding stopwords).
    Placeholder for TF-IDF / KeyBERT in the full pipeline.
    """
    import re
    STOPWORDS = {
        "the", "a", "an", "in", "on", "at", "to", "for", "of", "and",
        "or", "but", "is", "was", "are", "were", "be", "been", "has",
        "have", "had", "it", "its", "that", "this", "with", "from", "by",
        "said", "says", "will", "would", "could", "should", "may", "also",
        "as", "he", "she", "they", "we", "i", "you", "not", "no", "new",
        "year", "years", "more", "can", "about", "after", "before", "when",
    }
    words = re.findall(r"\b[a-z]{3,}\b", text.lower())
    freq: dict = {}
    for w in words:
        if w not in STOPWORDS:
            freq[w] = freq.get(w, 0) + 1
    sorted_words = sorted(freq, key=freq.get, reverse=True)
    return sorted_words[:top_n]


def extract_topic_tags(title: str, body: str) -> List[str]:
    """
    Rule-based topic tag extraction.
    Returns list of tags like ['AI', 'IPO', 'RBI', 'Conflict'].
    """
    from config.sources import DOMAIN_KEYWORDS
    combined = (title + " " + body).lower()
    tags = []

    # Domain-level tags
    for domain, keywords in DOMAIN_KEYWORDS.items():
        hits = [kw for kw in keywords if kw in combined]
        if hits:
            tags.append(domain.replace("_", " ").title())

    # Specific high-value topic tags
    TOPIC_MAP = {
        "artificial intelligence": "AI",
        "machine learning": "ML",
        "interest rate": "Interest Rates",
        "inflation": "Inflation",
        "ipo": "IPO",
        "merger": "M&A",
        "acquisition": "M&A",
        "election": "Election",
        "climate": "Climate",
        "cryptocurrency": "Crypto",
        "bitcoin": "Crypto",
        "semiconductor": "Semiconductors",
        "geopolit": "Geopolitics",
        "pandemic": "Pandemic",
        "vaccine": "Vaccine",
        "supply chain": "Supply Chain",
        "trade war": "Trade War",
        "sanctions": "Sanctions",
    }
    for keyword, tag in TOPIC_MAP.items():
        if keyword in combined and tag not in tags:
            tags.append(tag)

    return list(set(tags))[:8]   # cap at 8 tags


# ── Main Preprocessing Agent ─────────────────────────────────

class PreprocessingAgent:
    """
    Stateful agent that holds deduplication state across a batch.
    One instance per ingestion run.
    """

    def __init__(self, existing_hashes: List[str] = None):
        self.deduplicator = ArticleDeduplicator(
            simhash_threshold=3,     # Hamming distance ≤ 3 → duplicate
            minhash_threshold=0.5,   # Jaccard ≥ 0.5 → duplicate
        )
        if existing_hashes:
            self.deduplicator.load_existing_hashes(existing_hashes)

        self.stats = {
            "total_input":       0,
            "failed_quality":    0,
            "non_english":       0,
            "duplicates":        0,
            "processed":         0,
        }

    def process(self, raw: RawArticle) -> Tuple[ProcessedArticle | None, str]:
        """
        Process a single RawArticle.
        Returns (ProcessedArticle, "ok") or (None, "reason_skipped").
        """
        self.stats["total_input"] += 1

        # ── Step 1: Clean text ────────────────────────────────
        clean_title = clean_text(raw.title)
        clean_body  = clean_text(raw.body)

        # ── Step 2: Language detection ────────────────────────
        lang = detect_language(clean_body or clean_title)
        if lang == "unknown":
            lang = "en"  # assume English if detector fails on short text

        # ── Step 3: Quality gates ─────────────────────────────
        passes, reason = passes_quality_gates(
            title=clean_title,
            body=clean_body,
            language=lang,
            min_length=settings.min_article_length,
            require_english=(settings.primary_language == "en"),
        )
        if not passes:
            self.stats["failed_quality"] += 1
            logger.debug(f"Quality gate fail [{raw.article_id[:8]}]: {reason}")
            return None, f"quality:{reason}"

        # ── Step 4: Deduplication ─────────────────────────────
        sim_hash = self.deduplicator.compute_hash(clean_title, clean_body)
        if self.deduplicator.is_duplicate(raw.article_id, clean_title, clean_body, sim_hash):
            self.stats["duplicates"] += 1
            return None, "duplicate"
        self.deduplicator.register(sim_hash)

        # ── Step 5: Timestamp normalization ──────────────────
        pub_at = normalize_timestamp(raw.published_at)

        # ── Step 6: Domain classification ────────────────────
        domain = raw.domain
        if domain == Domain.GENERAL:
            classified = classify_domain(clean_body, clean_title)
            try:
                domain = Domain(classified)
            except ValueError:
                domain = Domain.GENERAL

        # ── Step 7: Sentiment ────────────────────────────────
        sentiment_score, sentiment_label = lexicon_sentiment(clean_body)

        # ── Step 8: Keywords & topic tags ────────────────────
        keywords   = extract_keywords(clean_body)
        topic_tags = extract_topic_tags(clean_title, clean_body)

        processed = ProcessedArticle(
            article_id=raw.article_id,
            title=clean_title,
            body=clean_body,
            url=raw.url,
            source_name=raw.source_name,
            source_type=raw.source_type,
            domain=domain,
            raw_source=raw.raw_metadata.get("feed_url", "") or str(raw.source_type.value),
            published_at=pub_at,
            ingested_at=datetime.utcnow(),
            language=lang,
            dedup_hash=sim_hash,
            sentiment_score=sentiment_score,
            sentiment_label=sentiment_label,
            keywords=keywords,
            topic_tags=topic_tags,
        )

        self.stats["processed"] += 1
        return processed, "ok"

    def process_batch(
        self, raw_articles: List[RawArticle]
    ) -> List[ProcessedArticle]:
        """
        Process a batch of raw articles.
        Logs per-batch statistics on completion.
        """
        processed_articles: List[ProcessedArticle] = []

        for raw in raw_articles:
            try:
                result, status = self.process(raw)
                if result:
                    processed_articles.append(result)
            except Exception as e:
                logger.error(
                    f"[Preprocessing] Unexpected error on {raw.article_id[:8]}: {e}"
                )

        # Log batch summary
        s = self.stats
        logger.info(
            f"[Preprocessing] Batch complete | "
            f"Input={s['total_input']} | "
            f"Processed={s['processed']} | "
            f"Dupes={s['duplicates']} | "
            f"QualityFail={s['failed_quality']}"
        )
        return processed_articles

    def get_stats(self) -> dict:
        return self.stats.copy()
