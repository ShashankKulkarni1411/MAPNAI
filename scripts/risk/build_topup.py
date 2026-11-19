"""
MAPNAI — scripts/risk/build_topup.py
Mines extra candidate articles for the rare Agent 4 event types (doping, match-fixing,
cancellations, bans, legal) from the full public datasets that build_dataset.py only samples.

The first labelling run (data/classifier/candidates.jsonl) gave only 2 match-fixing, ~40 doping and
~40 cancellation articles — too few to train on. Keywords only choose WHICH articles get labelled;
the LLM in scripts/risk/label_*.ipynb still assigns the actual event type.

Usage (from the project root):
    python -m scripts.risk.build_topup
Writes data/risk/candidates_extra.jsonl — upload it next to candidates.jsonl for labelling.
"""

import argparse
import json
import random
import re
from collections import Counter
from pathlib import Path

import pandas as pd
from huggingface_hub import hf_hub_download

from scripts.classifier.build_dataset import OUT_PATH as BASE_CANDIDATES, _rec

OUT_PATH = Path("data/risk/candidates_extra.jsonl")

# (target event type, hint_domain, regex, max articles)
TOPUP = [
    ("doping", "sports",
     r"\b(doping|dope test|drugs? tests?|tested positive|failed (a )?(drugs? |dope )?test|banned substance"
     r"|steroids?|EPO|anti-doping|WADA|USADA|nandrolone|meldonium|performance.enhancing)\b", 300),
    ("match_fixing", "sports",
     r"\b(match.fixing|spot.fixing|fix(ed|ing)? (a |the )?(match|game|race|fight)|point.shaving"
     r"|betting (scandal|scam|probe|inquiry|ring|syndicate)|illegal betting|bookmakers? (probe|inquiry)"
     r"|bribe(s|d|ry)?|corruption)\b", 300),
    ("cancellation", "sports",
     r"\b(postponed|called off|cancell?ed|rained off|washed out|abandoned|lockout|relocated|scrapped)\b", 250),
    ("cancellation", "entertainment_movies",
     r"\b(postponed|cancell?ed|called off|scrapped|shelved|pulled (from|the)|release (pushed|delayed)"
     r"|delays? (its |the )?release)\b", 200),
    ("ban_suspension", "sports",
     r"\b(suspended|suspension|banned|ban for|fined|sanction(s|ed)?|disqualified|expelled)\b", 250),
    ("ban_suspension", "entertainment_movies",
     r"\b(banned|censor(ed|ship)|boycott(s|ed)?|blacklist(ed)?|pulled from)\b", 100),
    ("legal", "sports",
     r"\b(lawsuit|sued|sues|arrested|charged with|indicted|convicted|sentenced|trial|pleads? guilty)\b", 100),
    ("legal", "entertainment_movies",
     r"\b(lawsuit|sued|sues|arrested|charged with|indicted|convicted|sentenced|trial|pleads? guilty)\b", 100),
]


def load_pools() -> dict:
    """Full sports / entertainment pools as (title, body) frames with a combined `text` column."""
    huff = pd.read_json(hf_hub_download("heegyu/news-category-dataset", "data.json", repo_type="dataset"),
                        lines=True)
    huff = huff[huff.short_description.str.len() > 40].rename(
        columns={"headline": "title", "short_description": "body"})
    ag = pd.read_parquet(hf_hub_download("fancyzhx/ag_news", "data/train-00000-of-00001.parquet",
                                         repo_type="dataset"))
    ag = ag[ag.label == 1].assign(title="", body=ag.text)
    bbc = pd.read_json(hf_hub_download("SetFit/bbc-news", "train.jsonl", repo_type="dataset"), lines=True)
    bbc = bbc.assign(title="", body=bbc.text)

    def frame(parts):
        df = pd.concat([p[["title", "body", "src"]] for p in parts], ignore_index=True)
        df["text"] = df.title + " " + df.body
        return df

    return {
        "sports": frame([huff[huff.category == "SPORTS"].assign(src="huffpost"),
                         ag.assign(src="ag_news"),
                         bbc[bbc.label_text == "sport"].assign(src="bbc_news")]),
        "entertainment_movies": frame([huff[huff.category == "ENTERTAINMENT"].assign(src="huffpost"),
                                       bbc[bbc.label_text == "entertainment"].assign(src="bbc_news")]),
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--seed", type=int, default=42)
    args = p.parse_args()

    with BASE_CANDIDATES.open(encoding="utf-8") as f:
        seen = {json.loads(line)["id"] for line in f if line.strip()}
    pools = load_pools()

    rows, hits_per_rule = [], []
    for event_type, hint, pattern, n in TOPUP:
        pool = pools[hint]
        pattern = re.sub(r"\((?!\?)", "(?:", pattern)  # non-capturing groups (avoids pandas warning)
        hits = pool[pool.text.str.contains(pattern, case=False, regex=True)]
        hits_per_rule.append((event_type, hint, len(hits)))
        added = 0
        for _, r in hits.sample(frac=1, random_state=args.seed).iterrows():
            rec = _rec(r.title, r.body, f"topup:{event_type}:{r.src}", hint)
            if rec["id"] in seen or len(rec["title"]) + len(rec["body"]) < 60:
                continue
            seen.add(rec["id"])
            rows.append(rec)
            added += 1
            if added >= n:
                break

    random.Random(args.seed).shuffle(rows)
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUT_PATH.open("w", encoding="utf-8") as f:
        f.writelines(json.dumps(r, ensure_ascii=False) + "\n" for r in rows)

    print(f"Wrote {len(rows)} new candidates to {OUT_PATH}")
    for event_type, hint, n_hits in hits_per_rule:
        print(f"  {event_type:15s} {hint:21s} keyword hits in full pool: {n_hits}")
    print("  added by target:", dict(Counter(r["source"].split(":")[1] for r in rows)))
    print("  added by dataset:", dict(Counter(r["source"].split(":")[2] for r in rows)))


if __name__ == "__main__":
    main()
