"""
MAPNAI — personalization/slate.py
The digest slate (pure: no DB, no clock; the RNG is injected).

  need      = m × max pi over the article's entities (the path of that entity explains it)
  rel       = interest + need_bonus · need                     (the ranking score outside must_know)
  must_know = need ≥ τ, by need desc, at most must_know_max; the overflow goes to `more_you_need` (never dropped)
  for_you   = MMR over the rest: argmax λ·rel − (1 − λ)·max sim(item, already picked), under per-topic caps
  explore   = Thompson sampling over topics the slate doesn't have yet, logged with its propensity

Topic caps: per_topic_cap (hard), tightened by calibration to round(share_t · k) + 1 for declared topics and 1 for
undeclared ones. If the calibrated caps can't fill the slate, they are relaxed back to per_topic_cap. must_know items
count towards the caps but are never removed by them.
"""

import hashlib
from typing import Callable, Dict, List, Optional, Sequence, Set, Tuple

from personalization.interest import prior
from personalization.keys import beta_key
from personalization.scoring import topic_shares

UNKNOWN_TOPIC = "unknown"

MUST_KNOW, FOR_YOU, EXPLORE, MORE_YOU_NEED = "must_know", "for_you", "explore", "more_you_need"


def topic_of(item: Dict) -> str:
    return str(item.get("topic") or UNKNOWN_TOPIC).strip().lower()


def cluster_key(item: Dict) -> str:
    return item.get("cluster_id") or item["article_id"]


# ── Need ─────────────────────────────────────────────────────

def pi_hits(entity_keys: Sequence[str], pi: Dict[str, Dict]) -> List[Dict]:
    """The pi entries of the article's entities, best first (ties → entity key)."""
    hits = {k: pi[k] for k in entity_keys if k in pi}
    return sorted(hits.values(), key=lambda e: (-float(e["score"]), e["entity"]))


def need(entity_keys: Sequence[str], m: Optional[float], pi: Dict[str, Dict]) -> Tuple[float, Optional[Dict]]:
    """need = m × max pi over the article's entities → (need, the pi entry that gives it | None)."""
    hits = pi_hits(entity_keys, pi)
    if not hits:
        return 0.0, None
    return round(float(m or 0.0) * float(hits[0]["score"]), 6), hits[0]


def relevance(interest: float, need_value: float, cfg) -> float:
    return round(float(interest) + cfg.need_bonus * float(need_value), 6)


# ── must_know ────────────────────────────────────────────────

def pick_must_know(items: Sequence[Dict], tau: float, cfg) -> Tuple[List[Dict], List[Dict]]:
    """Items with need ≥ τ by need desc (then rel, article_id) → (the first must_know_max, the overflow)."""
    above = sorted((i for i in items if float(i.get("need") or 0.0) >= tau),
                   key=lambda i: (-float(i["need"]), -float(i.get("rel") or 0.0), i["article_id"]))
    return above[: cfg.must_know_max], above[cfg.must_know_max:]


# ── Calibration + MMR ────────────────────────────────────────

def calibration_caps(declared: Dict[str, float], k: int, cfg) -> Dict[str, int]:
    """Declared topic t → round(share_t · k) + 1 (undeclared topics get 1: see topic_cap)."""
    return {t: int(round(s * k)) + 1 for t, s in topic_shares(declared).items()}


def topic_cap(topic: str, caps: Optional[Dict[str, int]], cfg) -> int:
    """per_topic_cap, tightened by the calibration caps when they are given (an undeclared topic → 1)."""
    if caps is None:
        return cfg.per_topic_cap
    return min(cfg.per_topic_cap, caps.get(topic, 1))


def mmr(items: Sequence[Dict], sim: Callable[[str, str], float], k: int, cfg,
        caps: Optional[Dict[str, int]] = None, selected: Sequence[Dict] = ()) -> List[Dict]:
    """
    Maximal marginal relevance: repeatedly take argmax λ·rel − (1 − λ)·max sim to everything picked so far
    (`selected` counts as picked, for both diversity and the topic caps). λ = 1 (or enable_mmr off) is greedy by rel.
    Items whose topic is at its cap are skipped. Returns at most k items; fewer when the caps run out.
    """
    lam = cfg.mmr_lambda if cfg.enable_mmr else 1.0
    picked: List[Dict] = list(selected)
    counts: Dict[str, int] = {}
    for item in picked:
        counts[topic_of(item)] = counts.get(topic_of(item), 0) + 1
    pool = list(items)
    out: List[Dict] = []
    while len(out) < k and pool:
        best, best_key = None, None
        for item in pool:
            topic = topic_of(item)
            if counts.get(topic, 0) >= topic_cap(topic, caps, cfg):
                continue
            div = max((sim(item["article_id"], p["article_id"]) for p in picked), default=0.0) if lam < 1 else 0.0
            score = lam * float(item["rel"]) - (1 - lam) * div
            key = (-score, -float(item["rel"]), item["article_id"])
            if best_key is None or key < best_key:
                best, best_key = item, key
        if best is None:
            break
        out.append(best)
        picked.append(best)
        pool.remove(best)
        counts[topic_of(best)] = counts.get(topic_of(best), 0) + 1
    return out


# ── Thompson explore ─────────────────────────────────────────

def rng_seed(user_id: str, date: str) -> int:
    """A stable seed per (user, local date), so a digest's explore draw and propensity are reproducible."""
    return int(hashlib.sha256(f"{user_id}|{date}".encode("utf-8")).hexdigest()[:16], 16)


