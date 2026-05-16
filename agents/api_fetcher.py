"""
MAPNAI — agents/api_fetcher.py
Agent 1b: News API Fetcher
Fetches from NewsAPI, GNews, and NewsData.io.
Rate-limit aware, retry-equipped, returns List[RawArticle].
"""

import requests
from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta, timezone
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from config.settings import settings
from utils.models import RawArticle, SourceType, Domain
from utils.text_cleaner import normalize_timestamp
from utils.logger import logger


# ── Base API helper ──────────────────────────────────────────

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=15),
    retry=retry_if_exception_type(requests.exceptions.RequestException),
    reraise=False,
)
def _get_json(url: str, params: dict, headers: dict = None) -> Optional[Dict]:
    """Make a GET request and return JSON, with retry logic."""
    try:
        resp = requests.get(
            url,
            params=params,
            headers=headers or {},
            timeout=settings.request_timeout_seconds,
        )
        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.Timeout:
        logger.warning(f"Timeout: {url}")
        raise
    except requests.exceptions.HTTPError as e:
        status = e.response.status_code
        if status == 429:
            logger.warning(f"Rate limit hit: {url} — backing off")
            raise   # tenacity will retry with backoff
        elif status in (401, 403):
            logger.error(f"Auth error {status}: {url} — check API key")
            return None  # Don't retry auth failures
        raise
    except Exception as e:
        logger.warning(f"API request error: {e}")
        raise


# ── Domain query mapping ─────────────────────────────────────
# Each domain maps to a search query sent to news APIs.
DOMAIN_QUERIES: Dict[str, str] = {
    "finance":      "finance OR economy OR stock market OR inflation OR RBI OR Fed Reserve",
    "geopolitics":  "geopolitics OR war OR election OR diplomacy OR sanctions OR NATO",
    "technology":   "technology OR AI OR artificial intelligence OR startup OR cybersecurity",
    "health":       "health OR pandemic OR vaccine OR WHO OR disease outbreak OR FDA",
    "supply_chain": "supply chain OR logistics OR shipping OR trade OR tariff OR port",
}


# ── NewsAPI ──────────────────────────────────────────────────

class NewsAPIFetcher:
    """
    Wraps https://newsapi.org/v2/everything
    Docs: https://newsapi.org/docs/endpoints/everything
    Free tier: 100 requests/day, 1 month back.
    """
    BASE_URL = "https://newsapi.org/v2/everything"

    def __init__(self, api_key: str = None):
        self.api_key = api_key or settings.newsapi_key

    def _is_configured(self) -> bool:
        return bool(self.api_key and self.api_key != "your_newsapi_key_here")

    def fetch(
        self,
        query: str,
        domain: str,
        max_articles: int = None,
        from_hours_ago: int = 24,
    ) -> List[RawArticle]:
        if not self._is_configured():
            logger.warning("[NewsAPI] API key not configured — skipping.")
            return []

        max_articles = max_articles or settings.max_articles_per_source
        from_dt = (datetime.now(timezone.utc) - timedelta(hours=from_hours_ago)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )

        params = {
            "q":          query,
            "from":       from_dt,
            "sortBy":     "publishedAt",
            "language":   "en",
            "pageSize":   min(max_articles, 100),
            "apiKey":     self.api_key,
        }

        data = _get_json(self.BASE_URL, params)
        if not data or data.get("status") != "ok":
            logger.error(f"[NewsAPI] Bad response: {data}")
            return []

        articles = []
        for item in data.get("articles", []):
            title  = (item.get("title") or "").strip()
            body   = (item.get("content") or item.get("description") or "").strip()
            url    = item.get("url", "")
            source = item.get("source", {}).get("name", "NewsAPI")

            if not title or title == "[Removed]":
                continue

            articles.append(RawArticle(
                title=title,
                body=body,
                url=url,
                source_name=source,
                source_type=SourceType.NEWS_API,
                domain=Domain(domain),
                published_at=normalize_timestamp(item.get("publishedAt")),
                language="en",
                raw_metadata={"author": item.get("author", ""), "query": query},
            ))

        logger.info(f"[NewsAPI] Fetched {len(articles)} articles for query: '{query[:40]}'")
        return articles

    def fetch_all_domains(self, max_per_domain: int = 25) -> List[RawArticle]:
        all_articles = []
        for domain, query in DOMAIN_QUERIES.items():
            try:
                articles = self.fetch(query, domain, max_articles=max_per_domain)
                all_articles.extend(articles)
            except Exception as e:
                logger.error(f"[NewsAPI] Error fetching domain '{domain}': {e}")
        logger.info(f"[NewsAPI] Total fetched: {len(all_articles)}")
        return all_articles


# ── GNews API ────────────────────────────────────────────────

