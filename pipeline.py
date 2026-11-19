"""
MAPNAI — pipeline.py
Agents 1–4 Pipeline: NER → Classification → Summarization → Risk Scoring

Runs AFTER the ingestion layer. Reads articles from MongoDB (processed_articles)
and FAISS (similar-article context), then chains:

  Agent 1 (NER)          → entities → MongoDB + Neo4j
  Agent 2 (Classifier)   → domain/category/sentiment → MongoDB
  Agent 3 (Summarizer)   → summary_short/summary_long → MongoDB
  Agent 4 (Risk Scorer)  → risk_score/confidence/recommendation → MongoDB

Flow:
  1. python ingestion_pipeline.py   → fetch, preprocess, store
  2. python pipeline.py             → Agents 1–4 on pending articles

Usage:
  python pipeline.py                         # full chain, up to 100 articles
  python pipeline.py --limit 10              # process at most 10
  python pipeline.py --agents 1              # NER only
  python pipeline.py --agents 2,3            # classify + summarize (already NER'd)
  python pipeline.py --agents 4              # risk score only (already summarized)
  python pipeline.py --article-id <uuid>     # one article through selected agents
  python pipeline.py --schedule 15           # poll every 15 minutes
"""

import argparse
import json
import time
from typing import Dict, List, Optional, Set

from agents.ner_agent import NERAgent
from agents.agent2_classifier import EventClassifierAgent
from agents.agent3_summarizer import SummarizationAgent
from agents.agent4_risk_scorer import RiskScoringAgent
from agents.pipeline_bridge import (
    mongo_doc_to_agent1_payload,
    mongo_doc_to_agent4_payload,
    enrich_with_similar_articles,
)
from config.settings import settings
from storage.mongo_store import MongoStore
from storage.faiss_store import FAISSStore
from utils.logger import logger


def _parse_agents(agents_arg: Optional[str]) -> Set[int]:
    if not agents_arg:
        return {1, 2, 3, 4}
    selected = set()
    for part in agents_arg.split(","):
        part = part.strip()
        if part in ("1", "2", "3", "4"):
            selected.add(int(part))
    return selected or {1, 2, 3, 4}


def _agent3_payload_from_doc(doc: dict, upstream: Optional[dict] = None) -> dict:
    """Merge MongoDB classification fields into the Agent 3 input contract."""
    base = upstream or mongo_doc_to_agent1_payload(doc)
    return {
        **base,
        "domain": (upstream or doc).get("domain", doc.get("domain", "general")),
        "category": (upstream or doc).get("category", doc.get("category", "Other")),
        "sentiment": float(
            (upstream or doc).get(
                "sentiment",
                doc.get("sentiment_score", 0.0),
            )
        ),
        "urgency_flag": (upstream or doc).get(
            "urgency_flag", doc.get("urgency_flag", False)
        ),
        "classification_confidence": (upstream or doc).get(
            "classification_confidence",
            doc.get("classification_confidence", 0.0),
        ),
        "taxonomy_version": (upstream or doc).get(
            "taxonomy_version", doc.get("taxonomy_version", "1.0.0")
        ),
    }


