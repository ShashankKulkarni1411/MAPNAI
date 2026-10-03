"""
Build the personalization FAISS index (data/pers_faiss_index + data/pers_faiss_metadata.pkl) from every
article in Mongo (PERSONALIZATION_PLAN.md C5). The pipeline's data/faiss_index is not touched.
The hourly clustering job keeps it in sync afterwards; run this once, or with --full to start over.

    python scripts/rebuild_pers_faiss.py [--full]
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from personalization.service import PersonalizationService  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the personalization FAISS index from Mongo")
    parser.add_argument("--full", action="store_true", help="discard the existing index and re-embed everything")
    args = parser.parse_args()

    svc = PersonalizationService()
    vectors = svc.vector_store()
    if args.full:
        vectors.reset()
    added = svc.sync_vectors()
    total = len(svc.articles.all_ids())
    print(f"added {added}; index ntotal = {vectors.total_vectors}; articles in Mongo = {total}")
    return 0 if vectors.total_vectors >= total else 1


if __name__ == "__main__":
    sys.exit(main())