def topic_beta(beta: Dict[str, Sequence[float]], topic: str, declared: Dict[str, float], cfg) -> List[float]:
    """The topic's learned Beta, else its declared-weight prior, else the flat [1, 1]."""
    key = beta_key("topic", topic)
    if key in beta:
        return [float(x) for x in beta[key]]
    w = (declared or {}).get(topic)
    return prior(w, cfg) if w is not None else [1.0, 1.0]


def thompson_explore(pool: Sequence[Dict], slate_topics: Set[str], beta: Dict[str, Sequence[float]],
                     declared: Dict[str, float], rng, cfg) -> Tuple[Optional[Dict], float]:
    """
    Among pool items whose topic is not in the slate: draw θ_t ~ Beta(topic t) once per topic, take the top-draw
    topic and its highest-m article (then rel, article_id). Propensity = the probability that this article is picked,
    estimated by re-running the draw propensity_sims times on the same RNG stream; the original draw is counted too,
    so it is in (0, 1]. → (item, propensity), or (None, 0.0) when the pool is empty.
    """
    by_topic: Dict[str, Dict] = {}
    for item in pool:
        topic = topic_of(item)
        if topic in slate_topics:
            continue
        cur = by_topic.get(topic)
        key = (-float(item.get("m") or 0.0), -float(item.get("rel") or 0.0), item["article_id"])
        if cur is None or key < (-float(cur.get("m") or 0.0), -float(cur.get("rel") or 0.0), cur["article_id"]):
            by_topic[topic] = item
    if not by_topic:
        return None, 0.0
    topics = sorted(by_topic)
    params = [topic_beta(beta, t, declared, cfg) for t in topics]

    def draw() -> str:
        thetas = [rng.beta(a, b) for a, b in params]
        return topics[max(range(len(topics)), key=lambda i: (thetas[i], -i))]

    chosen = draw()
    sims = max(0, int(cfg.propensity_sims))
    hits = sum(1 for _ in range(sims) if draw() == chosen)
    return by_topic[chosen], round((1 + hits) / (1 + sims), 6)


# ── Slate ────────────────────────────────────────────────────

def dedupe_clusters(items: Sequence[Dict]) -> List[Dict]:
    """Keep the first item per cluster (items are expected best-first)."""
    seen: Set[str] = set()
    out = []
    for item in items:
        ck = cluster_key(item)
        if ck not in seen:
            seen.add(ck)
            out.append(item)
    return out


def build_slate(items: Sequence[Dict], tau: float, persona: Dict, sim: Callable[[str, str], float], rng,
                cfg) -> Dict:
    """
    items: collapsed candidates, each {article_id, topic, cluster_id, m, need, rel, ...}.
    → {items: [{..., section, slot, propensity}], more_you_need: [...], stats: {...}}
    Slate = must_know (≤ must_know_max) + for_you (MMR) + explore (explore_slots), k = slate_k in total.
    """
    k = cfg.slate_k
    items = dedupe_clusters(sorted(items, key=lambda i: (-float(i.get("rel") or 0.0), i["article_id"])))
    declared = {str(t).strip().lower(): float(w) for t, w in (persona.get("topics") or {}).items() if w}
    beta = persona.get("beta") or {}

    must, overflow = pick_must_know(items, tau, cfg)
    must = must[:k]
    taken = {i["article_id"] for i in must + overflow}
    pool = [i for i in items if i["article_id"] not in taken]

    caps = calibration_caps(declared, k, cfg) if cfg.enable_calibration and declared else None
    n_explore = min(cfg.explore_slots, k - len(must)) if cfg.enable_explore else 0
    n_fill = max(0, k - len(must) - n_explore)
    fill = mmr(pool, sim, n_fill, cfg, caps, selected=must)
    caps_relaxed = False
    if len(fill) < n_fill and caps is not None:
        caps_relaxed = True
        fill_ids = {i["article_id"] for i in fill}
        rest = [i for i in pool if i["article_id"] not in fill_ids]
        fill += mmr(rest, sim, n_fill - len(fill), cfg, None, selected=must + fill)

    explore: List[Dict] = []
    explore_skipped = False
    for _ in range(n_explore):
        in_slate = must + fill + explore
        slate_ids = {i["article_id"] for i in in_slate}
        rest = [i for i in pool if i["article_id"] not in slate_ids]
        pick, propensity = thompson_explore(rest, {topic_of(i) for i in in_slate}, beta, declared, rng, cfg)
        if pick is None:
            explore_skipped = True     # the slot goes to MMR
            fill += mmr(rest, sim, 1, cfg, None, selected=in_slate)
        else:
            explore.append({**pick, "propensity": propensity})

    out = ([{**i, "section": MUST_KNOW, "propensity": 1.0} for i in must]
           + [{**i, "section": FOR_YOU, "propensity": 1.0} for i in fill]
           + [{**i, "section": EXPLORE} for i in explore])
    for slot, item in enumerate(out, start=1):
        item["slot"] = slot
    more = [{**i, "section": MORE_YOU_NEED, "propensity": 1.0, "slot": None} for i in overflow]
    return {
        "items": out,
        "more_you_need": more,
        "stats": {"tau": tau, "above_tau": len(must) + len(overflow), "must_know": len(must),
                  "more_you_need": len(overflow), "for_you": len(fill), "explore": len(explore),
                  "explore_skipped": explore_skipped,
                  "topic_caps": ({**{t: topic_cap(t, caps, cfg) for t in caps}, "(undeclared)": topic_cap("", caps, cfg)}
                                 if caps is not None else {"(any)": cfg.per_topic_cap}),
                  "caps_relaxed": caps_relaxed,
                  "pool": len(pool)},
    }
