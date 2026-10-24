"""
Gate 6 equivalence check: with every CAFG option off, decide() must reproduce factcheck.verify (gate v1) exactly —
same accept decision, same missing list, same added list — on every E02 item (the seeded edit generator of
research/experiments/e02_gate_perturbation.py replayed over the 2026-10-23 snapshot).

Writes research/experiments/results/cafg_equivalence_e02_<tag>.json; exits 1 on any mismatch.
Run: python research/faithgate/check_equivalence_e02.py --tag <tag>
"""

import argparse
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "research" / "experiments"))

import e02_gate_perturbation as E02                                       # noqa: E402
from _common import run_metadata, write_json                              # noqa: E402
from personalization import factcheck                                     # noqa: E402
from research.faithgate.cafg import CAFGConfig, decide                    # noqa: E402


def items(snapshot: str, seed: int = 13):
    rows = [json.loads(l) for l in (E02.DATA / f"e02_gate_sources_{snapshot}.jsonl").open(encoding="utf-8")]
    all_names = sorted({e["name"] for r in rows for e in r.get("entities") or [] if e.get("name")})
    rng = random.Random(seed)
    for r in rows:
        ents = [e for e in r.get("entities") or [] if e.get("name")]
        names = [e["name"] for e in ents]
        foreign = rng.sample(all_names, 40)
        for field in ("summary_short", "summary_long"):
            src = (r.get(field) or "").strip()
            if not src:
                continue
            ctx = {"names": names, "entities": ents, "rng": rng, "foreign_names": foreign}
            for edit, fn in E02.EDITS.items():
                rewrite = fn(src, ctx)
                if rewrite is None or (rewrite == src and edit != "identity"):
                    continue
                yield r["article_id"], field, edit, src, rewrite, names


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--snapshot", default="2026-10-23")
    ap.add_argument("--tag", required=True)
    args = ap.parse_args()
    n, mismatches = 0, []
    for aid, field, edit, src, rw, names in items(args.snapshot):
        n += 1
        ok, missing, added = factcheck.verify(src, rw, names)
        d = decide(src, rw, names, CAFGConfig())
        if (d.accept, d.missing, d.added) != (ok, missing, added):
            mismatches.append({"article_id": aid, "field": field, "edit": edit})
    payload = {"meta": run_metadata("research/faithgate/check_equivalence_e02.py", tag=args.tag,
                                    snapshot=args.snapshot, config="CAFGConfig() (all options off)"),
               "items": n, "mismatches": len(mismatches), "examples": mismatches[:20],
               "pass": not mismatches}
    print(write_json(f"cafg_equivalence_e02_{args.tag}.json", payload))
    print({k: payload[k] for k in ("items", "mismatches", "pass")})
    return 0 if not mismatches else 1


if __name__ == "__main__":
    raise SystemExit(main())
