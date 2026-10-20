"""
Backfill article images (`media`) for articles stored before ingestion kept images.

Scope: articles published in the last --window-h hours (default PERS_CLUSTER_WINDOW_H) without an image:
  - no `media` field at all: their feed metadata is gone, so each article page is read once (og:image / JSON-LD /
    twitter:image / in-article images, utils/image_extractor.py) — the same lookup ingestion's media phase does
  - still no image after that (or `media: null` from earlier runs): the Wikipedia image of the article's main
    entity (utils/image_fallback.py), as ingestion's fallback phase does
Every article handled gets `media_fallback_tried: true` (and `media: null` when nothing was found), so reruns
skip it and continue where the last run stopped.

    python scripts/backfill_media.py --dry-run          # count only
    python scripts/backfill_media.py [--window-h 48] [--max 500] [--workers 8]
"""

import argparse
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pymongo import UpdateOne  # noqa: E402

from agents.media_agent import fallback_media, fetch_page_images  # noqa: E402
from config.personalization import pers_settings  # noqa: E402
from config.settings import settings  # noqa: E402
from personalization.scoring import parse_ts  # noqa: E402
from storage.mongo_store import MongoStore  # noqa: E402
from utils.image_extractor import build_media  # noqa: E402
from utils.logger import logger  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--window-h", type=int, default=pers_settings.cand_window_h)
    ap.add_argument("--max", type=int, default=500)
    ap.add_argument("--workers", type=int, default=settings.media_lookup_workers)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    db = MongoStore().db
    col = db["processed_articles"]
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=args.window_h)
    coarse = (cutoff - timedelta(days=1)).date().isoformat()
    query = {"published_at": {"$gte": coarse}, "url": {"$regex": "^https?://"}, "source_type": {"$nin": ["bluesky"]},
             "media.primary_image": None, "media_fallback_tried": {"$ne": True}}
    fields = {"_id": 0, "article_id": 1, "url": 1, "published_at": 1, "title": 1, "summary_short": 1, "body": 1,
              "entities": 1, "media": 1}
    docs = [d for d in col.find(query, fields) if (ts := parse_ts(d.get("published_at"))) and cutoff <= ts <= now]
    docs.sort(key=lambda d: d["published_at"], reverse=True)
    docs = docs[: args.max]
    pages = [d for d in docs if "media" not in d]
    print(f"{len(docs)} articles in the last {args.window_h} h without an image ({len(pages)} never page-checked)")
    if args.dry_run or not docs:
        return

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        found = list(pool.map(lambda d: fetch_page_images(d["url"], settings.media_lookup_timeout_seconds), pages))
    for d, cands in zip(pages, found):
        d["media"] = build_media(cands)
    from_page = sum(1 for d in pages if d["media"])

    rest = [d for d in docs if not d.get("media")]
    for d, m in zip(rest, fallback_media([{"title": d.get("title", ""),
                                           "text": d.get("summary_short") or (d.get("body") or "")[:600],
                                           "entities": d.get("entities") or []} for d in rest],
                                         db)):
        d["media"] = m
    from_fallback = sum(1 for d in rest if d["media"])

    col.bulk_write([UpdateOne({"article_id": d["article_id"]},
                              {"$set": {"media": d.get("media"), "media_fallback_tried": True}}) for d in docs],
                   ordered=False)
    with_img = from_page + from_fallback
    logger.info(f"[BackfillMedia] {with_img}/{len(docs)} articles got an image "
                f"(page {from_page}, wikipedia {from_fallback})")
    print(f"done: {with_img}/{len(docs)} with an image (page {from_page}, wikipedia {from_fallback})")

if __name__ == "__main__":
    main()
