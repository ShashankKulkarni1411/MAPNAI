"""
E03 — Descriptive metrics of the live system (read-only MongoDB), computed with MAPNAI's own metric functions where
they exist. These describe the system and its developer usage; they are NOT evidence about real users.

Sections
  clusters     size distribution and singleton share (clusters assigned by the hourly job)
  materiality  distribution of m and of its components (personalization/materiality.py)
  render       fallback rate of cached rewrites with a Wilson interval (render_cache)
  serving      personalization/metrics.serving + engagement on impressions/feedback (developer accounts only)
  classifier   SILVER proxy: Agent 2's stored domain vs the domain of the RSS feed the article came from
               (config/sources.py). Feed domain is a weak label (movie feeds also carry TV/music news, which the
               taxonomy calls `other`), so this is a disagreement profile, not an accuracy.

    python research/experiments/e03_live_descriptives.py --tag 2026-10-23
"""

import argparse
import json
from collections import Counter, defaultdict

from _common import mongo_db, percentile, run_metadata, utf8_stdout, wilson, write_json

from config.sources import ALL_RSS_SOURCES
from personalization import metrics


def main() -> int:
    utf8_stdout()
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", required=True)
    args = ap.parse_args()
    db = mongo_db()
    A = db["processed_articles"]

    docs = list(A.find({}, {"_id": 0, "article_id": 1, "domain": 1, "source_name": 1, "raw_source": 1, "in_scope": 1,
                            "cluster_id": 1, "materiality": 1, "classification_confidence": 1}))
    out = {"meta": run_metadata("research/experiments/e03_live_descriptives.py",
                                source="live MongoDB (read-only aggregate reads)", articles=len(docs))}

    # clusters
    by_cluster = Counter(d["cluster_id"] for d in docs if d.get("cluster_id"))
    sizes = list(by_cluster.values())
    out["clusters"] = {
        "articles_clustered": sum(sizes), "clusters": len(sizes),
        "singleton_clusters": sum(1 for s in sizes if s == 1),
        "singleton_cluster_share": round(sum(1 for s in sizes if s == 1) / len(sizes), 4),
        "articles_in_multi_member_clusters": sum(s for s in sizes if s >= 2),
        "share_articles_in_multi_member": round(sum(s for s in sizes if s >= 2) / sum(sizes), 4),
        "size_histogram": dict(sorted(Counter(min(s, 10) for s in sizes).items())),
        "note": "histogram key 10 means ≥ 10",
    }

    # materiality
    mats = [d["materiality"] for d in docs if isinstance((d.get("materiality") or {}).get("m"), (int, float))]
    def dist(vals):
        vals = [float(v) for v in vals]
        return {"n": len(vals), "p10": round(percentile(vals, .1), 4), "p50": round(percentile(vals, .5), 4),
                "p90": round(percentile(vals, .9), 4), "max": round(max(vals), 4)} if vals else None
    out["materiality"] = {
        "m": dist(m["m"] for m in mats),
        "share_m_ge_0.6": round(sum(m["m"] >= 0.6 for m in mats) / len(mats), 4) if mats else None,
        "unscored_share": round(sum(bool(m.get("unscored")) for m in mats) / len(mats), 4) if mats else None,
        "first_report_share": round(sum(m.get("first_report") == 1 for m in mats) / len(mats), 4) if mats else None,
        "source_cred_values": dict(Counter(m.get("source_cred") for m in mats).most_common()),
        "size_score": dist(m.get("size_score") or 0 for m in mats),
    }

    # render
    rc = list(db["render_cache"].find({}, {"_id": 0, "fallback": 1, "reason": 1, "tone": 1, "length": 1, "jargon": 1}))
    fb = sum(1 for r in rc if r.get("fallback"))
    out["render"] = {"cached_rewrites": len(rc), "fallbacks": fb, "fallback_rate": round(fb / len(rc), 4) if rc else None,
                     "fallback_rate_wilson95": wilson(fb, len(rc)),
                     "by_length": {L: [sum(1 for r in rc if r.get("length") == L and r.get("fallback")),
                                       sum(1 for r in rc if r.get("length") == L)] for L in ("short", "medium")},
                     "note": "[fallbacks, total] per length; n is tiny"}

    # serving (developer accounts)
    imps = list(db["impressions"].find({}, {"_id": 0}))
    fbk = list(db["feedback"].find({}, {"_id": 0}))
    window_ids = {d["article_id"] for d in docs}
    served_ids = {i.get("article_id") for i in imps}
    topic_of = {d["article_id"]: d.get("domain") for d in docs}
    per_digest = defaultdict(list)
    for i in imps:
        per_digest[i.get("digest_id")].append(i)
    import math
    def entropy(xs):
        c = Counter(xs)
        n = sum(c.values())
        return -sum(v / n * math.log2(v / n) for v in c.values()) if n else 0.0
    ents = [entropy(topic_of.get(i.get("article_id")) for i in v if i.get("section") != "more_you_need")
            for v in per_digest.values()]
    out["serving_developer_accounts"] = {
        "label": "developer/demo accounts only — descriptive, not evidence about users",
        "metrics.serving": metrics.serving(imps),
        "metrics.engagement": metrics.engagement(fbk, imps, ["open", "more", "save", "dwell"]),
        "digests": len(per_digest),
        "catalog_coverage_unique_served_over_all_articles": round(len(served_ids & window_ids) / len(window_ids), 4),
        "topic_entropy_bits_per_digest_p50": round(percentile(ents, .5), 4) if ents else None,
        "must_know_share_of_slate_items": round(sum(1 for i in imps if i.get("section") == "must_know")
                                                / max(1, sum(1 for i in imps if i.get("section") != "more_you_need")), 4),
        "propensity_values_explore": sorted({round(float(i.get("propensity") or 0), 3) for i in imps
                                             if i.get("section") == "explore"}),
    }

    # classifier silver proxy
    feed = {s.name: s.domain for s in ALL_RSS_SOURCES}
    feed_by_url = {s.url: s.domain for s in ALL_RSS_SOURCES}
    pairs = []
    for d in docs:
        fd = feed.get(d.get("source_name")) or feed_by_url.get(d.get("raw_source"))
        if fd:
            pairs.append((fd, d.get("domain")))
    matrix = defaultdict(Counter)
    for fd, pred in pairs:
        matrix[fd][pred] += 1
    in_tax = [(fd, p) for fd, p in pairs if fd in ("sports", "entertainment_movies")]
    off_tax = [(fd, p) for fd, p in pairs if fd not in ("sports", "entertainment_movies")]
    out["classifier_silver_proxy"] = {
        "label": "SILVER: feed domain is not ground truth",
        "articles_matched_to_feed": len(pairs), "articles_total": len(docs),
        "feed_domain_x_a2_domain": {k: dict(v) for k, v in sorted(matrix.items())},
        "agreement_on_sports_and_movie_feeds": round(sum(fd == p for fd, p in in_tax) / len(in_tax), 4) if in_tax else None,
        "agreement_wilson95": wilson(sum(fd == p for fd, p in in_tax), len(in_tax)),
        "off_taxonomy_feeds_labelled_in_scope_share": round(sum(p in ("sports", "entertainment_movies")
                                                                for _, p in off_tax) / len(off_tax), 4) if off_tax else None,
        "confidence_p50": round(percentile([float(d["classification_confidence"]) for d in docs
                                            if isinstance(d.get("classification_confidence"), (int, float))], .5), 4),
    }

    path = write_json(f"e03_live_descriptives_{args.tag}.json", out)
    print(json.dumps({k: v for k, v in out.items() if k != "meta"}, indent=1, default=str)[:6000])
    print("wrote", path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
