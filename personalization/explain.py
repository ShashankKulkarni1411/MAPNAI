"""
MAPNAI — personalization/explain.py
Plain-language text (pure): profile sentences and the digest's why lines.

Why lines by section:
  must_know / more_you_need  why_exposure + why_need   ("You own Manchester City. Need 0.30 = materiality 0.30 ×
                                                         exposure 1.00; Manchester City drives 100% of it (also: …).")
  for_you                    why_exposure (if need_bonus · need ≥ why_min_need_lift) + why_interest
  explore                    why_explore
`names` maps entity keys to display names; a key without one is shown as the key.
"""

from typing import Dict, List, Optional, Sequence

from personalization.scoring import topic_shares


def _name(key: str, names: Optional[Dict[str, str]]) -> str:
    return (names or {}).get(key) or key


def topic_label(topic: Optional[str]) -> str:
    return str(topic or "unknown").replace("_", " ")


def _phrase(role: str, cfg) -> str:
    return cfg.role_phrases.get(role, str(role).replace("_", " "))


def _rel_label(rel: str, cfg) -> str:
    mapped = cfg.rel_type_map.get(rel, rel)
    return cfg.rel_labels.get(mapped, mapped.replace("_", " ").lower())


# ── Why lines ────────────────────────────────────────────────

def why_direct(path: Dict, cfg, names: Optional[Dict[str, str]] = None) -> str:
    """A seed hit: "You own Manchester City." """
    return f"You {_phrase(path['role'], cfg)} {_name(path['seed'], names)}."


def why_hop(entry: Dict, cfg, names: Optional[Dict[str, str]] = None) -> str:
    """
    A spread hit, read from the entity back to the seed:
    "It mentions Phil Foden, often mentioned with Manchester City, which you own."
    """
    path = entry["path"]
    chain = [_name(entry["entity"], names)]
    hops = list(zip([*path["via"]][::-1] + [path["seed"]], path["relations"][::-1]))
    for node, rel in hops:
        chain.append(f"{_rel_label(rel, cfg)} {_name(node, names)}")
    return f"It mentions {', '.join(chain)}, which you {_phrase(path['role'], cfg)}."


def why_exposure(entry: Dict, cfg, names: Optional[Dict[str, str]] = None) -> str:
    return why_direct(entry["path"], cfg, names) if not entry["path"]["relations"] else why_hop(entry, cfg, names)


def need_share(path_score: float, max_pi: float) -> float:
    """The path's share of the need: its pi over the best pi among the article's entities (1 for the best path)."""
    return round(float(path_score) / float(max_pi), 4) if max_pi else 0.0


def also_hits(hits: Sequence[Dict], cfg) -> List[Dict]:
    """
    The other exposure hits worth naming after the best one: [{entity, pi, share}], at most why_also_max, each with
    a share of the best pi that shows as at least why_also_min_share at two decimals.
    """
    if not hits:
        return []
    max_pi = float(hits[0]["score"])
    out = []
    for h in hits[1:]:
        share = need_share(h["score"], max_pi)
        if round(share, 2) >= cfg.why_also_min_share:
            out.append({"entity": h["entity"], "pi": h["score"], "share": share})
        if len(out) >= cfg.why_also_max:
            break
    return out


def why_need(need: float, m: float, hits: Sequence[Dict], cfg, names: Optional[Dict[str, str]] = None) -> str:
    """
    "Need 0.30 = materiality 0.30 × exposure 1.00; Manchester City drives 100% of it (also: England 0.67)."
    hits: the article's pi entries, best first (slate.pi_hits). The "also" shares are each hit's pi over the best pi.
    """
    top = hits[0]
    max_pi = float(top["score"])
    text = (f"Need {need:.2f} = materiality {float(m or 0):.2f} × exposure {max_pi:.2f}; "
            f"{_name(top['entity'], names)} drives {need_share(top['score'], max_pi):.0%} of it")
    also = [f"{_name(h['entity'], names)} {h['share']:.2f}" for h in also_hits(hits, cfg)]
    return text + (f" (also: {', '.join(also)})." if also else ".")


