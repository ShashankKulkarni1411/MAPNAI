"""
E02 (step 2) — SYNTHETIC stress test of MAPNAI's fact-preservation gate (personalization/factcheck.py:verify).

This is NOT an estimate of how often real LLM rewrites are wrong. It measures the gate's *sensitivity by error type*:
each source text is edited by a deterministic rule whose ground truth is known by construction, and the gate decides.

Sources: data/e02_gate_sources_<snapshot>.jsonl (real MAPNAI summaries; read-only snapshot of live Mongo).
Gate inputs exactly as in production (personalization/service.py render): verify(source, rewrite, article entity names).
Strata: source = summary_short ("short" style) and summary_long ("medium" style).

Edit families (expected gate decision):
  unfaithful  → should REJECT : number_change, number_added, entity_substitution, month_change,
                                entity_role_swap, negation_inserted, hedge_removed, outcome_flipped
  benign      → should ACCEPT : identity, number_reformat, possessive_stripped, sentence_reorder
  contestable → reported only : surname_only (full name → surname; common journalistic usage)
  omission    → reported only : drop_last_sentence, lead_50_words (an *extractive* rewrite that meets the
                                "short" length budget of render.STYLE_RULES: at most 50 words)

Output: results/e02_gate_perturbation_<tag>.json (+ per-item CSV)

    python research/experiments/e02_gate_perturbation.py --snapshot 2026-10-23 --tag 2026-10-23
"""

import argparse
import json
import random
import re
import time
from collections import defaultdict
from typing import Callable, Dict, List, Optional

from _common import DATA, percentile, run_metadata, utf8_stdout, wilson, write_csv, write_json

from personalization import factcheck

EXPECT = {
    "number_change": "reject", "number_added": "reject", "entity_substitution": "reject", "month_change": "reject",
    "entity_role_swap": "reject", "negation_inserted": "reject", "hedge_removed": "reject",
    "outcome_flipped": "reject",
    "identity": "accept", "number_reformat": "accept", "possessive_stripped": "accept", "sentence_reorder": "accept",
    "surname_only": "contestable",
    "drop_last_sentence": "omission", "lead_50_words": "omission",
}
LEXICAL_VISIBLE = {"number_change", "number_added", "entity_substitution", "month_change"}

_NUM_TOKEN = re.compile(r"(?<![\w.])(\d{1,3}(?:,\d{3})+|\d+)(?![\w,.]?\d)")
_AUX = re.compile(r"\b(is|are|was|were|has|have|had|will|would|can|could|should)\b")
_HEDGES = [(r"\bappears to have been\b", "was"), (r"\bappear to have been\b", "were"), (r"\bappears to\b", ""),
           (r"\bis expected to\b", "will"), (r"\bare expected to\b", "will"), (r"\bis likely to\b", "will"),
           (r"\bare likely to\b", "will"), (r"\bmay\b", "will"), (r"\bmight\b", "will"), (r"\bcould\b", "will"),
           (r"\breportedly\s", ""), (r"\ballegedly\s", ""), (r"\bpossibly\s", ""), (r"\bset to\b", "will")]
_FLIPS = [(r"\bwon\b", "lost"), (r"\bwins\b", "loses"), (r"\bbeat\b", "lost to"), (r"\bdefeated\b", "lost to"),
          (r"\bvictory\b", "defeat"), (r"\brose\b", "fell"), (r"\bincreased\b", "decreased"),
          (r"\bsigned\b", "released"), (r"\bconfirmed\b", "denied"), (r"\bapproved\b", "rejected")]
# no split after initials ("J.J. McCarthy", "U.S.") or common abbreviations
_SENT = re.compile(r"(?<![A-Z]\.)(?<!\bMr\.)(?<!\bMs\.)(?<!\bDr\.)(?<!\bSt\.)(?<!\bvs\.)(?<=[.!?])\s+(?=[A-Z\"“'‘(])")
_MONTH_NAMES = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
                "November", "December"]


def sentences(text: str) -> List[str]:
    return [s for s in _SENT.split(text.strip()) if s]


def present_entities(src: str, names: List[str]) -> List[str]:
    return factcheck.entities_in(src, names)


def sub_first(pattern: str, repl: str, text: str) -> Optional[str]:
    new, n = re.subn(pattern, repl, text, count=1)
    return re.sub(r"\s{2,}", " ", new) if n else None


# ── edits: (src, ctx) → rewrite | None (not applicable) ─────

def e_identity(src, ctx):
    return src


def e_number_change(src, ctx):
    iso = {m.span() for m in factcheck._ISO.finditer(src)}
    for m in _NUM_TOKEN.finditer(src):
        if any(a <= m.start() < b for a, b in iso):
            continue
        val = int(m.group(1).replace(",", ""))
        return src[:m.start()] + str(val + 1 if val < 1000 else val + 100) + src[m.end():]
    return None


