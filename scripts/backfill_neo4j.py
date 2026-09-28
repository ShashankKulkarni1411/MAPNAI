"""
MAPNAI — scripts/backfill_neo4j.py
Replay processed_articles from MongoDB into Neo4j through the existing
Neo4jStore.upsert_articles / upsert_entities (Article, Entity, Domain, Source nodes;
BELONGS_TO, PUBLISHED_BY, MENTIONS, MENTIONED_WITH edges). No new schema.

Batches are packed so each stays under Neo4jStore's silent 5000-pair co-occurrence cap.
Not idempotent (frequency / MENTIONED_WITH.count are incremented), so it refuses to run
on a graph that already has :Article nodes unless --force is given.

Usage: python -m scripts.backfill_neo4j [--batch 20] [--limit N] [--force] [--dry-run]
"""

import argparse
import sys
import time
from pathlib import Path
from typing import Dict, List, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from storage.mongo_store import MongoStore          # noqa: E402
from storage.neo4j_store import Neo4jStore          # noqa: E402
from utils.logger import logger                     # noqa: E402
from utils.models import ProcessedArticle           # noqa: E402

PAIR_CAP = 5000   # Neo4jStore._build_cooccurrence truncates beyond this per call


def _pairs(n: int) -> int:
    return n * (n - 1) // 2


def load_articles(mongo: MongoStore, limit: int) -> Tuple[List[ProcessedArticle], Dict[str, int]]:
    skipped: Dict[str, int] = {}
    articles: List[ProcessedArticle] = []
    cursor = mongo.db["processed_articles"].find({}, {"_id": 0}).limit(limit)
    for doc in cursor:
        # MERGE on a null name/type fails the whole UNWIND batch, so clean entities first.
        doc["entities"] = [
            {**e, "type": e.get("type") or "MISC"}
            for e in (doc.get("entities") or [])
            if isinstance(e, dict) and str(e.get("name") or "").strip()
        ]
        for key in ("keywords", "topic_tags"):
            if doc.get(key) is None:
                doc[key] = []
        try:
            articles.append(ProcessedArticle(**doc))
        except Exception as e:
            reason = type(e).__name__
            skipped[reason] = skipped.get(reason, 0) + 1
    return articles, skipped


def make_batches(articles: List[ProcessedArticle], batch_size: int) -> List[List[ProcessedArticle]]:
    batches, current, pairs = [], [], 0
    for article in articles:
        p = _pairs(len(article.entities))
        if p > PAIR_CAP:
            logger.warning(
                f"[Backfill] {article.article_id} has {len(article.entities)} entities "
                f"({p} pairs) — co-occurrence will be truncated"
            )
        if current and (len(current) >= batch_size or pairs + p > PAIR_CAP):
            batches.append(current)
            current, pairs = [], 0
        current.append(article)
        pairs += p
    if current:
        batches.append(current)
    return batches


def main():
    parser = argparse.ArgumentParser(description="Backfill Neo4j from MongoDB processed_articles")
    parser.add_argument("--batch", type=int, default=20)
    parser.add_argument("--limit", type=int, default=0, help="0 = all articles")
    parser.add_argument("--force", action="store_true", help="run even if :Article nodes exist")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    mongo, neo4j = MongoStore(), Neo4jStore()
    articles, skipped = load_articles(mongo, args.limit)
    batches = make_batches(articles, args.batch)
    total_pairs = sum(_pairs(len(a.entities)) for a in articles)
    print(f"Loaded {len(articles)} articles (skipped {skipped or 0}), "
          f"{sum(len(a.entities) for a in articles)} mentions, {total_pairs} pairs, "
          f"{len(batches)} batches")
    if args.dry_run:
        return

    with neo4j.driver.session() as session:
        existing = session.run("MATCH (a:Article) RETURN count(a) AS c").single()["c"]
    if existing and not args.force:
        print(f"Graph already has {existing} :Article nodes — rerun with --force to add again.")
        sys.exit(1)

    started = time.time()
    for i, batch in enumerate(batches, 1):
        neo4j.upsert_articles(batch)
        neo4j.upsert_entities(batch)
        if i % 10 == 0 or i == len(batches):
            print(f"  batch {i}/{len(batches)} ({time.time() - started:.0f}s)")

    stats = neo4j.get_graph_stats()
    print(f"Done in {time.time() - started:.0f}s. Graph stats: {stats}")
    neo4j.close()
    mongo.close()


if __name__ == "__main__":
    main()
