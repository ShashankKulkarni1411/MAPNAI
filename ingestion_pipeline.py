"""
MAPNAI — ingestion_pipeline.py
Master Ingestion Pipeline Orchestrator
Coordinates all fetchers, preprocessing, enrichment, and 3-way storage.
This is the single entry point for one complete ingestion run.

Pipeline flow:
  1. Fetch from RSS + APIs + Bluesky Firehose + Scrapers (parallel)
  2. Preprocess batch (clean, dedupe, classify, normalize, rank feed images)
  2b. Article images: page lookup (og:image / JSON-LD) for articles the feed gave no good image
  3. Enrich with entities (spaCy NER; Agent 1 re-runs NER with fine-tuned BERT)
  3b. Fallback images: Wikipedia image of the main entity for articles still without one
  4. Store to MongoDB + FAISS + Neo4j (simultaneous)
  4b. Sightings: duplicates from other outlets are recorded on the article they duplicate
  5. Log run statistics

Phases 2-4b are ingest_batch(), shared with the continuous stream (stream_worker.py), so a batch run and the
stream produce identical articles.

Usage:
  python ingestion_pipeline.py              # single run
  python ingestion_pipeline.py --schedule   # runs every N minutes
"""

import time
import argparse
from datetime import datetime, timezone
from typing import Dict, List, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed

from agents.rss_fetcher       import fetch_all_rss_sources
from agents.api_fetcher        import fetch_all_apis
from agents.bluesky_fetcher    import fetch_all_bluesky
from agents.web_scraper        import scrape_all_targets
from agents.preprocessing_agent import PreprocessingAgent
from agents.enrichment_agent   import EnrichmentAgent
from agents.media_agent        import MediaAgent

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
        "Scraper": lambda: scrape_all_targets(max_per_target=10),
    }
    if settings.bluesky_ingest_articles:   # raw firehose posts as articles: off by default (mostly noise)
        fetch_tasks["Bluesky"] = lambda: fetch_all_bluesky()

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
    existing_hashes: List,
    agent: Optional[PreprocessingAgent] = None,
) -> List[ProcessedArticle]:
    """
    Run preprocessing on all raw articles.
    Seeds deduplicator with existing DB hashes for cross-run deduplication (or uses `agent`, whose deduplicator
    may already hold them).
    """
    agent = agent or PreprocessingAgent(existing_hashes=existing_hashes)
    processed = agent.process_batch(raw_articles)

    stats = agent.get_stats()
    logger.info(
        f"[Pipeline] PREPROCESS PHASE COMPLETE — "
        f"Processed={stats['processed']} | "
        f"Dupes dropped={stats['duplicates']} | "
        f"Quality dropped={stats['failed_quality']}"
    )
    return processed


# ── Phase 2b: Article images ─────────────────────────────────

def _media_phase(articles: List[ProcessedArticle]) -> List[ProcessedArticle]:
    """Page lookup for articles without a good hero image. Failures leave articles unchanged."""
    return MediaAgent().enrich_batch(articles)


# ── Phase 3: Enrich ──────────────────────────────────────────

def _enrich_phase(articles: List[ProcessedArticle]) -> List[ProcessedArticle]:
    """Run NER enrichment on all processed articles."""
    agent = EnrichmentAgent()
    return agent.enrich_batch(articles)


def _image_fallback_phase(articles: List[ProcessedArticle]) -> List[ProcessedArticle]:
    """Wikipedia image of the main entity for articles still without one. Failures leave articles unchanged."""
    mongo = _get_mongo()
    return MediaAgent().fill_missing(articles, mongo.db if mongo.is_available() else None)


# ── Phase 4: Store (3-way simultaneous) ──────────────────────

