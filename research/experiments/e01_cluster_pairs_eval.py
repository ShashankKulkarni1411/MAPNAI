"""
E01 — Event-clustering pair rule: honest estimates, ablations and a near-duplicate baseline.

Data:   tests/data/cluster_pairs.jsonl (63 hand-labelled pairs; read-only)
Model:  personalization/clustering.py pair rule with config/personalization.py defaults (no .env overrides)
Output: results/e01_cluster_pairs_<tag>.json and results/e01_cluster_pairs_sweep_<tag>.csv

What it reports
  1. The configured rule (cos_join 0.77) on all pairs, with Wilson and pair-bootstrap 95% CIs.
     NOTE: cos_join was chosen on these same pairs, so (1) is an in-sample figure.
  2. Leave-one-out estimate of the *threshold-selection procedure* (the selection rule of
     scripts/calibrate_clustering.py, and a max-F1 variant): the threshold is chosen on 62 pairs and applied to
     the held-out pair.
  3. Ablations of the rule (cosine only; evidence components removed; evidence only), swept over thresholds.
  4. Rank-based AUROC of cosine and of title Jaccard for same_event.
  5. MAPNAI's ingestion near-duplicate detectors (SimHash Hamming ≤ 3, MinHash LSH J ≥ 0.5) on title + snippet.
Limitations: the pairs were sampled from the cosine band 0.68–0.89 (not at random), share articles (94 distinct
articles), and carry ~220-character snippets instead of the full body.

    python research/experiments/e01_cluster_pairs_eval.py --tag 2026-10-23
"""

import argparse
import json
import random
from datetime import datetime, timedelta, timezone
from typing import Callable, Dict, List

from _common import ROOT, prf, run_metadata, utf8_stdout, wilson, write_csv, write_json

from config.personalization import PersonalizationSettings
from personalization import clustering

PAIRS = ROOT / "tests" / "data" / "cluster_pairs.jsonl"
T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
GRID = [round(0.66 + 0.01 * i, 2) for i in range(25)]          # 0.66 … 0.90
CAL_GRID = [round(0.70 + 0.01 * i, 2) for i in range(13)]      # the calibration script's grid 0.70 … 0.82


