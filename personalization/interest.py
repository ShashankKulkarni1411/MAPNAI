"""
MAPNAI — personalization/interest.py
Interest model (pure: no DB, no clock — `now` is passed in).

  interest = w_lf·LF + w_topic·θ_topic + w_entity·θ_entity
  LF       = lf_short_w·LF_short + lf_long_w·LF_long   (LF_long alone when the short window is empty; 0 when both are)
  LF_win   = Σ_i w_i·d_i·s_i / Σ_i w_i·d_i  over history items in the window that have a vector
             (late fusion: similarities are fused, not vectors), s_i = max(0, cos(article, item_i)),
             d_i = 0.5^(age_i / half_life), w_i = the item's history weight.
  Short window: short_window_h, half-life short_half_life_h, items with win="long" (onboarding) excluded.
  Long window:  long_window_d, half-life long_half_life_d, every item.
  θ = α/(α+β) of the persona's Beta; a topic without a Beta uses its declared-weight prior, anything else [1, 1].
"""

from datetime import datetime
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

from personalization.keys import beta_key
from personalization.scoring import parse_ts


# ── Beta affinities ──────────────────────────────────────────

def theta(ab: Sequence[float]) -> float:
    """Posterior mean α / (α + β)."""
    a, b = float(ab[0]), float(ab[1])
    return a / (a + b) if a + b > 0 else 0.5


def prior(w: float, cfg) -> List[float]:
    """Declared weight w ∈ [0, 1] → [1 + s·w, 1 + s·(1 − w)] (s = prior_strength)."""
    w = min(max(float(w), 0.0), 1.0)
    s = cfg.prior_strength
    return [round(1 + s * w, 6), round(1 + s * (1 - w), 6)]


def topic_theta(beta: Dict[str, Sequence[float]], topic: Optional[str], declared: Dict[str, float], cfg) -> float:
    """θ of the article's topic: learned Beta, else the declared-weight prior, else [1, 1] (0.5)."""
    if not topic:
        return 0.5
    key = beta_key("topic", topic)
    if key in beta:
        return theta(beta[key])
    w = (declared or {}).get(str(topic).strip().lower())
    return theta(prior(w, cfg)) if w is not None else 0.5


def max_entity_theta(beta: Dict[str, Sequence[float]], entity_keys: Sequence[str]) -> float:
    """Highest θ over the article's entities; an entity without a Beta counts as the flat prior (0.5)."""
    return best_entity_theta(beta, entity_keys)[0]


def best_entity_theta(beta: Dict[str, Sequence[float]], entity_keys: Sequence[str]) -> Tuple[float, Optional[str]]:
    """(max_entity_theta, the entity key with a learned Beta that gives it | None when it is the flat prior)."""
    best, best_key = 0.5, None
    for e in entity_keys or []:
        k = beta_key("entity", e)
        if k in beta and theta(beta[k]) > best:
            best, best_key = theta(beta[k]), e
    if best_key is None and entity_keys:
        # every entity is unknown or below the flat prior: the max is the highest learned θ, or 0.5 if any is unknown
        thetas = [theta(beta[k]) if (k := beta_key("entity", e)) in beta else 0.5 for e in entity_keys]
        best = max(thetas)
    return best, best_key


def beta_updates(
    fb_type: str,
    value: Optional[float],
    topic: Optional[str],
    top_entities: List[str],
    cfg,
) -> Dict[str, List[float]]:
    """
    Beta deltas for one feedback event: the article's topic and its top entities
    each get cfg.beta_deltas[fb_type]. `dwell` counts only at ≥ dwell_min_s seconds.
    Types without a delta (save, needed, …) return {}.
    """
    delta = cfg.beta_deltas.get(fb_type)
    if delta is None:
        return {}
    if fb_type == "dwell" and (value is None or value < cfg.dwell_min_s):
        return {}
    out: Dict[str, List[float]] = {}
    if topic:
        out[beta_key("topic", topic)] = list(delta)
    for ent in top_entities[: cfg.beta_top_entities]:
        out[beta_key("entity", ent)] = list(delta)
    return out


