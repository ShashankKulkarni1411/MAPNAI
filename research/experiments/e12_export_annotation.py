"""
E12 — blind annotation export (research/PREREG.md §8; guideline research/annotation/GUIDELINES_D3.md v1).

Batch A (EXP-2 agreement pilot, dev): the pilot sources × cells short:plain:low and medium:plain:low; a random half
(seed 13) is flagged for double annotation.
Batch B (S4 evaluation, test): 60 items per cell; within each cell, gate-v1 rejects are sampled to 50% of the items
(all of them if fewer), the remainder from passes; weight = stratum population / items sampled from the stratum.

Blind: rows are shuffled, item ids are random, and the sheet has no model, style, split or gate column.
Writes (git-ignored, contain third-party text):
  research/annotation/export/annotation_<tag>.csv   the sheet for annotators
  research/annotation/export/key_<tag>.json         item id → article, cell, split, batch, gate decision, weight
and results/e12_export_<tag>.json (counts, weights, sha256 of both files; no text).
"""

import argparse
import csv
import hashlib
import json
import random
from collections import Counter

from _common import DATA, EXP_DIR, ROOT, run_metadata, utf8_stdout, write_json
from config.personalization import PersonalizationSettings
from personalization import render

OUT = ROOT / "research" / "annotation" / "export"
PILOT_CELLS = ("short:plain:low", "medium:plain:low")
LABEL_COLUMNS = ["addition", "distortion", "distortion_type", "omission", "faithful", "confidence", "note"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rewrites", default="main-2026-10-24")
    ap.add_argument("--scores", default="main-2026-10-24", help="e14 tag with gate-v1 decisions for --rewrites")
    ap.add_argument("--sources", default="e10_sources_2026-10-24.json")
    ap.add_argument("--snapshot", default="2026-10-23")
    ap.add_argument("--per-cell", type=int, default=60)
    ap.add_argument("--tag", required=True)
    ap.add_argument("--seed", type=int, default=13)
    args = ap.parse_args()
    utf8_stdout()
    cfg, rng = PersonalizationSettings(_env_file=None), random.Random(args.seed)
    split = {x["article_id"]: x for x in json.loads((DATA / args.sources).read_text(encoding="utf-8"))["items"]}
    rewrites = {}
    for line in (EXP_DIR / "cache" / f"e11_{args.rewrites}.jsonl").open(encoding="utf-8"):
        r = json.loads(line)
        rewrites[(r["article_id"], r["cell"])] = r
    gate = {}
    with (EXP_DIR / "results" / f"e14_scores_items_{args.scores}.csv").open(encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            gate[(r["article_id"], r["cell"])] = r["v1_serve"] == "True"
    docs = {}
    for line in (DATA / f"e02_gate_sources_{args.snapshot}.jsonl").open(encoding="utf-8"):
        d = json.loads(line)
        if d["article_id"] in split:
            docs[d["article_id"]] = d

    chosen = []
    pilot = sorted(k for k in rewrites if split[k[0]]["pilot"] and k[1] in PILOT_CELLS)
    double = set(rng.sample(pilot, len(pilot) // 2))
    chosen += [{"key": k, "batch": "A-pilot", "double": k in double, "weight": 1.0} for k in pilot]
    cells = sorted({k[1] for k in rewrites})
    strata = {}
    for cell in cells:
        test = sorted(k for k in rewrites if k[1] == cell and split[k[0]]["split"] == "test" and k in gate)
        rej = [k for k in test if not gate[k]]
        acc = [k for k in test if gate[k]]
        n_rej = min(len(rej), args.per_cell // 2)
        n_acc = min(len(acc), args.per_cell - n_rej)
        for name, pool, n in (("reject", rej, n_rej), ("pass", acc, n_acc)):
            picked = rng.sample(pool, n)
            strata[f"{cell}|{name}"] = {"population": len(pool), "sampled": n}
            chosen += [{"key": k, "batch": "B-test", "double": True, "weight": round(len(pool) / n, 6)}
                       for k in picked]

    rng.shuffle(chosen)
    OUT.mkdir(parents=True, exist_ok=True)
    sheet, key = OUT / f"annotation_{args.tag}.csv", OUT / f"key_{args.tag}.json"
    if sheet.exists() or key.exists():
        raise FileExistsError("export exists; use a new --tag")
    keyed = {}
    with sheet.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["item_id", "batch", "source", "rewrite"] + LABEL_COLUMNS)
        for c in chosen:
            aid, cell = c["key"]
            item_id = hashlib.sha1(f"{args.tag}|{aid}|{cell}".encode()).hexdigest()[:10]
            style = rewrites[c["key"]]["style"]
            source, _ = render.source_text(docs[aid], style["length"], cfg)
            w.writerow([item_id, c["batch"].split("-")[0], source, rewrites[c["key"]]["rewrite"] or ""] +
                       [""] * len(LABEL_COLUMNS))
            keyed[item_id] = {"article_id": aid, "cell": cell, "split": split[aid]["split"], "batch": c["batch"],
                              "double_annotate": c["double"], "gate_v1_serve": gate.get(c["key"]),
                              "weight": c["weight"]}
    key.write_text(json.dumps(keyed, indent=1), encoding="utf-8")
    payload = {"meta": run_metadata("research/experiments/e12_export_annotation.py", tag=args.tag, seed=args.seed,
                                    rewrites=args.rewrites, scores=args.scores, guideline="GUIDELINES_D3.md v1"),
               "items": len(keyed), "by_batch": dict(Counter(v["batch"] for v in keyed.values())),
               "double_annotated": sum(v["double_annotate"] for v in keyed.values()),
               "batch_b_strata": strata,
               "sheet_sha256": hashlib.sha256(sheet.read_bytes()).hexdigest(),
               "key_sha256": hashlib.sha256(key.read_bytes()).hexdigest()}
    print(write_json(f"e12_export_{args.tag}.json", payload))
    print({k: payload[k] for k in ("items", "by_batch", "double_annotated")})
    print(strata)


if __name__ == "__main__":
    main()
