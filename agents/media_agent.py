"""
MAPNAI — agents/media_agent.py
Article image lookup (ingestion, after preprocessing so only new, non-duplicate articles are fetched).

Fetchers already attach the images their feed or API exposes (preprocessing ranks them into
`media`). Many feeds carry none or only a ~240 px thumbnail, so for those articles this agent reads
the article page once and adds its og:image / JSON-LD / twitter:image / in-article images, then
re-ranks. Pages are fetched in parallel with a short timeout and a per-run cap; any failure leaves
the article as it was — an article without an image is stored normally.
"""

from concurrent.futures import ThreadPoolExecutor
from typing import List, Optional

import requests

from agents.web_scraper import SCRAPE_HEADERS
from config.settings import settings
from utils.image_extractor import from_html, merge, needs_page_lookup
from utils.logger import logger
from utils.models import ArticleMedia, ProcessedArticle, SourceType

_MAX_BYTES = 1_500_000            # og/JSON-LD sit in <head>; never read a whole huge page
_SKIP_TYPES = {SourceType.BLUESKY, SourceType.SCRAPER}   # posts have no page; the scraper read the page already


def fetch_page_images(url: str, timeout: int) -> List[dict]:
    """Image candidates from one article page; [] on any error or non-HTML answer."""
    try:
        with requests.get(url, headers=SCRAPE_HEADERS, timeout=timeout, stream=True) as resp:
            if resp.status_code != 200 or "html" not in resp.headers.get("Content-Type", "html"):
                return []
            chunks, size = [], 0
            for chunk in resp.iter_content(64 * 1024):
                chunks.append(chunk)
                size += len(chunk)
                if size >= _MAX_BYTES:
                    break
            html = b"".join(chunks).decode(resp.encoding or "utf-8", errors="replace")
        return from_html(html, resp.url or url)
    except Exception as e:
        logger.debug(f"[Media] page lookup failed for {url}: {type(e).__name__}")
        return []


class MediaAgent:
    def __init__(self, workers: Optional[int] = None, timeout: Optional[int] = None, max_lookups: Optional[int] = None):
        self.workers = workers or settings.media_lookup_workers
        self.timeout = timeout or settings.media_lookup_timeout_seconds
        self.max_lookups = settings.media_lookup_max if max_lookups is None else max_lookups
        self.stats = {"looked_up": 0, "improved": 0, "with_image": 0, "without_image": 0}

    def enrich_batch(self, articles: List[ProcessedArticle]) -> List[ProcessedArticle]:
        todo = [a for a in articles
                if a.url and a.source_type not in _SKIP_TYPES
                and needs_page_lookup(a.media.model_dump() if a.media else None)][: self.max_lookups]
        if todo and settings.media_page_lookup:
            with ThreadPoolExecutor(max_workers=self.workers, thread_name_prefix="Media") as pool:
                found = list(pool.map(lambda a: fetch_page_images(a.url, self.timeout), todo))
            for article, extra in zip(todo, found):
                before = article.media.primary_image.url if article.media and article.media.primary_image else None
                media = merge(article.media.model_dump() if article.media else None, extra)
                article.media = ArticleMedia(**media) if media else None
                after = article.media.primary_image.url if article.media and article.media.primary_image else None
                self.stats["improved"] += int(after is not None and after != before)
            self.stats["looked_up"] = len(todo)
        self.stats["with_image"] = sum(1 for a in articles if a.media and a.media.primary_image)
        self.stats["without_image"] = len(articles) - self.stats["with_image"]
        logger.info(f"[Media] Page lookups={self.stats['looked_up']} | improved={self.stats['improved']} | "
                    f"with image={self.stats['with_image']}/{len(articles)}")
        return articles
