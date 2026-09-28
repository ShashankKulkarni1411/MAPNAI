"""
Seed the entity_aliases collection from config/entity_aliases_seed.json (PERSONALIZATION_PLAN.md C2).
Each alias maps to a canonical entity key; aliases whose target key isn't in Neo4j are skipped.

    py -3.10 scripts/seed_entity_aliases.py [--file PATH] [--dry-run]
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from personalization.keys import entity_key  # noqa: E402
from storage.exposure_store import ExposureStore  # noqa: E402
from storage.pers_log_store import PersLogStore  # noqa: E402

DEFAULT_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "config", "entity_aliases_seed.json")


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed entity_aliases from a JSON file")
    parser.add_argument("--file", default=DEFAULT_FILE)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    with open(args.file, encoding="utf-8") as fh:
        aliases = json.load(fh)["aliases"]

    exposures = ExposureStore()
    rows, skipped = [], []
    for alias, target in aliases.items():
        alias, target = entity_key(alias), entity_key(target)
        if not alias or alias == target:
            continue
        if exposures.resolve_key(target):
            rows.append({"alias": alias, "entity_key": target})
        else:
            skipped.append(f"{alias} -> {target}")

    print(f"{len(rows)} aliases with a known target, {len(skipped)} skipped")
    for s in skipped:
        print(f"  skipped (target not in graph): {s}")
    if not args.dry_run:
        changed = PersLogStore().alias_upsert(rows, source="seed")
        print(f"upserted/modified: {changed}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
