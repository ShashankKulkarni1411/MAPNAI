"""
MAPNAI — agents/rss_fetcher.py
Agent 1a: RSS Feed Fetcher
Pulls articles from all configured RSS sources.
Handles timeouts, retries, and rate limiting per source.
Produces: List[RawArticle]
"""

import calendar
from dataclasses import dataclass, field

import feedparser
import requests
from typing import Dict, List, Optional
from datetime import datetime
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from config.settings import settings
from config.sources import RSSSource, ALL_RSS_SOURCES
from utils.models import RawArticle, SourceType, Domain
from utils.image_extractor import from_feed_entry
from utils.logger import logger
from stream.polling import ERROR, NOT_MODIFIED, OK, item_key, remember_seen

_HEADERS = {
    "User-Agent": "MAPNAI/1.0 NewsIngestion (research project)",
    "Accept": "application/rss+xml, application/xml, text/xml",
}


def _parse_published(entry: feedparser.FeedParserDict) -> Optional[datetime]:
    """Extract published datetime from feedparser entry."""
    from utils.text_cleaner import normalize_timestamp
    for field in ("published_parsed", "updated_parsed", "created_parsed"):
        val = getattr(entry, field, None)
        if val:
            try:
                # feedparser's *_parsed are UTC struct_times; time.mktime would read them as local time
                ts = calendar.timegm(val)
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


def _entry_to_article(entry: feedparser.FeedParserDict, source: RSSSource) -> Optional[RawArticle]:
    """One feed entry → RawArticle, or None when it has no title."""
    title = entry.get("title", "").strip()
    if not title:
        return None
    return RawArticle(
        title=title,
        body=_extract_body(entry).strip(),
        url=entry.get("link", ""),
        source_name=source.name,
        source_type=SourceType.RSS,
        domain=Domain(source.domain),
        published_at=_parse_published(entry),
        language=source.language,
        author=(entry.get("author") or "").strip() or None,
        raw_metadata={
            "feed_url": source.url,
            "feed_role": getattr(source, "role", "section"),
            "tags": [t.get("term", "") for t in entry.get("tags", [])],
        },
        images=from_feed_entry(entry),
    )


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type(Exception),
    reraise=False,
)
def _fetch_feed(url: str, timeout: int) -> Optional[feedparser.FeedParserDict]:
    """Fetch and parse a single RSS feed URL. Retries on failure."""
    # feedparser doesn't use requests by default — inject headers manually
    try:
        response = requests.get(url, headers=dict(_HEADERS), timeout=timeout)
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
            article = _entry_to_article(entry, source)
            if article is not None:
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


# ── Stream polling (stream_worker.py) ────────────────────────

@dataclass
class PollResult:
    """One poll of one feed. status: ok | not_modified | error (stream/polling.py)."""
    source: str
    status: str
    articles: List[RawArticle] = field(default_factory=list)     # unseen items, to store (empty for signal feeds)
    prominence: List[Dict] = field(default_factory=list)         # every item on a top_stories feed right now
    new_count: int = 0                                           # unseen items (stored or not)
    seen: Optional[List[str]] = None                             # the seen keys after this poll (None: unchanged)
    etag: Optional[str] = None
    last_modified: Optional[str] = None
    error: Optional[str] = None
    http_status: Optional[int] = None


def poll_rss_source(
    source: RSSSource,
    state: Optional[Dict] = None,
    max_articles: int = None,
    seen_keep: int = None,
    timeout: int = None,
) -> PollResult:
    """
    Poll one feed for the stream worker: a conditional GET (If-None-Match / If-Modified-Since from the previous
    poll's ETag / Last-Modified; 304 → nothing downloaded or parsed), then only items whose key (GUID, else link,
    else title) isn't among the source's remembered keys. A top_stories feed also reports all its current items as
    prominence rows; a feed with store_items=False is a signal only and returns no articles. Never raises.
    """
    state = state or {}
    max_articles = max_articles or settings.max_articles_per_source
    seen_keep = seen_keep or settings.stream_seen_keep
    timeout = timeout or settings.request_timeout_seconds
    headers = dict(_HEADERS)
    if state.get("etag"):
        headers["If-None-Match"] = state["etag"]
    if state.get("last_modified"):
        headers["If-Modified-Since"] = state["last_modified"]

    try:
        response = requests.get(source.url, headers=headers, timeout=timeout)
        if response.status_code == 304:
            return PollResult(source.name, NOT_MODIFIED, http_status=304)
        response.raise_for_status()
        feed = feedparser.parse(response.content)
    except Exception as e:
        status = getattr(getattr(e, "response", None), "status_code", None)
        logger.warning(f"[RSS] Poll failed for {source.name}: {type(e).__name__}: {e}")
        return PollResult(source.name, ERROR, error=f"{type(e).__name__}: {e}"[:300], http_status=status)

    entries = list(feed.entries[:max_articles])
    if not entries and getattr(feed, "bozo", False):
        reason = getattr(feed, "bozo_exception", None)
        return PollResult(source.name, ERROR, error=f"unparseable feed: {reason}"[:300],
                          http_status=response.status_code)

    seen = set(state.get("seen") or [])
    current_keys, articles, prominence, new_count = [], [], [], 0
    role = getattr(source, "role", "section")
    for entry in entries:
        key = item_key(entry)
        if not key:
            continue
        current_keys.append(key)
        if role == "top_stories":
            prominence.append({"feed": source.name, "url": entry.get("link", ""),
                               "title": (entry.get("title") or "").strip(), "domain": source.domain})
        if key in seen:
            continue
        new_count += 1
        if getattr(source, "store_items", True):
            article = _entry_to_article(entry, source)
            if article is not None:
                articles.append(article)

    return PollResult(
        source=source.name, status=OK, articles=articles, prominence=prominence, new_count=new_count,
        seen=remember_seen(state.get("seen") or [], current_keys, seen_keep),
        etag=response.headers.get("ETag"), last_modified=response.headers.get("Last-Modified"),
        http_status=response.status_code,
    )
