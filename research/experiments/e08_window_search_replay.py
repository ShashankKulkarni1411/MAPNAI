"""
E08 — F8: how often does the legacy neighbour search (global top cluster_nn+1, then filtered to the window) miss
window neighbours that an exact window search finds? Read-only replay on real vectors.

Vectors: data/faiss_index (git-tracked Agent 5 index, all-MiniLM-L6-v2 over "title. body[:300]", IndexFlatIP), the same
recipe as the personalization index, which is not available locally. Metadata: data/faiss_metadata.pkl (project file).
At the end of each day in the replay range, the pool = indexed articles published up to then, the window = the last
cluster_window_h hours. For every window article: legacy = top (cluster_nn + 1) of the pool, self removed, kept if in the
window; exact = clustering.window_neighbours over the window. A "missed pair" is a window pair with cosine ≥ cos_join
that exact search returns and legacy does not: a candidate the pair rule never gets to see.
Limits: published time stands in for ingestion time; this index covers 2,719 of 3,674 live articles (E03).
"""

import argparse
import pickle
from datetime import datetime, timedelta, timezone

import faiss
import numpy as np

from _common import ROOT, percentile, run_metadata, utf8_stdout, write_json
from config.personalization import PersonalizationSettings
from personalization import clustering
from personalization.scoring import parse_ts


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", required=True)
    ap.add_argument("--start", default="2026-09-28")
    ap.add_argument("--end", default="2026-10-18")
    args = ap.parse_args()
    utf8_stdout()
    cfg = PersonalizationSettings(_env_file=None)
    index = faiss.read_index(str(ROOT / "data" / "faiss_index"))
    with (ROOT / "data" / "faiss_metadata.pkl").open("rb") as fh:
        meta = pickle.load(fh)                          # project-owned, git-tracked file
    rows = meta if isinstance(meta, list) else list(meta.values())
    vecs = index.reconstruct_n(0, index.ntotal)
    items = []
    for i, r in enumerate(rows[: index.ntotal]):
        ts = parse_ts(r.get("published"))
        if ts is not None:
            items.append((r["article_id"], ts, vecs[i] / (np.linalg.norm(vecs[i]) or 1.0)))

    day, end = datetime.fromisoformat(args.start).replace(tzinfo=timezone.utc), \
        datetime.fromisoformat(args.end).replace(tzinfo=timezone.utc)
    per_day, totals = [], {"window_articles": 0, "articles_with_missed_pair": 0, "missed_pairs": 0,
                           "exact_pairs_ge_cos_join": 0}
    while day <= end:
        t = day + timedelta(hours=23, minutes=59)
        pool = [(a, v) for a, ts, v in items if ts <= t]
        window = {a: v for a, ts, v in items if t - timedelta(hours=cfg.cluster_window_h) < ts <= t}
        if window and pool:
            ids = [a for a, _ in pool]
            sub = faiss.IndexFlatIP(vecs.shape[1])
            sub.add(np.stack([v for _, v in pool]).astype(np.float32))
            q_ids = sorted(window)
            _, nn = sub.search(np.stack([window[a] for a in q_ids]).astype(np.float32), cfg.cluster_nn + 1)
            exact = clustering.window_neighbours(window, window, cfg.cluster_nn)
            missed_articles = missed = exact_pairs = 0
            for a, row in zip(q_ids, nn):
                legacy = {ids[j] for j in row if j >= 0 and ids[j] != a and ids[j] in window}
                good = [(b, s) for b, s in exact[a] if s >= cfg.cos_join]
                exact_pairs += len(good)
                m = sum(1 for b, _ in good if b not in legacy)
                missed += m
                missed_articles += int(m > 0)
            per_day.append({"day": day.date().isoformat(), "pool": len(pool), "window_articles": len(window),
                            "articles_with_missed_pair": missed_articles, "missed_pairs": missed,
                            "exact_pairs_ge_cos_join": exact_pairs})
            totals["window_articles"] += len(window)
            totals["articles_with_missed_pair"] += missed_articles
            totals["missed_pairs"] += missed
            totals["exact_pairs_ge_cos_join"] += exact_pairs
        day += timedelta(days=1)

    totals["share_articles_with_missed_pair"] = round(totals["articles_with_missed_pair"] /
                                                      max(1, totals["window_articles"]), 4)
    totals["share_pairs_missed"] = round(totals["missed_pairs"] / max(1, totals["exact_pairs_ge_cos_join"]), 4)
    payload = {"meta": run_metadata("research/experiments/e08_window_search_replay.py", tag=args.tag,
                                    cluster_nn=cfg.cluster_nn, cluster_window_h=cfg.cluster_window_h,
                                    cos_join=cfg.cos_join, index_rows=index.ntotal, dated_rows=len(items),
                                    label="read-only replay on the Agent 5 index (same embedding recipe)"),
               "totals": totals, "per_day": per_day,
               "pool_size_p50": percentile([d["pool"] for d in per_day], .5) if per_day else None}
    print(write_json(f"e08_window_search_replay_{args.tag}.json", payload))
    print(totals)


if __name__ == "__main__":
    main()
