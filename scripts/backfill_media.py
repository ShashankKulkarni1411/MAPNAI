"""
Backfill article images (`media`) for articles stored before ingestion kept images.

Scope: articles published in the last --window-h hours (default PERS_CLUSTER_WINDOW_H) that have no `media`
field at all. Their feed metadata is gone, so each article page is read once (og:image / JSON-LD /
twitter:image / in-article images, utils/image_extractor.py) — the same lookup ingestion's media phase does.
An article whose page has no usable image gets `media: null`, so reruns skip it; rerunning continues where
the last run stopped.

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

from agents.media_agent import fetch_page_images  # noqa: E402
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

    col = MongoStore().db["processed_articles"]
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=args.window_h)
    coarse = (cutoff - timedelta(days=1)).date().isoformat()
    docs = [d for d in col.find({"media": {"$exists": False}, "published_at": {"$gte": coarse},
                                 "url": {"$regex": "^https?://"}, "source_type": {"$nin": ["bluesky"]}},
                                {"_id": 0, "article_id": 1, "url": 1, "published_at": 1})
            if (ts := parse_ts(d.get("published_at"))) and cutoff <= ts <= now]
    docs.sort(key=lambda d: d["published_at"], reverse=True)
    docs = docs[: args.max]
    print(f"{len(docs)} articles in the last {args.window_h} h without media")
    if args.dry_run or not docs:
        return

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        found = list(pool.map(lambda d: fetch_page_images(d["url"], settings.media_lookup_timeout_seconds), docs))
    media = [build_media(c) for c in found]
    col.bulk_write([UpdateOne({"article_id": d["article_id"]}, {"$set": {"media": m}}) for d, m in zip(docs, media)],
                   ordered=False)
    with_img = sum(1 for m in media if m)
    logger.info(f"[BackfillMedia] {with_img}/{len(docs)} articles got an image")
    print(f"done: {with_img}/{len(docs)} with an image")


if __name__ == "__main__":
    main()
