"""
Seed three contrasting demo personas (sports / movies), created through PersonalizationService, with every
exposure checked against the live graph (PERSONALIZATION_PLAN.md §6 Phase 8):

  1. club_investor   — owns stakes in 5 clubs / teams            (≈ an equity investor holding 4–5 listed names)
  2. release_ops     — a film-release supply-chain manager that depends_on studios, streamers and a tentpole
                       production                                  (≈ a supply-chain manager and their suppliers)
  3. sports_media    — covers the governing bodies and the broadcasters of sport
                                                                   (≈ a tech-policy analyst: regulators + tech firms)

Each exposure lists fallback keys; the first key that resolves in Neo4j is used and a slot with none is skipped.
A re-run deletes the previous demo users (by name) first. The ids go to data/demo_personas.json for
scripts/smoke_test.py.

    python scripts/seed_demo_personas.py [--dry-run]
"""

import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from personalization.keys import entity_key  # noqa: E402
from personalization.service import PersonalizationService  # noqa: E402

IDS_FILE = os.path.join(ROOT, "data", "demo_personas.json")
MIN_EXPOSURES = 3

# (candidate keys, role, weight): the first candidate present in the graph wins
PERSONAS = [
    {
        "slug": "club_investor",
        "name": "Demo: Club & Team Investor",
        "topics": {"sports": 1.0, "finance": 0.3},
        "style": {"tone": "analyst", "length": "short", "jargon": "high"},
        "exposures": [
            (["manchester city"], "owns", "high"),
            (["chelsea"], "owns", "high"),
            (["mclaren"], "owns", "medium"),
            (["red bull", "red bull's"], "owns", "medium"),
            (["alpine", "mercedes"], "owns", "low"),
        ],
    },
    {
        "slug": "release_ops",
        "name": "Demo: Film Release Supply-Chain Manager",
        "topics": {"entertainment_movies": 1.0},
        "style": {"tone": "plain", "length": "medium", "jargon": "low"},
        "exposures": [
            (["netflix"], "depends_on", "high"),
            (["disney"], "depends_on", "high"),
            (["ramayana"], "depends_on", "medium"),
            (["hollywood"], "depends_on", "medium"),
            (["ott"], "depends_on", "medium"),
            (["drishyam"], "follows", "low"),
        ],
    },
    {
        "slug": "sports_media",
        "name": "Demo: Sports Governance & Media Analyst",
        "topics": {"sports": 1.0, "technology": 0.3},
        "style": {"tone": "analyst", "length": "medium", "jargon": "high"},
        "exposures": [
            (["uefa"], "covers", "high"),
            (["fifa"], "covers", "high"),
            (["espn"], "covers", "high"),
            (["fia"], "covers", "medium"),
            (["nfl"], "covers", "medium"),
            (["nba"], "covers", "low"),
        ],
    },
]


def mention_counts(svc: PersonalizationService, key: str) -> int:
    """Total graph mentions of the key (from entity search, which groups the key's type variants)."""
    for row in svc.search_entities(key):
        if row["key"] == key:
            return row.get("mention_count") or 0
    return 0


def window_counts(svc: PersonalizationService, keys) -> dict:
    """{key: articles in the candidate window mentioning it}, so the demo shows which seeds can reach a digest."""
    docs = svc.articles.window(svc.cfg.cand_window_h, svc.clock(),
                               projection={"_id": 0, "entity_keys": 1, svc.cfg.published_field: 1})
    return {k: sum(1 for d in docs if k in (d.get("entity_keys") or [])) for k in keys}


def resolve_exposures(svc: PersonalizationService, spec: dict) -> list:
    chosen = []
    for candidates, role, weight in spec["exposures"]:
        key = next((k for k in map(entity_key, candidates) if svc.exposures.resolve_key(k)), None)
        if key is None:
            print(f"  ! skipped {candidates}: none of them is in the graph")
            continue
        chosen.append({"key": key, "role": role, "weight": weight})
    return chosen


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed the three demo personas")
    parser.add_argument("--dry-run", action="store_true", help="resolve and print the exposures, write nothing")
    args = parser.parse_args()

    svc = PersonalizationService()
    out = {}
    for spec in PERSONAS:
        print(f"\n== {spec['name']}  [{spec['slug']}]")
        exps = resolve_exposures(svc, spec)
        in_window = window_counts(svc, [e["key"] for e in exps])
        print(f"  {'key':<18} {'role':<11} {'weight':<7} {'types':<34} {'mentions':>8} {'48h arts':>8}")
        for e in exps:
            types = sorted({v.get("type") for v in svc.exposures.resolve_key(e["key"]) if v.get("type")})
            print(f"  {e['key']:<18} {e['role']:<11} {e['weight']:<7} {','.join(types):<34} "
                  f"{mention_counts(svc, e['key']):>8} {in_window[e['key']]:>8}")
        if len(exps) < MIN_EXPOSURES:
            print(f"  ! only {len(exps)} exposures resolved (need {MIN_EXPOSURES}); not seeding this persona")
            continue
        if args.dry_run:
            continue

        for old in svc.personas.personas.find({"name": spec["name"]}, {"_id": 0, "user_id": 1}):
            svc.delete_user(old["user_id"])
            print(f"  removed previous demo user {old['user_id']}")
        user = svc.create_user(spec["name"], spec["topics"], spec["style"], exps)
        profile = svc.get_profile(user["user_id"])
        print(f"  created {user['user_id']} (persona_version {user['persona_version']})")
        for sentence in profile["sentences"]:
            print(f"    - {sentence}")
        top = ", ".join(f"{p['entity']} {p['score']:.3f}" for p in profile["pi_topk"][:8])
        print(f"    pi_topk[:8]: {top}")
        out[spec["slug"]] = {"user_id": user["user_id"], "name": spec["name"]}

    if not args.dry_run:
        os.makedirs(os.path.dirname(IDS_FILE), exist_ok=True)
        with open(IDS_FILE, "w", encoding="utf-8") as fh:
            json.dump(out, fh, indent=2)
        print(f"\nWrote {len(out)} personas to {os.path.relpath(IDS_FILE, ROOT)}")
    svc.exposures.neo4j.close()
    svc.mongo.close()
    return 0 if len(out) == len(PERSONAS) or args.dry_run else 1


if __name__ == "__main__":
    sys.exit(main())
