"""
MAPNAI — scripts/migrate_ner_misc_types.py
F6: Agent 1 stored the BERT model's CoNLL MISC label (nationalities, events, works of art) as type "Product".
spaCy maps its PRODUCT label to "Product/Technology", never to "Product", so every "Product" entity came from MISC.
This relabels them "Misc" in processed_articles.entities. Run it together with NER_MISC_LABEL=Misc so stored and new
data agree. Neo4j Entity nodes are keyed on (name, type), so relabelling them can merge nodes: that step is not
automated here and is reported only.

Default is a dry run: read-only counts and the most frequent names, nothing written. Writing needs --apply AND
--confirm <documents to change, as printed by the dry run>, so a stale or mistaken run cannot write.

Usage: python -m scripts.migrate_ner_misc_types [--report out.json] [--apply --confirm N]
"""

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Dict, Iterable

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

OLD, NEW = "Product", "Misc"
PROJECTION = {"_id": 0, "article_id": 1, "entities.name": 1, "entities.type": 1, "ner_metadata.model_used": 1}


def summarize(docs: Iterable[Dict], top: int = 40) -> Dict:
    """Counts of the entities a migration would relabel (pure: takes the projected documents)."""
    n_docs = n_docs_hit = mentions = 0
    by_model, names = Counter(), Counter()
    for d in docs:
        n_docs += 1
        hit = [e for e in d.get("entities") or [] if isinstance(e, dict) and e.get("type") == OLD]
        if hit:
            n_docs_hit += 1
            mentions += len(hit)
            by_model[(d.get("ner_metadata") or {}).get("model_used") or "unknown"] += len(hit)
            names.update(e.get("name") for e in hit if e.get("name"))
    return {"documents_scanned": n_docs, "documents_to_change": n_docs_hit, "entities_to_relabel": mentions,
            "entities_by_model_used": dict(by_model), "distinct_names": len(names),
            "top_names": names.most_common(top), "from_type": OLD, "to_type": NEW}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--report", help="write the dry-run summary as JSON here")
    ap.add_argument("--apply", action="store_true", help="write the change (needs --confirm)")
    ap.add_argument("--confirm", type=int, help="documents_to_change from the dry run")
    args = ap.parse_args(argv)
    if args.apply and args.confirm is None:
        print("refusing: --apply needs --confirm <documents_to_change from a dry run>", file=sys.stderr)
        return 2

    from pymongo import MongoClient                     # not MongoStore: its connect creates indexes (a write)
    from config.settings import settings
    col = MongoClient(settings.mongo_uri, serverSelectionTimeoutMS=20000)[settings.mongo_db_name]["processed_articles"]
    summary = summarize(col.find({"entities.type": OLD}, PROJECTION))
    summary["documents_scanned"] = col.estimated_document_count()
    summary["neo4j"] = "not migrated by this script: Entity nodes are MERGEd on (name, type)"
    summary["mode"] = "apply" if args.apply else "dry-run"
    print(json.dumps({k: v for k, v in summary.items() if k != "top_names"}, indent=1))
    if args.report:
        Path(args.report).write_text(json.dumps(summary, indent=1, ensure_ascii=False), encoding="utf-8")

    if not args.apply:
        return 0
    if args.confirm != summary["documents_to_change"]:
        print(f"refusing: --confirm {args.confirm} != {summary['documents_to_change']} documents now", file=sys.stderr)
        return 2
    res = col.update_many({"entities.type": OLD}, {"$set": {"entities.$[e].type": NEW}},
                          array_filters=[{"e.type": OLD}])
    print(f"modified {res.modified_count} documents")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
