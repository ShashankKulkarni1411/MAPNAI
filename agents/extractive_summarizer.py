"""
MAPNAI — agents/extractive_summarizer.py
Agent 3's offline summarizer: extractive TF-IDF sentence ranking (no LLM).

Each body sentence is scored with a weighted mix of:
  - TF-IDF cosine similarity to the article centroid
  - lead-position bias (news puts key facts first)
  - overlap with Agent 1's most salient entities
  - overlap with the title
  - domain keyword density (config.sources.DOMAIN_KEYWORDS)

The top 3 sentences form summary_short and the top 7 form summary_long, copied
verbatim and returned in original reading order, so nothing is hallucinated.
"""

import re
from typing import Dict, List

from config.sources import DOMAIN_KEYWORDS

SHORT_SENTENCES = 3
LONG_SENTENCES = 7

WEIGHTS = {
    "centroid": 0.35,
    "position": 0.20,
    "entity": 0.20,
    "title": 0.15,
    "domain": 0.10,
}

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])[\"')\]]?\s+(?=[\"'(\[]?[A-Z0-9])")
_WORD = re.compile(r"[a-z0-9']+")
_STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "of", "to", "in", "on", "at", "for", "with",
    "by", "from", "as", "is", "was", "are", "were", "be", "been", "it", "its", "this",
    "that", "has", "have", "had", "will", "would", "said", "says", "after", "over",
}


def split_sentences(text: str) -> List[str]:
    sentences = [s.strip() for s in _SENTENCE_SPLIT.split(text or "") if s.strip()]
    # Drop fragments (bylines, "Read more", captions) that make poor summary sentences
    return [s for s in sentences if len(s.split()) >= 5]


def _content_words(text: str) -> set:
    return {w for w in _WORD.findall(text.lower()) if w not in _STOPWORDS and len(w) > 2}


def _centroid_scores(sentences: List[str]) -> List[float]:
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.metrics.pairwise import cosine_similarity

    try:
        matrix = TfidfVectorizer(stop_words="english").fit_transform(sentences)
    except ValueError:   # every sentence was stop words only
        return [0.0] * len(sentences)
    centroid = matrix.mean(axis=0).A
    return cosine_similarity(matrix, centroid).ravel().tolist()


def _normalize(values: List[float]) -> List[float]:
    top = max(values) if values else 0.0
    return [v / top for v in values] if top > 0 else [0.0] * len(values)


def _pick(sentences: List[str], scores: List[float], k: int) -> str:
    top = sorted(range(len(sentences)), key=lambda i: scores[i], reverse=True)[:k]
    return " ".join(sentences[i] for i in sorted(top))


def extractive_summarize(
    title: str,
    body: str,
    entities: List[Dict],
    domain: str,
    urgency_flag: bool = False,
) -> Dict[str, str]:
    """Return {"summary_short", "summary_long"} built from verbatim body sentences."""
    sentences = split_sentences(body)
    if not sentences:
        fallback = (body or title or "").strip()[:500]
        return _tag_urgent({"summary_short": fallback, "summary_long": fallback}, urgency_flag)

    n = len(sentences)
    centroid = _normalize(_centroid_scores(sentences))
    position = [1.0 - (i / n) for i in range(n)]

    top_entities = sorted(entities or [], key=lambda e: e.get("salience", 0), reverse=True)[:10]
    entity_names = [
        (e.get("name") or e.get("text") or "").lower() for e in top_entities
    ]
    entity_names = [name for name in entity_names if name]
    entity = _normalize([
        sum(1 for name in entity_names if name in s.lower()) for s in sentences
    ])

    title_words = _content_words(title)
    title_overlap = _normalize([
        len(title_words & _content_words(s)) / len(title_words) if title_words else 0.0
        for s in sentences
    ])

    keywords = DOMAIN_KEYWORDS.get(domain, [])
    domain_density = _normalize([
        sum(1 for kw in keywords if re.search(r"\b" + re.escape(kw) + r"\b", s.lower()))
        / max(len(s.split()), 1)
        for s in sentences
    ])

    scores = [
        WEIGHTS["centroid"] * centroid[i]
        + WEIGHTS["position"] * position[i]
        + WEIGHTS["entity"] * entity[i]
        + WEIGHTS["title"] * title_overlap[i]
        + WEIGHTS["domain"] * domain_density[i]
        for i in range(n)
    ]

    return _tag_urgent({
        "summary_short": _pick(sentences, scores, SHORT_SENTENCES),
        "summary_long": _pick(sentences, scores, LONG_SENTENCES),
    }, urgency_flag)


def _tag_urgent(summaries: Dict[str, str], urgency_flag: bool) -> Dict[str, str]:
    if urgency_flag and summaries["summary_short"]:
        summaries["summary_short"] = f"[URGENT] {summaries['summary_short']}"
    return summaries