def _store_phase(articles: List[ProcessedArticle], save_faiss: bool = True) -> dict:
    """
    Write processed articles to MongoDB, FAISS, and Neo4j simultaneously.
    Each store is independent — failure in one doesn't block others.
    save_faiss=False leaves the FAISS index in memory (the stream worker saves it periodically).
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
        if save_faiss:
            faiss.save()   # persist to disk
        store_results["faiss"] = added
    except Exception as e:
        logger.error(f"[Pipeline] FAISS store failed: {e}")

    # ── Neo4j ─────────────────────────────────────────────────
    try:
        neo4j = _get_neo4j()
        neo4j.upsert_articles(articles)
        neo4j.upsert_entities(articles)   # also builds co-occurrence graph
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


# ── Phases 2-4b as one call (batch run and stream) ───────────

def ingest_batch(
    raw_articles: List[RawArticle],
    existing_hashes: Optional[List] = None,
    deduplicator=None,
    save_faiss: bool = True,
) -> Dict:
    """
    Preprocess → article images → NER enrichment → fallback images → store (Mongo + FAISS + Neo4j) → sightings.
    existing_hashes seeds a new deduplicator; `deduplicator` is a long-lived one (the stream worker's). Each phase
    is non-fatal, as in the batch run. Returns {input, cleaned, duplicates, quality_failed, stored, store,
    sightings, article_ids, errors}.
    """
    out: Dict = {"input": len(raw_articles), "cleaned": 0, "duplicates": 0, "quality_failed": 0, "stored": 0,
                 "store": {"mongo": 0, "faiss": 0, "neo4j": 0}, "sightings": 0, "article_ids": [], "errors": []}
    if not raw_articles:
        return out
    agent = PreprocessingAgent(existing_hashes=existing_hashes, deduplicator=deduplicator)
    try:
        processed = _preprocess_phase(raw_articles, [], agent=agent)
    except Exception as e:
        logger.error(f"[Pipeline] Preprocess phase failed: {e}")
        out["errors"].append(f"preprocess:{e}")
        processed = []
    stats = agent.get_stats()
    out.update(cleaned=len(processed), duplicates=stats.get("duplicates", 0),
               quality_failed=stats.get("failed_quality", 0))

    try:
        processed = _media_phase(processed)
    except Exception as e:
        logger.warning(f"[Pipeline] Media phase warning (non-fatal): {e}")
    try:
        processed = _enrich_phase(processed)
    except Exception as e:
        logger.warning(f"[Pipeline] Enrichment phase warning (non-fatal): {e}")
        # Continue with unenriched articles
    try:
        processed = _image_fallback_phase(processed)
    except Exception as e:
        logger.warning(f"[Pipeline] Image fallback warning (non-fatal): {e}")

    try:
        store_results = _store_phase(processed, save_faiss=save_faiss)
        out["store"] = store_results
        out["stored"] = store_results.get("mongo", 0)
    except Exception as e:
        logger.error(f"[Pipeline] Store phase failed: {e}")
        out["errors"].append(f"store:{e}")
    out["article_ids"] = [a.article_id for a in processed]

    # after the store, so an original from this same batch already exists
    sightings = agent.pop_sightings()
    if sightings:
        try:
            out["sightings"] = _get_mongo().record_sightings(sightings)
        except Exception as e:
            logger.warning(f"[Pipeline] Sightings not recorded (non-fatal): {e}")
    return out


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

    # ── Phase 0: MongoDB is the primary store — without it nothing reaches the agents
    mongo = _get_mongo()
    if not mongo.is_available():
        run_stats.errors.append("mongo:unavailable")
        run_stats.completed_at = datetime.now(timezone.utc)
        logger.error("[Pipeline] Aborting ingestion run: MongoDB is unavailable.")
        return run_stats

    # ── Seed deduplicator from DB: recent fingerprints, with their article and outlet (for sightings)
    try:
        existing_hashes = mongo.get_recent_hash_docs(settings.dedup_seed_days)
    except Exception as e:
        logger.warning(f"[Pipeline] Could not seed deduplicator: {e}")
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

    # ── Phases 2-4b: preprocess, images, enrich, store, sightings ─
    batch = ingest_batch(raw_articles, existing_hashes=existing_hashes)
    run_stats.total_cleaned    = batch["cleaned"]
    run_stats.total_duplicates = run_stats.total_fetched - batch["cleaned"]
    run_stats.total_stored     = batch["stored"]
    run_stats.errors.extend(batch["errors"])
    if batch["sightings"]:
        logger.info(f"[Pipeline] Recorded {batch['sightings']} sightings from other outlets")

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
