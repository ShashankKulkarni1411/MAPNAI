"""
MAPNAI — agents/pipeline_bridge.py
Shared helpers to pass real article data between Agents 1–4.
All payloads are built from MongoDB documents and FAISS search — no static mocks.
"""

from typing import Dict, List, Optional, Any


def _normalize_domain(domain) -> str:
    if hasattr(domain, "value"):
        return domain.value
    return str(domain) if domain else "general"


def mongo_doc_to_agent1_payload(doc: dict, ner_result: Optional[dict] = None) -> dict:
    """
    Build the Agent 2 input contract from a processed_articles MongoDB document.
    Optionally merge in a fresh NER result dict from Agent 1.
    """
    entities = doc.get("entities", [])
    metadata = {}
    if ner_result:
        entities = ner_result.get("entities", entities)
        metadata = ner_result.get("_metadata", {})

    return {
        "article_id": doc.get("article_id") or (ner_result or {}).get("article_id"),
        "title": doc.get("title", ""),
        "body": doc.get("body", ""),
        "entities": entities,
        "source_name": doc.get("source_name", ""),
        "source_type": doc.get("source_type", ""),
        "url": doc.get("url", ""),
        "published_at": doc.get("published_at"),
        "ingested_at": doc.get("ingested_at"),
        "language": doc.get("language", "en"),
        "preprocess_domain": _normalize_domain(doc.get("domain", "general")),
        "_metadata": metadata,
    }


def enrich_with_similar_articles(
    payload: dict,
    faiss_store,
    top_k: int = 3,
) -> dict:
    """
    Attach semantically similar articles from the FAISS index (ingestion embeddings).
    Excludes the current article_id.
    """
    if faiss_store is None or faiss_store.total_vectors == 0:
        return payload

    title = payload.get("title", "")
    body = payload.get("body", "")
    article_id = payload.get("article_id")
    if not title and not body:
        return payload

    query = f"{title}. {body[:300]}"
    domain_filter = payload.get("preprocess_domain") or payload.get("domain")

    try:
        hits = faiss_store.search(
            query,
            top_k=top_k + 2,
            domain_filter=domain_filter if domain_filter else None,
        )
    except Exception:
        return payload

    similar: List[Dict[str, Any]] = []
    for hit in hits:
        if hit.get("article_id") == article_id:
            continue
        similar.append({
            "article_id": hit.get("article_id"),
            "title": hit.get("title"),
            "domain": hit.get("domain"),
            "source": hit.get("source"),
            "similarity_score": hit.get("similarity_score"),
        })
        if len(similar) >= top_k:
            break

    if similar:
        payload = payload.copy()
        payload["similar_articles"] = similar
    return payload


def mongo_doc_to_agent4_payload(doc: dict, upstream: Optional[dict] = None) -> dict:
    """
    Build the Agent 4 input contract from a processed_articles MongoDB document.
    Requires Agent 1–3 fields (entities, classification, summaries).
    """
    base = upstream.copy() if upstream else mongo_doc_to_agent1_payload(doc)
    sentiment = float(base.get("sentiment", doc.get("sentiment_score", 0.0)))
    return {
        **base,
        "domain": base.get("domain", doc.get("domain", "general")),
        "category": base.get("category", doc.get("category", "Other")),
        "sentiment": sentiment,
        "urgency_flag": base.get("urgency_flag", doc.get("urgency_flag", False)),
        "classification_confidence": base.get(
            "classification_confidence", doc.get("classification_confidence", 0.0)
        ),
        "taxonomy_version": base.get(
            "taxonomy_version", doc.get("taxonomy_version", "1.0.0")
        ),
        "summary_short": base.get("summary_short", doc.get("summary_short", "")),
        "summary_long": base.get("summary_long", doc.get("summary_long", "")),
    }