def merge_deltas(parts: List[Dict[str, List[float]]]) -> Dict[str, List[float]]:
    """Sum several delta dicts key-wise."""
    out: Dict[str, List[float]] = {}
    for part in parts:
        for k, (da, db) in part.items():
            a, b = out.get(k, [0.0, 0.0])
            out[k] = [a + da, b + db]
    return out


# ── Late fusion over the reading history ─────────────────────

def decay(age_h: float, half_life_h: float) -> float:
    """0.5^(age / half-life); future timestamps (age < 0) count as now."""
    return 0.5 ** (max(0.0, float(age_h)) / float(half_life_h))


def _cos(a: np.ndarray, b: np.ndarray) -> float:
    na, nb = float(np.linalg.norm(a)), float(np.linalg.norm(b))
    return float(np.dot(a, b) / (na * nb)) if na > 0 and nb > 0 else 0.0


def late_fusion(vec: Optional[np.ndarray], history: List[Dict], hist_vecs: Dict[str, np.ndarray], now: datetime,
                window_h: float, half_life_h: float, include_long_only: bool) -> Tuple[float, Optional[Dict]]:
    """
    Decay- and weight-averaged cosine between the article and the history items read in the last window_h hours.
    Returns (LF, the item contributing most) — (0.0, None) when no usable item or no article vector.
    """
    if vec is None:
        return 0.0, None
    num = den = 0.0
    best, best_contrib = None, -1.0
    for item in history:
        if not include_long_only and item.get("win") == "long":
            continue
        hv = hist_vecs.get(item.get("article_id"))
        t = parse_ts(item.get("t"))
        if hv is None or t is None:
            continue
        age_h = (now - t).total_seconds() / 3600.0
        if age_h > window_h:
            continue
        weight = float(item.get("w") or 1.0) * decay(age_h, half_life_h)
        sim = max(0.0, _cos(vec, hv))
        num += weight * sim
        den += weight
        if weight * sim > best_contrib:
            best, best_contrib = item, weight * sim
    return (num / den, best) if den > 0 else (0.0, None)


def interest(article: Dict, vec: Optional[np.ndarray], persona: Dict, hist_vecs: Dict[str, np.ndarray],
             now: datetime, cfg) -> Tuple[float, Dict]:
    """
    article: {topic, entity_keys}; persona: {history, beta, topics}. Returns (score, parts) with parts
    {lf, lf_short, lf_long, theta_topic, theta_entity, closest: {article_id, title} | None, has_vector}.
    """
    history = persona.get("history") or []
    beta = persona.get("beta") or {}
    lf_short, close_short = late_fusion(vec, history, hist_vecs, now, cfg.short_window_h,
                                        cfg.short_half_life_h, include_long_only=False)
    lf_long, close_long = late_fusion(vec, history, hist_vecs, now, cfg.long_window_d * 24,
                                      cfg.long_half_life_d * 24, include_long_only=True)
    if close_short is not None:
        lf = cfg.lf_short_w * lf_short + cfg.lf_long_w * lf_long
    else:
        lf = lf_long                     # empty short window → long only (0 when the long window is empty too)
    th_topic = topic_theta(beta, article.get("topic"), persona.get("topics") or {}, cfg)
    th_entity, th_entity_key = best_entity_theta(beta, article.get("entity_keys") or [])
    score = cfg.w_lf * lf + cfg.w_topic * th_topic + cfg.w_entity * th_entity
    closest = close_short or close_long
    return round(score, 6), {
        "lf": round(lf, 6), "lf_short": round(lf_short, 6), "lf_long": round(lf_long, 6),
        "theta_topic": round(th_topic, 6), "theta_entity": round(th_entity, 6), "theta_entity_key": th_entity_key,
        "closest": {"article_id": closest.get("article_id"), "title": closest.get("title")} if closest else None,
        "has_vector": vec is not None,
    }
