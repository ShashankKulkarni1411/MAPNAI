"""
E04 — MIND-small validation and the 120-abstract generalization set for EXP-7.

Reads research/experiments/data/external/mind/{dev,train}/news.tsv (MIND-small, Microsoft Research License:
non-commercial research only, no redistribution, no material portion in publications [Wu2020MIND]).
Writes:
  data/external/mind_sources_120.jsonl      the selected abstracts (git-ignored; never committed)
  results/e04_mind_sources_<tag>.json       validation statistics and selection provenance (no news text)

Selection: dev news.tsv; non-empty abstract; abstract ≥ floor words (start 30, lowered by 5 only if < N remain);
one row per normalized title; categories allocated proportionally (largest remainder, ≥ 1 for every category
that has an eligible row when N allows); rows drawn within each category with seed 13.
"""

import argparse
import hashlib
import json
import random
import re
from collections import Counter
from pathlib import Path

from _common import DATA, run_metadata, percentile, utf8_stdout, write_json

MIND = DATA / "external" / "mind"
OUT = DATA / "external" / "mind_sources_120.jsonl"
COLUMNS = ["id", "category", "subcategory", "title", "abstract", "url", "title_entities", "abstract_entities"]


def read_news(path: Path):
    """news.tsv rows as dicts; every line must have exactly 8 tab-separated fields (no quoting in MIND)."""
    rows, bad = [], 0
    for line in path.read_text(encoding="utf-8").splitlines():
        parts = line.split("\t")
        if len(parts) != len(COLUMNS):
            bad += 1
            continue
        rows.append(dict(zip(COLUMNS, parts)))
    return rows, bad


def words(text: str) -> int:
    return len(text.split())


def norm_title(t: str) -> str:
    return re.sub(r"\W+", " ", t.lower()).strip()


def describe(rows):
    wc = [words(r["abstract"]) for r in rows]
    nonempty = [w for w in wc if w > 0]
    return {
        "rows": len(rows),
        "empty_abstract_rate": round(sum(1 for w in wc if w == 0) / len(rows), 4),
        "abstract_words_nonempty": {q: percentile(nonempty, p) for q, p in
                                    (("p05", .05), ("p10", .10), ("p25", .25), ("p50", .5), ("p75", .75),
                                     ("p90", .9), ("p95", .95))},
        "share_nonempty_ge_30_words": round(sum(1 for w in nonempty if w >= 30) / len(nonempty), 4),
        "categories": dict(Counter(r["category"] for r in rows).most_common()),
    }


def allocate(counts: Counter, n: int):
    """Proportional allocation with largest remainders, capped by availability."""
    total = sum(counts.values())
    quota = {c: n * k / total for c, k in counts.items()}
    alloc = {c: min(counts[c], int(q)) for c, q in quota.items()}
    for c in sorted(quota, key=lambda c: (-(quota[c] - int(quota[c])), c)):
        if sum(alloc.values()) >= n:
            break
        if alloc[c] < counts[c]:
            alloc[c] += 1
    while sum(alloc.values()) < n:                          # top up from the largest categories if caps bit
        c = max((c for c in counts if alloc[c] < counts[c]), key=lambda c: counts[c] - alloc[c])
        alloc[c] += 1
    return alloc


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", required=True)
    ap.add_argument("--n", type=int, default=120)
    ap.add_argument("--seed", type=int, default=13)
    ap.add_argument("--floor", type=int, default=30)
    args = ap.parse_args()
    utf8_stdout()

    stats, columns_ok = {}, {}
    for split in ("dev", "train"):
        rows, bad = read_news(MIND / split / "news.tsv")
        columns_ok[split] = {"rows_with_8_fields": len(rows), "rows_with_other_field_count": bad}
        stats[split] = describe(rows)
        behaviors = sum(1 for _ in (MIND / split / "behaviors.tsv").open(encoding="utf-8"))
        stats[split]["behaviors_rows"] = behaviors

    dev, _ = read_news(MIND / "dev" / "news.tsv")
    floor = args.floor
    while True:
        seen, pool = set(), []
        for r in dev:
            t = norm_title(r["title"])
            if r["abstract"].strip() and words(r["abstract"]) >= floor and t not in seen:
                seen.add(t)
                pool.append(r)
        if len(pool) >= args.n or floor <= 5:
            break
        floor -= 5

    by_cat = {}
    for r in pool:
        by_cat.setdefault(r["category"], []).append(r)
    alloc = allocate(Counter({c: len(v) for c, v in by_cat.items()}), args.n)
    rng = random.Random(args.seed)
    picked = []
    for c in sorted(alloc):
        rows = sorted(by_cat[c], key=lambda r: r["id"])
        picked += rng.sample(rows, alloc[c])
    picked.sort(key=lambda r: r["id"])

    if OUT.exists():
        raise FileExistsError(f"{OUT} exists; the selection is write-once")
    OUT.write_text("".join(json.dumps({"id": r["id"], "category": r["category"], "title": r["title"],
                                       "abstract": r["abstract"], "source": "MIND-small-dev"},
                                      ensure_ascii=False) + "\n" for r in picked), encoding="utf-8")
    digest = hashlib.sha256(OUT.read_bytes()).hexdigest()

    payload = {
        "meta": run_metadata("research/experiments/e04_mind_sources.py", seed=args.seed, tag=args.tag,
                             licence="Microsoft Research License (non-commercial research; no redistribution)",
                             source="huggingface.co/datasets/Recommenders/MIND @ 2115068f457b577f93a268fffe22373e45727d89"),
        "columns": COLUMNS,
        "column_check": columns_ok,
        "stats": stats,
        "selection": {
            "n": len(picked), "word_floor_used": floor, "eligible_pool": len(pool),
            "allocation": dict(sorted(alloc.items())),
            "abstract_words": {"min": min(words(r["abstract"]) for r in picked),
                               "p50": percentile([words(r["abstract"]) for r in picked], .5),
                               "max": max(words(r["abstract"]) for r in picked)},
            "file": str(OUT.relative_to(DATA.parent.parent.parent)).replace("\\", "/"),
            "file_sha256": digest,
            "ids": [r["id"] for r in picked],
        },
    }
    print(write_json(f"e04_mind_sources_{args.tag}.json", payload))
    print(json.dumps({k: payload[k] for k in ("column_check",)}, indent=1))
    print(json.dumps({s: {k: v for k, v in stats[s].items() if k != "categories"} for s in stats}, indent=1))
    print(json.dumps({k: v for k, v in payload["selection"].items() if k != "ids"}, indent=1))


if __name__ == "__main__":
    main()
