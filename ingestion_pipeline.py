"""
MAPNAI — ingestion_pipeline.py
Master Ingestion Pipeline Orchestrator
Coordinates all fetchers, preprocessing, enrichment, and 3-way storage.
This is the single entry point for one complete ingestion run.

Pipeline flow:
  1. Fetch from RSS + APIs + Bluesky Firehose + Scrapers (parallel)
  2. Preprocess batch (clean, dedupe, classify, normalize)
  3. Store to MongoDB + FAISS + Neo4j (simultaneous)
  4. Log run statistics

Agents 1–4 run separately after ingestion:
  python pipeline.py             # NER → Classifier → Summarizer → Risk Scorer

Usage:
  python ingestion_pipeline.py              # single run
  python ingestion_pipeline.py --schedule   # runs every N minutes
"""

import time
import argparse
from datetime import datetime, timezone
from typing import List
from concurrent.futures import ThreadPoolExecutor, as_completed

from agents.rss_fetcher       import fetch_all_rss_sources
from agents.api_fetcher        import fetch_all_apis
from agents.bluesky_fetcher    import fetch_all_bluesky
from agents.web_scraper        import scrape_all_targets
from agents.preprocessing_agent import PreprocessingAgent

from storage.mongo_store  import MongoStore
from storage.faiss_store  import FAISSStore
from storage.neo4j_store  import Neo4jStore

from utils.models  import RawArticle, ProcessedArticle, IngestionRunStats
from utils.logger  import logger
from config.settings import settings


# ── Storage singletons (initialized once per process) ────────
_mongo_store:  MongoStore  = None
_faiss_store:  FAISSStore  = None
_neo4j_store:  Neo4jStore  = None


def _get_mongo() -> MongoStore:
    global _mongo_store
    if _mongo_store is None:
        _mongo_store = MongoStore()
    return _mongo_store


def _get_faiss() -> FAISSStore:
    global _faiss_store
    if _faiss_store is None:
        _faiss_store = FAISSStore()
    return _faiss_store


def _get_neo4j() -> Neo4jStore:
    global _neo4j_store
    if _neo4j_store is None:
        _neo4j_store = Neo4jStore()
    return _neo4j_store


# ── Phase 1: Fetch all sources in parallel ───────────────────

def _fetch_phase(max_per_source: int = None) -> List[RawArticle]:
    """
    Run all fetchers concurrently using ThreadPoolExecutor.
    Returns combined raw article list.
    Failures in individual fetchers don't abort the run.
    """
    max_per_source = max_per_source or settings.max_articles_per_source
    all_raw: List[RawArticle] = []

    fetch_tasks = {
        "RSS":     lambda: fetch_all_rss_sources(max_per_source=max_per_source),
        "APIs":    lambda: fetch_all_apis(max_per_domain=max_per_source),
        "Bluesky": lambda: fetch_all_bluesky(),
        "Scraper": lambda: scrape_all_targets(max_per_target=10),
    }

    with ThreadPoolExecutor(max_workers=4, thread_name_prefix="Fetcher") as executor:
        future_to_name = {
            executor.submit(fn): name
            for name, fn in fetch_tasks.items()
        }

        for future in as_completed(future_to_name):
            name = future_to_name[future]
            try:
                articles = future.result()
                logger.info(f"[Pipeline] {name} completed: {len(articles)} raw articles")
                all_raw.extend(articles)
            except Exception as e:
                logger.error(f"[Pipeline] {name} fetcher failed: {e}")

    logger.info(f"[Pipeline] FETCH PHASE COMPLETE — Total raw: {len(all_raw)}")
    return all_raw


# ── Phase 2: Preprocess ──────────────────────────────────────

def _preprocess_phase(
    raw_articles: List[RawArticle],
    existing_hashes: List[str],
) -> List[ProcessedArticle]:
    """
    Run preprocessing on all raw articles.
    Seeds deduplicator with existing DB hashes for cross-run deduplication.
    """
    agent = PreprocessingAgent(existing_hashes=existing_hashes)
    processed = agent.process_batch(raw_articles)

    stats = agent.get_stats()
    logger.info(
        f"[Pipeline] PREPROCESS PHASE COMPLETE — "
        f"Processed={stats['processed']} | "
        f"Dupes dropped={stats['duplicates']} | "
        f"Quality dropped={stats['failed_quality']}"
    )
    return processed


# ── Phase 3: Store (3-way simultaneous) ──────────────────────

