"""
E20 — any checker on LLM-AggreFact under the protocol in research/PREREG.md §2 (P-fixed: prediction = prob > 0.5, no
tuning; balanced accuracy × 100 per dataset; Average = unweighted mean over datasets).

Checkers:
  minicheck-ft5        MiniCheck-Flan-T5-Large @ 96eafd01 (minicheck @ b58b9fa, chunk 500, max len 2048)  [checker venv]
  minicheck-deberta    MiniCheck-DeBERTa-v3-Large @ 2f2d01a5 (chunk 400, max len 2048)                    [checker venv]

Resumable: per-instance probabilities are appended to cache/e20_<checker>_<split>_<tag>.jsonl in shards; a rerun with
the same tag skips scored rows. Output (write-once): results/e20_<checker>_<split>_<tag>.json (per-dataset BAcc with
95% bootstrap CIs, News-3 mean, 11-dataset average, 10-dataset average without RAGTruth, timings) and
results/e20_<checker>_<split>_<tag>_preds.jsonl.gz (row, dataset, label, prob, pred; no text).

Bootstrap: 2,000 resamples, seed 13, instances resampled within each dataset; averages are recomputed per replicate.
"""

import argparse
import gzip
import json
import os
import time
from pathlib import Path

import numpy as np

from _common import EXP_DIR, ROOT, run_metadata, utf8_stdout, write_json

os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
os.environ.setdefault("NLTK_DATA", str(ROOT / "models" / "nltk_data"))

DATA = EXP_DIR / "data" / "external" / "llm_aggrefact" / "data"
CACHE = EXP_DIR / "cache"
REVISION = "981dfd0bd8e58e7238a9ab92b2e6ea44bce918e4"
NEWS3 = ("AggreFact-CNN", "AggreFact-XSum", "TofuEval-MediaS")
CHECKERS = {"minicheck-ft5": "flan-t5-large", "minicheck-deberta": "deberta-v3-large"}
PUBLISHED = {"minicheck-ft5": {"avg11": 75.0, "avg10_paper": 74.7}, "minicheck-deberta": {"avg11": 73.1}}


def bacc(y, p) -> float:
    y, p = np.asarray(y), np.asarray(p)
    pos, neg = y == 1, y == 0
    tpr = (p[pos] == 1).mean() if pos.any() else np.nan
    tnr = (p[neg] == 0).mean() if neg.any() else np.nan
    return float(np.nanmean([tpr, tnr]) * 100)


def summarize(rows, n_boot: int = 2000, seed: int = 13) -> dict:
    by = {}
    for r in rows:
        by.setdefault(r["dataset"], []).append((r["label"], r["pred"]))
    names = sorted(by)
    arrays = {d: (np.array([a for a, _ in v]), np.array([b for _, b in v])) for d, v in by.items()}
    point = {d: bacc(*arrays[d]) for d in names}
    rng = np.random.default_rng(seed)
    boots = {d: [] for d in names}
    for _ in range(n_boot):
        for d in names:
            y, p = arrays[d]
            idx = rng.integers(0, len(y), len(y))
            boots[d].append(bacc(y[idx], p[idx]))
    boots = {d: np.array(v) for d, v in boots.items()}

    def agg(sel):
        sel = [d for d in sel if d in point]
        if not sel:
            return None
        reps = np.mean([boots[d] for d in sel], axis=0)
        return {"bacc": round(float(np.mean([point[d] for d in sel])), 2),
                "ci95": [round(float(np.percentile(reps, 2.5)), 2), round(float(np.percentile(reps, 97.5)), 2)],
                "datasets": sel}

    return {
        "per_dataset": {d: {"n": int(len(arrays[d][0])), "bacc": round(point[d], 2),
                            "ci95": [round(float(np.percentile(boots[d], 2.5)), 2),
                                     round(float(np.percentile(boots[d], 97.5)), 2)]} for d in names},
        "avg_all": agg(names),
        "avg_without_ragtruth": agg([d for d in names if d != "RAGTruth"]),
        "news3": agg(list(NEWS3)),
    }


