"""
MAPNAI — agents/query_retriever.py
Hybrid Retrieval Layer for Query Agent (Agent 5).

Provides:
  - Keyword / Entity Retrieval: Direct MongoDB text, regex, and entity-level search
  - Semantic Retrieval: Dense vector search via FAISS + sentence-transformers
  - Graph Retrieval: articles that MENTION the entities of a "how is X connected to Y?" question (Neo4j)
  - Automated Query Routing: Heuristic detection between entity/specific vs general questions
  - Ranked result aggregation and score normalization
"""

import math
import re
import threading
import time
from typing import List, Dict, Any, Optional, Tuple, Union
from config.settings import settings
from storage.mongo_store import MongoStore
from storage.faiss_store import FAISSStore
from utils.logger import logger


# "how is X connected to Y", "relationship between X and Y", "what links X to Y"
_CONNECTION_PATTERNS = [
    re.compile(r"\b(?:how|what)\s+(?:is|are|was|were)\s+(.+?)\s+(?:connected|related|linked|tied)\s+(?:to|with)\s+(.+)", re.I),
    re.compile(r"\b(?:connection|connections|relationship|relation|link|links|ties)\s+between\s+(.+?)\s+and\s+(.+)", re.I),
    re.compile(r"\bwhat\s+(?:links|connects|ties)\s+(.+?)\s+(?:to|and|with)\s+(.+)", re.I),
]

# Question words that say nothing about which story is meant ("what happens next", "any news on")
_STOPWORDS = {
    "what", "whats", "did", "does", "do", "done", "the", "and", "for", "with", "this", "that", "these", "those",
    "from", "into", "about", "recent", "recently", "news", "week", "month", "year", "today", "yesterday",
    "who", "whos", "whom", "how", "where", "when", "why", "which", "are", "were", "been", "being", "have", "has",
    "had", "in", "on", "at", "to", "by", "of", "a", "an", "is", "was", "it", "as", "or", "be", "so", "up", "out",
    "if", "then", "than", "its", "their", "there", "here", "now", "next", "new", "latest", "last", "any", "anyone",
    "anything", "some", "more", "most", "much", "many", "all", "also", "just", "very", "will", "would", "could",
    "should", "can", "may", "might", "not", "no", "yes", "he", "she", "they", "them", "him", "his", "her", "hers",
    "you", "your", "me", "my", "we", "our", "us", "happen", "happens", "happened", "happening", "going", "go",
    "get", "got", "tell", "know", "say", "said", "says", "update", "updates", "story", "stories", "after",
    "before", "over", "like", "still", "ever", "again", "other",
}
_TERM_FIELDS = ("title", "body", "summary_short", "summary_long", "entities.name", "entities.text")
_KEYWORD_SCAN_PER_ANCHOR = 100     # newest articles fetched per anchor term
_KEYWORD_MIN_COVERAGE = 0.15       # share of the question's (rarity-weighted) terms an article must match
_KEYWORD_RELATIVE_CUTOFF = 0.5     # drop articles scoring under half the best one


def _domain_list(domain_filter: Union[str, List[str], None]) -> Optional[List[str]]:
    """One domain, several (Ask's "All" = every in-scope domain) or None for no filter."""
    if not domain_filter:
        return None
    return [domain_filter] if isinstance(domain_filter, str) else list(domain_filter)