def _store_phase(articles: List[ProcessedArticle]) -> dict:
    """
    Write processed articles to MongoDB, FAISS, and Neo4j simultaneously.
    Each store is independent — failure in one doesn't block others.
    """
    if not articles:
        logger.info("[Pipeline] No articles to store.")
        return {"mongo": 0, "faiss": 0, "neo4j": 0}

    store_results = {"mongo": 0, "faiss": 0, "neo4j": 0}

    # ── MongoDB ──────────────────────────────────────────────
    try:
        mongo = _get_mongo()
        result = mongo.upsert_articles(articles)
        store_results["mongo"] = result.get("inserted", 0) + result.get("updated", 0)
    except Exception as e:
        logger.error(f"[Pipeline] MongoDB store failed: {e}")

    # ── FAISS ─────────────────────────────────────────────────
    try:
        faiss = _get_faiss()
        added = faiss.add_articles(articles)
        faiss.save()   # persist to disk
        store_results["faiss"] = added
    except Exception as e:
        logger.error(f"[Pipeline] FAISS store failed: {e}")

    # ── Neo4j (article graph only; entities added by Agent 1 / pipeline.py) ──
    try:
        neo4j = _get_neo4j()
        neo4j.upsert_articles(articles)
        store_results["neo4j"] = len(articles)
    except Exception as e:
        logger.error(f"[Pipeline] Neo4j store failed: {e}")

    logger.info(
        f"[Pipeline] STORE PHASE COMPLETE — "
        f"MongoDB={store_results['mongo']} | "
        f"FAISS={store_results['faiss']} | "
        f"Neo4j={store_results['neo4j']}"
    )
    return store_results


# ── Main Pipeline ─────────────────────────────────────────────

def run_ingestion_pipeline() -> IngestionRunStats:
    """
    Execute one complete ingestion run.
    Returns IngestionRunStats object with full metrics.
    """
    run_stats = IngestionRunStats()
    run_stats.started_at = datetime.now(timezone.utc)

    logger.info("=" * 60)
    logger.info(f"[Pipeline] INGESTION RUN STARTED — {run_stats.run_id[:8]}")
    logger.info("=" * 60)

    # ── Phase 0: Seed deduplicator from DB ───────────────────
    try:
        mongo = _get_mongo()
        existing_hashes = mongo.get_existing_hashes()
    except Exception as e:
        logger.warning(f"[Pipeline] Could not seed deduplicator (DB unavailable): {e}")
        existing_hashes = []

    # ── Phase 1: Fetch ────────────────────────────────────────
    try:
        raw_articles = _fetch_phase()
        run_stats.total_fetched = len(raw_articles)

        # Log per-source breakdown
        source_counts: dict = {}
        for art in raw_articles:
            key = f"[{art.source_type.value.upper()}] {art.source_name}"
            source_counts[key] = source_counts.get(key, 0) + 1
        run_stats.source_breakdown = source_counts

    except Exception as e:
        logger.error(f"[Pipeline] Fetch phase failed: {e}")
        run_stats.errors.append(f"fetch:{e}")
        raw_articles = []

    # ── Phase 2: Preprocess ──────────────────────────────────
    try:
        processed = _preprocess_phase(raw_articles, existing_hashes)
        run_stats.total_cleaned    = len(processed)
        run_stats.total_duplicates = (
            run_stats.total_fetched - len(processed)
        )
    except Exception as e:
        logger.error(f"[Pipeline] Preprocess phase failed: {e}")
        run_stats.errors.append(f"preprocess:{e}")
        processed = []

    # ── Phase 3: Store (NER runs later via pipeline.py / Agent 1) ─
    try:
        store_results = _store_phase(processed)
        run_stats.total_stored = store_results.get("mongo", 0)
    except Exception as e:
        logger.error(f"[Pipeline] Store phase failed: {e}")
        run_stats.errors.append(f"store:{e}")

    # ── Finalize ─────────────────────────────────────────────
    run_stats.completed_at = datetime.now(timezone.utc)
    duration = (run_stats.completed_at - run_stats.started_at).total_seconds()

    logger.info("=" * 60)
    logger.info(f"[Pipeline] RUN COMPLETE — {run_stats.log_summary()}")
    logger.info(f"[Pipeline] Duration: {duration:.1f}s")
    logger.info("=" * 60)

    # Log run stats to MongoDB (best-effort)
    try:
        _get_mongo().log_ingestion_run({
            **run_stats.model_dump(),
            "duration_seconds": duration,
        })
    except Exception:
        pass

    return run_stats


# ── Scheduler ────────────────────────────────────────────────

def run_with_schedule(interval_minutes: int = None):
    """
    Run ingestion pipeline on a fixed interval using `schedule` library.
    Runs once immediately, then on interval.
    """
    import schedule

    interval = interval_minutes or settings.ingestion_interval_minutes
    logger.info(f"[Scheduler] Starting scheduled ingestion every {interval} minutes.")

    # Run once immediately on start
    run_ingestion_pipeline()

    schedule.every(interval).minutes.do(run_ingestion_pipeline)

    while True:
        schedule.run_pending()
        time.sleep(30)   # check every 30 seconds


# ── CLI ──────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="MAPNAI Ingestion Pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python ingestion_pipeline.py                   # single run
  python ingestion_pipeline.py --schedule        # run every 30 min (default)
  python ingestion_pipeline.py --schedule --interval 60  # run every 60 min
        """,
    )
    parser.add_argument(
        "--schedule",
        action="store_true",
        help="Run on a recurring schedule instead of single run",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=None,
        help="Interval in minutes for scheduled runs (default from .env)",
    )

    args = parser.parse_args()

    if args.schedule:
        run_with_schedule(interval_minutes=args.interval)
    else:
        stats = run_ingestion_pipeline()
        print(f"\n✅ {stats.log_summary()}")