def score_minicheck(checker, df, cache_path, shard, batch_size):
    from minicheck.minicheck import MiniCheck
    done = {}
    if cache_path.exists():
        for line in cache_path.open(encoding="utf-8"):
            r = json.loads(line)
            done[r["row"]] = r["prob"]
    todo = [i for i in range(len(df)) if i not in done]
    print(f"{len(done)} cached, {len(todo)} to score", flush=True)
    if todo:
        scorer = MiniCheck(model_name=CHECKERS[checker], cache_dir=str(ROOT / "models" / "ckpts"),
                           batch_size=batch_size)
        t0 = time.time()
        with cache_path.open("a", encoding="utf-8") as fh:
            for s in range(0, len(todo), shard):
                ids = todo[s:s + shard]
                _, probs, _, _ = scorer.score(docs=[df.doc[i] for i in ids], claims=[df.claim[i] for i in ids])
                for i, p in zip(ids, probs):
                    fh.write(json.dumps({"row": i, "prob": float(p)}) + "\n")
                    done[i] = float(p)
                fh.flush()
                rate = (s + len(ids)) / (time.time() - t0)
                print(f"  {s + len(ids)}/{len(todo)}  {rate:.1f} rows/s  eta {(len(todo) - s - len(ids)) / rate / 60:.0f} min",
                      flush=True)
    return done


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--checker", required=True, choices=sorted(CHECKERS))
    ap.add_argument("--split", default="test", choices=["test", "dev"])
    ap.add_argument("--tag", required=True)
    ap.add_argument("--limit", type=int, default=0, help="debug: first N rows only (never for a reported result)")
    ap.add_argument("--shard", type=int, default=256)
    ap.add_argument("--batch-size", type=int, default=16)
    args = ap.parse_args()
    utf8_stdout()
    import pandas as pd
    import torch

    df = pd.read_parquet(DATA / f"{args.split}-00000-of-00001.parquet")
    if args.limit:
        df = df.head(args.limit)
    df = df.reset_index(drop=True)
    CACHE.mkdir(exist_ok=True)
    name = f"e20_{args.checker}_{args.split}_{args.tag}"
    t0 = time.time()
    probs = score_minicheck(args.checker, df, CACHE / f"{name}.jsonl", args.shard, args.batch_size)
    elapsed = time.time() - t0
    rows = [{"row": i, "dataset": df.dataset[i], "label": int(df.label[i]), "prob": round(probs[i], 6),
             "pred": int(probs[i] > 0.5)} for i in range(len(df))]
    out = summarize(rows)
    payload = {
        "meta": run_metadata("research/experiments/e20_aggrefact_eval.py", checker=args.checker, split=args.split,
                             tag=args.tag, limit=args.limit, dataset_revision=REVISION, protocol="P-fixed",
                             batch_size=args.batch_size, torch=torch.__version__,
                             gpu=torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
                             wall_seconds_this_run=round(elapsed, 1)),
        "n": len(rows),
        "published": PUBLISHED.get(args.checker),
        **out,
    }
    if args.checker in PUBLISHED and out["avg_all"] and not args.limit and args.split == "test":
        payload["s1_gap_vs_published_avg11"] = round(out["avg_all"]["bacc"] - PUBLISHED[args.checker]["avg11"], 2)
    print(write_json(f"{name}.json", payload))
    with gzip.open(Path(EXP_DIR / "results" / f"{name}_preds.jsonl.gz"), "wt", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")
    print(json.dumps({k: payload[k] for k in ("n", "avg_all", "avg_without_ragtruth", "news3")}, indent=1))
    print({d: v["bacc"] for d, v in out["per_dataset"].items()})


if __name__ == "__main__":
    main()
