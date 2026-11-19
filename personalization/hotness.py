"""
MAPNAI — personalization/hotness.py
Hotness H of a story (event cluster): how fast and how widely it is spreading right now (pure: no DB, no clock).
continousexplanation.md §5.8.

Materiality m asks "how much does this matter?"; hotness asks "is this blowing up right now?".

Outlets. S = every outlet that carried the story: the sources of the cluster's articles plus the outlets recorded
as sightings (duplicates dropped at ingestion). An outlet's arrival time is the earliest time it carried the story
(publish time, else ingestion time; a sighting's own time). cred(s) ∈ [0, 1] from config/source_credibility.json.

Components (each in [0, 1]):
    breadth     1 − exp(−Σ_{s∈S} cred(s) / breadth_scale)
    velocity    1 − exp(−Σ cred(s) over outlets that arrived in the last velocity_window_min / velocity_scale)
    prominence  1 if a member's URL or title is on a top-stories front page (last prominence_window_h), else 0
    severity    max Agent 4 risk_score / risk_scale_max over the members; urgent_severity when only Agent 2's
                urgency flag is set; absent otherwise
    social      1 − exp(−posts / social_scale) from the Bluesky counter; absent when it isn't running
Score:   raw = Σ w·x / Σ w over the components present;   H = raw × 0.5^(hours since the last new outlet / half_life)
Tiers:   breaking  H ≥ breaking_h ∧ ≥ breaking_min_credible outlets with cred ≥ credible_min arrived within
                   breaking_fast_min of the first report ∧ first report < breaking_max_age_h old
         trending  H ≥ trending_h ∧ ≥ trending_min_outlets outlets
         normal    otherwise
"""

import math
import re
from collections import Counter
from datetime import datetime, timedelta
from typing import Dict, Iterable, List, Optional, Sequence, Set

from personalization.clustering import title_tokens
from personalization.scoring import parse_ts

BREAKING, TRENDING, NORMAL = "breaking", "trending", "normal"
TIER_RANK = {BREAKING: 2, TRENDING: 1, NORMAL: 0}

_PUBLISHER_TAIL = re.compile(r"\s+[-–—|]\s+([^-–—|]{1,60})$")


def strip_publisher(title: str) -> str:
    """'Kohli out of the final - Cricbuzz' → 'Kohli out of the final' (aggregators append the outlet's name)."""
    title = (title or "").strip()
    m = _PUBLISHER_TAIL.search(title)
    if m and len(m.group(1).split()) <= 6 and m.start() > 0:
        return title[:m.start()].strip()
    return title


def cred(source: Optional[str], cfg) -> float:
    return min(1.0, max(0.0, float(cfg.source_cred.get(source, cfg.source_cred_default))))


def saturate(x: float, scale: float) -> float:
    """1 − exp(−x / scale): 0 at 0, rising quickly, never above 1."""
    return 0.0 if x <= 0 else 1.0 - math.exp(-x / max(float(scale), 1e-9))


# ── Prominence ───────────────────────────────────────────────

class ProminenceIndex:
    """Front-page items ({url, title}) with a URL set and a token → items inverted index for title matching."""

    def __init__(self, signals: Iterable[Dict], min_jaccard: float):
        self.min_jaccard = float(min_jaccard)
        self.urls: Set[str] = set()
        self.tokens: List[Set[str]] = []
        self._by_token: Dict[str, List[int]] = {}
        for s in signals or []:
            if s.get("url"):
                self.urls.add(s["url"].strip())
            toks = title_tokens(strip_publisher(s.get("title") or ""))
            if toks:
                i = len(self.tokens)
                self.tokens.append(toks)
                for t in toks:
                    self._by_token.setdefault(t, []).append(i)

    def __len__(self) -> int:
        return len(self.tokens) + len(self.urls)

    def match(self, url: Optional[str], title: Optional[str]) -> bool:
        if url and url.strip() in self.urls:
            return True
        toks = title_tokens(strip_publisher(title or ""))
        if not toks:
            return False
        candidates = {i for t in toks for i in self._by_token.get(t, [])}
        return any(len(toks & self.tokens[i]) / len(toks | self.tokens[i]) >= self.min_jaccard for i in candidates)


# ── Outlets ──────────────────────────────────────────────────

def member_time(member: Dict, now: datetime) -> datetime:
    """When this article's outlet carried the story: publish time, else ingestion time, never after now."""
    t = parse_ts(member.get("published")) or parse_ts(member.get("ingested")) or now
    return min(t, now)


def outlets(members: Sequence[Dict], now: datetime) -> Dict[str, datetime]:
    """{outlet: the earliest time it carried the story} over the articles and their sightings."""
    out: Dict[str, datetime] = {}
    for m in members:
        if m.get("source"):
            t = member_time(m, now)
            if m["source"] not in out or t < out[m["source"]]:
                out[m["source"]] = t
        for s in m.get("sightings") or []:
            src = s.get("source")
            if not src:
                continue
            t = min(parse_ts(s.get("at")) or now, now)
            if src not in out or t < out[src]:
                out[src] = t
    return out


def domain_of(members: Sequence[Dict]) -> Optional[str]:
    counts = Counter(m.get("domain") for m in members if m.get("domain"))
    return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[0][0] if counts else None


