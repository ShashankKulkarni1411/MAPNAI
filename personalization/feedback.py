"""
MAPNAI — personalization/feedback.py
Section I (pure: no DB, no clock): the adaptive must_know threshold τ and exposure proposals.

  τ ← clip(τ − tau_step·(miss_rate − miss_target), tau_min, tau_max),  miss_rate = missed / (missed + needed)
      over the last tau_window_d days. `needed` counts once per (user, article) and only when that article was
      served in must_know; `missed` counts once per (user, article). Denominator 0 → τ unchanged.
      Too many misses lower τ (more items qualify as must_know); mostly-needed must_know items raise it.

  Engagement proposals: an entity among the top entities of ≥ proposal_min_articles distinct articles the user
      engaged with (open/more/save, dwell ≥ dwell_min_s) in the window, whose θ_entity ≥ proposal_min_theta,
      that is neither an exposure nor already proposed (any status: a rejected entity is not proposed again).

  A4-fact proposals: a fact {type, subject, object} whose rule side is one of the user's exposures proposes the
      entity on the other side with the rule's role. Only used when cfg.a4_facts_field is set.
"""

from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

from personalization.interest import theta
from personalization.keys import beta_key, entity_key


# ── Adaptive τ ───────────────────────────────────────────────

def tau_counts(rows: Iterable[Dict], served_pairs: Set[Tuple[str, str]]) -> Dict[str, int]:
    """
    rows: feedback {user_id, article_id, type}; served_pairs: (user_id, article_id) served in the τ section.
    Returns distinct (user, article) counts: needed (served), needed_ignored (not served there), missed, not_needed.
    """
    seen: Dict[str, Set[Tuple[str, str]]] = {"needed": set(), "missed": set(), "not_needed": set()}
    for r in rows:
        if r.get("type") in seen:
            seen[r["type"]].add((r.get("user_id"), r.get("article_id")))
    needed = seen["needed"] & served_pairs
    return {"needed": len(needed), "needed_ignored": len(seen["needed"]) - len(needed),
            "missed": len(seen["missed"]), "not_needed": len(seen["not_needed"])}


def tau_update(tau: float, missed: int, needed: int, cfg) -> Dict:
    """{tau, prev_tau, miss_rate} — miss_rate is None and τ unchanged when there is no evidence."""
    denom = missed + needed
    if denom == 0:
        return {"tau": tau, "prev_tau": tau, "miss_rate": None}
    miss_rate = missed / denom
    new = min(max(tau - cfg.tau_step * (miss_rate - cfg.miss_target), cfg.tau_min), cfg.tau_max)
    return {"tau": round(new, 6), "prev_tau": tau, "miss_rate": round(miss_rate, 6)}


# ── Proposals ────────────────────────────────────────────────

def is_engaged(row: Dict, cfg) -> bool:
    """An engagement signal: open/more/save, or dwell of at least dwell_min_s seconds."""
    if row.get("type") not in cfg.read_feedback_types:
        return False
    return row["type"] != "dwell" or float(row.get("value") or 0.0) >= cfg.dwell_min_s


def suggested_weight(theta_value: float, cfg) -> int:
    return cfg.weight_levels["medium"] if theta_value >= cfg.proposal_medium_theta else cfg.weight_levels["low"]


def entity_theta(beta: Dict[str, Sequence[float]], keys: Iterable[str]) -> float:
    """Best learned θ over the raw spellings of one canonical entity; 0.5 (flat prior) when none has a Beta."""
    thetas = [theta(beta[k]) for k in (beta_key("entity", x) for x in keys) if k in beta]
    return max(thetas) if thetas else 0.5


def engagement_proposals(
    rows: Iterable[Dict],
    beta: Dict[str, Sequence[float]],
    exposure_keys: Set[str],
    blocked_keys: Set[str],
    cfg,
    aliases: Optional[Dict[str, str]] = None,
) -> List[Dict]:
    """
    rows: one user's feedback in the window {article_id, type, value, entity_keys}. Keys are made canonical through
    aliases. Returns candidates sorted by (articles desc, θ desc, key), at most proposal_max_per_user:
    [{entity_key, suggested_role, suggested_weight, reason, evidence, articles, theta}].
    """
    aliases = aliases or {}
    articles: Dict[str, Set[str]] = {}
    spellings: Dict[str, Set[str]] = {}
    for r in rows:
        if not is_engaged(r, cfg):
            continue
        for raw in (r.get("entity_keys") or [])[: cfg.beta_top_entities]:
            key = aliases.get(raw, raw)
            articles.setdefault(key, set()).add(r["article_id"])
            spellings.setdefault(key, set()).update({raw, key})

    out = []
    for key, ids in articles.items():
        if key in exposure_keys or key in blocked_keys or len(ids) < cfg.proposal_min_articles:
            continue
        th = entity_theta(beta, spellings[key])
        if th < cfg.proposal_min_theta:
            continue
        out.append({"entity_key": key, "suggested_role": cfg.proposal_role,
                    "suggested_weight": suggested_weight(th, cfg), "reason": "engagement",
                    "evidence": sorted(ids), "articles": len(ids), "theta": round(th, 6)})
    out.sort(key=lambda p: (-p["articles"], -p["theta"], p["entity_key"]))
    return out[: cfg.proposal_max_per_user]


def fact_proposals(
    articles: Iterable[Dict],
    exposure_keys: Set[str],
    blocked_keys: Set[str],
    cfg,
    aliases: Optional[Dict[str, str]] = None,
) -> List[Dict]:
    """
    articles: {article_id, facts: [{type, subject, object}]}. A fact whose rule side (cfg.a4_fact_rules) is an
    exposure proposes the other side's entity with the rule's role (weight low). One proposal per entity, the
    first rule seen wins; evidence collects every supporting article.
    """
    aliases = aliases or {}
    other = {"subject": "object", "object": "subject"}
    found: Dict[str, Dict] = {}
    for art in articles:
        for fact in art.get("facts") or []:
            rule = cfg.a4_fact_rules.get(str(fact.get("type") or "").strip().lower())
            if not rule:
                continue
            side, role = rule
            anchor = entity_key(str(fact.get(side) or ""))
            target = entity_key(str(fact.get(other.get(side, "")) or ""))
            anchor, target = aliases.get(anchor, anchor), aliases.get(target, target)
            if not anchor or not target or anchor == target or anchor not in exposure_keys:
                continue
            if target in exposure_keys or target in blocked_keys:
                continue
            prop = found.setdefault(target, {
                "entity_key": target, "suggested_role": role, "suggested_weight": cfg.weight_levels["low"],
                "reason": "a4_fact", "evidence": [], "fact_type": fact["type"], "via": anchor,
            })
            if art["article_id"] not in prop["evidence"]:
                prop["evidence"].append(art["article_id"])
    out = sorted(found.values(), key=lambda p: (-len(p["evidence"]), p["entity_key"]))
    return out[: cfg.proposal_max_per_user]
