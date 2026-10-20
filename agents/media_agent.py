"""
MAPNAI — agents/media_agent.py
Article image lookup (ingestion, after preprocessing so only new, non-duplicate articles are fetched).

Fetchers already attach the images their feed or API exposes (preprocessing ranks them into
`media`). Many feeds carry none or only a ~240 px thumbnail, so for those articles this agent reads
the article page once and adds its og:image / JSON-LD / twitter:image / in-article images, then
re-ranks. Pages are fetched in parallel with a short timeout and a per-run cap; any failure leaves
the article as it was — an article without an image is stored normally.

After NER, articles that still have no image get a fallback (fill_missing): the free Wikipedia image of
their main named entity (utils/image_fallback.py), cached per entity name in Mongo `entity_images`.
"""

from concurrent.futures import ThreadPoolExecutor
from typing import Dict, List, Optional

import requests
from pymongo import UpdateOne

from agents.web_scraper import SCRAPE_HEADERS
from config.settings import settings
from utils.image_extractor import build_media, from_html, merge, needs_page_lookup
from utils.image_fallback import fallback_image, pick_entities, resolve
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


# ── Entity image cache (Mongo `entity_images`: {_id: name, hit: {page, extract, image} | None}) ──

def load_entity_cache(db, names) -> Dict:
    if db is None or not names:
        return {}
    try:
        return {d["_id"]: d.get("hit") for d in db["entity_images"].find({"_id": {"$in": list(names)}})}
    except Exception as e:
        logger.debug(f"[Media] entity image cache read failed: {e}")
        return {}


def save_entity_cache(db, cache: Dict, known: Dict) -> None:
    new = [UpdateOne({"_id": k}, {"$set": {"hit": v}}, upsert=True) for k, v in cache.items() if k not in known]
    if db is None or not new:
        return
    try:
        db["entity_images"].bulk_write(new, ordered=False)
    except Exception as e:
        logger.debug(f"[Media] entity image cache write failed: {e}")


def fallback_media(items: List[Dict], db=None) -> List[Optional[Dict]]:
    """items: [{title, text, entities}] → a `media` dict (Wikipedia image) or None for each."""
    names = {e["name"] for it in items for e in pick_entities(it["title"], it["entities"])}
    known = load_entity_cache(db, {n.lower() for n in names})
    cache = dict(known)
    resolve(names, cache)
    save_entity_cache(db, cache, known)
    found = [fallback_image(it["title"], it["text"], it["entities"], cache) for it in items]
    return [build_media([img]) if img else None for img in found]


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

    def fill_missing(self, articles: List[ProcessedArticle], db=None) -> List[ProcessedArticle]:
        """Fallback image for articles still without one (needs entities, so runs after NER)."""
        todo = [a for a in articles if not (a.media and a.media.primary_image) and a.entities]
        if not todo or not settings.media_fallback:
            return articles
        media = fallback_media([{"title": a.title, "text": a.summary_short or a.body[:600], "entities": a.entities}
                                for a in todo], db)
        for article, m in zip(todo, media):
            if m:
                article.media = ArticleMedia(**m)
        filled = sum(1 for m in media if m)
        self.stats["fallback"] = filled
        logger.info(f"[Media] Fallback images={filled}/{len(todo)} articles without a publisher image")
        return articles
