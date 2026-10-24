"""
F10 — why is materiality unscored for every article, and why are 92.8% of clusters singletons? Investigation only,
read-only (live MongoDB + the git-tracked Agent 5 index for vectors).

Risk side: counts of in-scope articles, A4 processing flags, usable risk_score values, and whether any article that
has a risk_score still carries materiality.unscored = True (that would be a field-name bug).
Cluster side: the share of clustered articles that have at least one other article within the clustering window
(cluster_window_h) at cosine ≥ cos_join / ≥ cos_strong, an upper bound on how many could be non-singletons under
the pair rule (which also needs time + entity/title evidence below cos_strong). Vectors from data/faiss_index (same
recipe as the personalization index, verified in F7); articles absent from that index are reported, not imputed.
"""

import argparse
import pickle
from collections import Counter
from datetime import timedelta

import faiss
import numpy as np

from _common import ROOT, mongo_db, run_metadata, utf8_stdout, write_json
from config.personalization import PersonalizationSettings
from personalization.scoring import parse_ts


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", required=True)
    args = ap.parse_args()
    utf8_stdout()
    cfg = PersonalizationSettings(_env_file=None)
    db = mongo_db()
    col = db.processed_articles
    proj = {"_id": 0, "article_id": 1, "in_scope": 1, "risk_processed": 1, "risk_score": 1, "materiality": 1,
            "cluster_id": 1, "cluster_size": 1, "published_at": 1, "summarization_processed": 1, "risk_level": 1}
    docs = list(col.find({}, proj))

    risk = Counter()
    scored_but_unscored = 0
    for d in docs:
        has = d.get("risk_score") is not None
        risk["in_scope"] += d.get("in_scope") is True
        risk["summarized"] += bool(d.get("summarization_processed"))
        risk["risk_processed_flag"] += bool(d.get("risk_processed"))
        risk["risk_score_present"] += has
        risk["risk_processed_without_score"] += bool(d.get("risk_processed")) and not has
        risk["in_scope_without_risk_processed"] += d.get("in_scope") is True and not d.get("risk_processed")
        m = d.get("materiality") or {}
        risk["materiality_present"] += bool(m)
        if has and m and m.get("unscored"):
            scored_but_unscored += 1
    risk["risk_score_present_but_materiality_unscored"] = scored_but_unscored
    jobs = Counter(j.get("job") for j in db.job_runs.find({}, {"_id": 0, "job": 1}))
    backfill_calls = db.a4_backfill_calls.estimated_document_count() if "a4_backfill_calls" in \
        db.list_collection_names() else None

    index = faiss.read_index(str(ROOT / "data" / "faiss_index"))
    with (ROOT / "data" / "faiss_metadata.pkl").open("rb") as fh:
        meta = pickle.load(fh)
    vec = index.reconstruct_n(0, index.ntotal)
    pos = {m["article_id"]: i for i, m in enumerate(meta)}
    clustered = [d for d in docs if d.get("cluster_id")]
    with_vec = [d for d in clustered if d["article_id"] in pos and parse_ts(d.get("published_at"))]
    ts = {d["article_id"]: parse_ts(d.get("published_at")) for d in with_vec}
    ids = [d["article_id"] for d in with_vec]
    mat = np.stack([vec[pos[a]] for a in ids])
    sims = mat @ mat.T
    np.fill_diagonal(sims, -1.0)
    window = timedelta(hours=cfg.cluster_window_h)
    ge_join = ge_strong = 0
    for i, a in enumerate(ids):
        near = np.array([abs(ts[a] - ts[b]) <= window for b in ids])
        ge_join += bool(((sims[i] >= cfg.cos_join) & near).any())
        ge_strong += bool(((sims[i] >= cfg.cos_strong) & near).any())
    sizes = Counter(d.get("cluster_size") or 1 for d in clustered)

    payload = {
        "meta": run_metadata("research/experiments/f10_materiality_investigation.py", tag=args.tag,
                             source="live MongoDB (read-only) + data/faiss_index", cos_join=cfg.cos_join,
                             cos_strong=cfg.cos_strong, cluster_window_h=cfg.cluster_window_h),
        "articles": len(docs),
        "risk": dict(risk),
        "job_runs_by_job": dict(jobs),
        "a4_backfill_calls": backfill_calls,
        "clusters": {
            "clustered_articles": len(clustered),
            "singleton_articles": sizes.get(1, 0),
            "clustered_with_vector": len(with_vec),
            "share_with_window_neighbour_ge_cos_join": round(ge_join / len(with_vec), 4) if with_vec else None,
            "share_with_window_neighbour_ge_cos_strong": round(ge_strong / len(with_vec), 4) if with_vec else None,
        },
    }
    print(write_json(f"f10_materiality_investigation_{args.tag}.json", payload))
    print(payload["risk"]); print(payload["job_runs_by_job"], payload["a4_backfill_calls"]); print(payload["clusters"])


if __name__ == "__main__":
    main()