def e_number_added(src, ctx):
    have = factcheck.numbers(src) | factcheck.number_words(src)
    n = next(x for x in range(13, 99) if str(x) not in have)
    return src.rstrip() + f" It was the {n}th such case this season."


def e_entity_substitution(src, ctx):
    present = [e for e in present_entities(src, ctx["names"]) if len(e) >= 4]
    if not present:
        return None
    target = ctx["rng"].choice(present)
    pool = [n for n in ctx["foreign_names"] if n.lower() not in src.lower() and len(n) >= 4]
    repl = ctx["rng"].choice(pool)
    return re.sub(rf"(?<!\w){re.escape(target)}(?!\w)", repl, src, flags=re.I)


def e_month_change(src, ctx):
    for m in re.finditer(r"\b(" + "|".join(_MONTH_NAMES) + r")\b", src):
        if m.group(1) in ("May", "March") and not re.search(r"\d", src[max(0, m.start() - 4):m.end() + 4]):
            continue
        new = _MONTH_NAMES[(_MONTH_NAMES.index(m.group(1)) + 3) % 12]
        return src[:m.start()] + new + src[m.end():]
    return None


def e_entity_role_swap(src, ctx):
    present = [e for e in present_entities(src, ctx["names"]) if len(e) >= 3]
    # two names that no other present name overlaps (swapping "Colapinto" must not break "Franco Colapinto"),
    # each occurring once, swapped in place
    def isolated(x):
        return all(x.lower() not in o.lower() and o.lower() not in x.lower() for o in present if o != x)
    once = [e for e in present if isolated(e)
            and len(re.findall(rf"(?<!\w){re.escape(e)}(?!\w)", src, re.I)) == 1]
    for i, a in enumerate(once):
        for b in once[i + 1:]:
            ma = re.search(rf"(?<!\w){re.escape(a)}(?!\w)", src, re.I)
            mb = re.search(rf"(?<!\w){re.escape(b)}(?!\w)", src, re.I)
            if not ma or not mb:
                continue
            (s1, t1), (s2, t2) = sorted([(ma, b), (mb, a)], key=lambda x: x[0].start())
            return src[:s1.start()] + t1 + src[s1.end():s2.start()] + t2 + src[s2.end():]
    return None


def e_negation_inserted(src, ctx):
    m = _AUX.search(src)
    if not m:
        return None
    return src[:m.end()] + " not" + src[m.end():]


def e_hedge_removed(src, ctx):
    for pat, repl in _HEDGES:
        out = sub_first(pat, repl, src)
        if out is not None:
            return out
    return None


def e_outcome_flipped(src, ctx):
    for pat, repl in _FLIPS:
        out = sub_first(pat, repl, src)
        if out is not None:
            return out
    return None


def e_number_reformat(src, ctx):
    out = re.sub(r"(\d),(\d{3})", r"\1\2", src)
    out = re.sub(r"(\d)\s*(?:per\s?cent|percent)\b", r"\1%", out, flags=re.I)
    return out if out != src else None


def e_possessive_stripped(src, ctx):
    poss = [n for n in ctx["names"] if re.search(r"['’]s$", n.strip()) and n in src]
    if not poss:
        return None
    out = src
    for n in poss:
        out = out.replace(n, re.sub(r"['’]s$", "", n.strip()))
    return out


def e_sentence_reorder(src, ctx):
    s = sentences(src)
    return " ".join(reversed(s)) if len(s) >= 2 else None


def e_surname_only(src, ctx):
    persons = [e["name"] for e in ctx["entities"] if (e.get("type") or "").lower() == "person"
               and len(e["name"].split()) >= 2 and e["name"] in src]
    if not persons:
        return None
    full = persons[0]
    return src.replace(full, full.split()[-1])


def e_drop_last_sentence(src, ctx):
    s = sentences(src)
    return " ".join(s[:-1]) if len(s) >= 2 else None


def e_lead_50_words(src, ctx):
    words = src.split()
    if len(words) <= 50:
        return None
    kept, count = [], 0
    for s in sentences(src):
        n = len(s.split())
        if count + n > 50:
            break
        kept.append(s)
        count += n
    return " ".join(kept) if kept else " ".join(words[:50])


EDITS: Dict[str, Callable] = {name: globals()[f"e_{name}"] for name in EXPECT}


