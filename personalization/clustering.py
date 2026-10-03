"""
MAPNAI — personalization/clustering.py
Event clustering (pure): assigns new articles to clusters given their FAISS neighbours, a similarity function
and article metadata.

ArtMeta = {article_id, published: datetime | ISO str, entity_keys: [str], title: str, cluster_id?: str}

Pair rule (`pair_joins`): two articles are linked when
    cos ≥ cos_strong                                                        (no-evidence override), or
    |Δt| ≤ cluster_time_h ∧ cos ≥ cos_join ∧ (fuzzy shared entity ∨ title Jaccard ≥ title_jaccard_min).
Cluster rule (`assign_clusters`): an article joins a cluster when it is linked to at least one member and its
mean similarity to all members is ≥ cos_join − chain_margin (the anti-chaining guard). Among qualifying clusters
the best max-similarity wins (ties → smaller cluster_id); otherwise the article starts a new cluster whose id is
its own article_id. Two existing clusters are never merged; a would-be merge is reported in `merge_candidates`.
"""

import re
import unicodedata
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from rapidfuzz import fuzz

from personalization.scoring import parse_ts

_EPOCH = datetime.min.replace(tzinfo=timezone.utc)
_NON_ALNUM = re.compile(r"[^a-z0-9]+")
_POSSESSIVE = re.compile(r"'s\b", re.IGNORECASE)

# English function words plus news-title filler; kept small and explicit so Jaccard stays predictable
STOPWORDS = frozenset("""
a an the and or but nor of in on at to for from by with without into onto over under after before about as
is are was were be been being am do does did has have had having will would shall should can could may might
must it its this that these those there here he she they them their his her him we our you your i me my
not no so than then too very just also more most much many some any all each both few other such only own
same up down out off again further once new says say said vs v via amid as per how what when where who whom
why which while live watch update updates latest news report reports video photos
""".split())


def _published(meta: Dict) -> datetime:
    return parse_ts(meta.get("published")) or _EPOCH


def _fold(text: str) -> str:
    """Drop possessive 's, strip accents, lower-case, punctuation → spaces."""
    text = _POSSESSIVE.sub("", str(text or "").replace("’", "'"))
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii").lower()
    return _NON_ALNUM.sub(" ", text).strip()


def normalize_entity(name: str) -> str:
    """
    Entity key for fuzzy matching: accents/punctuation stripped, lower-case, possessive 's and a leading "the"
    dropped, and standalone number tokens dropped (so "Sarapatta 2" → "sarapatta", "The Asian Games 2026" →
    "asian games").
    """
    tokens = _fold(name).split()
    if tokens and tokens[0] == "the":
        tokens = tokens[1:]
    return " ".join(t for t in tokens if not t.isdigit())


def fuzzy_shared_entities(keys_a: Sequence[str], keys_b: Sequence[str], min_ratio: float) -> List[Tuple[str, str]]:
    """Pairs (a, b) whose normalized names are equal or have rapidfuzz ratio ≥ min_ratio."""
    norm_b = [(k, normalize_entity(k)) for k in keys_b]
    out = []
    for ka in keys_a:
        na = normalize_entity(ka)
        if not na:
            continue
        for kb, nb in norm_b:
            if nb and (na == nb or fuzz.ratio(na, nb) >= min_ratio):
                out.append((ka, kb))
                break
    return out


def title_tokens(title: str) -> set:
    return {t for t in _fold(title).split() if len(t) > 1 and t not in STOPWORDS}


def title_jaccard(title_a: str, title_b: str) -> float:
    a, b = title_tokens(title_a), title_tokens(title_b)
    return len(a & b) / len(a | b) if a and b else 0.0


def evidence(left: Dict, right: Dict, cfg) -> Dict:
    """{entities: [(a, b)], jaccard, ok}: the non-embedding evidence that two articles are the same event."""
    shared = fuzzy_shared_entities(left.get("entity_keys") or [], right.get("entity_keys") or [],
                                   cfg.fuzzy_entity_min)
    jac = title_jaccard(left.get("title") or "", right.get("title") or "")
    return {"entities": shared, "jaccard": round(jac, 4), "ok": bool(shared) or jac >= cfg.title_jaccard_min}


