"""
MAPNAI — stream/polling.py
Adaptive polling rules for the stream worker (pure: no I/O, no clock). continousexplanation.md §5.2–5.3.

Each source keeps its own interval. After a poll:
    error (timeout, HTTP error, parse error)   interval × 2      (back off)
    nothing new (or HTTP 304)                  interval × 1.25   (slow down)
    1 to many_new − 1 new items                interval × 0.8    (speed up)
    many_new or more                           interval × 0.5    (we are late)
clamped to [min, max] for the source's role. Since ln 1.25 = −ln 0.8, the interval settles where about half of the
polls find something new, so a feed's interval follows its publishing rate with no per-feed tuning, and a dead
feed backs off on its own.
"""

from datetime import datetime
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

ERROR, NOT_MODIFIED, OK = "error", "not_modified", "ok"

BACKOFF = 2.0
SLOWER = 1.25
FASTER = 0.8
MUCH_FASTER = 0.5
MANY_NEW = 5


def bounds(role: str, cfg) -> Tuple[float, float]:
    """(min, max) polling interval in seconds for a source role."""
    low = cfg.stream_min_interval_top_s if role == "top_stories" else cfg.stream_min_interval_s
    high = max(float(cfg.stream_max_interval_s), float(low))
    return float(low), high


def next_interval(prev_s: Optional[float], status: str, new_count: int, role: str, cfg) -> float:
    """The interval after a poll that ended with `status` and found `new_count` unseen items."""
    low, high = bounds(role, cfg)
    prev = float(prev_s) if prev_s else float(cfg.stream_initial_interval_s)
    if status == ERROR:
        factor = BACKOFF
    elif new_count >= MANY_NEW:
        factor = MUCH_FASTER
    elif new_count > 0:
        factor = FASTER
    else:                                   # NOT_MODIFIED, or OK with nothing unseen
        factor = SLOWER
    return min(high, max(low, prev * factor))


def initial_interval(role: str, cfg) -> float:
    low, high = bounds(role, cfg)
    return min(high, max(low, float(cfg.stream_initial_interval_s)))


def item_key(entry) -> str:
    """A feed item's identity: its GUID / id, else its link, else its title ("" when it has none of them)."""
    get = entry.get if hasattr(entry, "get") else (lambda k, d=None: getattr(entry, k, d))
    for field in ("id", "guid", "link", "title"):
        value = get(field, None)
        if value and str(value).strip():
            return f"{field}:{str(value).strip()}"
    return ""


def remember_seen(seen: Sequence[str], new_keys: Iterable[str], cap: int) -> List[str]:
    """The seen-key list after a poll: the newest keys first, no repeats, at most `cap` keys."""
    out: List[str] = []
    marked = set()
    for key in list(new_keys) + list(seen or []):
        if key and key not in marked:
            marked.add(key)
            out.append(key)
            if len(out) >= cap:
                break
    return out


def is_due(state: Dict, now: datetime) -> bool:
    nxt = state.get("next_poll_at")
    if nxt is None:
        return True
    if nxt.tzinfo is None and now.tzinfo is not None:      # Mongo hands back naive UTC
        nxt = nxt.replace(tzinfo=now.tzinfo)
    return nxt <= now


def due(states: Iterable[Dict], now: datetime) -> List[Dict]:
    """The active sources whose next poll time has come, the most overdue first."""
    ready = [s for s in states if s.get("active", True) and is_due(s, now)]
    return sorted(ready, key=lambda s: (s.get("next_poll_at") is not None, _naive(s.get("next_poll_at")), s["name"]))


def _naive(t: Optional[datetime]):
    if t is None:
        return datetime.min
    return t.replace(tzinfo=None) if t.tzinfo else t
