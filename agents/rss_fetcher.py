"""
MAPNAI — agents/rss_fetcher.py
Agent 1a: RSS Feed Fetcher
Pulls articles from all configured RSS sources.
Handles timeouts, retries, and rate limiting per source.
Produces: List[RawArticle]
"""

import feedparser
import requests
from typing import List, Optional
from datetime import datetime
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from config.settings import settings
from config.sources import RSSSource, ALL_RSS_SOURCES
from utils.models import RawArticle, SourceType, Domain
from utils.logger import logger


def _parse_published(entry: feedparser.FeedParserDict) -> Optional[datetime]:
    """Extract published datetime from feedparser entry."""
    from utils.text_cleaner import normalize_timestamp
    for field in ("published_parsed", "updated_parsed", "created_parsed"):
        val = getattr(entry, field, None)
        if val:
            import time
            try:
                ts = time.mktime(val)
                return normalize_timestamp(ts)
            except Exception:
                continue
    for field in ("published", "updated", "created"):
        val = entry.get(field, "")
        if val:
            return normalize_timestamp(val)
    return None


def _extract_body(entry: feedparser.FeedParserDict) -> str:
    """Try to get the fullest body text from a feed entry."""
    # Prefer content[0].value → summary → title
    if hasattr(entry, "content") and entry.content:
        return entry.content[0].get("value", "")
    if hasattr(entry, "summary") and entry.summary:
        return entry.summary
    if hasattr(entry, "description") and entry.description:
        return entry.description
    return entry.get("title", "")


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type(Exception),
    reraise=False,
)
def _fetch_feed(url: str, timeout: int) -> Optional[feedparser.FeedParserDict]:
    """Fetch and parse a single RSS feed URL. Retries on failure."""
    # feedparser doesn't use requests by default — inject headers manually
    headers = {
        "User-Agent": "MAPNAI/1.0 NewsIngestion (research project)",
        "Accept": "application/rss+xml, application/xml, text/xml",
    }
    try:
        response = requests.get(url, headers=headers, timeout=timeout)
        response.raise_for_status()
        feed = feedparser.parse(response.content)
        return feed
    except requests.exceptions.Timeout:
        logger.warning(f"Timeout fetching RSS: {url}")
        raise
    except requests.exceptions.HTTPError as e:
        logger.warning(f"HTTP {e.response.status_code} for RSS: {url}")
        raise
    except Exception as e:
        logger.warning(f"RSS fetch error ({url}): {e}")
        raise


def fetch_rss_source(
    source: RSSSource,
    max_articles: int = None,
) -> List[RawArticle]:
    """
    Fetch articles from a single RSS source.
    Returns list of RawArticle objects (uncleaned).
    """
    if not source.active:
        return []

    max_articles = max_articles or settings.max_articles_per_source
    articles: List[RawArticle] = []

    try:
        feed = _fetch_feed(source.url, settings.request_timeout_seconds)
        if feed is None:
            return []

        entries = feed.entries[:max_articles]
        for entry in entries:
            title = entry.get("title", "").strip()
            body  = _extract_body(entry).strip()
            url   = entry.get("link", "")

            if not title:
                continue

            article = RawArticle(
                title=title,
                body=body,
                url=url,
                source_name=source.name,
                source_type=SourceType.RSS,
                domain=Domain(source.domain),
                published_at=_parse_published(entry),
                language=source.language,
                raw_metadata={
                    "feed_url": source.url,
                    "tags": [t.get("term", "") for t in entry.get("tags", [])],
                },
            )
            articles.append(article)

        logger.info(f"[RSS] Fetched {len(articles)} articles from {source.name}")

    except Exception as e:
        logger.error(f"[RSS] Failed to fetch {source.name} ({source.url}): {e}")

    return articles


def fetch_all_rss_sources(
    sources: List[RSSSource] = None,
    max_per_source: int = None,
) -> List[RawArticle]:
    """
    Fetch all configured RSS sources sequentially with per-source error isolation.
    Returns combined list of RawArticle objects.
    """
    sources = sources or ALL_RSS_SOURCES
    max_per_source = max_per_source or settings.max_articles_per_source

    all_articles: List[RawArticle] = []
    for source in sources:
        try:
            articles = fetch_rss_source(source, max_per_source)
            all_articles.extend(articles)
        except Exception as e:
            logger.error(f"[RSS] Critical error on source {source.name}: {e}")
            # Continue to next source — fault-tolerant by design

    logger.info(f"[RSS] Total fetched across all sources: {len(all_articles)}")
    return all_articles
