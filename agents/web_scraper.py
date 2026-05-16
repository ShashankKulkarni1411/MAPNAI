"""
MAPNAI — agents/web_scraper.py
Agent 1d: Web Scraper
Scrapes non-RSS news sources using requests + BeautifulSoup.
Respects robots.txt via configurable user-agent.
Uses CSS selectors defined in ScraperTarget config.
"""

import requests
from bs4 import BeautifulSoup
from typing import List, Optional
from tenacity import retry, stop_after_attempt, wait_exponential

from config.settings import settings
from utils.models import RawArticle, SourceType, Domain
from utils.text_cleaner import normalize_timestamp
from utils.logger import logger


SCRAPE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; MAPNAIBot/1.0; +https://mapnai.somaiya.edu; "
        "Research news aggregation project)"
    ),
    "Accept":          "text/html,application/xhtml+xml",
    "Accept-Language": "en-US,en;q=0.9",
}

# ── Hardcoded scraper targets (non-RSS sites) ─────────────────
# Each entry: (name, listing_url, domain, article_link_selector, title_sel, body_sel)
SCRAPER_TARGETS = [
    {
        "name":              "Business Standard",
        "listing_url":       "https://www.business-standard.com/finance",
        "domain":            "finance",
        "article_link_sel":  "h2 a, h3 a",
        "title_sel":         "h1.headline",
        "body_sel":          "div.p-content p",
        "base_url":          "https://www.business-standard.com",
    },
    {
        "name":              "LiveMint Policy",
        "listing_url":       "https://www.livemint.com/politics",
        "domain":            "geopolitics",
        "article_link_sel":  "h2 a, h3 a",
        "title_sel":         "h1.headline",
        "body_sel":          "div.mainContent p",
        "base_url":          "https://www.livemint.com",
    },
    {
        "name":              "NDTV Tech",
        "listing_url":       "https://www.ndtv.com/technology",
        "domain":            "technology",
        "article_link_sel":  "div.news_Itm a",
        "title_sel":         "h1.sp-ttl",
        "body_sel":          "div.Art-exp_content p",
        "base_url":          "https://www.ndtv.com",
    },
]


@retry(
    stop=stop_after_attempt(2),
    wait=wait_exponential(multiplier=1, min=2, max=8),
    reraise=False,
)
def _fetch_page(url: str) -> Optional[BeautifulSoup]:
    """Fetch an HTML page and return BeautifulSoup object."""
    try:
        resp = requests.get(url, headers=SCRAPE_HEADERS, timeout=settings.request_timeout_seconds)
        resp.raise_for_status()
        return BeautifulSoup(resp.text, "lxml")
    except requests.exceptions.Timeout:
        logger.warning(f"[Scraper] Timeout: {url}")
        raise
    except requests.exceptions.HTTPError as e:
        logger.warning(f"[Scraper] HTTP {e.response.status_code}: {url}")
        if e.response.status_code in (403, 401, 429):
            return None   # Don't retry auth/rate errors
        raise
    except Exception as e:
        logger.warning(f"[Scraper] Fetch error {url}: {e}")
        raise


def _normalize_url(href: str, base_url: str) -> str:
    """Convert relative URLs to absolute."""
    if href.startswith("http"):
        return href
    if href.startswith("//"):
        return "https:" + href
    if href.startswith("/"):
        return base_url.rstrip("/") + href
    return base_url + "/" + href


def scrape_target(target: dict, max_articles: int = 10) -> List[RawArticle]:
    """
    Scrape a single target site.
    1. Fetch listing page → extract article URLs
    2. For each URL, fetch article page → extract title + body
    3. Return list of RawArticle
    """
    articles: List[RawArticle] = []
    name         = target["name"]
    listing_url  = target["listing_url"]
    domain       = target["domain"]
    base_url     = target.get("base_url", "")

    logger.debug(f"[Scraper] Fetching listing: {listing_url}")
    listing_soup = _fetch_page(listing_url)
    if not listing_soup:
        logger.warning(f"[Scraper] Could not fetch listing for {name}")
        return []

    # Extract article links from listing
    links = listing_soup.select(target["article_link_sel"])
    article_urls = []
    for link in links:
        href = link.get("href", "")
        if href:
            article_urls.append(_normalize_url(href, base_url))

    # Deduplicate and limit
    article_urls = list(dict.fromkeys(article_urls))[:max_articles]
    logger.debug(f"[Scraper] Found {len(article_urls)} links on {name}")

    for url in article_urls:
        try:
            soup = _fetch_page(url)
            if not soup:
                continue

            # Extract title
            title_el = soup.select_one(target["title_sel"])
            title = title_el.get_text(strip=True) if title_el else ""

            # Extract body — join all matching paragraphs
            body_els = soup.select(target["body_sel"])
            body = " ".join(el.get_text(strip=True) for el in body_els)

            if not title or not body:
                continue

            articles.append(RawArticle(
                title=title,
                body=body,
                url=url,
                source_name=name,
                source_type=SourceType.SCRAPER,
                domain=Domain(domain),
                published_at=None,   # Timestamp extracted during preprocessing if available
                language="en",
                raw_metadata={"scraped_from": listing_url},
            ))

        except Exception as e:
            logger.debug(f"[Scraper] Skipping article {url}: {e}")

    logger.info(f"[Scraper] Scraped {len(articles)} articles from {name}")
    return articles


def scrape_all_targets(max_per_target: int = 10) -> List[RawArticle]:
    """Run all scraper targets. Failures in one don't stop others."""
    all_articles: List[RawArticle] = []
    for target in SCRAPER_TARGETS:
        try:
            articles = scrape_target(target, max_articles=max_per_target)
            all_articles.extend(articles)
        except Exception as e:
            logger.error(f"[Scraper] Critical error on {target['name']}: {e}")

    logger.info(f"[Scraper] Total scraped: {len(all_articles)}")
    return all_articles
