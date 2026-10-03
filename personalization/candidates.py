"""
MAPNAI — personalization/candidates.py
Candidate generation (pure: no DB, no clock). The service fetches the candidate window once and hands the docs
(and, for R3, the vector hits) to these functions.

  R1 exposure  — articles mentioning any pi_topk entity (article keys canonicalized through entity_aliases),
                 ranked by that entity's pi (then m, then recency)
  R2 material  — highest materiality m in the last r2_window_h hours (top r2_top)
  R3 similar   — FAISS neighbours of the user's last r3_history_items history articles (one list per item)
  R4 topic     — per declared topic, ranked by recency decay × m (top r4_per_topic)
Fusion: reciprocal-rank fusion over all lists, cut to fused_top — except that every R1 and R2 article is kept
(they bypass the cut, so exposure hits and material news are never lost to ranking). Then read articles are
dropped, and after scoring each cluster collapses to its best article with an "another angle" from the rest.
"""

from datetime import datetime
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

from personalization.interest import decay
from personalization.keys import entity_key
from personalization.scoring import parse_ts

_EPOCH_TS = 0.0


def doc_entity_keys(doc: Dict, cfg) -> List[str]:
    """entity_keys written by the clustering job, else derived from `entities` (articles it hasn't reached yet)."""
    keys = doc.get("entity_keys")
    if keys is not None:
        return list(keys)
    ents = sorted(doc.get(cfg.entities_field) or [], key=lambda e: -(e.get(cfg.entity_salience_key) or 0.0))
    return list(dict.fromkeys(k for e in ents if (k := entity_key(e.get(cfg.entity_name_key, "")))))


def _m(doc: Dict) -> float:
    return float((doc.get("materiality") or {}).get("m") or 0.0)


def _ts(doc: Dict, cfg) -> float:
    ts = parse_ts(doc.get(cfg.published_field))
    return ts.timestamp() if ts else _EPOCH_TS


def canonical_keys(keys: Iterable[str], aliases: Optional[Dict[str, str]] = None) -> List[str]:
    """The keys plus their alias targets (entity_aliases: "man city" → "manchester city")."""
    aliases = aliases or {}
    return list(dict.fromkeys(x for k in keys for x in (k, aliases.get(k)) if x))


def resolve_keys(keys: Iterable[str], aliases: Optional[Dict[str, str]] = None) -> List[str]:
    """Each key replaced by its alias target ("man city" → "manchester city"), deduplicated, order kept."""
    aliases = aliases or {}
    return list(dict.fromkeys(aliases.get(k, k) for k in keys if k))


def r1_exposure(docs: Sequence[Dict], pi: Sequence[Dict], cfg,
                aliases: Optional[Dict[str, str]] = None) -> List[str]:
    scores = {e["entity"]: float(e["score"]) for e in pi}
    hits = []
    for d in docs:
        keys = canonical_keys(doc_entity_keys(d, cfg), aliases)
        best = max((scores[k] for k in keys if k in scores), default=None)
        if best is not None:
            hits.append((best, _m(d), _ts(d, cfg), d[cfg.id_field]))
    hits.sort(key=lambda h: (-h[0], -h[1], -h[2], h[3]))
    return [h[3] for h in hits]


def r2_material(docs: Sequence[Dict], now: datetime, cfg) -> List[str]:
    cutoff = now.timestamp() - cfg.r2_window_h * 3600
    hits = [(_m(d), _ts(d, cfg), d[cfg.id_field]) for d in docs if d.get("materiality") and _ts(d, cfg) >= cutoff]
    hits.sort(key=lambda h: (-h[0], -h[1], h[2]))
    return [h[2] for h in hits[: cfg.r2_top]]


def r4_topic(docs: Sequence[Dict], topic: str, now: datetime, cfg) -> List[str]:
    hits = []
    for d in docs:
        if (d.get(cfg.topic_field) or "").lower() != topic:
            continue
        age_h = (now.timestamp() - _ts(d, cfg)) / 3600.0
        hits.append((decay(age_h, cfg.recency_half_life_h) * _m(d), _ts(d, cfg), d[cfg.id_field]))
    hits.sort(key=lambda h: (-h[0], -h[1], h[2]))
    return [h[2] for h in hits[: cfg.r4_per_topic]]


def r3_similar(hits_per_item: Dict[str, Sequence[Tuple[str, float]]], window_ids: Set[str], cfg) -> List[List[str]]:
    """Each history item's vector hits, restricted to the window and without the item itself."""
    return [[b for b, _ in hits if b in window_ids and b != item][: cfg.r3_per_item]
            for item, hits in hits_per_item.items()]


def rrf(lists: Iterable[Sequence[str]], k: int) -> List[Tuple[str, float]]:
    """Reciprocal-rank fusion: score(d) = Σ_lists 1 / (k + rank), rank from 1. Ties → article_id."""
    scores: Dict[str, float] = {}
    for lst in lists:
        for rank, item in enumerate(lst, start=1):
            scores[item] = scores.get(item, 0.0) + 1.0 / (k + rank)
    return sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))


def merge_candidates(r1: Sequence[str], r2: Sequence[str], r3_lists: Sequence[Sequence[str]],
                     r4_lists: Sequence[Sequence[str]], cfg) -> Tuple[List[Tuple[str, float]], Dict[str, Set[str]]]:
    """
    → (fused [(article_id, rrf)] in fused order, sources {article_id: {"R1", …}}). The top fused_top by RRF are
    kept, plus every R1/R2 article (bypass).
    """
    sources: Dict[str, Set[str]] = {}
    for name, lists in (("R1", [r1]), ("R2", [r2]), ("R3", r3_lists), ("R4", r4_lists)):
        for lst in lists:
            for a in lst:
                sources.setdefault(a, set()).add(name)
    fused = rrf([r1, r2, *r3_lists, *r4_lists], cfg.rrf_k)
    keep = {a for a, _ in fused[: cfg.fused_top]} | set(r1) | set(r2)
    return [(a, s) for a, s in fused if a in keep], {a: src for a, src in sources.items() if a in keep}


def drop_read(fused: Sequence[Tuple[str, float]], read_ids: Set[str]) -> List[Tuple[str, float]]:
    return [(a, s) for a, s in fused if a not in read_ids]


def collapse_clusters(scored: List[Dict], score_key: str = "score") -> List[Dict]:
    """
    One item per cluster_id (items without one are their own cluster): the highest-scoring member wins
    (ties → article_id). The runner-up — preferring a different source_name — becomes its `another_angle`.
    """
    groups: Dict[str, List[Dict]] = {}
    for item in scored:
        groups.setdefault(item.get("cluster_id") or item["article_id"], []).append(item)
    out = []
    for members in groups.values():
        members = sorted(members, key=lambda x: (-x[score_key], x["article_id"]))
        best, rest = members[0], members[1:]
        angle: Optional[Dict] = next((m for m in rest if m.get("source_name") != best.get("source_name")),
                                     rest[0] if rest else None)
        out.append({**best, "cluster_members": len(members),
                    "another_angle": {k: angle.get(k) for k in ("article_id", "title", "source_name")}
                    if angle else None})
    out.sort(key=lambda x: (-x[score_key], x["article_id"]))
    return out
