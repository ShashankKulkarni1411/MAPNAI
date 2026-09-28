"""
MAPNAI — scripts/classifier/collect_rss.py
Collects sports / movie articles (plus a sample of other domains as negatives)
straight from RSS into data/classifier/rss_raw.jsonl for classifier training.

Feeds only expose their latest ~10-100 items, so run this once or twice a day;
each run appends only articles not seen before (deduplicated by URL / title).

Usage (from the project root):
    python -m scripts.classifier.collect_rss
"""

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from agents.rss_fetcher import fetch_rss_source
from config.sources import (
    ENTERTAINMENT_MOVIES_RSS,
    FINANCE_RSS,
    GEOPOLITICS_RSS,
    HEALTH_RSS,
    SPORTS_RSS,
    TECHNOLOGY_RSS,
)
from utils.text_cleaner import clean_text
from utils.logger import logger

OUT_PATH = Path("data/classifier/rss_raw.jsonl")

# Negative examples for the "other" domain — a few feeds per non-target domain.
OTHER_RSS = FINANCE_RSS[:3] + GEOPOLITICS_RSS[:3] + TECHNOLOGY_RSS[:3] + HEALTH_RSS[:2]


def _key(url: str, title: str) -> str:
    return hashlib.sha1((url or title.lower()).encode("utf-8")).hexdigest()


def _load_seen() -> set:
    if not OUT_PATH.exists():
        return set()
    with OUT_PATH.open(encoding="utf-8") as f:
        return {json.loads(line)["id"] for line in f if line.strip()}


def main():
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    seen = _load_seen()
    counts = {"sports": 0, "entertainment_movies": 0, "other": 0}
    collected_at = datetime.now(timezone.utc).isoformat()

    with OUT_PATH.open("a", encoding="utf-8") as out:
        for source in SPORTS_RSS + ENTERTAINMENT_MOVIES_RSS + OTHER_RSS:
            hint = source.domain if source.domain in counts else "other"
            for art in fetch_rss_source(source, max_articles=200):
                key = _key(art.url, art.title)
                if key in seen:
                    continue
                seen.add(key)
                out.write(json.dumps({
                    "id": key,
                    "title": clean_text(art.title),
                    "body": clean_text(art.body),
                    "source": f"rss:{source.name}",
                    "hint_domain": hint,
                    "collected_at": collected_at,
                }, ensure_ascii=False) + "\n")
                counts[hint] += 1

    logger.info(f"[collect_rss] New articles: {counts} | Total stored: {len(seen)}")
    print(f"New: {counts} | Total in {OUT_PATH}: {len(seen)}")


if __name__ == "__main__":
    main()
