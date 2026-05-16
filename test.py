"""
Development runner for Agent 1 (NER).
Fetches articles from MongoDB (written by ingestion_pipeline.py) — no hardcoded samples.

Usage:
  python test.py                         # process ALL pending articles
  python test.py --limit 5               # process at most 5 pending articles
  python test.py --verbose               # print full entity JSON (not just summary)
  python test.py --article-id <uuid>     # process one article by ID from DB
"""

import argparse
import json
import sys

from agents.ner_agent import NERAgent
from storage.mongo_store import MongoStore

BATCH_SIZE = 100


def main():
    parser = argparse.ArgumentParser(
        description="NER dev runner — reads from ingestion MongoDB store",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Max pending articles to process (0 = all, default)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print full NER JSON per article (default: summary only)",
    )
    parser.add_argument(
        "--article-id",
        type=str,
        help="Process a specific article by article_id from processed_articles",
    )
    args = parser.parse_args()

    mongo = MongoStore()
    agent = NERAgent(mongo_store=mongo)

    summary = {
        "processed": 0,
        "failed": 0,
        "total_entities": 0,
        "articles": [],
    }
    full_results = []

    if args.article_id:
        doc = mongo.get_article_by_id(args.article_id)
        if not doc:
            print(
                f"No article found with article_id={args.article_id!r}",
                file=sys.stderr,
            )
            print("Run ingestion first: python ingestion_pipeline.py", file=sys.stderr)
            agent.close()
            mongo.close()
            sys.exit(1)
        _process_one(doc, agent, summary, full_results)
    else:
        pending = mongo.count_articles_pending_ner()
        if pending == 0:
            total = mongo.count_articles()
            print("No articles pending NER in MongoDB.", file=sys.stderr)
            print(
                f"  processed_articles total={total} | pending_ner=0",
                file=sys.stderr,
            )
            print("Run: python ingestion_pipeline.py", file=sys.stderr)
            agent.close()
            mongo.close()
            sys.exit(0)

        max_count = args.limit if args.limit > 0 else pending
        processed = 0

        while processed < max_count:
            batch_limit = min(BATCH_SIZE, max_count - processed)
            batch = mongo.get_articles_pending_ner(limit=batch_limit)
            if not batch:
                break

            for doc in batch:
                _process_one(doc, agent, summary, full_results)
                processed += 1
                if processed >= max_count:
                    break

    summary["remaining_pending"] = mongo.count_articles_pending_ner()

    if args.verbose:
        payload = full_results if len(full_results) != 1 else full_results[0]
        print(json.dumps(payload, indent=2))
    else:
        print(json.dumps(summary, indent=2))

    agent.close()
    mongo.close()


def _process_one(doc, agent, summary, full_results):
    try:
        output = agent.process(doc)
        summary["processed"] += 1
        summary["total_entities"] += output["_metadata"]["entity_count"]
        summary["articles"].append({
            "article_id": output["article_id"],
            "title": doc.get("title", "")[:80],
            "entity_count": output["_metadata"]["entity_count"],
        })
        full_results.append(output)
    except Exception as e:
        summary["failed"] += 1
        summary["articles"].append({
            "article_id": doc.get("article_id", "?"),
            "error": str(e),
        })


if __name__ == "__main__":
    main()
