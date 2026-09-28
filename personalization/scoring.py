"""
MAPNAI — personalization/scoring.py
Shared pure helpers for the personalization modules (topic shares, timestamps).
No database calls, no I/O and no clock.
"""

from datetime import datetime, timezone
from typing import Any, Dict, Optional


# ── Topics ───────────────────────────────────────────────────

def topic_shares(topics: Dict[str, float]) -> Dict[str, float]:
    """Declared topic weights (0–1 each) → shares that sum to 1 (share_t = w_t / Σ w)."""
    clean = {str(k).strip().lower(): max(float(v), 0.0) for k, v in (topics or {}).items() if str(k).strip()}
    total = sum(clean.values())
    if total <= 0:
        return {k: 0.0 for k in clean}
    return {k: round(v / total, 4) for k, v in clean.items()}


# ── Time ─────────────────────────────────────────────────────

def parse_ts(value: Any) -> Optional[datetime]:
    """
    ISO string (with or without offset) or datetime → timezone-aware UTC datetime.
    processed_articles stores published_at with an offset and ingested_at naive (UTC).
    """
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        try:
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