def main() -> int:
    utf8_stdout()
    ap = argparse.ArgumentParser()
    ap.add_argument("--snapshot", required=True)
    ap.add_argument("--tag", required=True)
    ap.add_argument("--seed", type=int, default=13)
    args = ap.parse_args()

    rows = [json.loads(line) for line in (DATA / f"e02_gate_sources_{args.snapshot}.jsonl").open(encoding="utf-8")]
    all_names = sorted({e["name"] for r in rows for e in r.get("entities") or [] if e.get("name")})
    rng = random.Random(args.seed)

    items, timings = [], []
    for r in rows:
        ents = [e for e in r.get("entities") or [] if e.get("name")]
        names = [e["name"] for e in ents]
        foreign = rng.sample(all_names, 40)
        for field in ("summary_short", "summary_long"):
            src = (r.get(field) or "").strip()
            if not src:
                continue
            ctx = {"names": names, "entities": ents, "rng": rng, "foreign_names": foreign}
            for edit, fn in EDITS.items():
                rewrite = fn(src, ctx)
                if rewrite is None or (rewrite == src and edit != "identity"):
                    continue
                t0 = time.perf_counter()
                ok, missing, added = factcheck.verify(src, rewrite, names)
                timings.append((time.perf_counter() - t0) * 1e6)
                items.append({"article_id": r["article_id"], "field": field, "domain": r.get("domain"),
                              "edit": edit, "expected": EXPECT[edit], "gate_pass": ok,
                              "missing_kinds": "|".join(sorted({m.split(":")[0] for m in missing})),
                              "n_missing": len(missing), "n_added": len(added),
                              "src_words": len(src.split()), "rewrite_words": len(rewrite.split())})

    def summarize(sel: List[Dict]) -> Dict:
        out = {}
        groups = defaultdict(list)
        for it in sel:
            groups[it["edit"]].append(it)
        for edit, its in groups.items():
            n, rej = len(its), sum(not i["gate_pass"] for i in its)
            kinds = defaultdict(int)
            for i in its:
                for k in filter(None, i["missing_kinds"].split("|")):
                    kinds[k] += 1
                if i["n_added"]:
                    kinds["added_number"] += 1
            out[edit] = {"expected": EXPECT[edit], "n": n, "rejected": rej, "reject_rate": round(rej / n, 4),
                         "reject_rate_wilson95": wilson(rej, n), "reasons": dict(kinds)}
        return dict(sorted(out.items(), key=lambda kv: (list(EXPECT).index(kv[0]))))

    per_field = {f: summarize([i for i in items if i["field"] == f]) for f in ("summary_short", "summary_long")}
    pooled = summarize(items)

    def macro(sel_edits, want):
        rates = [pooled[e]["reject_rate"] if want == "reject" else 1 - pooled[e]["reject_rate"]
                 for e in sel_edits if e in pooled]
        return round(sum(rates) / len(rates), 4) if rates else None

    unfaithful = [e for e, x in EXPECT.items() if x == "reject"]
    benign = [e for e, x in EXPECT.items() if x == "accept" and e != "identity"]
    tpr_vis = macro([e for e in unfaithful if e in LEXICAL_VISIBLE], "reject")
    tpr_sem = macro([e for e in unfaithful if e not in LEXICAL_VISIBLE], "reject")
    tnr = macro(benign, "accept")
    result = {
        "meta": run_metadata("research/experiments/e02_gate_perturbation.py", seed=args.seed,
                             snapshot=f"data/e02_gate_sources_{args.snapshot}.jsonl", source_rows=len(rows),
                             gate="personalization/factcheck.py:verify (unchanged)",
                             label="SYNTHETIC perturbations — sensitivity diagnostic, not a real-world error rate"),
        "pooled": pooled,
        "per_field": per_field,
        "summary": {
            "macro_detection_lexically_visible_edits": tpr_vis,
            "macro_detection_semantic_edits": tpr_sem,
            "macro_acceptance_benign_edits": tnr,
            "macro_balanced_accuracy_all_unfaithful_vs_benign": round((macro(unfaithful, "reject") + tnr) / 2, 4),
            "identity_pass_rate": round(1 - pooled["identity"]["reject_rate"], 4),
        },
        "latency_us_per_verify": {"n": len(timings), "mean": round(sum(timings) / len(timings), 1),
                                  "p50": round(percentile(timings, 0.5), 1),
                                  "p95": round(percentile(timings, 0.95), 1)},
        "source_length": {
            f: {"words_p50": percentile([i["src_words"] for i in items if i["field"] == f and i["edit"] == "identity"], 0.5),
                "share_over_50_words": round(sum(1 for i in items if i["field"] == f and i["edit"] == "identity"
                                                 and i["src_words"] > 50)
                                             / max(1, sum(1 for i in items if i["field"] == f and i["edit"] == "identity")), 4)}
            for f in ("summary_short", "summary_long")},
    }
    out = write_json(f"e02_gate_perturbation_{args.tag}.json", result)
    out_csv = write_csv(f"e02_gate_perturbation_items_{args.tag}.csv", items)
    print(json.dumps({"summary": result["summary"], "latency": result["latency_us_per_verify"],
                      "source_length": result["source_length"]}, indent=1))
    for e, v in pooled.items():
        print(f"{e:22s} {v['expected']:12s} n={v['n']:5d} reject={v['reject_rate']:.3f} {v['reject_rate_wilson95']} {v['reasons']}")
    print("wrote", out, out_csv)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