def load() -> List[Dict]:
    with PAIRS.open(encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def metas(row: Dict):
    left = {"article_id": row["a"], "published": T0, "title": row["title_a"], "entity_keys": row["entity_keys_a"]}
    right = {"article_id": row["b"], "published": T0 + timedelta(hours=row["dt_h"]), "title": row["title_b"],
             "entity_keys": row["entity_keys_b"]}
    return left, right


def make_rule(cfg, *, use_strong=True, use_time=True, use_entities=True, fuzzy=True, use_jaccard=True,
              use_cos=True) -> Callable[[Dict, float], bool]:
    """A re-implementation of clustering.pair_joins with switchable parts (checked against it in main)."""
    def rule(row: Dict, t: float) -> bool:
        cos = row["cos"]
        if use_strong and cos >= cfg.cos_strong:
            return True
        if use_cos and cos < t:
            return False
        if use_time and abs(row["dt_h"]) > cfg.cluster_time_h:
            return False
        ent = False
        if use_entities:
            if fuzzy:
                ent = bool(clustering.fuzzy_shared_entities(row["entity_keys_a"], row["entity_keys_b"],
                                                            cfg.fuzzy_entity_min))
            else:
                na = {clustering.normalize_entity(k) for k in row["entity_keys_a"]} - {""}
                nb = {clustering.normalize_entity(k) for k in row["entity_keys_b"]} - {""}
                ent = bool(na & nb)
        jac = use_jaccard and clustering.title_jaccard(row["title_a"], row["title_b"]) >= cfg.title_jaccard_min
        return ent or jac
    return rule


def confusion(rows: List[Dict], pred: Callable[[Dict], bool]) -> Dict:
    tp = fp = fn = tn = 0
    for r in rows:
        p, g = pred(r), bool(r["same_event"])
        tp += p and g
        fp += p and not g
        fn += g and not p
        tn += (not p) and (not g)
    return {"tp": tp, "fp": fp, "fn": fn, "tn": tn, **prf(tp, fp, fn)}


def bootstrap_f1(rows, pred, b: int, seed: int) -> Dict:
    rng = random.Random(seed)
    preds = [(pred(r), bool(r["same_event"])) for r in rows]
    stats = {"precision": [], "recall": [], "f1": []}
    for _ in range(b):
        s = [preds[rng.randrange(len(preds))] for _ in preds]
        tp = sum(p and g for p, g in s)
        fp = sum(p and not g for p, g in s)
        fn = sum(g and not p for p, g in s)
        m = prf(tp, fp, fn)
        for k in stats:
            if m[k] is not None:
                stats[k].append(m[k])
    out = {}
    for k, v in stats.items():
        v.sort()
        out[k] = [round(v[int(0.025 * len(v))], 4), round(v[int(0.975 * len(v)) - 1], 4)] if v else None
    return out


def choose_calibration(rows, rule, min_precision: float) -> float:
    """scripts/calibrate_clustering.choose: lowest t with precision ≥ min_precision, else highest precision (lowest t)."""
    res = [(t, confusion(rows, lambda r: rule(r, t))) for t in CAL_GRID]
    ok = [t for t, m in res if (m["precision"] or 0) >= min_precision]
    if ok:
        return min(ok)
    best = max((m["precision"] or 0) for _, m in res)
    return min(t for t, m in res if (m["precision"] or 0) == best)


def choose_f1(rows, rule) -> float:
    res = [(t, confusion(rows, lambda r: rule(r, t))["f1"] or 0.0) for t in CAL_GRID]
    best = max(f for _, f in res)
    return min(t for t, f in res if f == best)


def loocv(rows, rule, chooser) -> Dict:
    held, chosen = [], []
    for i, r in enumerate(rows):
        train = rows[:i] + rows[i + 1:]
        t = chooser(train, rule)
        chosen.append(t)
        held.append((rule(r, t), bool(r["same_event"])))
    tp = sum(p and g for p, g in held)
    fp = sum(p and not g for p, g in held)
    fn = sum(g and not p for p, g in held)
    tn = sum((not p) and (not g) for p, g in held)
    return {"tp": tp, "fp": fp, "fn": fn, "tn": tn, **prf(tp, fp, fn),
            "chosen_thresholds": {str(t): chosen.count(t) for t in sorted(set(chosen))}}


def auroc(scores: List[float], labels: List[bool]) -> float:
    """Mann–Whitney AUROC with ties counted as 0.5."""
    pos = [s for s, y in zip(scores, labels) if y]
    neg = [s for s, y in zip(scores, labels) if not y]
    wins = sum((p > n) + 0.5 * (p == n) for p in pos for n in neg)
    return wins / (len(pos) * len(neg))


def dedup_baseline(rows) -> Dict:
    from utils.deduplicator import MinHashDeduplicator, compute_simhash, simhash_distance
    sim_pred, mh_pred, ham = [], [], []
    for r in rows:
        ha = compute_simhash(r["title_a"], r.get("snippet_a") or "")
        hb = compute_simhash(r["title_b"], r.get("snippet_b") or "")
        d = simhash_distance(ha, hb)
        ham.append(d)
        sim_pred.append(d <= 3)
        mh = MinHashDeduplicator(threshold=0.5, num_perm=128)
        mh.is_duplicate(r["a"], r["title_a"], r.get("snippet_a") or "")
        mh_pred.append(mh.is_duplicate(r["b"], r["title_b"], r.get("snippet_b") or ""))
    gold = [bool(r["same_event"]) for r in rows]

    def cm(pred):
        tp = sum(p and g for p, g in zip(pred, gold))
        fp = sum(p and not g for p, g in zip(pred, gold))
        fn = sum(g and not p for p, g in zip(pred, gold))
        return {"tp": tp, "fp": fp, "fn": fn, **prf(tp, fp, fn)}
    return {"simhash_hamming_le_3": cm(sim_pred), "minhash_lsh_j_ge_0.5": cm(mh_pred),
            "union": cm([a or b for a, b in zip(sim_pred, mh_pred)]),
            "hamming_min_median_max": [min(ham), sorted(ham)[len(ham) // 2], max(ham)],
            "input_note": "title + ~220-char snippet (production uses title + body[:500])"}


def main() -> int:
    utf8_stdout()
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", required=True)
    ap.add_argument("--bootstrap", type=int, default=5000)
    ap.add_argument("--seed", type=int, default=13)
    args = ap.parse_args()

    rows = load()
    cfg = PersonalizationSettings(_env_file=None)
    current = make_rule(cfg)

    # sanity: the re-implementation equals clustering.pair_joins on every pair and threshold
    for t in GRID:
        for r in rows:
            a, b = metas(r)
            assert current(r, t) == clustering.pair_joins(a, b, r["cos"], cfg, cos_join=t), (r["id"], t)

    variants = {
        "cosine_only": make_rule(cfg, use_strong=False, use_time=False, use_entities=False, use_jaccard=False),
        "current_rule": current,
        "no_title_jaccard": make_rule(cfg, use_jaccard=False),
        "no_entity_evidence": make_rule(cfg, use_entities=False),
        "exact_entities_only": make_rule(cfg, fuzzy=False),
        "no_strong_override": make_rule(cfg, use_strong=False),
        "evidence_only_no_cos": make_rule(cfg, use_strong=False, use_cos=False),
    }
    # cosine_only must ignore evidence: evaluate it as cos ≥ t
    variants["cosine_only"] = lambda r, t: r["cos"] >= t

    sweep = []
    for name, rule in variants.items():
        for t in GRID:
            m = confusion(rows, lambda r: rule(r, t))
            sweep.append({"variant": name, "threshold": t, **{k: (round(v, 4) if isinstance(v, float) else v)
                                                              for k, v in m.items()}})

    at_cfg = {name: confusion(rows, lambda r: rule(r, cfg.cos_join)) for name, rule in variants.items()}
    cur = at_cfg["current_rule"]
    result = {
        "meta": run_metadata("research/experiments/e01_cluster_pairs_eval.py", seed=args.seed,
                             bootstrap_resamples=args.bootstrap),
        "data": {"file": "tests/data/cluster_pairs.jsonl", "pairs": len(rows),
                 "positives": sum(bool(r["same_event"]) for r in rows),
                 "distinct_articles": len({r["a"] for r in rows} | {r["b"] for r in rows}),
                 "cos_range": [min(r["cos"] for r in rows), max(r["cos"] for r in rows)],
                 "dt_h_max": max(r["dt_h"] for r in rows)},
        "config": {k: getattr(cfg, k) for k in ("cos_join", "cos_strong", "cluster_time_h", "fuzzy_entity_min",
                                                 "title_jaccard_min", "chain_margin")},
        "equivalence_check": "re-implemented rule == clustering.pair_joins on all pairs × thresholds: passed",
        "current_rule_in_sample": {
            **cur,
            "precision_wilson95": wilson(cur["tp"], cur["tp"] + cur["fp"]),
            "recall_wilson95": wilson(cur["tp"], cur["tp"] + cur["fn"]),
            "pair_bootstrap95": bootstrap_f1(rows, lambda r: current(r, cfg.cos_join), args.bootstrap, args.seed),
            "caveat": "cos_join was selected on these pairs: in-sample",
        },
        "loocv_threshold_selection": {
            "calibration_rule_min_precision_0.95": loocv(rows, current, lambda tr, ru: choose_calibration(tr, ru, 0.95)),
            "max_f1_rule": loocv(rows, current, choose_f1),
        },
        "variants_at_configured_threshold": at_cfg,
        "auroc_same_event": {
            "cosine": round(auroc([r["cos"] for r in rows], [bool(r["same_event"]) for r in rows]), 4),
            "title_jaccard": round(auroc([clustering.title_jaccard(r["title_a"], r["title_b"]) for r in rows],
                                         [bool(r["same_event"]) for r in rows]), 4),
            "note": "within the sampled cosine band only",
        },
        "near_duplicate_baseline": dedup_baseline(rows),
    }
    out = write_json(f"e01_cluster_pairs_{args.tag}.json", result)
    out_csv = write_csv(f"e01_cluster_pairs_sweep_{args.tag}.csv", sweep)
    print(json.dumps({k: result[k] for k in ("current_rule_in_sample", "loocv_threshold_selection",
                                             "auroc_same_event", "near_duplicate_baseline")}, indent=1, default=str))
    print("variants @cfg:", {k: (v["precision"], v["recall"], v["f1"]) for k, v in at_cfg.items()})
    print("wrote", out, out_csv)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