def severity(members: Sequence[Dict], cfg) -> Optional[float]:
    risks = []
    for m in members:
        r = m.get("risk_score")
        if r is not None and not isinstance(r, bool):
            try:
                risks.append(min(1.0, max(0.0, float(r) / float(cfg.risk_scale_max))))
            except (TypeError, ValueError):
                pass
    if risks:
        return max(risks)
    if any(m.get("urgency_flag") for m in members):
        return float(cfg.hot_urgent_severity)
    return None


# ── Score ────────────────────────────────────────────────────

def hotness(members: Sequence[Dict], now: datetime, cfg, prominence: Optional[ProminenceIndex] = None,
            social_count: Optional[int] = None) -> Dict:
    """
    members: the cluster's articles [{article_id, source, published, ingested?, url, title, sightings, risk_score,
    urgency_flag, domain}]. Returns {score, raw, tier, components, weights_used, outlets, credible_outlets,
    fast_credible, velocity_outlets, first_seen, last_source_at, decay, domain}.
    """
    arrivals = outlets(members, now)
    domain = domain_of(members)
    scale = float((cfg.hot_domain_scale or {}).get(domain, 1.0)) or 1.0
    if not arrivals:
        return {"score": 0.0, "raw": 0.0, "tier": NORMAL, "components": {}, "outlets": 0, "credible_outlets": 0,
                "fast_credible": 0, "velocity_outlets": 0, "first_seen": None, "last_source_at": None,
                "decay": 1.0, "domain": domain}

    since = now - timedelta(minutes=cfg.hot_velocity_window_min)
    breadth_sum = sum(cred(s, cfg) for s in arrivals) / scale
    recent = [s for s, t in arrivals.items() if t >= since]
    velocity_sum = sum(cred(s, cfg) for s in recent) / scale

    parts = {
        "breadth": saturate(breadth_sum, cfg.hot_breadth_scale),
        "velocity": saturate(velocity_sum, cfg.hot_velocity_scale),
        "prominence": 1.0 if prominence is not None and any(prominence.match(m.get("url"), m.get("title"))
                                                           for m in members) else 0.0,
    }
    sev = severity(members, cfg)
    if sev is not None:
        parts["severity"] = sev
    if social_count is not None:
        parts["social"] = saturate(float(social_count), cfg.hot_social_scale)
    weights = {"breadth": cfg.hot_w_breadth, "velocity": cfg.hot_w_velocity, "prominence": cfg.hot_w_prominence,
               "severity": cfg.hot_w_severity, "social": cfg.hot_w_social}
    total_w = sum(weights[k] for k in parts)
    raw = sum(weights[k] * v for k, v in parts.items()) / total_w if total_w > 0 else 0.0

    first_seen = min(arrivals.values())
    last_source_at = max(arrivals.values())
    age_h = max(0.0, (now - last_source_at).total_seconds() / 3600.0)
    decay = 0.5 ** (age_h / max(float(cfg.hot_half_life_h), 1e-9))
    score = min(1.0, max(0.0, raw * decay))

    fast_by = first_seen + timedelta(minutes=cfg.hot_breaking_fast_min)
    credible = [s for s in arrivals if cred(s, cfg) >= cfg.hot_credible_min]
    fast_credible = [s for s in credible if arrivals[s] <= fast_by]
    out = {
        "score": round(score, 6), "raw": round(raw, 6),
        "components": {k: round(v, 6) for k, v in parts.items()},
        "outlets": len(arrivals), "credible_outlets": len(credible), "fast_credible": len(fast_credible),
        "velocity_outlets": len(recent), "first_seen": first_seen, "last_source_at": last_source_at,
        "decay": round(decay, 6), "domain": domain,
    }
    out["tier"] = tier(out, now, cfg)
    return out


def tier(h: Dict, now: datetime, cfg) -> str:
    first = h.get("first_seen")
    if (h["score"] >= cfg.hot_breaking_h and h["fast_credible"] >= cfg.hot_breaking_min_credible
            and first is not None and now - first <= timedelta(hours=cfg.hot_breaking_max_age_h)):
        return BREAKING
    if h["score"] >= cfg.hot_trending_h and h["outlets"] >= cfg.hot_trending_min_outlets:
        return TRENDING
    return NORMAL


def history_due(prev: Optional[Dict], new: Dict, cfg) -> bool:
    """A hot_history row: on every tier change, and while a story is hot on every score move ≥ min_delta."""
    prev_tier = (prev or {}).get("tier", NORMAL)
    if new["tier"] != prev_tier:
        return True
    if new["tier"] == NORMAL:
        return False
    return abs(float(new["score"]) - float((prev or {}).get("score") or 0.0)) >= cfg.hot_history_min_delta


def explain(h: Dict) -> str:
    """'Breaking · 6 outlets, 4 in the last hour' — the line the app shows under a hot story."""
    label = {BREAKING: "Breaking", TRENDING: "Trending"}.get(h.get("tier"), "In the news")
    n, recent = int(h.get("outlets") or 0), int(h.get("velocity_outlets") or 0)
    text = f"{label} · {n} outlet{'s' if n != 1 else ''}"
    if recent:
        text += f", {recent} in the last hour"
    if (h.get("components") or {}).get("prominence"):
        text += " · on front pages"
    return text


def rank_key(h: Optional[Dict]):
    """Sort key: breaking before trending before normal, then higher H."""
    h = h or {}
    return (-TIER_RANK.get(h.get("tier"), 0), -float(h.get("score") or 0.0))
