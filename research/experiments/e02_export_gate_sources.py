"""
E02 (step 1) — Read-only snapshot of the texts MAPNAI's render step rewrites, so the gate experiments are reproducible
after the live database changes.

Reads processed_articles (no writes) and saves, for every article with both summaries:
    {article_id, domain, source_name, summary_short, summary_long, entities: [{name, type}]}
to data/e02_gate_sources_<tag>.jsonl. The entity names are exactly what service.render passes to factcheck.verify.

The snapshot contains third-party news text (summaries of publisher articles): keep it for internal research use,
do not redistribute it.

    python research/experiments/e02_export_gate_sources.py --tag 2026-10-23
"""

import argparse
import json

from _common import DATA, mongo_db, run_metadata, utf8_stdout


def main() -> int:
    utf8_stdout()
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", required=True)
    args = ap.parse_args()

    out = DATA / f"e02_gate_sources_{args.tag}.jsonl"
    if out.exists():
        raise FileExistsError(f"{out} exists; snapshots are never overwritten")
    DATA.mkdir(parents=True, exist_ok=True)

    db = mongo_db()
    query = {"summary_short": {"$nin": [None, ""]}, "summary_long": {"$nin": [None, ""]}}
    proj = {"_id": 0, "article_id": 1, "domain": 1, "source_name": 1, "summary_short": 1, "summary_long": 1,
            "entities.name": 1, "entities.type": 1}
    n = 0
    with out.open("w", encoding="utf-8") as fh:
        for d in db["processed_articles"].find(query, proj).sort("article_id", 1):
            fh.write(json.dumps(d, ensure_ascii=False) + "\n")
            n += 1
    meta = run_metadata("research/experiments/e02_export_gate_sources.py", rows=n, query=str(query),
                        collection="processed_articles (read-only)")
    (DATA / f"e02_gate_sources_{args.tag}.meta.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
    print(f"wrote {n} rows to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