def _process_one_article(
    doc: dict,
    *,
    ner_agent: Optional[NERAgent],
    classifier: Optional[EventClassifierAgent],
    summarizer: Optional[SummarizationAgent],
    risk_scorer: Optional[RiskScoringAgent],
    faiss_store: Optional[FAISSStore],
    agents: Set[int],
    stats: Dict,
    mongo: Optional[MongoStore] = None,
) -> None:
    article_id = doc.get("article_id", "?")
    payload: Optional[dict] = None

    try:
        # ── Agent 1: NER ──────────────────────────────────────
        if 1 in agents:
            if not doc.get("ner_processed"):
                ner_result = ner_agent.process(doc)
                stats["ner_processed"] += 1
                stats["total_entities"] += ner_result["_metadata"]["entity_count"]
                payload = mongo_doc_to_agent1_payload(doc, ner_result)
            else:
                payload = mongo_doc_to_agent1_payload(doc)
                logger.debug(f"[Pipeline] Skipping NER — already done for {article_id[:8]}")
        else:
            payload = mongo_doc_to_agent1_payload(doc)

        if faiss_store is not None:
            payload = enrich_with_similar_articles(payload, faiss_store)

        # ── Agent 2: Classification ─────────────────────────
        if 2 in agents:
            if not doc.get("classification_processed"):
                payload = classifier.process_article(payload)
                stats["classified"] += 1
            else:
                logger.debug(
                    f"[Pipeline] Skipping classification — already done for {article_id[:8]}"
                )
                payload = {**payload, **{
                    k: doc[k]
                    for k in (
                        "domain", "category", "urgency_flag",
                        "classification_confidence", "taxonomy_version",
                        "in_scope", "out_of_scope_reason",
                    )
                    if k in doc
                }}
                payload["sentiment"] = float(doc.get("sentiment_score", 0.0))

        # Off-topic / low-confidence articles stop here (no LLM calls wasted on them)
        if payload.get("in_scope", doc.get("in_scope")) is False:
            stats["out_of_scope"] += 1
            stats["articles_ok"] += 1
            logger.debug(
                f"[Pipeline] {article_id[:8]} out of scope "
                f"({payload.get('out_of_scope_reason', doc.get('out_of_scope_reason'))}) — skipping Agents 3-4"
            )
            return

        # ── Agent 3: Summarization ────────────────────────────
        if 3 in agents:
            if not doc.get("summarization_processed"):
                agent3_input = _agent3_payload_from_doc(doc, upstream=payload)
                if faiss_store is not None:
                    agent3_input = enrich_with_similar_articles(
                        agent3_input, faiss_store
                    )
                payload = summarizer.process_article(agent3_input)
                stats["summarized"] += 1
            else:
                logger.debug(
                    f"[Pipeline] Skipping summarization — already done for {article_id[:8]}"
                )
                payload = {**payload, **{
                    k: doc[k]
                    for k in ("summary_short", "summary_long")
                    if k in doc
                }}

        # ── Agent 4: Risk Scoring ─────────────────────────────
        if 4 in agents:
            shared = _shared_risk(doc, mongo) if not doc.get("risk_processed") else None
            if shared and mongo.update_article_risk(article_id, shared):
                stats["risk_shared"] = stats.get("risk_shared", 0) + 1
                logger.debug(f"[Pipeline] Risk for {article_id[:8]} shared from {shared['risk_shared_from'][:8]}")
            elif not doc.get("risk_processed"):
                agent4_input = mongo_doc_to_agent4_payload(doc, upstream=payload)
                payload = risk_scorer.process_article(agent4_input)
                if payload.pop("risk_skipped", False):
                    stats["risk_skipped"] += 1
                else:
                    stats["risk_scored"] += 1
            else:
                logger.debug(
                    f"[Pipeline] Skipping risk scoring — already done for {article_id[:8]}"
                )

        stats["articles_ok"] += 1

    except Exception as e:
        stats["failed"] += 1
        logger.error(f"[Pipeline] Failed on {article_id[:8]}: {e}")
        stats["errors"].append({"article_id": article_id, "error": str(e)})


_SHARED_RISK_FIELDS = ("risk_score", "risk_confidence", "risk_level", "risk_reasoning", "action_recommendation",
                       "risk_model")


def _shared_risk(doc: dict, mongo: Optional[MongoStore]) -> Optional[dict]:
    """
    Risk sharing (continousexplanation.md §5.6): when another article of the same event cluster already has a
    model-made Agent 4 score, reuse it instead of another LLM call. None when sharing is off, the article has no
    cluster yet, or no cluster-mate is scored.
    """
    if mongo is None or not settings.risk_share_in_cluster or not doc.get("cluster_id"):
        return None
    sibling = mongo.find_cluster_risk(doc["cluster_id"], doc.get("article_id"))
    if not sibling or sibling.get("risk_score") is None:
        return None
    return {**{k: sibling.get(k) for k in _SHARED_RISK_FIELDS if k in sibling},
            "risk_shared_from": sibling["article_id"]}


