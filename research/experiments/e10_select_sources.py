"""
E10 (EXP-1 step 1) — the MAPNAI source pool and its grouped dev/test split, fixed BEFORE any tuning (R2).

From the E02 snapshot (1,843 in-scope articles with both summaries): strata = domain × source length (summary_short
≤ 50 words / > 50 words). Equal allocation of --n sources over the 4 strata (seed 13); every selected article is
assigned to dev (30%) or test (70%) within its stratum, so all style rewrites of one article share a split. The EXP-1
pilot (--pilot sources, equal per stratum) is drawn from DEV only, so test is never touched by pilot work.

Output: data/e10_sources_<tag>.json (article ids, strata, split, pilot flag, stratum population weights; no text).
It is committed and its sha256 goes into research/PREREG.md (Phase 5).
"""

import argparse
import hashlib
import json
import random
from collections import Counter

from _common import DATA, run_metadata, utf8_stdout


def stratum(row) -> str:
    return f"{row['domain']}|{'le50' if len(row['summary_short'].split()) <= 50 else 'gt50'}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--snapshot", default="2026-10-23")
    ap.add_argument("--tag", required=True)
    ap.add_argument("--n", type=int, default=480)
    ap.add_argument("--dev-share", type=float, default=0.3)
    ap.add_argument("--pilot", type=int, default=80)
    ap.add_argument("--seed", type=int, default=13)
    args = ap.parse_args()
    utf8_stdout()
    out = DATA / f"e10_sources_{args.tag}.json"
    if out.exists():
        raise FileExistsError(f"{out} exists; the split is write-once")

    rows = [json.loads(l) for l in (DATA / f"e02_gate_sources_{args.snapshot}.jsonl").open(encoding="utf-8")]
    rng = random.Random(args.seed)
    by = {}
    for r in sorted(rows, key=lambda r: r["article_id"]):
        by.setdefault(stratum(r), []).append(r)
    strata = sorted(by)
    per = args.n // len(strata)
    if any(len(by[s]) < per for s in strata):
        raise SystemExit(f"a stratum has fewer than {per} articles: { {s: len(by[s]) for s in strata} }")

    items = []
    for s in strata:
        picked = rng.sample(by[s], per)
        n_dev = round(per * args.dev_share)
        n_pilot = args.pilot // len(strata)
        for i, r in enumerate(picked):
            split = "dev" if i < n_dev else "test"
            items.append({"article_id": r["article_id"], "stratum": s, "domain": r["domain"], "split": split,
                          "pilot": split == "dev" and i < n_pilot,
                          "src_words_short": len(r["summary_short"].split()),
                          "src_words_long": len(r["summary_long"].split()),
                          "weight": round(len(by[s]) / per, 6)})
    items.sort(key=lambda x: x["article_id"])
    payload = {"meta": run_metadata("research/experiments/e10_select_sources.py", seed=args.seed, tag=args.tag,
                                    snapshot=f"data/e02_gate_sources_{args.snapshot}.jsonl", n=args.n,
                                    dev_share=args.dev_share, pilot=args.pilot,
                                    note="pilot ⊂ dev; weight = stratum population / sampled per stratum"),
               "population_by_stratum": {s: len(by[s]) for s in strata},
               "counts": {"by_split": dict(Counter(x["split"] for x in items)),
                          "pilot": sum(x["pilot"] for x in items),
                          "by_stratum_split": dict(Counter(f"{x['stratum']}|{x['split']}" for x in items))},
               "items": items}
    text = json.dumps(payload, indent=1, ensure_ascii=False)
    out.write_text(text, encoding="utf-8")
    print(out, "sha256", hashlib.sha256(text.encode("utf-8")).hexdigest())
    print(payload["population_by_stratum"], payload["counts"])


if __name__ == "__main__":
    main()