def pair_joins(left: Dict, right: Dict, cosine: float, cfg, cos_join: Optional[float] = None) -> bool:
    """The pair rule. cos_join overrides cfg.cos_join (used by the calibration sweep)."""
    if cosine >= cfg.cos_strong:
        return True
    threshold = cfg.cos_join if cos_join is None else cos_join
    if cosine < threshold:
        return False
    delta_h = abs((_published(left) - _published(right)).total_seconds()) / 3600.0
    return delta_h <= cfg.cluster_time_h and evidence(left, right, cfg)["ok"]


def assign_clusters(new: List[Dict], neighbours: Dict[str, List[Tuple[str, float]]], known: Dict[str, Dict],
                    cfg, sim: Optional[Callable[[str, str], Optional[float]]] = None) -> List[Dict]:
    """
    new: unclustered articles; neighbours: article_id → [(neighbour_id, cos)] (candidate clusters come from these);
    known: already-clustered articles (article_id → ArtMeta with cluster_id); sim(a, b) → cosine or None
    (defaults to the neighbour lists only). New articles are processed oldest first, so earlier reports seed
    clusters and later ones are compared against every member so far.
    Returns one op per new article: {article_id, cluster_id, created, best_cos, mean_cos, merge_candidates}.
    """
    metadata = dict(known)
    members: Dict[str, List[str]] = {}
    for a, m in known.items():
        if m.get("cluster_id"):
            members.setdefault(m["cluster_id"], []).append(a)
    nn = {a: dict(hits) for a, hits in neighbours.items()}

    def similarity(a: str, b: str) -> Optional[float]:
        if b in nn.get(a, {}):
            return float(nn[a][b])
        return sim(a, b) if sim else None

    operations = []
    for article in sorted(new, key=lambda item: (_published(item), item["article_id"])):
        article_id = article["article_id"]
        candidates = {metadata[b]["cluster_id"] for b, _ in neighbours.get(article_id, [])
                      if b != article_id and b in metadata and metadata[b].get("cluster_id")}
        qualified: Dict[str, Tuple[float, float]] = {}
        for cid in candidates:
            sims = [(m, similarity(article_id, m)) for m in members.get(cid, []) if m != article_id]
            sims = [(m, s) for m, s in sims if s is not None]
            if not sims:
                continue
            best = max(s for _, s in sims)
            mean = sum(s for _, s in sims) / len(sims)
            linked = any(pair_joins(article, metadata[m], s, cfg) for m, s in sims)
            if linked and mean >= cfg.cos_join - cfg.chain_margin:
                qualified[cid] = (best, mean)

        if qualified:
            cluster_id = min(qualified, key=lambda k: (-qualified[k][0], k))
            best_cos, mean_cos = qualified[cluster_id]
            merge_candidates, created = sorted(k for k in qualified if k != cluster_id), False
        else:
            cluster_id, best_cos, mean_cos, merge_candidates, created = article_id, None, None, [], True
        metadata[article_id] = {**article, "cluster_id": cluster_id}
        members.setdefault(cluster_id, []).append(article_id)
        operations.append({
            "article_id": article_id,
            "cluster_id": cluster_id,
            "created": created,
            "best_cos": best_cos,
            "mean_cos": None if mean_cos is None else round(mean_cos, 4),
            "merge_candidates": merge_candidates,
        })
    return operations


def cluster_summary(members: List[Dict]) -> Dict:
    """size, first_report (earliest published; tie → smaller article_id), first_published, entity key union."""
    if not members:
        return {"size": 0, "first_report": None, "first_published": None, "entity_keys": []}
    first = min(members, key=lambda item: (_published(item), item["article_id"]))
    return {
        "size": len(members),
        "first_report": first["article_id"],
        "first_published": first.get("published"),
        "entity_keys": sorted({key for item in members for key in (item.get("entity_keys") or [])}),
    }
