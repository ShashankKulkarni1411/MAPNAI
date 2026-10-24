"""
E09 — F9: why summary_short == summary_long for most articles (read-only).

For every live article with both summaries: body sentence count (utils.extractive_summarizer.split_sentences),
whether short == long, whether the stored pair equals extractive_summarize(...) today (i.e. which Agent 3 path wrote it),
and a SIMULATED alternative rule (nothing is written): short = max(1, n - 1) sentences when the body has n ≤ 3
sentences, long unchanged. Output: results/e09_summary_identity_<tag>.json (counts only).
"""

import argparse
import re
from collections import defaultdict

from _common import mongo_db, run_metadata, utf8_stdout, write_json
from utils.extractive_summarizer import extractive_summarize, split_sentences


def norm(t: str) -> str:
    return re.sub(r"\s+", " ", t or "").strip()


def bucket(n: int) -> str:
    return "1" if n <= 1 else "2" if n == 2 else "3" if n == 3 else "4-7" if n <= 7 else "8+"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", required=True)
    args = ap.parse_args()
    utf8_stdout()
    db = mongo_db()
    docs = list(db.processed_articles.find(
        {"summary_short": {"$nin": [None, ""]}, "summary_long": {"$nin": [None, ""]}},
        {"_id": 0, "title": 1, "body": 1, "summary_short": 1, "summary_long": 1, "domain": 1, "entities": 1,
         "urgency_flag": 1}))
    by = defaultdict(lambda: {"n": 0, "identical": 0, "identical_simulated": 0})
    extractive, substring = 0, 0
    for d in docs:
        body = d.get("body") or ""
        n = len(split_sentences(body))
        same = norm(d["summary_short"]) == norm(d["summary_long"])
        ex = extractive_summarize(d.get("title", ""), body, d.get("entities") or [], d.get("domain", "general"),
                                  d.get("urgency_flag", False))
        is_ex = norm(ex["summary_short"]) == norm(d["summary_short"]) and norm(ex["summary_long"]) == norm(d["summary_long"])
        extractive += is_ex
        substring += same and norm(d["summary_short"]) in norm(body)
        sim_short = (extractive_summarize(d.get("title", ""), body, d.get("entities") or [], d.get("domain", "general"),
                                          d.get("urgency_flag", False), short_sentences=max(1, n - 1))["summary_short"]
                     if is_ex and n <= 3 else d["summary_short"])
        b = by[bucket(n)]
        b["n"] += 1
        b["identical"] += same
        b["identical_simulated"] += norm(sim_short) == norm(d["summary_long"])
    total = {k: sum(v[k] for v in by.values()) for k in ("n", "identical", "identical_simulated")}
    payload = {
        "meta": run_metadata("research/experiments/e09_summary_identity.py", tag=args.tag,
                             source="live MongoDB processed_articles (read-only)",
                             simulated_rule="short = max(1, n-1) sentences when n <= 3 (extractive rows only); NOT applied"),
        "total": total,
        "identical_rate": round(total["identical"] / total["n"], 4),
        "identical_rate_simulated": round(total["identical_simulated"] / total["n"], 4),
        "stored_pair_equals_extractive_output": extractive,
        "identical_and_substring_of_body": substring,
        "by_body_sentences": dict(sorted(by.items())),
    }
    print(write_json(f"e09_summary_identity_{args.tag}.json", payload))
    print({k: payload[k] for k in ("total", "identical_rate", "identical_rate_simulated",
                                   "stored_pair_equals_extractive_output", "identical_and_substring_of_body")})
    print(payload["by_body_sentences"])


if __name__ == "__main__":
    main()
