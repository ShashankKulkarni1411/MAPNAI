"""
S5 ceiling: Bespoke-MiniCheck-7B on LLM-AggreFact (test) under protocol P-fixed (research/PREREG.md §2).

Runs on Google Colab (or any Linux box) with one GPU of >= 40 GB (A100 recommended). It cannot run on the
project laptop (RTX 3050, 6 GB) and vLLM is Linux-only. See research/colab/README.md for the exact steps.

Protocol (copied from MiniCheck @ b58b9fa, benchmark_evaluation_demo.ipynb):
  test split, default max_model_len 32768 (chunk = max_len - 300), pred = prob > 0.5 (no tuning),
  balanced_accuracy_score x 100 per dataset, Average = unweighted mean over datasets.

Security (R8): the model needs trust_remote_code (InternLM2). The four .py files at the pinned revision were read
and scanned on 2026-10-23 (no network, exec/eval, subprocess or pickle use; sha256 recorded in README.md).
The script checks those hashes before loading and loads only through minicheck/vLLM, never transformers.AutoModel
(whose auto_map points at an unpinned third-party repository).

Outputs (outputs/, never committed; copy back to research/experiments/results/ by hand):
  bespoke_preds_<tag>.jsonl.gz   per-instance raw probability + prediction (no text)
  bespoke_aggrefact_<tag>.json   per-dataset BAcc, News-3 mean, 11-dataset average, environment, timings
"""

import argparse
import gzip
import hashlib
import json
import os
import platform
import subprocess
import sys
import time
from datetime import datetime, timezone

MODEL_REPO = "bespokelabs/Bespoke-MiniCheck-7B"
MODEL_REV = "1ed7786bcda3fa1dc35f7c4ed9e3f36b785d33b8"
CODE_SHA256 = {
    "configuration_internlm2.py": "89863f76efbb7f31b39e8feb789285b7362d243e7c9c2a07ac018e0e313fd856",
    "modeling_internlm2.py": "1b781ec759a151caa48e03641e9b01411376f157cacd9a28044a714e4abad005",
    "tokenization_internlm2.py": "444d4c2b0da158e61c34b3c727943f0ad454770c74b307f4d881f03603335eef",
    "tokenization_internlm2_fast.py": "1fe5f033032afc400b9b8b0274f16efd57c6ebaab46a2f6fe9f961afb868ae10",
}
NEWS3 = ("AggreFact-CNN", "AggreFact-XSum", "TofuEval-MediaS")


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 22), b""):
            h.update(b)
    return h.hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", required=True)
    ap.add_argument("--dataset-revision", required=True, help="LLM-AggreFact commit sha recorded in data/MANIFEST.json")
    ap.add_argument("--cache-dir", default="./ckpts")
    ap.add_argument("--out", default="./outputs")
    ap.add_argument("--limit", type=int, default=0, help="debug only: score the first N test rows")
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)
    res_path = os.path.join(args.out, f"bespoke_aggrefact_{args.tag}.json")
    if os.path.exists(res_path):
        sys.exit(f"{res_path} exists; results are write-once, use a new --tag")

    from huggingface_hub import snapshot_download
    local = snapshot_download(MODEL_REPO, revision=MODEL_REV, cache_dir=args.cache_dir)
    for fn, want in CODE_SHA256.items():
        got = sha256(os.path.join(local, fn))
        if got != want:
            sys.exit(f"remote code {fn} changed: {got} != {want}; stop and re-review before running")

    import pandas as pd
    from datasets import load_dataset
    from sklearn.metrics import balanced_accuracy_score
    from minicheck.minicheck import MiniCheck

    df = pd.DataFrame(load_dataset("lytang/LLM-AggreFact", revision=args.dataset_revision)["test"])
    if args.limit:
        df = df.head(args.limit)

    t0 = time.time()
    scorer = MiniCheck(model_name="Bespoke-MiniCheck-7B", enable_prefix_caching=False, cache_dir=args.cache_dir)
    load_s = time.time() - t0
    t1 = time.time()
    pred, prob, _, _ = scorer.score(docs=df.doc.tolist(), claims=df.claim.tolist())
    score_s = time.time() - t1

    df["pred"], df["prob"] = pred, prob
    per = {ds: round(balanced_accuracy_score(g.label, g.pred) * 100, 2) for ds, g in df.groupby("dataset")}
    out = {
        "meta": {"script": "research/colab/run_bespoke.py", "tag": args.tag,
                 "run_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                 "model": MODEL_REPO, "model_revision": MODEL_REV, "dataset_revision": args.dataset_revision,
                 "protocol": "P-fixed (threshold 0.5, test split, default max_model_len 32768)",
                 "python": platform.python_version(), "limit": args.limit,
                 "gpu": subprocess.run(["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"],
                                       capture_output=True, text=True).stdout.strip(),
                 "pip_freeze": subprocess.run([sys.executable, "-m", "pip", "freeze"], capture_output=True,
                                              text=True).stdout.splitlines()},
        "n": int(len(df)),
        "per_dataset_bacc": per,
        "average_all": round(sum(per.values()) / len(per), 2),
        "news3_mean": round(sum(per[d] for d in NEWS3 if d in per) / sum(d in per for d in NEWS3), 2)
        if any(d in per for d in NEWS3) else None,
        "timing_s": {"load": round(load_s, 1), "score": round(score_s, 1)},
    }
    with gzip.open(os.path.join(args.out, f"bespoke_preds_{args.tag}.jsonl.gz"), "wt", encoding="utf-8") as fh:
        for i, r in df.reset_index().iterrows():
            fh.write(json.dumps({"row": int(r["index"]), "dataset": r["dataset"], "label": int(r["label"]),
                                 "prob": float(r["prob"]), "pred": int(r["pred"])}) + "\n")
    with open(res_path, "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=1)
    print(json.dumps({k: out[k] for k in ("n", "per_dataset_bacc", "average_all", "news3_mean", "timing_s")}, indent=1))


if __name__ == "__main__":
    main()
