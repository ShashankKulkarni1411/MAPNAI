"""n01: build the scoring input, article statistics, pilot ids and the human-validation sample.

Outputs (data/ is git-ignored because it holds MIND text):
  data/articles_to_score.jsonl   {id, title, abstract}; every article shown as a candidate
                                 in MIND-small train or dev; pilot items first
  data/article_meta.csv          id, category, subcategory, impressions and clicks per split
  data/human_sample.json         100 ids for the two human labellers, stratified by category
  results/n01_prepare_<tag>.json counts, seeds and file hashes (no text; safe to commit)

Usage:  python research2/n01_prepare.py --tag 2026-11-15
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import random
from collections import Counter, defaultdict
from datetime import datetime, timezone

from nv_common import (ABSTRACT_MAX_CHARS, DATA, RESULTS, SEED, iter_impressions, load_news,
                       prompt_sha256, sha256_file, truncate, write_json)

PILOT_N = 50
HUMAN_N = 100
HUMAN_MIN_IMPRESSIONS = 50     # same exposure floor as analysis A3
HUMAN_MIN_PER_CATEGORY = 2


def allocate(sizes: dict, total: int, floor: int) -> dict:
    """Allocation proportional to sqrt(size), at least `floor` each, largest remainder; sums to total."""
    cats = [c for c, n in sizes.items() if n >= floor]
    w = {c: math.sqrt(sizes[c]) for c in cats}
    spare = total - floor * len(cats)
    raw = {c: spare * w[c] / sum(w.values()) for c in cats}
    alloc = {c: floor + int(raw[c]) for c in cats}
    left = total - sum(alloc.values())
    for c in sorted(cats, key=lambda c: raw[c] - int(raw[c]), reverse=True)[:left]:
        alloc[c] += 1
    for c in cats:                       # never ask for more than exist
        alloc[c] = min(alloc[c], sizes[c])
    return alloc


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", required=True)
    args = ap.parse_args()

    news = load_news()
    imps = {s: Counter() for s in ("train", "dev")}
    clicks = {s: Counter() for s in ("train", "dev")}
    n_imp = Counter()
    for split in ("train", "dev"):
        for _, _, _, _, cands in iter_impressions(split):
            n_imp[split] += 1
            for nid, lab in cands:
                imps[split][nid] += 1
                clicks[split][nid] += lab

    cand_ids = sorted(set(imps["train"]) | set(imps["dev"]))
    missing = [i for i in cand_ids if i not in news]
    assert not missing, f"{len(missing)} candidate ids missing from news.tsv"

    rng = random.Random(SEED)
    order = cand_ids[:]
    rng.shuffle(order)
    pilot = order[:PILOT_N]

    DATA.mkdir(parents=True, exist_ok=True)
    out_jsonl = DATA / "articles_to_score.jsonl"
    with open(out_jsonl, "w", encoding="utf-8", newline="\n") as f:
        for nid in order:
            a = news[nid]
            f.write(json.dumps({"id": nid, "title": " ".join(a["title"].split()),
                                "abstract": truncate(a["abstract"])}, ensure_ascii=False) + "\n")

    with open(DATA / "article_meta.csv", "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["id", "category", "subcategory", "imps_train", "clicks_train", "imps_dev", "clicks_dev"])
        for nid in cand_ids:
            a = news[nid]
            w.writerow([nid, a["category"], a["subcategory"], imps["train"][nid], clicks["train"][nid],
                        imps["dev"][nid], clicks["dev"][nid]])

    # Human sample: well-exposed articles, stratified by category, pilot items excluded
    total_imps = {nid: imps["train"][nid] + imps["dev"][nid] for nid in cand_ids}
    pilot_set = set(pilot)
    pool = defaultdict(list)
    for nid in cand_ids:
        if total_imps[nid] >= HUMAN_MIN_IMPRESSIONS and nid not in pilot_set:
            pool[news[nid]["category"]].append(nid)
    alloc = allocate({c: len(v) for c, v in pool.items()}, HUMAN_N, HUMAN_MIN_PER_CATEGORY)
    rng_h = random.Random(SEED + 1)
    human = []
    for c in sorted(alloc):
        human += rng_h.sample(sorted(pool[c]), alloc[c])
    rng_h.shuffle(human)                 # labellers see a mixed order, not blocks by category
    assert len(human) == HUMAN_N, len(human)
    write_json(DATA / "human_sample.json", {"seed": SEED + 1, "ids": human,
                                            "allocation": alloc, "pilot_ids": pilot})

    empty_abs = sum(1 for nid in cand_ids if not news[nid]["abstract"].strip())
    truncated = sum(1 for nid in cand_ids if len(" ".join(news[nid]["abstract"].split())) > ABSTRACT_MAX_CHARS)
    cat_counts = Counter(news[nid]["category"] for nid in cand_ids)
    exposed = [nid for nid in cand_ids if total_imps[nid] >= HUMAN_MIN_IMPRESSIONS]
    summary = {
        "meta": {"script": "research2/n01_prepare.py", "tag": args.tag,
                 "run_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"), "seed": SEED},
        "impressions": dict(n_imp),
        "articles_in_news_tsv": len(news),
        "candidate_articles": len(cand_ids),
        "candidate_articles_train_only": len(set(imps["train"]) - set(imps["dev"])),
        "candidate_articles_dev_only": len(set(imps["dev"]) - set(imps["train"])),
        "candidate_articles_both": len(set(imps["train"]) & set(imps["dev"])),
        "empty_abstract": empty_abs,
        "abstract_truncated_at_chars": ABSTRACT_MAX_CHARS,
        "abstract_truncated": truncated,
        "categories": dict(cat_counts.most_common()),
        "exposed_ge_50_impressions": len(exposed),
        "exposed_ge_50_with_click": sum(1 for nid in exposed if clicks["train"][nid] + clicks["dev"][nid] > 0),
        "pilot_n": PILOT_N,
        "human_n": HUMAN_N,
        "human_allocation": alloc,
        "prompt_sha256": prompt_sha256(),
        "files": {"data/articles_to_score.jsonl": sha256_file(out_jsonl),
                  "data/article_meta.csv": sha256_file(DATA / "article_meta.csv"),
                  "data/human_sample.json": sha256_file(DATA / "human_sample.json")},
    }
    write_json(RESULTS / f"n01_prepare_{args.tag}.json", summary)
    print(json.dumps({k: summary[k] for k in ("impressions", "candidate_articles", "empty_abstract",
                                              "abstract_truncated", "exposed_ge_50_impressions",
                                              "human_allocation", "prompt_sha256")}, indent=1))
    print("articles_to_score.jsonl sha256:", summary["files"]["data/articles_to_score.jsonl"])


if __name__ == "__main__":
    main()
