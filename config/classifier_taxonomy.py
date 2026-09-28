"""
MAPNAI — config/classifier_taxonomy.py
Single source of truth for Agent 2's label space.

Shared by the Colab labelling/training notebook and Agent 2 itself, so the trained
model's outputs always line up with what the pipeline expects.
Changing anything here requires re-training the classifier (bump TAXONOMY_VERSION).

Two real categories — entertainment_movies and sports — plus "other" as a reject
label for off-topic articles (finance, politics, tech...) that the pipeline also ingests.
Agent 2 reports the category equal to the domain.
"""

from typing import List

TAXONOMY_VERSION = "3.0.0"

DOMAINS: List[str] = ["entertainment_movies", "sports", "other"]
DOMAIN_TO_ID = {d: i for i, d in enumerate(DOMAINS)}

# Bump when the labelling prompt changes; the Colab notebook re-labels rows made with older prompts.
LABEL_PROMPT_VERSION = 3

DOMAIN_DEFINITIONS = (
    "entertainment_movies: news about films and the film industry, including "
    "streaming films/series releases on OTT platforms and film celebrities. "
    "sports: news about any professional or amateur sport. "
    "other: everything else (finance, politics, technology, health, music-only "
    "or TV-news-only stories, etc.)."
)

URGENCY_DEFINITION = (
    "urgency_flag is true ONLY for breaking, time-critical, NEGATIVE disruptions: a major "
    "injury ruling a key player out of an imminent match, a death, arrest or serious "
    "health emergency of a notable person, a match-fixing / doping / corruption "
    "scandal, a match or tournament cancelled or suspended, or a film release "
    "banned, pulled or postponed at short notice. "
    "Everything else is false — most articles are NOT urgent (expect under 10%). In particular "
    "these are always false: match results and wins/losses (even finals and records), "
    "squad or team announcements, previews, fixtures, rankings, transfers and rumours, "
    "reviews, trailers, release dates, box-office numbers, awards, casting, and gossip."
)


def build_label_prompt() -> str:
    """System prompt for the LLM that creates training labels (one article per request)."""
    return f"""You label a news article for training a classifier.

DOMAINS (choose exactly one): {DOMAIN_DEFINITIONS}

URGENCY: {URGENCY_DEFINITION}

SENTIMENT: a float from -1.0 (very negative news) to 1.0 (very positive news); 0.0 is neutral/factual.

Return ONLY this JSON object, nothing else:
{{"domain": "<entertainment_movies|sports|other>", "sentiment": <float>, "urgency_flag": <true|false>}}"""


def validate_label(raw: dict):
    """Return a clean label dict, or None if the LLM output breaks the taxonomy."""
    if not isinstance(raw, dict) or raw.get("domain") not in DOMAINS:
        return None
    try:
        sentiment = max(-1.0, min(1.0, float(raw.get("sentiment", 0.0))))
    except (TypeError, ValueError):
        return None
    urgency = raw.get("urgency_flag")
    if not isinstance(urgency, bool):
        return None
    return {"domain": raw["domain"], "sentiment": sentiment, "urgency_flag": urgency}


def label_config(max_length: int = 256, urgency_threshold: float = 0.5) -> dict:
    """Metadata saved next to the trained model so Agent 2 can decode its outputs."""
    return {
        "taxonomy_version": TAXONOMY_VERSION,
        "domains": DOMAINS,
        "max_length": max_length,
        "urgency_threshold": urgency_threshold,
    }