class QueryRetriever:
    """
    Retrieval engine implementing both keyword and semantic search routes
    over processed articles stored in MongoDB and indexed in FAISS.
    """

    def __init__(
        self,
        mongo_store: Optional[MongoStore] = None,
        faiss_store: Optional[FAISSStore] = None,
        neo4j_store=None,
    ):
        self.mongo_store = mongo_store or MongoStore()
        self.faiss_store = faiss_store or FAISSStore()
        self._neo4j_store = neo4j_store   # storage.neo4j_store.Neo4jStore, created on the first graph search
        self._neo4j_down_until = 0.0
        self._neo4j_lock = threading.Lock()

    # ── Main Retrieval Entry Point ───────────────────────────

    def retrieve(
        self,
        query: str,
        domain_filter: Union[str, List[str], None] = None,
        top_k: int = 5,
        route: Optional[str] = None,
        context_article_id: Optional[str] = None,
    ) -> Tuple[List[Dict[str, Any]], str]:
        """
        Intelligently routes and retrieves the top-K relevant articles.
        `route` ("keyword" / "semantic") skips the intent heuristic; the other route stays the fallback.
        `context_article_id` is the story the question is asked from: it always comes back first, whatever its
        domain, and its title steers the semantic search ("what happens next?" says nothing on its own).

        Returns:
            (ranked_articles, route_used)
        """
        route_decision = route or self.classify_query_intent(query)
        logger.info(f"[QueryRetriever] Query: '{query}' | Route Decision: '{route_decision}'")

        pinned = self.context_record(context_article_id)
        semantic_query = f"{query} {pinned['title']}" if pinned else query
        articles: List[Dict[str, Any]] = []

        if route_decision == "keyword":
            articles = self.keyword_search(query, domain_filter=domain_filter, top_k=top_k)
            route_used = "keyword"
            # Fallback to semantic if keyword found nothing
            if not articles:
                logger.info("[QueryRetriever] Keyword search yielded 0 results, falling back to semantic search.")
                semantic_results = self.semantic_search(semantic_query, domain_filter=domain_filter, top_k=top_k)
                if semantic_results:
                    articles = semantic_results
                    route_used = "semantic"
        else:
            articles = self.semantic_search(semantic_query, domain_filter=domain_filter, top_k=top_k)
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
        return self.pin(articles, pinned, top_k), route_used

    def context_record(self, article_id: Optional[str]) -> Optional[Dict[str, Any]]:
        """The story a question is asked from, as a retrieval record (None when absent or unknown)."""
        if not article_id:
            return None
        doc = self.mongo_store.get_article_by_id(article_id)
        return self._format_article_record(doc, 0.98) if doc else None

    @staticmethod
    def pin(articles: List[Dict[str, Any]], pinned: Optional[Dict[str, Any]], top_k: int) -> List[Dict[str, Any]]:
        """`pinned` first (once), then the rest, capped at top_k."""
        if not pinned:
            return articles[:top_k]
        rest = [a for a in articles if a.get("article_id") != pinned["article_id"]]
        return ([pinned] + rest)[:top_k]

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

    @staticmethod
    def extract_connection_entities(query: str) -> List[str]:
        """
        The two entities of a connection question ("How is X connected to Y?"), lowercased; [] for any other
        question. Leading articles and trailing punctuation are stripped.
        """
        for pattern in _CONNECTION_PATTERNS:
            match = pattern.search(query.strip())
            if not match:
                continue
            names = []
            for raw in match.groups():
                name = re.sub(r"^(?:the|a|an)\s+", "", raw.strip(" ?.!,;:'\""), flags=re.I).strip().lower()
                if len(name) >= 2:
                    names.append(name)
            if len(names) == 2 and names[0] != names[1]:
                return names
        return []

    # ── Graph Search ─────────────────────────────────────────

    def graph_search(
        self,
        entities: List[str],
        domain_filter: Union[str, List[str], None] = None,
        top_k: int = 10,
    ) -> List[Dict[str, Any]]:
        """
        Articles whose (Article)-[:MENTIONS]->(Entity) edges match the given entity names, ranked by how many
        of them they mention, hydrated from MongoDB. Raises when Neo4j is unreachable (or cooling down after a
        failure) so the caller can tell "graph down" from "no match".
        """
        keys = [e.strip().lower() for e in entities if len(e.strip()) >= 2]
        if not keys:
            return []
        domains = _domain_list(domain_filter)
        if time.monotonic() < self._neo4j_down_until:
            raise ConnectionError("Neo4j marked unavailable (cooling down after a failure)")

        cypher = """
        UNWIND $keys AS k
        MATCH (a:Article)-[:MENTIONS]->(e:Entity)
        WHERE coalesce(e.name_lower, toLower(trim(e.name))) CONTAINS k
        WITH a, count(DISTINCT k) AS hits
        WHERE $domains IS NULL OR a.domain IN $domains
        RETURN a.article_id AS article_id, hits
        ORDER BY hits DESC, a.published_at DESC
        LIMIT $limit
        """
        try:
            with self._neo4j_lock:
                if self._neo4j_store is None:
                    from storage.neo4j_store import Neo4jStore
                    self._neo4j_store = Neo4jStore()
            with self._neo4j_store.driver.session() as session:
                rows = [r.data() for r in session.run(cypher, keys=keys, domains=domains, limit=top_k)]
        except Exception:
            self._neo4j_down_until = time.monotonic() + settings.query_graph_neo4j_cooldown_seconds
            raise

        ranked_results: List[Dict[str, Any]] = []
        for row in rows:
            doc = self.mongo_store.get_article_by_id(row["article_id"])
            if not doc or (domains and doc.get("domain") not in domains):   # MongoDB holds Agent 2's domain
                continue
            # Mentions every entity → 0.90; fewer → scaled down from there
            relevance = 0.55 + 0.35 * (int(row["hits"]) / len(keys))
            ranked_results.append(self._format_article_record(doc, relevance))
        return ranked_results

    # ── Keyword Search ───────────────────────────────────────

    def keyword_search(
        self,
        query: str,
        domain_filter: Union[str, List[str], None] = None,
        top_k: int = 10,
    ) -> List[Dict[str, Any]]:
        """
        Direct MongoDB retrieval searching title, body, summaries and entity names.

        Terms are weighted by rarity (IDF over the searched articles), so a name like "Pattinson" outweighs a
        common word like "cast". Candidates must match an anchor term: the names in the question (capitalised
        words, acronyms) or, when it has none, its two rarest terms. Anchors are fetched one by one, newest
        first, so a rare term's articles are never crowded out by a common one's.
        """
        tokens = [t for t in re.findall(r"\b[A-Za-z0-9_-]+\b", query) if len(t) > 1]
        if not tokens:
            return []
        key_terms = list(dict.fromkeys(t.lower() for t in tokens if t.lower() not in _STOPWORDS))
        if not key_terms:
            key_terms = list(dict.fromkeys(t.lower() for t in tokens))
        names = {t.lower() for i, t in enumerate(tokens)
                 if t.lower() in key_terms and (t.isupper() or (i > 0 and t[0].isupper()))}

        logger.debug(f"[QueryRetriever] Extracted search keywords: {key_terms} | names: {sorted(names)}")

        try:
            col = self.mongo_store.db["processed_articles"]
            domains = _domain_list(domain_filter)
            total = col.count_documents(self._scoped({}, domains))
            freq = {t: col.count_documents(self._scoped(self._term_match(t), domains)) for t in key_terms}
            present = [t for t in key_terms if freq[t] > 0]
            if not present:
                return []
            anchors = [t for t in present if t in names] or sorted(present, key=freq.get)[:2]

            candidates: Dict[str, Dict[str, Any]] = {}
            for term in anchors:
                cursor = (col.find(self._scoped(self._term_match(term), domains), {"_id": 0})
                          .sort("published_ts", -1).limit(_KEYWORD_SCAN_PER_ANCHOR))
                for doc in cursor:
                    candidates.setdefault(str(doc.get("article_id")), doc)
        except Exception as e:
            logger.error(f"[QueryRetriever] MongoDB keyword fetch error: {e}")
            return []

        weights = {t: math.log((total + 1) / (freq[t] + 1)) + 1.0 for t in present}
        scored = [(self._compute_keyword_coverage(doc, weights), doc) for doc in candidates.values()]
        scored = [(cov, doc) for cov, doc in scored if cov >= _KEYWORD_MIN_COVERAGE]
        if not scored:
            return []
        best = max(cov for cov, _ in scored)

        ranked_results = [
            self._format_article_record(doc, min(0.98, 0.30 + 0.68 * cov))
            for cov, doc in scored if cov >= best * _KEYWORD_RELATIVE_CUTOFF
        ]
        ranked_results.sort(key=lambda x: x["relevance_score"], reverse=True)
        return ranked_results[:top_k]

    @staticmethod
    def _term_match(term: str) -> Dict[str, Any]:
        rgx = {"$regex": r"\b" + re.escape(term) + r"\b", "$options": "i"}
        return {"$or": [{field: rgx} for field in _TERM_FIELDS]}

    @staticmethod
    def _scoped(query: Dict[str, Any], domains: Optional[List[str]]) -> Dict[str, Any]:
        """Restrict to Agent 2's domains (the `domain` field) when a filter is set."""
        if not domains:
            return query
        scope = {"domain": {"$in": domains}}
        return {"$and": [scope, query]} if query else scope

    def _compute_keyword_coverage(self, doc: Dict[str, Any], weights: Dict[str, float]) -> float:
        """
        Rarity-weighted share of the question's terms an article matches, 0–1. Per term, where it matches:
          - Entity name: 0.45
          - Title: 0.35
          - Summary / Body: 0.25
          - Category / Domain: 0.15
        """
        title = str(doc.get("title", "")).lower()
        texts = [str(doc.get(f) or "").lower() for f in ("summary_short", "summary_long", "body")]
        labels = [str(doc.get("category", "")).lower(),
                  str(doc.get("domain") or doc.get("preprocess_domain") or "").lower()]

        entity_names = []
        for ent in doc.get("entities", []):
            if isinstance(ent, dict):
                name = ent.get("name") or ent.get("text")
                if name:
                    entity_names.append(name.lower())
            elif isinstance(ent, str):
                entity_names.append(ent.lower())

        score = 0.0
        for term, weight in weights.items():
            word_pattern = re.compile(r"\b" + re.escape(term) + r"\b")
            if any(word_pattern.search(ent) for ent in entity_names):
                term_score = 0.45
            elif word_pattern.search(title):
                term_score = 0.35
            elif any(word_pattern.search(t) for t in texts):
                term_score = 0.25
            elif any(word_pattern.search(t) for t in labels):
                term_score = 0.15
            else:
                term_score = 0.0
            score += weight * term_score

        return score / (0.45 * sum(weights.values()))

    # ── Semantic Search ──────────────────────────────────────

    def semantic_search(
        self,
        query: str,
        domain_filter: Union[str, List[str], None] = None,
        top_k: int = 10,
        min_similarity_threshold: float = 0.22,
    ) -> List[Dict[str, Any]]:
        """
        Vector similarity search using FAISS, hydrated with full MongoDB documents.
        Filters out low-similarity noise to prevent hallucinations.

        With a domain filter, the domain is checked on the MongoDB document (Agent 2's label): the FAISS
        metadata keeps the domain from ingestion time. Articles missing from MongoDB are then skipped too.
        """
        domains = _domain_list(domain_filter)
        faiss_results = self.faiss_store.search(
            query=query,
            top_k=top_k * 6 if domains else top_k,
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
            if domains and (not doc or doc.get("domain") not in domains):
                continue
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
            "source_name": doc.get("source_name"),
        }
