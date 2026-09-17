"""
MAPNAI — test_query.py
Interactive CLI Test Interface for Agent 5 (Query Agent).

Loads the designated test articles into MongoDB and FAISS vector index,
then accepts natural language questions via command-line arguments or interactive CLI prompt.
"""

import os
import sys
import json
import time
from typing import List, Dict, Any

from agents.agent5_query import QueryAgent
from agents.query_llm import GroqQueryLLM
from agents.query_retriever import QueryRetriever
from storage.mongo_store import MongoStore
from storage.faiss_store import FAISSStore
from utils.models import ProcessedArticle, Domain, SourceType, SentimentLabel
from utils.logger import logger


# ── Seed Articles (User Specified) ───────────────────────────

TEST_ARTICLES = [
    {
        "article_id": "b1ffa832-7a8e-4a6c-9c7d-8d8e0e9f1a2b",
        "title": "Christopher Nolan's new sci-fi film stars Cillian Murphy",
        "body": "Director Christopher Nolan announced his next cinematic project today, a high-budget sci-fi thriller starring Cillian Murphy. The film is scheduled to release in summer 2027 and is expected to be a major box office hit.",
        "entities": [
            {"text": "Christopher Nolan", "label": "PERSON", "start": 9, "end": 26, "score": 1.0},
            {"text": "Cillian Murphy", "label": "PERSON", "start": 42, "end": 56, "score": 1.0}
        ],
        "source_name": "Variety",
        "source_type": "rss",
        "url": "https://variety.com/news/christopher-nolan-new-film-12345",
        "published_at": "2026-08-24T19:00:00Z",
        "ingested_at": "2026-08-24T19:15:00Z",
        "language": "en",
        "preprocess_domain": "entertainment",
        "domain": "entertainment",
        "sentiment_score": 0.6,
        "summary_short": "Christopher Nolan announced a new high-budget sci-fi thriller starring Cillian Murphy, scheduled for summer 2027.",
        "summary_long": "Director Christopher Nolan announced his next cinematic project today, a high-budget sci-fi thriller starring Cillian Murphy. The film is scheduled to release in summer 2027 and is expected to be a major box office hit.",
        "_metadata": {
            "model_used": "en_core_web_sm",
            "latency_seconds": 0.08,
            "entity_count": 2
        }
    },
    {
        "article_id": "a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11",
        "title": "Manchester United wins the Premier League match against Chelsea",
        "body": "In a thrilling match yesterday at Old Trafford, Manchester United secured a 2-1 victory over Chelsea. The winning goal was scored in the 88th minute, placing them at the top of the Premier League table.",
        "entities": [
            {"text": "Manchester United", "label": "ORG", "start": 0, "end": 17, "score": 1.0},
            {"text": "Chelsea", "label": "ORG", "start": 44, "end": 51, "score": 1.0},
            {"text": "Old Trafford", "label": "LOC", "start": 82, "end": 94, "score": 0.9}
        ],
        "source_name": "BBC Sports",
        "source_type": "rss",
        "url": "https://www.bbc.com/sport/football/12345",
        "published_at": "2026-08-24T18:00:00Z",
        "ingested_at": "2026-08-24T18:30:00Z",
        "language": "en",
        "preprocess_domain": "sports",
        "domain": "sports",
        "sentiment_score": 0.8,
        "summary_short": "Manchester United secured a 2-1 victory over Chelsea at Old Trafford with an 88th-minute winning goal.",
        "summary_long": "In a thrilling match yesterday at Old Trafford, Manchester United secured a 2-1 victory over Chelsea. The winning goal was scored in the 88th minute, placing them at the top of the Premier League table.",
        "_metadata": {
            "model_used": "en_core_web_sm",
            "latency_seconds": 0.12,
            "entity_count": 3
        }
    },
    {
        "article_id": "c2ddb741-5a6b-3c7d-9e1e-2f3a4b5c6d7e",
        "title": "Central Bank announces new monetary policy to curb inflation",
        "body": "The Federal Reserve chairman announced a 25 basis point hike in interest rates to address persistent inflation pressures. Economic analysts predict this will slow down growth in the housing market over the next quarter.",
        "entities": [
            {"text": "Federal Reserve", "label": "ORG", "start": 4, "end": 19, "score": 1.0}
        ],
        "source_name": "Wall Street Journal",
        "source_type": "rss",
        "url": "https://www.wsj.com/economy/fed-rates-hike-12345",
        "published_at": "2026-08-24T20:00:00Z",
        "ingested_at": "2026-08-24T20:10:00Z",
        "language": "en",
        "preprocess_domain": "finance",
        "domain": "finance",
        "sentiment_score": -0.2,
        "summary_short": "The Federal Reserve chairman announced a 25 basis point rate hike to tackle inflation pressures.",
        "summary_long": "The Federal Reserve chairman announced a 25 basis point hike in interest rates to address persistent inflation pressures. Economic analysts predict this will slow down growth in the housing market over the next quarter.",
        "_metadata": {
            "model_used": "en_core_web_sm",
            "latency_seconds": 0.05,
            "entity_count": 1
        }
    }
]