class AgentPool:
    """
    Agents 1–4, the FAISS store and the Mongo store, loaded once and reused by every run_agent_pipeline call
    (the stream worker keeps one for its lifetime instead of reloading the models per run). Agents are created on
    first use. The FAISS store can be the ingestion store, so similar-article context sees the newest vectors.
    """

    def __init__(self, mongo: Optional[MongoStore] = None, faiss_store: Optional[FAISSStore] = None):
        self.mongo = mongo or MongoStore()
        self.faiss_store = faiss_store
        self._faiss_tried = faiss_store is not None
        self.ner_agent = self.classifier = self.summarizer = self.risk_scorer = None

    def ensure(self, agents: Set[int]) -> "AgentPool":
        if 1 in agents and self.ner_agent is None:
            self.ner_agent = NERAgent(mongo_store=self.mongo)
        if 2 in agents and self.classifier is None:
            self.classifier = EventClassifierAgent(mongo_store=self.mongo)
        if 3 in agents and self.summarizer is None:
            self.summarizer = SummarizationAgent(mongo_store=self.mongo)
        if 4 in agents and self.risk_scorer is None:
            self.risk_scorer = RiskScoringAgent(mongo_store=self.mongo)
        if (2 in agents or 3 in agents) and not self._faiss_tried:
            self._faiss_tried = True
            self.faiss_store = _load_faiss()
        return self

    def close(self) -> None:
        _close_all(self.ner_agent, self.classifier, self.summarizer, self.risk_scorer, self.mongo)
        self.ner_agent = self.classifier = self.summarizer = self.risk_scorer = None


def _load_faiss() -> Optional[FAISSStore]:
    try:
        store = FAISSStore()
        logger.info(f"[Pipeline] FAISS loaded — {store.total_vectors} vectors")
        return store
    except Exception as e:
        logger.warning(f"[Pipeline] FAISS unavailable (continuing without similar articles): {e}")
        return None


def run_agent_pipeline(
    limit: int = 100,
    skip: int = 0,
    agents: Optional[Set[int]] = None,
    article_id: Optional[str] = None,
    pool: Optional[AgentPool] = None,
    article_ids: Optional[List[str]] = None,
) -> Dict:
    """
    Run Agents 1–4 on articles from MongoDB (+ FAISS context).
    pool: reuse loaded agents (nothing is loaded or closed here). article_ids: exactly these articles (the stream
    worker's newly stored ones) instead of the pending queues.
    """
    agents = agents or {1, 2, 3, 4}
    mongo = pool.mongo if pool else MongoStore()
    if not mongo.is_available():
        # Agents 1-4 read their work queue from MongoDB; nothing to do without it
        return {"agents_run": sorted(agents), "pending_found": 0, "articles_ok": 0,
                "errors": [{"error": "MongoDB unavailable"}]}
    if pool:
        pool.ensure(agents)
        faiss_store = pool.faiss_store if (2 in agents or 3 in agents) else None
        ner_agent = pool.ner_agent if 1 in agents else None
        classifier = pool.classifier if 2 in agents else None
        summarizer = pool.summarizer if 3 in agents else None
        risk_scorer = pool.risk_scorer if 4 in agents else None
    else:
        faiss_store = _load_faiss() if (2 in agents or 3 in agents) else None
        ner_agent = NERAgent(mongo_store=mongo) if 1 in agents else None
        classifier = (
            EventClassifierAgent(mongo_store=mongo) if 2 in agents else None
        )
        summarizer = (
            SummarizationAgent(mongo_store=mongo) if 3 in agents else None
        )
        risk_scorer = (
            RiskScoringAgent(mongo_store=mongo) if 4 in agents else None
        )

    def finish():
        if not pool:
            _close_all(ner_agent, classifier, summarizer, risk_scorer, mongo)

    stats = {
        "agents_run": sorted(agents),
        "pending_found": 0,
        "articles_ok": 0,
        "failed": 0,
        "ner_processed": 0,
        "classified": 0,
        "summarized": 0,
        "risk_scored": 0,
        "risk_skipped": 0,
        "risk_shared": 0,
        "out_of_scope": 0,
        "total_entities": 0,
        "errors": [],
    }

    if article_id:
        doc = mongo.get_article_by_id(article_id)
        if not doc:
            logger.error(f"[Pipeline] No article found: {article_id}")
            finish()
            return stats
        docs = [doc]
    elif article_ids is not None:
        docs = mongo.get_articles_by_ids(article_ids)
    else:
        docs = _collect_pending_docs(mongo, agents, limit, skip)

    stats["pending_found"] = len(docs)

    if not docs:
        logger.info(
            "[Pipeline] No articles to process for agents "
            f"{sorted(agents)}. Run ingestion first."
        )
        finish()
        return stats

    logger.info(
        f"[Pipeline] Processing {len(docs)} articles | agents={sorted(agents)}"
    )

    for doc in docs:
        _process_one_article(
            doc,
            ner_agent=ner_agent,
            classifier=classifier,
            summarizer=summarizer,
            risk_scorer=risk_scorer,
            faiss_store=faiss_store,
            agents=agents,
            stats=stats,
            mongo=mongo,
        )

    stats["remaining_pending_ner"] = mongo.count_articles_pending_ner()
    stats["remaining_pending_classification"] = (
        mongo.count_articles_pending_classification()
    )
    stats["remaining_pending_summarization"] = (
        mongo.count_articles_pending_summarization()
    )
    stats["remaining_pending_risk_scoring"] = (
        mongo.count_articles_pending_risk_scoring()
    )

    logger.info(
        f"[Pipeline] Done — ok={stats['articles_ok']} | failed={stats['failed']} | "
        f"ner={stats['ner_processed']} | classified={stats['classified']} | "
        f"summarized={stats['summarized']} | risk_scored={stats['risk_scored']} | "
        f"risk_skipped={stats['risk_skipped']} | risk_shared={stats['risk_shared']} | "
        f"out_of_scope={stats['out_of_scope']}"
    )

    finish()
    return stats


