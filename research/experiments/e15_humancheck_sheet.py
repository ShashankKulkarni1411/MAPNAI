"""
E15 — blind human-check sheet for S4 (research/PREREG.md §10, v3).

Picks 10 items per sampling stratum (cell × gate-v1 decision) from the 240 batch-B test items of an e12 export,
seed 13, and writes them in random order with empty label columns and no judge labels:
  research/annotation/export/humancheck_<tag>.csv     (git-ignored: third-party text)
  research/annotation/export/humancheck_ids_<tag>.json (item ids only)
Prints counts only (never a gate decision), so the judge stays blind.
"""

import argparse
import csv
import hashlib
import json
import random

from _common import ROOT, run_metadata, utf8_stdout, write_json

OUT = ROOT / "research" / "annotation" / "export"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", default="gold-2026-11-01")
    ap.add_argument("--per-stratum", type=int, default=10)
    ap.add_argument("--seed", type=int, default=13)
    args = ap.parse_args()
    utf8_stdout()
    key = json.loads((OUT / f"key_{args.tag}.json").read_text(encoding="utf-8"))
    strata = {}
    for item_id, v in sorted(key.items()):
        if v["batch"] == "B-test":
            strata.setdefault(f"{v['cell']}|{'pass' if v['gate_v1_serve'] else 'reject'}", []).append(item_id)
    rng = random.Random(args.seed)
    picked = []
    for s in sorted(strata):
        picked += rng.sample(strata[s], args.per_stratum)
    rng.shuffle(picked)
    with (OUT / f"main_A1_{args.tag}.csv").open(encoding="utf-8", newline="") as fh:
        rows = {r[0]: r for r in csv.reader(fh)}
    header = rows.pop("item_id")
    sheet = OUT / f"humancheck_{args.tag}.csv"
    ids = OUT / f"humancheck_ids_{args.tag}.json"
    if sheet.exists() or ids.exists():
        raise FileExistsError("human-check sheet exists")
    with sheet.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(header)
        for i in picked:
            w.writerow(rows[i])
    ids.write_text(json.dumps(sorted(picked), indent=1), encoding="utf-8")
    payload = {"meta": run_metadata("research/experiments/e15_humancheck_sheet.py", tag=args.tag, seed=args.seed),
               "items": len(picked), "strata": len(strata), "per_stratum": args.per_stratum,
               "sheet_sha256": hashlib.sha256(sheet.read_bytes()).hexdigest(),
               "ids_sha256": hashlib.sha256(ids.read_bytes()).hexdigest()}
    print(write_json(f"e15_humancheck_{args.tag}.json", payload))
    print({k: payload[k] for k in ("items", "strata", "per_stratum")})


if __name__ == "__main__":
    main()
