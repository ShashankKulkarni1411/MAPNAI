"""
Calibrate PERS_COS_JOIN on the labelled pair set tests/data/cluster_pairs.jsonl.
Sweeps cos_join over [0.70, 0.82] in 0.01 steps with the pair rule of personalization/clustering.py and prints
precision / recall / F1 per threshold, then the lowest threshold with precision ≥ --min-precision.
Offline: the file carries each pair's cosine, time gap, titles and entity keys.

    python scripts/calibrate_clustering.py [--file PATH] [--min-precision 0.95]
"""

import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Tuple

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from config.personalization import PersonalizationSettings  # noqa: E402
from personalization.clustering import pair_joins  # noqa: E402

DEFAULT_FILE = os.path.join(ROOT, "tests", "data", "cluster_pairs.jsonl")
_T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)


def load_pairs(path: str) -> List[Dict]:
    with open(path, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def as_meta(row: Dict) -> tuple:
    left = {"article_id": row["a"], "published": _T0, "title": row["title_a"], "entity_keys": row["entity_keys_a"]}
    right = {"article_id": row["b"], "published": _T0 + timedelta(hours=row["dt_h"]), "title": row["title_b"],
             "entity_keys": row["entity_keys_b"]}
    return left, right


def score(rows: List[Dict], cfg, threshold: float) -> Dict:
    tp = fp = fn = tn = 0
    for row in rows:
        left, right = as_meta(row)
        pred, gold = pair_joins(left, right, row["cos"], cfg, cos_join=threshold), row["same_event"]
        tp += pred and gold
        fp += pred and not gold
        fn += gold and not pred
        tn += not pred and not gold
    precision = tp / (tp + fp) if tp + fp else 1.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {"t": round(threshold, 2), "tp": tp, "fp": fp, "fn": fn, "tn": tn,
            "precision": precision, "recall": recall, "f1": f1}


def sweep(rows: List[Dict], cfg, lo: float = 0.70, hi: float = 0.82, step: float = 0.01) -> List[Dict]:
    n = int(round((hi - lo) / step)) + 1
    return [score(rows, cfg, lo + i * step) for i in range(n)]


def choose(results: List[Dict], min_precision: float) -> Tuple[float, bool]:
    """
    (threshold, target_met): the lowest threshold with precision ≥ min_precision; if none reaches it,
    the highest-precision threshold (ties → lowest, i.e. the most recall), with target_met=False.
    """
    ok = [r["t"] for r in results if r["precision"] >= min_precision]
    if ok:
        return min(ok), True
    best = max(r["precision"] for r in results)
    return min(r["t"] for r in results if r["precision"] == best), False


def main() -> int:
    parser = argparse.ArgumentParser(description="Sweep PERS_COS_JOIN on the labelled pairs")
    parser.add_argument("--file", default=DEFAULT_FILE)
    parser.add_argument("--min-precision", type=float, default=0.95)
    args = parser.parse_args()

    rows = load_pairs(args.file)
    cfg = PersonalizationSettings(_env_file=None)
    results = sweep(rows, cfg)
    print(f"{len(rows)} pairs, {sum(r['same_event'] for r in rows)} same_event; "
          f"cos_strong={cfg.cos_strong} time≤{cfg.cluster_time_h}h fuzzy≥{cfg.fuzzy_entity_min} "
          f"jaccard≥{cfg.title_jaccard_min}")
    print("| cos_join | TP | FP | FN | TN | precision | recall | F1 |")
    print("|---|---|---|---|---|---|---|---|")
    for r in results:
        print(f"| {r['t']:.2f} | {r['tp']} | {r['fp']} | {r['fn']} | {r['tn']} | "
              f"{r['precision']:.3f} | {r['recall']:.3f} | {r['f1']:.3f} |")
    chosen, met = choose(results, args.min_precision)
    if met:
        print(f"lowest threshold with precision ≥ {args.min_precision}: {chosen}")
    else:
        print(f"NO threshold reaches precision ≥ {args.min_precision}; "
              f"highest precision (ties → lowest threshold): {chosen}")
    print(f"current default cos_join = {cfg.cos_join}")
    return 0 if met else 1


if __name__ == "__main__":
    sys.exit(main())
