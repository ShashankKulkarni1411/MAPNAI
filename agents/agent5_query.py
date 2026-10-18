"""
MAPNAI — agents/agent5_query.py
Agent 5: RAG-based Query Agent & Question Answering System.

Receives natural language questions and produces grounded, factual responses
citing stored article summaries from MongoDB and FAISS vector store.

Supports:
  - LangGraph orchestration (agents/query_graph.py): route → retrieve → grade → rewrite → credibility →
    generate → check, when QUERY_GRAPH_ENABLED and a Groq key are set; otherwise, and whenever the graph
    degrades, the single-pass retrieve → generate path below
  - Automated routing (Keyword vs. Semantic retrieval; Graph for "how is X connected to Y?" questions)
  - Swappable modular LLM layer (GroqQueryLLM / CustomModelQueryLLM)
  - Zero-hallucination fallback for out-of-domain / missing knowledge
  - Strict JSON contract adherence for MAPNAI pipeline downstream
"""

import time
from typing import Dict, Any, List, Optional, Tuple

from agents.query_llm import QueryLLM, GroqQueryLLM, CustomModelQueryLLM
from agents.query_retriever import QueryRetriever
from config.settings import settings
from storage.mongo_store import MongoStore
from storage.faiss_store import FAISSStore
from utils.logger import logger


