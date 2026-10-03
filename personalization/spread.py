"""
MAPNAI — personalization/spread.py
Exposure spread (pure): the user's EXPOSED_TO seeds → pi_topk, the entities they are exposed to and why.

Seed    = {key, role, weight: int}
Nbr     = {key, rel_type, strength: float, freq?: int}
PiEntry = {entity, score, path: {seed, role, via: [intermediate keys], relations: [rel types]}}

A path reads seed -relations[0]-> via[0] -relations[1]-> ... -> entity, so a seed has relations=[],
a hop-1 entity has via=[] and one relation, and a hop-2 entity has one via and two relations.

Scores: seed = weight / max weight level. A hop takes each source's top-`top` neighbours by strength
(ties → higher freq, then key) and scores them source × rel_weight × strength / max strength × factor
(factor 1 for hop 1, hop2_decay for hop 2). Per entity the best path is kept. Seeds keep their own score and
are never changed by a hop; hop 2 expands only the hop-1 entities that aren't seeds.
"""

from typing import Dict, List, Optional


def seed_score(weight: int, cfg) -> float:
    return min(1.0, max(0.0, float(weight) / max(cfg.weight_levels.values())))


def rel_weight(rel_type: str, cfg) -> float:
    """Neo4j relationship type → rel_type_map → rel_weights, else the UNKNOWN weight."""
    mapped = cfg.rel_type_map.get(rel_type, rel_type)
    return float(cfg.rel_weights.get(mapped, cfg.rel_weights.get("UNKNOWN", 0.0)))


def _keep_best(target: Dict[str, Dict], entry: Dict) -> None:
    current = target.get(entry["entity"])
    if current is None or entry["score"] > current["score"]:
        target[entry["entity"]] = entry


def hop(frontier: Dict[str, Dict], nbrs: Dict[str, List[Dict]], top: int,
        factor: float, cfg) -> Dict[str, Dict]:
    """Expand each frontier entity through its `top` strongest neighbours. Returns the best entry per entity."""
    results: Dict[str, Dict] = {}
    for source, source_entry in frontier.items():
        strongest = sorted(
            (n for n in nbrs.get(source, []) if float(n.get("strength") or 0) > 0 and n["key"] != source),
            key=lambda n: (-float(n["strength"]), -int(n.get("freq") or 0), n["key"]),
        )[:max(0, top)]
        if not strongest:
            continue
        max_strength = float(strongest[0]["strength"])
        prior = source_entry["path"]
        # the source is an intermediate unless it is the seed itself
        via = [*prior["via"], source] if prior["relations"] else []
        for neighbour in strongest:
            relation = neighbour.get("rel_type") or "UNKNOWN"
            score = (source_entry["score"] * rel_weight(relation, cfg)
                     * float(neighbour["strength"]) / max_strength * factor)
            _keep_best(results, {
                "entity": neighbour["key"],
                "score": score,
                "path": {"seed": prior["seed"], "role": prior["role"], "via": via,
                         "relations": [*prior["relations"], relation]},
            })
    return results


def spread(seeds: List[Dict], hop1: Dict[str, List[Dict]],
           hop2: Optional[Dict[str, List[Dict]]], cfg) -> List[Dict]:
    """seeds ∪ hop 1 ∪ hop 2 (if enabled and given), best path per entity, sorted by score desc, ≤ pi_topk_max."""
    seed_entries: Dict[str, Dict] = {}
    for seed in seeds:
        _keep_best(seed_entries, {
            "entity": seed["key"],
            "score": seed_score(seed["weight"], cfg),
            "path": {"seed": seed["key"], "role": seed["role"], "via": [], "relations": []},
        })

    entries = dict(seed_entries)
    first_hop = {k: e for k, e in hop(seed_entries, hop1, cfg.hop1_top, 1.0, cfg).items()
                 if k not in seed_entries}
    for entry in first_hop.values():
        _keep_best(entries, entry)

    if cfg.enable_hop2 and hop2 is not None:
        for key, entry in hop(first_hop, hop2, cfg.hop2_top, cfg.hop2_decay, cfg).items():
            if key not in seed_entries:
                _keep_best(entries, entry)

    ranked = sorted(entries.values(), key=lambda item: (-item["score"], item["entity"]))[:cfg.pi_topk_max]
    return [{**e, "score": round(e["score"], 6)} for e in ranked]


def canonical(key: str, aliases: Optional[Dict[str, str]]) -> str:
    return (aliases or {}).get(key, key)


def with_alias_sources(keys: List[str], aliases: Optional[Dict[str, str]]) -> List[str]:
    """The keys plus every alias that points at one of them — the graph nodes to query for canonical keys."""
    wanted = set(keys)
    return list(dict.fromkeys([*keys, *sorted(a for a, t in (aliases or {}).items() if t in wanted)]))


def canonicalize_seeds(seeds: List[Dict], aliases: Optional[Dict[str, str]]) -> List[Dict]:
    return [{**s, "key": canonical(s["key"], aliases)} for s in seeds]


def canonicalize_nbrs(nbrs: Dict[str, List[Dict]], aliases: Optional[Dict[str, str]]) -> Dict[str, List[Dict]]:
    """
    Map sources and neighbours through entity_aliases ("man city" → "manchester city"), so an alias is never its
    own neighbour: self-loops are dropped, and a neighbour reached under several spellings is merged per relation
    type (strength and freq summed, like the type variants in ExposureStore.neighbours).
    """
    out: Dict[str, Dict] = {}
    for src, lst in nbrs.items():
        csrc = canonical(src, aliases)
        acc = out.setdefault(csrc, {})
        for n in lst:
            key = canonical(n["key"], aliases)
            if key == csrc:
                continue
            slot = (key, n.get("rel_type"))
            if slot in acc:
                acc[slot]["strength"] = float(acc[slot]["strength"]) + float(n.get("strength") or 0)
                acc[slot]["freq"] = int(acc[slot].get("freq") or 0) + int(n.get("freq") or 0)
            else:
                acc[slot] = {**n, "key": key}
    return {src: sorted(acc.values(), key=lambda n: (-float(n["strength"]), -int(n.get("freq") or 0), n["key"]))
            for src, acc in out.items()}


def hop1_keys(pi: List[Dict]) -> List[str]:
    """Keys whose best path is one hop long — the frontier the hop-2 neighbour query must fetch."""
    return [e["entity"] for e in pi if len(e["path"]["relations"]) == 1]
