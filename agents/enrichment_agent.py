"""
MAPNAI — agents/enrichment_agent.py
Agent 3: Enrichment Agent (Ingestion Layer)
Applies lightweight entity extraction during ingestion using spaCy.
NOTE: The full GLiNER / BERT-based NER (Agent 1 in AI pipeline) runs
      downstream. This agent handles fast, rule-based enrichment at
      ingestion time to populate entity fields before DB storage.

Entity types extracted: ORG, GPE (geopolitical), PERSON, PRODUCT, EVENT
"""

from typing import List, Dict, Optional
from utils.models import ProcessedArticle
from utils.logger import logger


def _load_spacy_model():
    """Lazy-load spaCy model. Falls back gracefully if not installed."""
    try:
        import spacy
        try:
            return spacy.load("en_core_web_sm")
        except OSError:
            logger.warning(
                "[Enrichment] spaCy model 'en_core_web_sm' not found. "
                "Run: python -m spacy download en_core_web_sm"
            )
            return None
    except ImportError:
        logger.warning("[Enrichment] spaCy not installed. Entity extraction skipped.")
        return None


_NLP = None  # Lazy-loaded singleton


def _get_nlp():
    global _NLP
    if _NLP is None:
        _NLP = _load_spacy_model()
    return _NLP


# ── Entity extraction ────────────────────────────────────────

ENTITY_TYPES_TO_KEEP = {"ORG", "GPE", "PERSON", "PRODUCT", "EVENT", "NORP", "FAC", "LOC"}


def extract_entities(text: str, max_chars: int = 1000) -> List[Dict[str, str]]:
    """
    Extract named entities from text using spaCy.
    Returns list of {name, type, salience} dicts.
    Limits to first max_chars for speed.
    """
    nlp = _get_nlp()
    if not nlp:
        return []

    snippet = text[:max_chars]
    try:
        doc = nlp(snippet)
    except Exception as e:
        logger.debug(f"[Enrichment] spaCy error: {e}")
        return []

    # Count entity frequency for salience score
    entity_freq: Dict[str, int] = {}
    entity_types: Dict[str, str] = {}

    for ent in doc.ents:
        if ent.label_ not in ENTITY_TYPES_TO_KEEP:
            continue
        name = ent.text.strip()
        if len(name) < 2:
            continue
        # Normalize: "U.S." → "US", remove trailing punctuation
        name = name.rstrip(".,;:")
        entity_freq[name] = entity_freq.get(name, 0) + 1
        entity_types[name] = ent.label_

    if not entity_freq:
        return []

    max_freq = max(entity_freq.values())
    entities = [
        {
            "name":     name,
            "type":     entity_types[name],
            "salience": round(freq / max_freq, 3),
        }
        for name, freq in sorted(entity_freq.items(), key=lambda x: -x[1])
    ]

    return entities[:20]   # Cap at 20 entities per article


# ── Enrichment Agent ─────────────────────────────────────────

class EnrichmentAgent:
    """
    Adds entity annotations to ProcessedArticle objects in-place.
    Designed to run on batches — loads spaCy once for the batch.
    """

    def __init__(self):
        # Pre-warm spaCy model
        _get_nlp()

    def enrich(self, article: ProcessedArticle) -> ProcessedArticle:
        """
        Enrich a single article with entity data.
        Returns the same article object with entities populated.
        """
        combined = article.title + " " + article.body
        entities = extract_entities(combined)
        article.entities = entities
        return article

    def enrich_batch(
        self, articles: List[ProcessedArticle]
    ) -> List[ProcessedArticle]:
        """
        Enrich a batch of articles with entities.
        Returns enriched article list.
        """
        enriched_count = 0
        for article in articles:
            try:
                self.enrich(article)
                if article.entities:
                    enriched_count += 1
            except Exception as e:
                logger.debug(
                    f"[Enrichment] Error enriching {article.article_id[:8]}: {e}"
                )

        logger.info(
            f"[Enrichment] Enriched {enriched_count}/{len(articles)} articles with entities."
        )
        return articles