# ── Environment & DB Setup ───────────────────────────────────

def setup_database():
    """Initializes and seeds MongoDB and FAISS with the test articles."""
    mongo_store = MongoStore()
    use_mock = False

    try:
        mongo_store.db.command("ping")
    except Exception as e:
        logger.warning(f"[Setup] Live MongoDB unreachable ({e}). Using mongomock for test isolation.")
        import mongomock
        mock_client = mongomock.MongoClient()
        mongo_store._client = mock_client
        mongo_store._db = mock_client["mapnai_test"]
        use_mock = True

    # Use isolated FAISS vector store
    test_faiss_idx = "./data/test_faiss_index"
    test_faiss_meta = "./data/test_faiss_metadata.pkl"
    faiss_store = FAISSStore(index_path=test_faiss_idx, metadata_path=test_faiss_meta)

    # Populate MongoDB and FAISS
    col = mongo_store.db["processed_articles"]
    processed_objs = []

    for art in TEST_ARTICLES:
        doc = art.copy()
        col.update_one({"article_id": art["article_id"]}, {"$set": doc}, upsert=True)

        domain_str = art.get("preprocess_domain") or art.get("domain", "general")
        domain_enum = Domain.GENERAL
        try:
            domain_enum = Domain(domain_str)
        except ValueError:
            domain_enum = Domain.GENERAL

        p_art = ProcessedArticle(
            article_id=art["article_id"],
            title=art["title"],
            body=art["body"],
            source_name=art.get("source_name", "TestFeed"),
            source_type=SourceType.RSS,
            domain=domain_enum,
            summary_short=art.get("summary_short") or art["body"][:200],
            summary_long=art.get("summary_long") or art["body"],
            entities=art["entities"],
            sentiment_score=art.get("sentiment_score", 0.0),
        )
        processed_objs.append(p_art)

    faiss_store.add_articles(processed_objs)
    logger.info(f"[Setup] Database loaded with {len(TEST_ARTICLES)} test articles.")

    return mongo_store, faiss_store


def cleanup_database(mongo_store: MongoStore, faiss_store: FAISSStore):
    """Cleans up articles from MongoDB and removes temporary FAISS files."""
    try:
        test_ids = [a["article_id"] for a in TEST_ARTICLES]
        mongo_store.db["processed_articles"].delete_many({"article_id": {"$in": test_ids}})
        logger.info("[Cleanup] Cleaned up test articles from MongoDB.")
    except Exception as e:
        logger.warning(f"[Cleanup] Cleanup warning: {e}")

    for path in [faiss_store.index_path, faiss_store.metadata_path]:
        if "test_faiss" in path and os.path.exists(path):
            try:
                os.remove(path)
            except Exception:
                pass


# ── Interactive CLI Loop ─────────────────────────────────────

def run_cli():
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass

    print("\n" + "=" * 80)
    print("  MAPNAI -- AGENT 5 (QUERY AGENT) CLI INTERFACE")
    print("=" * 80)
    print("\nLoading knowledge base into MongoDB and FAISS...")

    mongo_store, faiss_store = setup_database()
    retriever = QueryRetriever(mongo_store=mongo_store, faiss_store=faiss_store)
    agent = QueryAgent(llm=GroqQueryLLM(), retriever=retriever, mongo_store=mongo_store, faiss_store=faiss_store)

    print("\nKnowledge Base Loaded:")
    for idx, a in enumerate(TEST_ARTICLES, 1):
        domain = a.get("preprocess_domain") or a.get("domain")
        print(f"  [{idx}] [{domain.upper()}] {a['title']}")

    print("\n" + "-" * 80)

    try:
        # Check if query was passed via command line arguments
        if len(sys.argv) > 1:
            cli_query = " ".join(sys.argv[1:]).strip()
            print(f"\nQUERY: \"{cli_query}\"\n")
            response = agent.process(cli_query)
            print(json.dumps(response, indent=2))
            return

        # Interactive loop
        print("Enter your questions below. Type 'exit', 'quit', or 'q' to stop.")
        print("-" * 80 + "\n")

        # Check if running in an interactive terminal
        if not sys.stdin.isatty():
            # Example non-interactive sample queries
            sample_queries = [
                "What did Christopher Nolan announce?",
                "Who won the match between Manchester United and Chelsea?",
                "What did the Federal Reserve do regarding interest rates?",
            ]
            for q in sample_queries:
                print(f"\n> Query: {q}")
                res = agent.process(q)
                print(json.dumps(res, indent=2))
            return

        while True:
            try:
                user_input = input("\nQuery: ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\nExiting CLI...")
                break

            if not user_input:
                continue

            if user_input.lower() in {"exit", "quit", "q"}:
                print("Exiting...")
                break

            print("\n" + "-" * 40 + " AGENT RESPONSE " + "-" * 40)
            res = agent.process(user_input)
            print(json.dumps(res, indent=2))
            print("-" * 96)

    finally:
        cleanup_database(mongo_store, faiss_store)
        print("\nKnowledge base unloaded. Session finished.\n")


if __name__ == "__main__":
    run_cli()
