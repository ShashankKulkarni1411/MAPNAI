"""
MAPNAI — scripts/rebuild_agent5_faiss.py
F7: Agent 5's semantic index (data/faiss_index + data/faiss_metadata.pkl) is appended to at ingestion and has drifted
from MongoDB (articles missing, rows for articles no longer stored). This rebuilds it from processed_articles with the
production path (ProcessedArticle → FAISSStore.add_articles: all-MiniLM-L6-v2 over "title. body[:300]").

Default is a dry run: coverage of the current index against MongoDB, nothing written. --write builds a NEW index at
--out-index / --out-metadata; it refuses the live paths (settings.faiss_index_path / faiss_metadata_path) and any file
that already exists. Switching Agent 5 to the new files is a separate, manual step (FAISS_INDEX_PATH).
MongoDB is read with a plain client (MongoStore's connect creates indexes, which is a write).

Usage: python -m scripts.rebuild_agent5_faiss [--report out.json]
       python -m scripts.rebuild_agent5_faiss --write --out-index X --out-metadata Y [--model-path DIR] [--report out.json]
"""

import argparse
import json
import os
import pickle
import sys
from collections import Counter
from pathlib import Path
from typing import Dict, Iterable

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def coverage(index_ids: Iterable[str], live_ids: Iterable[str]) -> Dict:
    """How many live articles the index holds, and how many index rows point at no live article."""
    rows, live = list(index_ids), set(live_ids)
    held = set(rows)
    return {"live": len(live), "index_rows": len(rows), "indexed_live": len(live & held),
            "missing": len(live - held), "stale_rows": sum(1 for a in rows if a not in live),
            "duplicate_rows": sum(n - 1 for n in Counter(rows).values() if n > 1),
            "coverage": round(len(live & held) / len(live), 4) if live else None}


def _same(a: str, b: str) -> bool:
    return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--write", action="store_true", help="build a new index (default: dry run)")
    ap.add_argument("--out-index")
    ap.add_argument("--out-metadata")
    ap.add_argument("--model-path", help="local sentence-transformers directory (default: settings.embedding_model)")
    ap.add_argument("--report", help="write the coverage report as JSON here")
    args = ap.parse_args(argv)

    from config.settings import settings
    if args.write:
        if not (args.out_index and args.out_metadata):
            print("refusing: --write needs --out-index and --out-metadata", file=sys.stderr)
            return 2
        for out, live in ((args.out_index, settings.faiss_index_path),
                          (args.out_metadata, settings.faiss_metadata_path)):
            if _same(out, live):
                print(f"refusing: {out} is the live index path", file=sys.stderr)
                return 2
            if os.path.exists(out):
                print(f"refusing: {out} exists (results are never overwritten)", file=sys.stderr)
                return 2

    from pymongo import MongoClient
    col = MongoClient(settings.mongo_uri, serverSelectionTimeoutMS=20000)[settings.mongo_db_name]["processed_articles"]
    docs = list(col.find({}, {"_id": 0}))
    live_ids = [d["article_id"] for d in docs if d.get("article_id")]
    with open(settings.faiss_metadata_path, "rb") as fh:
        current = coverage([m.get("article_id") for m in pickle.load(fh)], live_ids)
    report = {"current_index": current, "mode": "write" if args.write else "dry-run"}

    if args.write:
        from storage import faiss_store
        from storage.faiss_store import FAISSStore
        from utils.models import ProcessedArticle
        if args.model_path:
            from sentence_transformers import SentenceTransformer
            faiss_store._MODEL = SentenceTransformer(args.model_path)       # the store's lazily cached model
        articles, skipped = [], Counter()
        for d in docs:
            d["entities"] = [e for e in d.get("entities") or [] if isinstance(e, dict) and e.get("name")]
            for key in ("keywords", "topic_tags"):
                if d.get(key) is None:
                    d[key] = []
            try:
                articles.append(ProcessedArticle(**d))
            except Exception as e:
                skipped[type(e).__name__] += 1
        store = FAISSStore(index_path=args.out_index, metadata_path=args.out_metadata)
        added = sum(store.add_articles(articles[i:i + 256]) for i in range(0, len(articles), 256))
        store.save()
        with open(args.out_metadata, "rb") as fh:
            new = coverage([m["article_id"] for m in pickle.load(fh)], live_ids)
        report.update({"new_index": new, "added": added, "skipped_invalid": dict(skipped),
                       "out_index": args.out_index, "out_metadata": args.out_metadata,
                       "model": args.model_path or settings.embedding_model})

    print(json.dumps(report, indent=1))
    if args.report:
        Path(args.report).write_text(json.dumps(report, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
