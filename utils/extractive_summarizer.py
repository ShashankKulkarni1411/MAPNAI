"""
MAPNAI — utils/extractive_summarizer.py

Non-LLM extractive summarizer used by Agent 3.

Scores each sentence in the article body on:
  1. TF-IDF similarity to the document centroid (how "central" the
     sentence's content is to the article as a whole)
  2. Lead-position bias (news writing follows the inverted pyramid,
     so earlier sentences are weighted higher)
  3. Entity overlap — reuses the `entities` list already produced by
     Agent 1, so the most salient named entities are preserved without
     needing an LLM to "notice" them
  4. Title overlap (sentences that echo the headline tend to be central)
  5. Domain keyword density (a lightweight stand-in for the old LLM
     persona/tone logic — nudges selection toward domain-relevant content
     since extractive summarization can't rewrite prose/tone)

The top-N sentences are picked and returned in their original reading
order, never rewritten, so summaries can never contain invented facts.
"""

import re
from typing import List, Sequence

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

# Lightweight per-domain keyword sets. These replace the old LLM "persona"
# instructions — since extractive summarization can't shift tone, they
# instead bias sentence *selection* toward what that vertical cares about.
DOMAIN_KEYWORDS = {
    "finance": [r"\$\d", r"\d+%", "percent", "quarter", "revenue",
                "earnings", "stock", "shares", "market", "rate",
                "inflation", "gdp", "profit", "loss"],
    "geopolitics": ["sanctions", "treaty", "border", "military",
                     "ceasefire", "diplomat", "summit", "alliance",
                     "regime", "conflict", "troops", "negotiations"],
    "health": ["outbreak", "vaccine", "cdc", "who", "cases", "hospital",
               "disease", "infection", "treatment", "public health",
               "symptoms"],
    "technology": [r"\bai\b", "chip", "software", "cybersecurity",
                    "breach", "regulation", "launch", "startup", "data",
                    "algorithm"],
    "supply_chain": ["shipping", "port", "tariff", "logistics",
                      "shortage", "factory", "supplier", "delay",
                      "capacity", "freight"],
}

# Sentence splitter tuned for news prose. Python's `re` only allows
# fixed-width lookbehind, so instead of trying to exclude abbreviations in
# the split pattern itself, split on every plausible boundary and then
# re-merge fragments that were only split because of a trailing abbreviation.
_SENTENCE_SPLIT_RE = re.compile(r'(?<=[.!?])\s+(?=[A-Z"\u201c\u2018])')
_ABBREVIATIONS = {
    "mr", "mrs", "ms", "dr", "prof", "sr", "jr", "vs", "etc",
    "inc", "corp", "ltd", "co", "st", "u.s", "u.k", "u.n",
}


def split_sentences(text: str) -> List[str]:
    """Split article body text into clean sentences."""
    if not text:
        return []
    text = re.sub(r"\s+", " ", text.strip())
    raw_parts = _SENTENCE_SPLIT_RE.split(text)

    sentences: List[str] = []
    buffer = ""
    for part in raw_parts:
        buffer = f"{buffer} {part}".strip() if buffer else part
        words = buffer.split()
        last_word = re.sub(r"[.!?]+$", "", words[-1]).lower() if words else ""
        if last_word in _ABBREVIATIONS:
            continue  # likely an abbreviation, not a real sentence end — keep buffering
        sentences.append(buffer)
        buffer = ""
    if buffer:
        sentences.append(buffer)

    return [s.strip() for s in sentences if s.strip() and len(s.strip()) > 3]


def _entity_terms(entities: Sequence) -> List[str]:
    """Normalize an entities list (dicts or plain strings) into lowercase terms."""
    terms = []
    for e in entities or []:
        if isinstance(e, dict):
            name = e.get("name") or e.get("text") or e.get("entity")
        else:
            name = e
        if name:
            terms.append(str(name).lower())
    return terms


def _normalize(arr: np.ndarray) -> np.ndarray:
    m = arr.max() if arr.size else 0
    return arr / m if m > 0 else arr


def _score_sentences(
    sentences: List[str],
    title: str,
    entities: Sequence,
    domain: str,
) -> np.ndarray:
    """Blend the scoring signals into one importance score per sentence."""
    n = len(sentences)
    if n == 0:
        return np.array([])
    if n == 1:
        return np.array([1.0])

    # 1. TF-IDF centroid similarity
    try:
        vectorizer = TfidfVectorizer(stop_words="english", ngram_range=(1, 2))
        tfidf_matrix = vectorizer.fit_transform(sentences)
        centroid = np.asarray(tfidf_matrix.mean(axis=0))
        centroid_sim = cosine_similarity(tfidf_matrix, centroid).flatten()
    except ValueError:
        # e.g. every sentence is entirely stopwords/punctuation
        centroid_sim = np.ones(n)
    centroid_sim = _normalize(centroid_sim)

    # 2. Lead-position bias
    position_score = np.array([1.0 / (1.0 + i * 0.15) for i in range(n)])

    # 3. Entity overlap boost (reuses Agent 1's extracted entities)
    entity_score = np.zeros(n)
    entity_terms = _entity_terms(entities)
    if entity_terms:
        for i, sent in enumerate(sentences):
            low = sent.lower()
            entity_score[i] = sum(1 for term in entity_terms if term in low)
        entity_score = _normalize(entity_score)

    # 4. Title overlap boost
    title_score = np.zeros(n)
    if title:
        title_terms = set(re.findall(r"[a-z]{4,}", title.lower()))
        if title_terms:
            for i, sent in enumerate(sentences):
                sent_terms = set(re.findall(r"[a-z]{4,}", sent.lower()))
                title_score[i] = len(title_terms & sent_terms)
            title_score = _normalize(title_score)

    # 5. Domain keyword density
    domain_score = np.zeros(n)
    keywords = DOMAIN_KEYWORDS.get(domain, [])
    if keywords:
        pattern = re.compile("|".join(keywords), re.IGNORECASE)
        for i, sent in enumerate(sentences):
            domain_score[i] = len(pattern.findall(sent))
        domain_score = _normalize(domain_score)

    return (
        0.40 * centroid_sim
        + 0.20 * position_score
        + 0.20 * entity_score
        + 0.10 * title_score
        + 0.10 * domain_score
    )


def _select_top_sentences(sentences: List[str], scores: np.ndarray, count: int) -> List[str]:
    """Pick the top-scoring sentences, returned in original reading order."""
    if len(sentences) <= count:
        return sentences
    top_indices = sorted(np.argsort(scores)[-count:])
    return [sentences[i] for i in top_indices]


def extractive_summarize(
    title: str,
    body: str,
    entities: Sequence,
    domain: str,
    urgency_flag: bool,
    short_sentences: int = 3,
    long_sentences: int = 7,
) -> dict:
    """
    Produce summary_short / summary_long via extractive sentence selection.

    No API call, no hallucination risk: every sentence returned is copied
    verbatim from the article body. `entities` (from Agent 1) and `domain`
    (from Agent 2) are used purely to bias *which* sentences get picked.
    """
    sentences = split_sentences(body)
    if not sentences:
        return {"summary_short": "", "summary_long": ""}

    scores = _score_sentences(sentences, title, entities, domain)

    short = _select_top_sentences(sentences, scores, short_sentences)
    long_ = _select_top_sentences(sentences, scores, long_sentences)

    prefix = "[URGENT] " if urgency_flag else ""

    return {
        "summary_short": prefix + " ".join(short),
        "summary_long": prefix + " ".join(long_),
    }