class GNewsFetcher:
    """
    Wraps https://gnews.io/api/v4/search
    Docs: https://gnews.io/docs/
    Free tier: 100 requests/day.
    """
    BASE_URL = "https://gnews.io/api/v4/search"

    def __init__(self, api_key: str = None):
        self.api_key = api_key or settings.gnews_api_key

    def _is_configured(self) -> bool:
        return bool(self.api_key and self.api_key != "your_gnews_key_here")

    def fetch(self, query: str, domain: str, max_articles: int = 10) -> List[RawArticle]:
        if not self._is_configured():
            logger.warning("[GNews] API key not configured — skipping.")
            return []

        params = {
            "q":        query,
            "lang":     "en",
            "max":      min(max_articles, 10),  # GNews free cap
            "apikey":   self.api_key,
            "sortby":   "publishedAt",
        }

        data = _get_json(self.BASE_URL, params)
        if not data:
            return []

        articles = []
        for item in data.get("articles", []):
            title = (item.get("title") or "").strip()
            body  = (item.get("content") or item.get("description") or "").strip()
            url   = item.get("url", "")
            source = item.get("source", {}).get("name", "GNews")

            if not title:
                continue

            articles.append(RawArticle(
                title=title,
                body=body,
                url=url,
                source_name=source,
                source_type=SourceType.GNEWS,
                domain=Domain(domain),
                published_at=normalize_timestamp(item.get("publishedAt")),
                language="en",
                raw_metadata={"query": query},
            ))

        logger.info(f"[GNews] Fetched {len(articles)} for '{query[:40]}'")
        return articles

    def fetch_all_domains(self, max_per_domain: int = 10) -> List[RawArticle]:
        all_articles = []
        for domain, query in DOMAIN_QUERIES.items():
            try:
                articles = self.fetch(query, domain, max_articles=max_per_domain)
                all_articles.extend(articles)
            except Exception as e:
                logger.error(f"[GNews] Error fetching domain '{domain}': {e}")
        logger.info(f"[GNews] Total fetched: {len(all_articles)}")
        return all_articles


# ── NewsData.io ──────────────────────────────────────────────

class NewsDataFetcher:
    """
    Wraps https://newsdata.io/api/1/news
    Docs: https://newsdata.io/documentation
    Free tier: 200 credits/day.
    """
    BASE_URL = "https://newsdata.io/api/1/news"

    def __init__(self, api_key: str = None):
        self.api_key = api_key or settings.newsdata_api_key

    def _is_configured(self) -> bool:
        return bool(self.api_key and self.api_key != "your_newsdata_key_here")

    def fetch(self, query: str, domain: str, max_articles: int = 10) -> List[RawArticle]:
        if not self._is_configured():
            logger.warning("[NewsData] API key not configured — skipping.")
            return []

        params = {
            "apikey":   self.api_key,
            "q":        query,
            "language": "en",
            "size":     min(max_articles, 10),
        }

        data = _get_json(self.BASE_URL, params)
        if not data or data.get("status") != "success":
            logger.error(f"[NewsData] Bad response status")
            return []

        articles = []
        for item in data.get("results", []):
            title  = (item.get("title") or "").strip()
            body   = (item.get("content") or item.get("description") or "").strip()
            url    = item.get("link", "")
            source = item.get("source_id", "NewsData")

            if not title:
                continue

            articles.append(RawArticle(
                title=title,
                body=body,
                url=url,
                source_name=source,
                source_type=SourceType.NEWSDATA,
                domain=Domain(domain),
                published_at=normalize_timestamp(item.get("pubDate")),
                language=item.get("language", "en"),
                raw_metadata={
                    "keywords": item.get("keywords", []),
                    "query":    query,
                },
            ))

        logger.info(f"[NewsData] Fetched {len(articles)} for '{query[:40]}'")
        return articles

    def fetch_all_domains(self, max_per_domain: int = 10) -> List[RawArticle]:
        all_articles = []
        for domain, query in DOMAIN_QUERIES.items():
            try:
                articles = self.fetch(query, domain, max_articles=max_per_domain)
                all_articles.extend(articles)
            except Exception as e:
                logger.error(f"[NewsData] Error fetching domain '{domain}': {e}")
        logger.info(f"[NewsData] Total fetched: {len(all_articles)}")
        return all_articles


# ── Unified API fetcher entry point ──────────────────────────

def fetch_all_apis(max_per_domain: int = 25) -> List[RawArticle]:
    """Fetch from all three news APIs and combine results."""
    all_articles: List[RawArticle] = []

    for FetcherClass in [NewsAPIFetcher, GNewsFetcher, NewsDataFetcher]:
        try:
            fetcher  = FetcherClass()
            articles = fetcher.fetch_all_domains(max_per_domain=max_per_domain)
            all_articles.extend(articles)
        except Exception as e:
            logger.error(f"Error in {FetcherClass.__name__}: {e}")

    logger.info(f"[APIs] Combined total: {len(all_articles)} articles")
    return all_articles
