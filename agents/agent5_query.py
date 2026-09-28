"""
MAPNAI — agents/agent5_query.py
Agent 5: RAG-based Query Agent & Question Answering System.

Receives natural language questions and produces grounded, factual responses
citing stored article summaries from MongoDB and FAISS vector store.

Supports:
  - Automated routing (Keyword vs. Semantic retrieval)
  - Swappable modular LLM layer (GroqQueryLLM / CustomModelQueryLLM)
  - Zero-hallucination fallback for out-of-domain / missing knowledge
  - Strict JSON contract adherence for MAPNAI pipeline downstream
"""

import time
from typing import Dict, Any, List, Optional

from agents.query_llm import QueryLLM, GroqQueryLLM, CustomModelQueryLLM
from agents.query_retriever import QueryRetriever
from storage.mongo_store import MongoStore
from storage.faiss_store import FAISSStore
from utils.logger import logger


class QueryAgent:
    """
    Main Agent 5 class in the MAPNAI pipeline.
    Answers natural language queries using RAG over stored news summaries.
    """

    def __init__(
        self,
        llm: Optional[QueryLLM] = None,
        retriever: Optional[QueryRetriever] = None,
        mongo_store: Optional[MongoStore] = None,
        faiss_store: Optional[FAISSStore] = None,
    ):
        self.llm = llm or GroqQueryLLM()
        self.retriever = retriever or QueryRetriever(
            mongo_store=mongo_store,
            faiss_store=faiss_store,
        )
        logger.info(f"[QueryAgent] Initialized with LLM: {self.llm.__class__.__name__}")

    # ── Public API ───────────────────────────────────────────

    def process(
        self,
        query: str,
        domain_filter: Optional[str] = None,
        top_k: int = 5,
    ) -> Dict[str, Any]:
        """
        Process a natural language user question and return the standard MAPNAI response contract.

        Args:
            query: The user's natural language question.
            domain_filter: Optional domain constraint (e.g. 'finance', 'technology').
            top_k: Maximum number of source articles to retrieve.

        Returns:
            JSON-serializable dictionary following the MAPNAI Query Agent contract.
        """
        start_time = time.time()
        clean_query = query.strip() if query else ""

        if not clean_query:
            return self._build_empty_response(
                query=query,
                answer="No query provided. Please ask a valid question about news events.",
                latency=time.time() - start_time,
                route="none",
            )

        logger.info(f"[QueryAgent] Processing query: '{clean_query}'")

        # 1. Retrieve relevant articles
        articles, route_used = self.retriever.retrieve(
            query=clean_query,
            domain_filter=domain_filter,
            top_k=top_k,
        )

        logger.info(
            f"[QueryAgent] Retrieved {len(articles)} articles via route '{route_used}' "
            f"for query: '{clean_query}'"
        )

        # 2. Handle zero results fallback (strict zero-hallucination rule)
        if not articles:
            return self._build_empty_response(
                query=clean_query,
                answer="No relevant articles found in the database to answer this question.",
                latency=time.time() - start_time,
                route=route_used,
            )

        # 3. Format context string for LLM
        context_str = self._format_context(articles)

        # 4. Generate grounded answer via LLM
        answer = self.llm.generate_answer(question=clean_query, context=context_str)

        # 5. Format sources and compute confidence
        sources = [
            {
                "article_id": a["article_id"],
                "title": a["title"],
                "domain": a["domain"],
                "relevance_score": a["relevance_score"],
            }
            for a in articles
        ]

        confidence = self._calculate_confidence(articles)
        latency = time.time() - start_time
        model_name = self._resolve_model_name()

        response = {
            "query": clean_query,
            "answer": answer,
            "sources": sources,
            "retrieval_route": route_used,
            "confidence": confidence,
            "_metadata": {
                "articles_retrieved": len(articles),
                "model_used": model_name,
                "latency_seconds": round(latency, 2),
            },
        }

        logger.info(
            f"[QueryAgent] Answer generated | Route: {route_used} | "
            f"Sources: {len(sources)} | Confidence: {confidence} | Latency: {latency:.2f}s"
        )
        return response

    # ── Context Formatting ───────────────────────────────────

    def _format_context(self, articles: List[Dict[str, Any]]) -> str:
        """
        Builds a structured context block emphasizing short & long summaries and entities.
        """
        blocks = []
        for idx, art in enumerate(articles, start=1):
            art_id = art.get("article_id", f"art-{idx}")
            title = art.get("title", "Untitled")
            domain = art.get("domain", "general")
            cat = art.get("category", "")
            summary_short = art.get("summary_short", "")
            summary_long = art.get("summary_long", "")
            entities = art.get("entities", [])

            ent_names = []
            for e in entities:
                if isinstance(e, dict):
                    name = e.get("name") or e.get("text")
                    etype = e.get("type") or e.get("label", "Entity")
                    if name:
                        ent_names.append(f"{name} ({etype})")
                elif isinstance(e, str):
                    ent_names.append(e)

            ent_str = ", ".join(ent_names) if ent_names else "None listed"

            block = (
                f"[Source Article {idx} - ID: {art_id}]\n"
                f"Title: {title}\n"
                f"Domain: {domain}" + (f" | Category: {cat}\n" if cat else "\n") +
                f"Short Summary: {summary_short}\n"
                f"Detailed Summary: {summary_long}\n"
                f"Key Entities: {ent_str}\n"
            )
            blocks.append(block)

        return "\n".join(blocks)

    # ── Internal Helpers ─────────────────────────────────────

    def _calculate_confidence(self, articles: List[Dict[str, Any]]) -> float:
        """
        Calculates confidence score based on top retrieved article scores.
        """
        if not articles:
            return 0.0
        scores = [a.get("relevance_score", 0.5) for a in articles]
        top_score = max(scores)
        avg_score = sum(scores) / len(scores)
        # Weight top match heavily (70%) and general cluster match (30%)
        combined = (top_score * 0.70) + (avg_score * 0.30)
        return round(min(0.99, max(0.10, combined)), 2)

    def _resolve_model_name(self) -> str:
        """Identifies model label for metadata output."""
        if isinstance(self.llm, GroqQueryLLM):
            return f"groq-{self.llm.model_name}"
        elif isinstance(self.llm, CustomModelQueryLLM):
            return "custom-ml-model"
        return getattr(self.llm, "model_name", "query-llm")

    def _build_empty_response(
        self,
        query: str,
        answer: str,
        latency: float,
        route: str,
    ) -> Dict[str, Any]:
        """Constructs response when no valid articles or queries are present."""
        return {
            "query": query,
            "answer": answer,
            "sources": [],
            "retrieval_route": route,
            "confidence": 0.0,
            "_metadata": {
                "articles_retrieved": 0,
                "model_used": self._resolve_model_name(),
                "latency_seconds": round(latency, 2),
            },
        }


def main() -> None:
    import argparse
    import json

    parser = argparse.ArgumentParser(description="Ask the MAPNAI news store a question.")
    parser.add_argument("query", nargs="+", help="Question to ask about stored news.")
    parser.add_argument("--domain", help="Optional domain filter, e.g. finance.")
    parser.add_argument("--top-k", type=int, default=5, help="Maximum source articles.")
    args = parser.parse_args()

    mongo = MongoStore()
    if not mongo.is_available():
        raise SystemExit(1)
    faiss = FAISSStore()
    agent = QueryAgent(mongo_store=mongo, faiss_store=faiss)
    try:
        response = agent.process(
            " ".join(args.query), domain_filter=args.domain, top_k=args.top_k
        )
        print(json.dumps(response, indent=2, default=str))
    finally:
        mongo.close()


if __name__ == "__main__":
    main()
