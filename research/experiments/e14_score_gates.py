"""
E14 (EXP-1 step 3) — score E11 rewrites with the fact gates, using production inputs.

For each rewrite (latest row per (article, cell)): the source is recomputed with render.source_text and must match the
stored source_hash; entity names = the article's NER names (as personalization/service.py render passes them).
An unparseable response is a fallback with reason "unparseable_response" (as Renderer.render).
Gates: factcheck.GATE_VERSIONS (v1 = production default; v2 = F2 + F5). Each gate is scored twice and the decisions
must be identical (determinism check).

Output: results/e14_scores_<tag>.json (serve rate per gate × length with Wilson CIs, reasons, length compliance
≤ 50 / ≤ 120 words) and results/e14_scores_items_<tag>.csv (ids, cell, decisions, reason kinds, word counts; no text).
"""

import argparse
import json
from collections import Counter, defaultdict

from _common import DATA, EXP_DIR, run_metadata, utf8_stdout, wilson, write_csv, write_json
from config.personalization import PersonalizationSettings
from personalization import factcheck, render

LIMIT = {"short": 50, "medium": 120}


def kinds(items):
    return sorted({x.split(":")[0] for x in items})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rewrites", required=True, help="E11 tag")
    ap.add_argument("--snapshot", default="2026-10-23")
    ap.add_argument("--gates", default="v1,v2")
    ap.add_argument("--tag", required=True)
    args = ap.parse_args()
    utf8_stdout()
    cfg = PersonalizationSettings(_env_file=None)
    gates = args.gates.split(",")

    last = {}
    for line in (EXP_DIR / "cache" / f"e11_{args.rewrites}.jsonl").open(encoding="utf-8"):
        r = json.loads(line)
        last[(r["article_id"], r["cell"])] = r
    ids = {a for a, _ in last}
    docs = {}
    for line in (DATA / f"e02_gate_sources_{args.snapshot}.jsonl").open(encoding="utf-8"):
        d = json.loads(line)
        if d["article_id"] in ids:
            docs[d["article_id"]] = d

    items, mismatched_source, nondeterministic = [], 0, 0
    for (aid, cell), r in sorted(last.items()):
        if r["error"] is not None:
            continue                                              # transport error: not a gate decision
        doc, style = docs[aid], r["style"]
        source, _ = render.source_text(doc, style["length"], cfg)
        if render.source_hash(source) != r["source_hash"]:
            mismatched_source += 1
            continue
        names = [e["name"] for e in doc.get("entities") or [] if e.get("name")]
        rw = r["rewrite"]
        row = {"article_id": aid, "cell": cell, "length": style["length"], "parsed": rw is not None,
               "src_words": len(source.split()), "rewrite_words": len(rw.split()) if rw else None,
               "length_ok": (len(rw.split()) <= LIMIT[style["length"]]) if rw else None,
               "identical_to_source": rw is not None and rw.strip() == source.strip()}
        for g in gates:
            if rw is None:
                ok, missing, added = False, [], []
            else:
                ok, missing, added = factcheck.verify(source, rw, names, **factcheck.GATE_VERSIONS[g])
                if factcheck.verify(source, rw, names, **factcheck.GATE_VERSIONS[g])[0] != ok:
                    nondeterministic += 1
            row[f"{g}_serve"] = ok
            row[f"{g}_missing_kinds"] = "|".join(kinds(missing))
            row[f"{g}_added_kinds"] = "|".join(sorted({"name" if a.startswith("name:") else "number" for a in added}))
            row[f"{g}_n_missing"], row[f"{g}_n_added"] = len(missing), len(added)
        items.append(row)

    table = defaultdict(dict)
    for g in gates:
        for length in ("short", "medium", "all"):
            sel = [i for i in items if length == "all" or i["length"] == length]
            k = sum(i[f"{g}_serve"] for i in sel)
            reasons = Counter(x for i in sel if not i[f"{g}_serve"]
                              for x in (i[f"{g}_missing_kinds"].split("|") + [f"added_{a}" for a in
                                        i[f"{g}_added_kinds"].split("|")]) if x and x != "added_")
            table[g][length] = {"n": len(sel), "served": k, "serve_rate": round(k / len(sel), 4) if sel else None,
                                "serve_rate_wilson95": wilson(k, len(sel)), "fallback_reasons": dict(reasons),
                                "unparseable": sum(not i["parsed"] for i in sel)}
    compliance = {length: {"n": len([i for i in items if i["length"] == length and i["parsed"]]),
                           "within_limit": sum(bool(i["length_ok"]) for i in items if i["length"] == length),
                           "identical_to_source": sum(i["identical_to_source"] for i in items
                                                      if i["length"] == length)}
                  for length in ("short", "medium")}
    payload = {
        "meta": run_metadata("research/experiments/e14_score_gates.py", tag=args.tag, rewrites=args.rewrites,
                             gates={g: factcheck.GATE_VERSIONS[g] for g in gates},
                             label="no human labels: serve rates only, not FRR/FAR"),
        "n_items": len(items), "source_hash_mismatches": mismatched_source,
        "nondeterministic_decisions": nondeterministic,
        "serve": table, "length_compliance": compliance,
        "e03_live_reference": "render_cache 2026-10-23: 8/12 served (short 4/7, medium 4/5), descriptive",
    }
    print(write_json(f"e14_scores_{args.tag}.json", payload))
    write_csv(f"e14_scores_items_{args.tag}.csv", items)
    print(json.dumps({k: payload[k] for k in ("n_items", "source_hash_mismatches", "nondeterministic_decisions",
                                              "length_compliance")}, indent=1))
    for g in gates:
        print(g, {l: (v["served"], v["n"], v["serve_rate"], v["serve_rate_wilson95"], v["fallback_reasons"])
                  for l, v in table[g].items()})


if __name__ == "__main__":
    main()
