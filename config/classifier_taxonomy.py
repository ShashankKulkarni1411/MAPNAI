"""
MAPNAI — config/classifier_taxonomy.py
Single source of truth for Agent 2's label space.

Shared by the LLM labelling script, the training script, and Agent 2 itself,
so the trained model's output heads always line up with what the pipeline expects.
Changing anything here requires re-training the classifier (bump TAXONOMY_VERSION).
"""

from typing import Dict, List

TAXONOMY_VERSION = "2.0.0"

TAXONOMY: Dict[str, List[str]] = {
    "entertainment_movies": [
        "Box Office",
        "Reviews",
        "Releases & Trailers",
        "Casting & Production",
        "Awards & Festivals",
        "Celebrity News",
        "Streaming/OTT",
    ],
    "sports": [
        "Cricket",
        "Football",
        "Tennis",
        "Basketball",
        "Motorsport",
        "Olympics & Other Sports",
    ],
    "other": ["Other"],
}

DOMAINS: List[str] = list(TAXONOMY)

# Flat category list: the model predicts one of these; each belongs to exactly one domain.
CATEGORIES: List[str] = [c for cats in TAXONOMY.values() for c in cats]
CATEGORY_TO_DOMAIN: Dict[str, str] = {c: d for d, cats in TAXONOMY.items() for c in cats}

DOMAIN_TO_ID = {d: i for i, d in enumerate(DOMAINS)}
CATEGORY_TO_ID = {c: i for i, c in enumerate(CATEGORIES)}

# Bump when the labelling prompt changes; the Colab notebook re-labels rows made with older prompts.
LABEL_PROMPT_VERSION = 2

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

# One-line guide per category, so the labeller separates close categories consistently.
CATEGORY_GUIDE = {
    "Box Office": "ticket sales, opening-weekend / collection numbers, commercial performance only",
    "Reviews": "critics' or audience verdicts on a film or series, ratings, review round-ups",
    "Releases & Trailers": "trailers, teasers, posters, release dates, first looks, premieres",
    "Casting & Production": "who is cast, directing or producing, filming updates, sequels announced",
    "Awards & Festivals": "Oscars, BAFTAs, Filmfare, Golden Globes, nominations, Cannes/Venice/TIFF",
    "Celebrity News": "actors' personal lives, relationships, controversies, interviews, style",
    "Streaming/OTT": "platform deals, what's streaming this week, Netflix/Prime/Disney+/JioCinema strategy",
    "Cricket": "cricket at any level, including IPL and squad news",
    "Football": "soccer at any level (Premier League, ISL, UEFA, FIFA); American football goes to Olympics & Other Sports",
    "Tennis": "tennis at any level",
    "Basketball": "basketball (NBA, WNBA, FIBA, college)",
    "Motorsport": "Formula 1, MotoGP, rallying, NASCAR, IndyCar",
    "Olympics & Other Sports": "Olympics and any sport not listed above (athletics, hockey, golf, boxing, NFL, badminton...)",
    "Other": "not about films or sport",
}

DOMAIN_DEFINITIONS = (
    "entertainment_movies: news about films and the film industry, including "
    "streaming films/series releases on OTT platforms and film celebrities. "
    "sports: news about any professional or amateur sport. "
    "other: everything else (finance, politics, technology, health, music-only "
    "or TV-news-only stories, etc.)."
)


def build_label_prompt() -> str:
    """System prompt for the LLM that creates training labels (one article per request)."""
    import json
    return f"""You label a news article for training a classifier.

TAXONOMY (domain -> allowed categories):
{json.dumps(TAXONOMY, indent=2)}

DOMAINS: {DOMAIN_DEFINITIONS}

CATEGORY GUIDE (pick the category matching the article's MAIN news event, not just a word it mentions;
e.g. an awards win is "Awards & Festivals" even if box office is mentioned):
{json.dumps(CATEGORY_GUIDE, indent=2)}

URGENCY: {URGENCY_DEFINITION}

SENTIMENT: a float from -1.0 (very negative news) to 1.0 (very positive news); 0.0 is neutral/factual.

Return ONLY this JSON object, nothing else:
{{"domain": "<domain>", "category": "<category of that domain>", "sentiment": <float>, "urgency_flag": <true|false>}}
Use only the exact domain and category strings above."""


def validate_label(raw: dict):
    """Return a clean label dict, or None if the LLM output breaks the taxonomy."""
    if not isinstance(raw, dict):
        return None
    domain, category = raw.get("domain"), raw.get("category")
    if domain not in TAXONOMY or category not in TAXONOMY[domain]:
        return None
    try:
        sentiment = max(-1.0, min(1.0, float(raw.get("sentiment", 0.0))))
    except (TypeError, ValueError):
        return None
    urgency = raw.get("urgency_flag")
    if not isinstance(urgency, bool):
        return None
    return {"domain": domain, "category": category, "sentiment": sentiment, "urgency_flag": urgency}


def label_config(max_length: int = 256, urgency_threshold: float = 0.5) -> dict:
    """Metadata saved next to the trained model so Agent 2 can decode its outputs."""
    return {
        "taxonomy_version": TAXONOMY_VERSION,
        "domains": DOMAINS,
        "categories": CATEGORIES,
        "category_to_domain": CATEGORY_TO_DOMAIN,
        "max_length": max_length,
        "urgency_threshold": urgency_threshold,
    }
