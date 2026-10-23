"""
Backfill the BSON date fields recaps query on, for articles stored before ingestion wrote them:
  published_ts  the article's time: published_at, else ingested_at
  ingested_ts   ingested_at
  date_source   "published" when published_at is set, else "ingested"
published_at / ingested_at themselves are never rewritten. RSS times stored before the 2026-10 fix may be early by
the ingesting machine's UTC offset (5 h 30 m in IST, none in Docker), and which machine ingested a row isn't
recorded, so they are left as they are.

    python scripts/backfill_dates.py            # dry run: count what would change
    python scripts/backfill_dates.py --apply
"""

import argparse
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pymongo import UpdateOne  # noqa: E402

from personalization.scoring import parse_ts  # noqa: E402
from storage.mongo_store import MongoStore  # noqa: E402


def date_fields(doc: dict) -> dict:
    """The three fields for one article doc; {} when it has no usable time at all."""
    published, ingested = parse_ts(doc.get("published_at")), parse_ts(doc.get("ingested_at"))
    if not (published or ingested):
        return {}
    out = {"published_ts": published or ingested, "date_source": "published" if published else "ingested"}
    if ingested:
        out["ingested_ts"] = ingested
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true", help="write the fields (default: dry run)")
    ap.add_argument("--batch", type=int, default=1000)
    args = ap.parse_args()

    col = MongoStore().db["processed_articles"]
    query = {"$or": [{"published_ts": {"$exists": False}}, {"ingested_ts": {"$exists": False}}]}
    fields = {"_id": 0, "article_id": 1, "published_at": 1, "ingested_at": 1, "source_type": 1}
    ops, sources, unusable, written = [], Counter(), 0, 0
    for doc in col.find(query, fields):
        update = date_fields(doc)
        if not update:
            unusable += 1
            continue
        sources[(doc.get("source_type"), update["date_source"])] += 1
        ops.append(UpdateOne({"article_id": doc["article_id"]}, {"$set": update}))
        if args.apply and len(ops) >= args.batch:
            written += col.bulk_write(ops, ordered=False).modified_count
            ops = []
    if args.apply and ops:
        written += col.bulk_write(ops, ordered=False).modified_count

    total = sum(sources.values())
    print(f"{total} articles to backfill ({unusable} with no usable time, skipped)")
    for (source_type, date_source), n in sorted(sources.items(), key=lambda kv: -kv[1]):
        print(f"  {source_type or '?':<10} {date_source:<10} {n}")
    print(f"written: {written}" if args.apply else "dry run: nothing written (pass --apply)")


if __name__ == "__main__":
    main()
