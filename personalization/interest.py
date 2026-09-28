"""
MAPNAI — personalization/interest.py
Interest model (pure). Phase 1 holds the Beta parts used by onboarding and feedback:
priors, θ and the per-feedback Beta deltas. Late fusion and the interest score come in Phase 3.
"""

from typing import Dict, List, Optional, Sequence

from personalization.keys import beta_key


def theta(ab: Sequence[float]) -> float:
    """Posterior mean α / (α + β)."""
    a, b = float(ab[0]), float(ab[1])
    return a / (a + b) if a + b > 0 else 0.5


def prior(w: float, cfg) -> List[float]:
    """Declared weight w ∈ [0, 1] → [1 + s·w, 1 + s·(1 − w)] (s = prior_strength)."""
    w = min(max(float(w), 0.0), 1.0)
    s = cfg.prior_strength
    return [round(1 + s * w, 6), round(1 + s * (1 - w), 6)]


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
