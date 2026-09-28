"""Run ingestion followed by Agents 1-4 as one MAPNAI pipeline."""

import argparse
import json

from ingestion_pipeline import run_ingestion_pipeline
from pipeline import run_agent_pipeline


def run_full_pipeline(limit: int = 100) -> dict:
    ingestion_stats = run_ingestion_pipeline()
    runs = []
    previous_pending = None
    while True:
        stats = run_agent_pipeline(limit=limit)
        runs.append(stats)
        pending_keys = (
            "remaining_pending_ner",
            "remaining_pending_classification",
            "remaining_pending_summarization",
            "remaining_pending_risk_scoring",
        )
        pending_state = tuple(stats.get(key, 0) for key in pending_keys)
        if (
            stats.get("pending_found", 0) == 0
            or stats.get("articles_ok", 0) == 0
            or pending_state == previous_pending
        ):
            break
        previous_pending = pending_state

    total_keys = (
        "articles_ok",
        "failed",
        "ner_processed",
        "classified",
        "summarized",
        "risk_scored",
        "out_of_scope",
        "total_entities",
    )
    agent_stats = {
        key: sum(run.get(key, 0) for run in runs)
        for key in total_keys
    }
    agent_stats["batches"] = len(runs)
    agent_stats["remaining_pending"] = {
        key: runs[-1].get(key, 0) for key in pending_keys
    }
    agent_stats["errors"] = [error for run in runs for error in run.get("errors", [])]
    return {
        "ingestion": ingestion_stats.model_dump(),
        "agents": agent_stats,
    }


def check_setup() -> bool:
    """Print what the pipeline can use on this machine. Returns False if a required
    piece is missing (MongoDB or the Agent 2 classifier)."""
    from pathlib import Path
    from config.settings import settings

    root = Path(__file__).resolve().parent
    results = []   # (required, ok, label, hint)

    results.append((False, (root / ".env").exists(), ".env file",
                    "copy .env.example to .env and fill it in"))

    try:
        from pymongo import MongoClient
        from storage.mongo_store import mask_uri
        mongo_label = f"MongoDB at {mask_uri(settings.mongo_uri)}"
        # Atlas needs longer than a local server: DNS SRV lookup + TLS handshake
        MongoClient(settings.mongo_uri, serverSelectionTimeoutMS=10000).admin.command("ping")
        results.append((True, True, mongo_label, ""))
    except Exception as e:
        reason = str(e).split(", Timeout:")[0].split(", Topology")[0][:300]
        results.append((True, False, mongo_label, f"fix MONGO_URI in .env ({e.__class__.__name__}: {reason})"))

    try:
        from neo4j import GraphDatabase
        with GraphDatabase.driver(settings.neo4j_uri, auth=(settings.neo4j_user, settings.neo4j_password)) as driver:
            driver.verify_connectivity()
        results.append((False, True, f"Neo4j at {settings.neo4j_uri}", ""))
    except Exception as e:
        results.append((False, False, f"Neo4j at {settings.neo4j_uri}", f"optional — graph writes will be skipped ({e.__class__.__name__})"))

    results.append((False, (root / "models" / "mapnai-ner-bert" / "config.json").exists(),
                    "Agent 1 BERT NER model (models/mapnai-ner-bert)",
                    "without it Agent 1 reuses spaCy entities from ingestion"))
    results.append((True, (root / "models" / "classifier" / "label_config.json").exists(),
                    "Agent 2 classifier (models/classifier)",
                    "hf download satvik4577/mapnai-classifier --local-dir models/classifier"))

    try:
        import spacy
        spacy.load("en_core_web_sm")
        results.append((False, True, "spaCy en_core_web_sm (ingestion entities)", ""))
    except Exception:
        results.append((False, False, "spaCy en_core_web_sm (ingestion entities)",
                        "python -m spacy download en_core_web_sm"))

    has_groq = bool(settings.groq_api_key)
    results.append((False, has_groq, "GROQ_API_KEY (Agent 4 risk, Agent 5 answers)",
                    "Agent 4 leaves articles pending; Agent 3 uses extractive summaries"))

    ok = True
    for required, passed, label, hint in results:
        mark = "OK  " if passed else ("FAIL" if required else "WARN")
        print(f"[{mark}] {label}" + ("" if passed else f" -> {hint}"))
        ok = ok and (passed or not required)
    print(f"\nAgent 3 summarizer backend: {settings.summarizer_backend}")
    print("Ready to run." if ok else "Fix the FAIL items before running.")
    return ok


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run MAPNAI news ingestion and Agents 1-4."
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=100,
        help="Articles per agent batch until queues drain (default: 100).",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Only check services, models and keys; don't run the pipeline.",
    )
    args = parser.parse_args()
    if args.check:
        raise SystemExit(0 if check_setup() else 1)
    print(json.dumps(run_full_pipeline(limit=args.limit), indent=2, default=str))


if __name__ == "__main__":
    main()