def why_interest(parts: Dict, topic: Optional[str], cfg, names: Optional[Dict[str, str]] = None,
                 m: Optional[float] = None, skip_entity: Optional[str] = None) -> str:
    """
    The interest component that lifts the item most above neutral (lf above 0, θ above 0.5):
      lf     → "Similar to “<title>”, which you read."          (only from lf ≥ why_min_lf)
      topic  → "Matches your interest in sports (affinity 80%)."
      entity → "Features Knicks, which you engage with."
      none   → "A notable sports story (materiality 0.30)."
    skip_entity: an entity the caller already named (the exposure sentence), so the entity reason isn't repeated.
    """
    lf = float(parts.get("lf") or 0.0)
    lift = {
        "lf": cfg.w_lf * lf if parts.get("closest") and lf >= cfg.why_min_lf else 0.0,
        "topic": cfg.w_topic * (float(parts.get("theta_topic") or 0.5) - 0.5),
        "entity": cfg.w_entity * (float(parts.get("theta_entity") or 0.5) - 0.5),
    }
    if skip_entity is not None and parts.get("theta_entity_key") == skip_entity:
        lift["entity"] = 0.0
    best = max(lift, key=lambda k: (lift[k], k == "lf", k == "topic"))
    if lift[best] <= 0:
        suffix = f" (materiality {float(m):.2f})" if m is not None else ""
        return f"A notable {topic_label(topic)} story{suffix}."
    if best == "lf":
        return f"Similar to “{parts['closest'].get('title') or parts['closest'].get('article_id')}”, which you read."
    if best == "topic":
        return f"Matches your interest in {topic_label(topic)} (affinity {float(parts['theta_topic']):.0%})."
    key = parts.get("theta_entity_key")
    return f"Features {_name(key, names)}, which you engage with." if key else "Features entities you engage with."


def why_explore(topic: Optional[str]) -> str:
    return f"Something different: a top {topic_label(topic)} story, outside the topics in your digest."


def why_proposal(proposal: Dict, cfg, names: Optional[Dict[str, str]] = None) -> str:
    """Why an exposure is suggested: the engagement evidence, or the A4 fact linking it to an exposure."""
    name = _name(proposal["entity_key"], names)
    days = cfg.proposal_window_d
    if proposal.get("reason") == "a4_fact":
        via = _name(proposal.get("via", ""), names)
        return (f"A recent article reports a {proposal.get('fact_type')} link between {name} and {via}; "
                f"you may {_phrase(proposal['suggested_role'], cfg)} {name}.")
    n = proposal.get("articles") or len(proposal.get("evidence") or [])
    return (f"You engaged with {n} articles featuring {name} in the last {days} days "
            f"(affinity {float(proposal.get('theta') or 0):.0%}). Add it as something you "
            f"{_phrase(proposal['suggested_role'], cfg)}?")


def profile_sentences(exposures: List[Dict], topics: Dict[str, float], style: Dict, cfg) -> List[str]:
    """
    One sentence per exposure ("You own Manchester City (high)."), then declared topics
    as shares, then the reading style. Exposures are already grouped per entity key;
    one added from an accepted proposal says so.
    """
    sentences: List[str] = []
    for exp in exposures:
        phrase = cfg.role_phrases.get(exp["role"], exp["role"].replace("_", " "))
        origin = ", from a suggestion you accepted" if exp.get("provenance") == "confirmed" else ""
        sentences.append(f"You {phrase} {exp['name']} ({exp['weight_label']}{origin}).")

    shares = topic_shares(topics)
    ranked = sorted(((t, s) for t, s in shares.items() if s > 0), key=lambda ts: (-ts[1], ts[0]))
    if ranked:
        parts = [f"{t.replace('_', ' ')} ({s:.0%})" for t, s in ranked]
        sentences.append(f"You are interested in {', '.join(parts)}.")

    if style:
        sentences.append(
            f"You prefer {style.get('length', '?')}, {style.get('tone', '?')} summaries "
            f"with {style.get('jargon', '?')} jargon."
        )
    return sentences
