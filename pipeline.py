"""
MAPNAI — pipeline.py
Agent 1 Pipeline: NER & Entity Extraction

Runs AFTER the ingestion layer. Fetches articles from MongoDB
(processed_articles) that ingestion_pipeline.py stored, runs the NER agent,
and writes entities back to MongoDB + Neo4j using the ingestion storage layer.

Flow:
  1. python ingestion_pipeline.py   → fetch, preprocess, store (no NER)
  2. python pipeline.py             → NER on pending articles from MongoDB

Usage:
  python pipeline.py                    # process all pending (up to 100)
  python pipeline.py --limit 50         # process at most 50 articles
  python pipeline.py --schedule 15      # re-run every 15 minutes
"""

import argparse
import json
import time
from typing import Dict

from agents.ner_agent import NERAgent
from storage.mongo_store import MongoStore
from utils.logger import logger


def run_ner_pipeline(limit: int = 100, skip: int = 0) -> Dict:
    """
    Fetch articles pending NER from MongoDB and process them through Agent 1.
    Returns run statistics.
    """
    mongo = MongoStore()
    agent = NERAgent(mongo_store=mongo)

    pending = mongo.get_articles_pending_ner(limit=limit, skip=skip)
    stats = {
        "pending_found": len(pending),
        "processed": 0,
        "failed": 0,
        "total_entities": 0,
    }

    if not pending:
        logger.info("[NER Pipeline] No articles pending NER. Run ingestion first.")
        agent.close()
        return stats

    logger.info(f"[NER Pipeline] Processing {len(pending)} articles from ingestion store...")

    for doc in pending:
        try:
            result = agent.process(doc)
            stats["processed"] += 1
            stats["total_entities"] += result["_metadata"]["entity_count"]
        except Exception as e:
            stats["failed"] += 1
            aid = doc.get("article_id", "?")
            logger.error(f"[NER Pipeline] Failed on {aid[:8]}: {e}")

    remaining = mongo.count_articles_pending_ner()
    stats["remaining_pending"] = remaining

    logger.info(
        f"[NER Pipeline] Done — processed={stats['processed']} | "
        f"failed={stats['failed']} | "
        f"entities={stats['total_entities']} | "
        f"still_pending={remaining}"
    )

    agent.close()
    return stats


def run_ner_with_schedule(interval_minutes: int = 15, batch_limit: int = 100):
    """Poll for new ingested articles and run NER on each interval."""
    import schedule

    logger.info(
        f"[NER Scheduler] Running Agent 1 every {interval_minutes} min "
        f"(batch limit {batch_limit})."
    )

    run_ner_pipeline(limit=batch_limit)

    schedule.every(interval_minutes).minutes.do(
        lambda: run_ner_pipeline(limit=batch_limit)
    )

    while True:
        schedule.run_pending()
        time.sleep(30)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="MAPNAI Agent 1 — NER pipeline (post-ingestion)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=100,
        help="Max articles to process in one run (default: 100)",
    )
    parser.add_argument(
        "--skip",
        type=int,
        default=0,
        help="Skip N articles in the pending queue",
    )
    parser.add_argument(
        "--schedule",
        type=int,
        nargs="?",
        const=15,
        metavar="MINUTES",
        help="Run on a recurring schedule (default: every 15 minutes)",
    )

    args = parser.parse_args()

    if args.schedule is not None:
        run_ner_with_schedule(interval_minutes=args.schedule, batch_limit=args.limit)
    else:
        stats = run_ner_pipeline(limit=args.limit, skip=args.skip)
        print(f"\n✅ NER pipeline complete: {json.dumps(stats, indent=2)}")
