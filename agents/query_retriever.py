"""
MAPNAI — agents/query_retriever.py
Hybrid Retrieval Layer for Query Agent (Agent 5).

Provides:
  - Keyword / Entity Retrieval: Direct MongoDB text, regex, and entity-level search
  - Semantic Retrieval: Dense vector search via FAISS + sentence-transformers
  - Automated Query Routing: Heuristic detection between entity/specific vs general questions
  - Ranked result aggregation and score normalization
"""

import re
from typing import List, Dict, Any, Optional, Tuple
from storage.mongo_store import MongoStore
from storage.faiss_store import FAISSStore
from utils.logger import logger


class QueryRetriever:
    """
    Retrieval engine implementing both keyword and semantic search routes
    over processed articles stored in MongoDB and indexed in FAISS.
    """

    def __init__(
        self,
        mongo_store: Optional[MongoStore] = None,
        faiss_store: Optional[FAISSStore] = None,
    ):
        self.mongo_store = mongo_store or MongoStore()
        self.faiss_store = faiss_store or FAISSStore()

    # ── Main Retrieval Entry Point ───────────────────────────

    def retrieve(
        self,
        query: str,
        domain_filter: Optional[str] = None,
        top_k: int = 5,
    ) -> Tuple[List[Dict[str, Any]], str]:
        """
        Intelligently routes and retrieves the top-K relevant articles.

        Returns:
            (ranked_articles, route_used)
        """
        route_decision = self.classify_query_intent(query)
        logger.info(f"[QueryRetriever] Query: '{query}' | Route Decision: '{route_decision}'")

        articles: List[Dict[str, Any]] = []

        if route_decision == "keyword":
            articles = self.keyword_search(query, domain_filter=domain_filter, top_k=top_k)
            route_used = "keyword"
            # Fallback to semantic if keyword found nothing
            if not articles:
                logger.info("[QueryRetriever] Keyword search yielded 0 results, falling back to semantic search.")
                semantic_results = self.semantic_search(query, domain_filter=domain_filter, top_k=top_k)
                if semantic_results:
                    articles = semantic_results
                    route_used = "semantic"
        else:
            articles = self.semantic_search(query, domain_filter=domain_filter, top_k=top_k)
            route_used = "semantic"
            # Fallback to keyword if semantic found nothing
            if not articles:
                logger.info("[QueryRetriever] Semantic search yielded 0 results, falling back to keyword search.")
                keyword_results = self.keyword_search(query, domain_filter=domain_filter, top_k=top_k)
                if keyword_results:
                    articles = keyword_results
                    route_used = "keyword"

        # Sort and cap by relevance score
        articles.sort(key=lambda x: x.get("relevance_score", 0.0), reverse=True)
        return articles[:top_k], route_used

    # ── Intent Classification / Routing ──────────────────────

    @staticmethod
    def classify_query_intent(query: str) -> str:
        """
        Classifies query as 'keyword' (specific entity/action) or 'semantic' (broad/general).

        Heuristics:
          - Broad inquiry patterns (general trend/overview questions) -> 'semantic'
          - Specific entity inquiry question forms ("What did <X> do?", "Who is <X>?") -> 'keyword'
          - Uppercase acronyms (e.g. RBI, WHO, IMF, NATO) -> 'keyword'
          - Capitalized proper nouns -> 'keyword'
          - Default -> 'semantic'
        """
        q = query.strip()
        lower_q = q.lower()
        tokens = re.findall(r"\b[A-Za-z0-9_-]+\b", q)

        # 1. Broad / General inquiry patterns (High priority for semantic discovery)
        broad_patterns = [
            r"\bwhat is happening\b",
            r"\bwhat's happening\b",
            r"\boverview\b",
            r"\blatest trends\b",
            r"\bglobal\b",
            r"\bmarket trend\b",
            r"\bstate of\b",
            r"\bwhat are the latest\b",
            r"\brecent developments\b",
            r"\bdevelopments in\b",
            r"\bsummary of\b",
        ]
        if any(re.search(pat, lower_q) for pat in broad_patterns):
            # However, if it specifically asks "what did <Entity> do in recent developments", allow keyword
            if not re.search(r"\bwhat did\b|\bwhat does\b", lower_q):
                return "semantic"

        # 2. Check for specific entity inquiry questions
        entity_question_patterns = [
            r"\bwhat did\b",
            r"\bwhat does\b",
            r"\bwho is\b",
            r"\bwho are\b",
            r"\bhow did\b",
            r"\bwhere is\b",
            r"\bwhich company\b",
            r"\bwhich agency\b",
            r"\bwhich person\b",
        ]
        if any(re.search(pat, lower_q) for pat in entity_question_patterns):
            return "keyword"

        # 3. Check for uppercase acronyms (length >= 2, e.g. RBI, SEC, UN, GDP, NATO)
        acronyms = [t for t in tokens if t.isupper() and len(t) >= 2 and t not in {"AI", "US", "UK", "EU"}]
        if acronyms:
            return "keyword"

        # 4. Capitalized words (excluding sentence start) denote named entities
        if len(tokens) > 1:
            mid_capitalized = [t for t in tokens[1:] if t[0].isupper() and not t.isupper()]
            if mid_capitalized:
                return "keyword"

        return "semantic"

    # ── Keyword Search ───────────────────────────────────────

    def keyword_search(
        self,
        query: str,
        domain_filter: Optional[str] = None,
        top_k: int = 10,
    ) -> List[Dict[str, Any]]:
        """
        Direct MongoDB retrieval searching title, summaries, and entity names.
        """
        clean_tokens = [t.strip() for t in re.findall(r"\b[A-Za-z0-9_-]+\b", query) if len(t.strip()) > 1]
        if not clean_tokens:
            return []

        stopwords = {
            "what", "did", "does", "the", "and", "for", "with", "this", "that",
            "from", "into", "about", "recent", "recently", "news", "week", "month",
            "who", "how", "where", "which", "are", "were", "been", "have", "has",
            "in", "on", "at", "to", "by", "of", "a", "an", "is", "was", "it", "as",
            "or", "be", "do", "so", "up", "out", "if", "then", "than", "its", "their",
        }
        key_terms = [t for t in clean_tokens if t.lower() not in stopwords]
        if not key_terms:
            key_terms = clean_tokens

        logger.debug(f"[QueryRetriever] Extracted search keywords: {key_terms}")

        # Fetch candidate documents from MongoDB
        candidates = self._fetch_mongo_candidates(key_terms, domain_filter=domain_filter, limit=top_k * 5)
        if not candidates:
            return []

        ranked_results: List[Dict[str, Any]] = []
        for doc in candidates:
            score = self._compute_keyword_relevance(doc, key_terms)
            if score >= 0.25:
                item = self._format_article_record(doc, score)
                ranked_results.append(item)

        ranked_results.sort(key=lambda x: x["relevance_score"], reverse=True)
        return ranked_results[:top_k]

    def _fetch_mongo_candidates(
        self,
        key_terms: List[str],
        domain_filter: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """
        Queries MongoDB processed_articles collection using word-boundary regex and entity matching.
        """
        try:
            db = self.mongo_store.db
            col = db["processed_articles"]

            # Build word-boundary regex patterns
            regex_clauses = []
            for term in key_terms:
                rgx = {"$regex": r"\b" + re.escape(term) + r"\b", "$options": "i"}
                regex_clauses.append({"title": rgx})
                regex_clauses.append({"body": rgx})
                regex_clauses.append({"summary_short": rgx})
                regex_clauses.append({"summary_long": rgx})
                regex_clauses.append({"entities.name": rgx})
                regex_clauses.append({"entities.text": rgx})
                regex_clauses.append({"category": rgx})
                regex_clauses.append({"preprocess_domain": rgx})

            if not regex_clauses:
                return []

            query: Dict[str, Any] = {"$or": regex_clauses}
            if domain_filter:
                query = {"$and": [{"$or": [{"domain": domain_filter}, {"preprocess_domain": domain_filter}]}, query]}

            cursor = col.find(query, {"_id": 0}).limit(limit)
            return list(cursor)
        except Exception as e:
            logger.error(f"[QueryRetriever] MongoDB keyword fetch error: {e}")
            return []

    def _compute_keyword_relevance(self, doc: Dict[str, Any], key_terms: List[str]) -> float:
        """
        Scores an article against key terms using word-boundary matching.
        Weights:
          - Exact entity match: +0.45
          - Title word match: +0.35
          - Summary / Body word match: +0.25
          - Category / Domain word match: +0.15
        """
        score = 0.0
        title = str(doc.get("title", "")).lower()
        body = str(doc.get("body", "")).lower()
        summary_short = str(doc.get("summary_short", "")).lower()
        summary_long = str(doc.get("summary_long", "")).lower()
        category = str(doc.get("category", "")).lower()
        domain = str(doc.get("domain") or doc.get("preprocess_domain") or "").lower()

        entities = doc.get("entities", [])
        entity_names = []
        for ent in entities:
            if isinstance(ent, dict):
                name = ent.get("name") or ent.get("text")
                if name:
                    entity_names.append(name.lower())
            elif isinstance(ent, str):
                entity_names.append(ent.lower())

        for term in key_terms:
            t = term.lower()
            term_score = 0.0
            word_pattern = re.compile(r"\b" + re.escape(t) + r"\b", re.IGNORECASE)

            # Entity match (highest signal for specific queries)
            if any(t == ent or word_pattern.search(ent) for ent in entity_names):
                term_score = max(term_score, 0.45)

            # Title match
            if word_pattern.search(title):
                term_score = max(term_score, 0.35)

            # Summary or Body match
            if (
                word_pattern.search(summary_short)
                or word_pattern.search(summary_long)
                or word_pattern.search(body)
            ):
                term_score = max(term_score, 0.25)

            # Category / Domain match
            if word_pattern.search(category) or word_pattern.search(domain):
                term_score = max(term_score, 0.15)

            score += term_score

        if score <= 0.0:
            return 0.0

        # Normalize score between 0.30 and 0.98
        normalized_score = min(0.98, max(0.30, (score / max(1, len(key_terms))) * 1.5))
        return round(float(normalized_score), 2)

    # ── Semantic Search ──────────────────────────────────────

    def semantic_search(
        self,
        query: str,
        domain_filter: Optional[str] = None,
        top_k: int = 10,
        min_similarity_threshold: float = 0.22,
    ) -> List[Dict[str, Any]]:
        """
        Vector similarity search using FAISS, hydrated with full MongoDB documents.
        Filters out low-similarity noise to prevent hallucinations.
        """
        faiss_results = self.faiss_store.search(
            query=query,
            top_k=top_k,
            domain_filter=domain_filter,
        )

        if not faiss_results:
            return []

        ranked_results: List[Dict[str, Any]] = []
        for res in faiss_results:
            sim_score = float(res.get("similarity_score", 0.0))
            if sim_score < min_similarity_threshold:
                continue

            article_id = res.get("article_id")

            # Hydrate full document from MongoDB
            doc = self.mongo_store.get_article_by_id(article_id)
            if not doc:
                # Fallback to FAISS metadata if MongoDB doc isn't populated
                doc = {
                    "article_id": article_id,
                    "title": res.get("title", ""),
                    "domain": res.get("domain", "general"),
                    "summary_short": res.get("title", ""),
                    "summary_long": "",
                    "entities": [],
                }

            # Normalize cosine similarity into [0.50, 0.98] range for RAG display
            relevance = min(0.98, max(0.50, 0.50 + (sim_score * 0.50)))
            item = self._format_article_record(doc, relevance)
            ranked_results.append(item)

        ranked_results.sort(key=lambda x: x["relevance_score"], reverse=True)
        return ranked_results[:top_k]

    # ── Formatting Helper ────────────────────────────────────

    @staticmethod
    def _format_article_record(doc: Dict[str, Any], relevance_score: float) -> Dict[str, Any]:
        """Ensures all necessary fields are cleanly formatted for downstream LLM and agent payload."""
        domain_val = doc.get("domain") or doc.get("preprocess_domain") or "general"
        if hasattr(domain_val, "value"):
            domain_val = domain_val.value

        return {
            "article_id": str(doc.get("article_id", "")),
            "title": str(doc.get("title", "")),
            "domain": str(domain_val),
            "category": str(doc.get("category", "")),
            "summary_short": str(doc.get("summary_short") or doc.get("body", "")[:200]),
            "summary_long": str(doc.get("summary_long") or doc.get("body", "")),
            "entities": doc.get("entities", []),
            "relevance_score": round(float(relevance_score), 2),
            "risk_score": doc.get("risk_score"),
        }
