"""
MAPNAI — personalization/alerts.py
Push alerts (pure: no DB, no clock). PERSONALIZATION_PLAN.md §5 "Alerts":

  inverted index   entity key → the users whose pi_topk holds it with pi ≥ alert_min_need. need = m × pi and m ≤ 1,
                   so an entry below alert_min_need can never fire and pruning it loses nothing. An article is scored
                   only for the users its entities hit; every other user is never looked at.
  threshold        need ≥ alert_min_need ∧ m ≥ alert_min_m
  one per cluster  at most one alert per (user, cluster), ever; within a run the cluster's highest-need article
  per-day cap      alert_prefs.max_per_day alerts per local day of *delivery* (the user's tz), highest need first,
                   so deferred alerts count towards the day the user receives them
  quiet hours      [quiet_start, quiet_end) in the user's local time, possibly across midnight; an alert created
                   inside it is delivered at quiet_end
"""

from datetime import datetime, time, timedelta, timezone
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


# ── Preferences / time zones ─────────────────────────────────

def zone(tz: Optional[str], default: str) -> ZoneInfo:
    """The user's zone, else the default one (an unknown name falls back too)."""
    try:
        return ZoneInfo(str(tz)) if tz else ZoneInfo(default)
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo(default)


def prefs(raw: Optional[Dict], cfg) -> Dict:
    """alert_prefs with the missing fields taken from alert_prefs_default."""
    return {**cfg.alert_prefs_default, **{k: v for k, v in (raw or {}).items() if v is not None}}


def parse_hhmm(value: str) -> time:
    hh, mm = str(value).split(":")
    return time(int(hh), int(mm))


def quiet_end(now: datetime, p: Dict, default_tz: str) -> Optional[datetime]:
    """
    The UTC end of the quiet window `now` falls in, or None outside it. start == end means no quiet hours.
    22:00–07:00 wraps midnight: 23:30 → 07:00 the next day, 02:00 → 07:00 the same day.
    """
    z = zone(p.get("tz"), default_tz)
    local = now.astimezone(z)
    start, end = parse_hhmm(p["quiet_start"]), parse_hhmm(p["quiet_end"])
    t = local.time()
    if start == end:
        return None
    if start < end:
        if not start <= t < end:
            return None
        end_date = local.date()
    elif t >= start:
        end_date = local.date() + timedelta(days=1)
    elif t < end:
        end_date = local.date()
    else:
        return None
    return datetime.combine(end_date, end, tzinfo=z).astimezone(timezone.utc)


def deliver_after(now: datetime, p: Dict, default_tz: str) -> Tuple[datetime, bool]:
    """(when the alert may be delivered, whether quiet hours deferred it)."""
    end = quiet_end(now, p, default_tz)
    return (end, True) if end else (now, False)


def day_bounds(t: datetime, z: ZoneInfo) -> Tuple[datetime, datetime]:
    """The local day containing t, as a UTC [start, end) pair."""
    day = t.astimezone(z).date()
    start = datetime.combine(day, time(0), tzinfo=z)
    end = datetime.combine(day + timedelta(days=1), time(0), tzinfo=z)
    return start.astimezone(timezone.utc), end.astimezone(timezone.utc)


# ── Inverted index ───────────────────────────────────────────

def build_index(rows: Iterable[Dict], min_score: float) -> Dict[str, Set[str]]:
    """rows: [{user_id, pi_topk}] → {entity key: {user_id}} over the pi entries with score ≥ min_score."""
    index: Dict[str, Set[str]] = {}
    for row in rows:
        for e in row.get("pi_topk") or []:
            if float(e.get("score") or 0.0) >= min_score:
                index.setdefault(e["entity"], set()).add(row["user_id"])
    return index


def users_for(keys: Sequence[str], index: Dict[str, Set[str]]) -> Set[str]:
    """The users any of the article's entity keys reach."""
    return set().union(*(index.get(k, set()) for k in keys)) if keys else set()


# ── Selection ────────────────────────────────────────────────

def eligible(need: float, m: Optional[float], cfg) -> bool:
    return m is not None and float(need) >= cfg.alert_min_need and float(m) >= cfg.alert_min_m


def select(cands: Sequence[Dict], alerted: Set[str], remaining: int) -> Tuple[List[Dict], Dict[str, int]]:
    """
    One user's eligible candidates [{article_id, cluster_id, need, m}] → (the alerts to create, drop counts).
    Highest need first (then m, article_id); one per cluster; clusters already alerted are skipped; at most
    `remaining` alerts.
    """
    dropped = {"already_alerted": 0, "same_cluster": 0, "capped": 0}
    best: Dict[str, Dict] = {}
    for c in sorted(cands, key=lambda c: (-float(c["need"]), -float(c["m"]), c["article_id"])):
        if c["cluster_id"] in alerted:
            dropped["already_alerted"] += 1
        elif c["cluster_id"] in best:
            dropped["same_cluster"] += 1
        else:
            best[c["cluster_id"]] = c
    ranked = list(best.values())
    chosen = ranked[:max(0, int(remaining))]
    dropped["capped"] = len(ranked) - len(chosen)
    return chosen, dropped