def _collect_pending_docs(
    mongo: MongoStore,
    agents: Set[int],
    limit: int,
    skip: int,
) -> List[dict]:
    """Choose the earliest non-empty queue among the selected agents."""
    pending_getters = {
        1: mongo.get_articles_pending_ner,
        2: mongo.get_articles_pending_classification,
        3: mongo.get_articles_pending_summarization,
        4: mongo.get_articles_pending_risk_scoring,
    }
    for agent_number in sorted(agents):
        docs = pending_getters[agent_number](limit=limit, skip=skip)
        if docs:
            return docs
    return []


def _close_all(ner_agent, classifier, summarizer, risk_scorer, mongo):
    if ner_agent:
        ner_agent.close()
    if classifier:
        classifier.close()
    if summarizer:
        summarizer.close()
    if risk_scorer:
        risk_scorer.close()
    mongo.close()


def run_agent_pipeline_with_schedule(
    interval_minutes: int = 15,
    batch_limit: int = 100,
    agents: Optional[Set[int]] = None,
):
    """Poll for new ingested articles and run the agent chain on each interval."""
    import schedule

    agents = agents or {1, 2, 3, 4}
    logger.info(
        f"[Pipeline Scheduler] Agents {sorted(agents)} every "
        f"{interval_minutes} min (batch limit {batch_limit})."
    )

    run_agent_pipeline(limit=batch_limit, agents=agents)

    schedule.every(interval_minutes).minutes.do(
        lambda: run_agent_pipeline(limit=batch_limit, agents=agents)
    )

    while True:
        schedule.run_pending()
        time.sleep(30)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="MAPNAI Agents 1–4 pipeline (post-ingestion)",
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
        "--agents",
        type=str,
        default=None,
        help="Comma-separated agents to run: 1,2,3,4 (default: all)",
    )
    parser.add_argument(
        "--article-id",
        type=str,
        default=None,
        help="Process a single article by article_id",
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
    selected_agents = _parse_agents(args.agents)

    if args.schedule is not None:
        run_agent_pipeline_with_schedule(
            interval_minutes=args.schedule,
            batch_limit=args.limit,
            agents=selected_agents,
        )
    else:
        stats = run_agent_pipeline(
            limit=args.limit,
            skip=args.skip,
            agents=selected_agents,
            article_id=args.article_id,
        )
        print(f"\n✅ Agent pipeline complete: {json.dumps(stats, indent=2)}")