NO_ARTICLES_ANSWER = "No relevant articles found in the database to answer this question."
UNSUPPORTED_ANSWER = (
    "The stored articles mention this topic, but none of them support a verifiable answer to this question."
)


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
        graph=None,
    ):
        self.llm = llm or GroqQueryLLM()
        self.retriever = retriever or QueryRetriever(
            mongo_store=mongo_store,
            faiss_store=faiss_store,
        )
        # agents.query_graph.QueryGraph; None → single-pass only
        self.graph = graph if graph is not None else self._build_graph()
        logger.info(
            f"[QueryAgent] Initialized with LLM: {self.llm.__class__.__name__} | "
            f"graph: {'on' if self.graph is not None else 'off'}"
        )

    def _build_graph(self):
        """The LangGraph path needs the setting on, the default Groq LLM and its key; else single-pass."""
        if not settings.query_graph_enabled:
            return None
        if not isinstance(self.llm, GroqQueryLLM) or not self.llm.api_key:
            logger.info("[QueryAgent] Query graph off: needs GroqQueryLLM with a GROQ_API_KEY.")
            return None
        try:
            from agents.query_graph import QueryGraph
            return QueryGraph.from_settings(self.retriever, api_key=self.llm.api_key)
        except Exception as e:
            logger.warning(f"[QueryAgent] Query graph unavailable ({type(e).__name__}: {e}); using single-pass.")
            return None

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

        if self.graph is None:
            return self._process_single_pass(clean_query, domain_filter, top_k, start_time)

        try:
            state = self.graph.run(clean_query, domain_filter=domain_filter, top_k=top_k)
        except Exception:
            logger.exception("[QueryAgent] Query graph failed; answering single-pass.")
            return self._process_single_pass(
                clean_query, domain_filter, top_k, start_time,
                graph_meta={"outcome": "degraded", "reason": "graph raised", "llm_calls": None},
            )

        if state.get("outcome") == "degraded":
            logger.warning(f"[QueryAgent] Query graph degraded ({state.get('reason')}); answering single-pass.")
            return self._process_single_pass(
                clean_query, domain_filter, top_k, start_time,
                articles=state.get("first_retrieval"),
                route=state.get("retrieval_route"),
                graph_meta=self._graph_meta(state),
            )
        return self._graph_response(clean_query, state, start_time)

    # ── Single-pass path (pre-graph behaviour; also the graph's degraded fallback) ──

    def _process_single_pass(
        self,
        clean_query: str,
        domain_filter: Optional[str],
        top_k: int,
        start_time: float,
        articles: Optional[List[Dict[str, Any]]] = None,
        route: Optional[str] = None,
        graph_meta: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Retrieve (unless the graph already did) → one generate call. `graph_meta` → _metadata.graph."""
        # 1. Retrieve relevant articles
        if articles is None:
            articles, route_used = self.retriever.retrieve(
                query=clean_query,
                domain_filter=domain_filter,
                top_k=top_k,
            )
        else:
            route_used = route or "semantic"

        logger.info(
            f"[QueryAgent] Retrieved {len(articles)} articles via route '{route_used}' "
            f"for query: '{clean_query}'"
        )

        # 2. Handle zero results fallback (strict zero-hallucination rule)
        if not articles:
            response = self._build_empty_response(
                query=clean_query,
                answer=NO_ARTICLES_ANSWER,
                latency=time.time() - start_time,
                route=route_used,
            )
            if graph_meta is not None:
                response["_metadata"]["graph"] = graph_meta
            return response

        # 3. Format context string for LLM
        context_str = self._format_context(articles)

        # 4. Generate grounded answer via LLM
        answer = self.llm.generate_answer(question=clean_query, context=context_str)
        if graph_meta is not None and graph_meta.get("llm_calls") is not None:
            graph_meta["llm_calls"] += 1

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
        if graph_meta is not None:
            response["_metadata"]["graph"] = graph_meta

        logger.info(
            f"[QueryAgent] Answer generated | Route: {route_used} | "
            f"Sources: {len(sources)} | Confidence: {confidence} | Latency: {latency:.2f}s"
        )
        return response

    # ── Graph path ───────────────────────────────────────────

    def _graph_response(self, clean_query: str, state: Dict[str, Any], start_time: float) -> Dict[str, Any]:
        """
        Same contract as the single-pass path. Additive only: each source gains `credibility` and `cited`,
        and `_metadata.graph` carries the traced path. `[n]` in the answer is sources[n-1].
        """
        meta = self._graph_meta(state)
        route = state.get("retrieval_route") or "semantic"
        model_name = f"groq-{self.graph.model_name}"

        if state.get("outcome") == "no_answer" and not state.get("relevant"):
            response = self._build_empty_response(
                query=clean_query,
                answer=NO_ARTICLES_ANSWER,
                latency=time.time() - start_time,
                route=route,
            )
            response["_metadata"]["model_used"] = model_name
            response["_metadata"]["graph"] = meta
            return response

        context = state.get("context") or []
        unsupported = state.get("outcome") == "no_answer"
        # [n] markers belong to the answer; a withheld answer cites nothing
        cited = set() if unsupported else set(state.get("cited") or [])
        sources = [
            {
                "article_id": a["article_id"],
                "title": a["title"],
                "domain": a["domain"],
                "relevance_score": a["relevance_score"],
                "credibility": a.get("credibility"),
                "cited": idx in cited,
            }
            for idx, a in enumerate(context, start=1)
        ]

        if unsupported:
            # Relevant articles exist, but no answer they support: say so instead of guessing.
            answer = UNSUPPORTED_ANSWER
            confidence = 0.0
        else:
            answer = state.get("answer", "")
            confidence, meta["confidence_components"] = self._graph_confidence(context, cited)

        response = {
            "query": clean_query,
            "answer": answer,
            "sources": sources,
            "retrieval_route": route,
            "confidence": confidence,
            "_metadata": {
                "articles_retrieved": len(context),
                "model_used": model_name,
                "latency_seconds": round(time.time() - start_time, 2),
                "graph": meta,
            },
        }
        logger.info(
            f"[QueryAgent] Graph answer | Outcome: {meta['outcome']} | Path: {' -> '.join(meta['path'])} | "
            f"LLM calls: {meta['llm_calls']} | Confidence: {confidence} | "
            f"Latency: {response['_metadata']['latency_seconds']}s"
        )
        return response

    def _graph_confidence(self, context: List[Dict[str, Any]], cited: set) -> Tuple[float, Dict[str, float]]:
        """
        retrieval × credibility over the cited articles (all context articles if none are cited):
          retrieval   = _calculate_confidence (0.7·top + 0.3·mean relevance), the single-pass score
          credibility = 0.7 + 0.3·mean source_cred, so an all-default (0.5) answer keeps 85% of it
        Clamped to [0.10, 0.99] like the single-pass score. Explainable, not calibrated against labels.
        """
        used = [a for i, a in enumerate(context, start=1) if i in cited] or context
        retrieval = self._calculate_confidence(used)
        creds = [a["credibility"] for a in used]     # set by the graph's credibility node
        cred_factor = 0.7 + 0.3 * (sum(creds) / len(creds)) if creds else 0.85
        confidence = round(min(0.99, max(0.10, retrieval * cred_factor)), 2)
        return confidence, {"retrieval": retrieval, "credibility_factor": round(cred_factor, 3)}

    @staticmethod
    def _graph_meta(state: Dict[str, Any]) -> Dict[str, Any]:
        trace = state.get("trace") or []
        return {
            "outcome": state.get("outcome"),
            "reason": state.get("reason"),
            "path": [t["node"] for t in trace],
            "trace": trace,
            "llm_calls": state.get("llm_calls", 0),
            "rewrites": state.get("rewrites", 0),
            "regenerations": max(0, state.get("generations", 0) - 1),
            "grounded": state.get("grounded"),
            "search_queries": state.get("search_queries", []),
            "routes_used": state.get("routes_used", []),
        }

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
