"""
MAPNAI — scripts/classifier/build_dataset.py
Builds the pool of candidate articles that the LLM will label for training.

Sources:
  - data/classifier/rss_raw.jsonl (from collect_rss.py) — real pipeline-style articles
  - Hugging Face public datasets (downloaded once, cached by huggingface_hub):
      fancyzhx/ag_news              — short news; "Sports" class + negatives
      SetFit/bbc-news               — full articles; sport / entertainment + negatives
      heegyu/news-category-dataset  — HuffPost; ENTERTAINMENT / SPORTS + negatives

`hint_domain` is only the source's claim. The LLM assigns the real label, so e.g. a
HuffPost "ENTERTAINMENT" item about a music album correctly ends up as "other".

Usage (from the project root):
    python -m scripts.classifier.build_dataset
"""

import argparse
import hashlib
import json
import random
import re
from pathlib import Path

import pandas as pd
from huggingface_hub import hf_hub_download

from utils.text_cleaner import clean_text

OUT_DIR = Path("data/classifier")
RSS_PATH = OUT_DIR / "rss_raw.jsonl"
OUT_PATH = OUT_DIR / "candidates.jsonl"


def _id(title: str, body: str) -> str:
    return hashlib.sha1((title.lower() + "|" + body[:200].lower()).encode("utf-8")).hexdigest()


def _rec(title: str, body: str, source: str, hint: str) -> dict:
    title, body = clean_text(title), clean_text(body)
    return {"id": _id(title, body), "title": title, "body": body,
            "source": source, "hint_domain": hint}


def _sample(df: pd.DataFrame, n: int, seed: int) -> pd.DataFrame:
    return df.sample(n=min(n, len(df)), random_state=seed)


def load_ag_news(n_sports: int, n_other: int, seed: int) -> list:
    path = hf_hub_download("fancyzhx/ag_news", "data/train-00000-of-00001.parquet", repo_type="dataset")
    df = pd.read_parquet(path)
    out = []
    for _, r in _sample(df[df.label == 1], n_sports, seed).iterrows():
        out.append(_rec("", r.text, "ag_news", "sports"))
    for _, r in _sample(df[df.label != 1], n_other, seed).iterrows():
        out.append(_rec("", r.text, "ag_news", "other"))
    return out


def load_bbc(n_sport: int, n_ent: int, n_other: int, seed: int) -> list:
    path = hf_hub_download("SetFit/bbc-news", "train.jsonl", repo_type="dataset")
    df = pd.read_json(path, lines=True)
    out = []
    for label, n, hint in (("sport", n_sport, "sports"), ("entertainment", n_ent, "entertainment_movies")):
        for _, r in _sample(df[df.label_text == label], n, seed).iterrows():
            out.append(_rec("", r.text, "bbc_news", hint))
    others = df[~df.label_text.isin(["sport", "entertainment"])]
    for _, r in _sample(others, n_other, seed).iterrows():
        out.append(_rec("", r.text, "bbc_news", "other"))
    return out


def load_huffpost(n_sports: int, n_ent: int, n_other: int, seed: int) -> list:
    path = hf_hub_download("heegyu/news-category-dataset", "data.json", repo_type="dataset")
    df = pd.read_json(path, lines=True)
    df = df[df.short_description.str.len() > 40]
    out = []
    for cat, n, hint in (("SPORTS", n_sports, "sports"), ("ENTERTAINMENT", n_ent, "entertainment_movies")):
        for _, r in _sample(df[df.category == cat], n, seed).iterrows():
            out.append(_rec(r.headline, r.short_description, "huffpost", hint))
    # Near-miss categories make the best negatives; keep them over-represented.
    near = df[df.category.isin(["MEDIA", "COMEDY", "ARTS & CULTURE", "CULTURE & ARTS", "STYLE & BEAUTY"])]
    rest = df[~df.category.isin(["SPORTS", "ENTERTAINMENT"]) & ~df.index.isin(near.index)]
    for part, n in ((near, n_other // 3), (rest, n_other - n_other // 3)):
        for _, r in _sample(part, n, seed).iterrows():
            out.append(_rec(r.headline, r.short_description, "huffpost", "other"))
    return out


# Keyword-targeted extra candidates for urgency cases the random samples under-cover
# (urgent events are rare, and routine results are the easiest to mistake for them).
# These only choose WHICH articles get labelled — the LLM still assigns the actual label.
TARGETED = [
    # (name, hint_domain, regex, n)
    ("urgent",    "sports", r"\b(injur\w*|ruled out|died|dies|death|arrested|banned|doping|suspended|postponed|cancell?ed|scandal|match.fixing)\b", 250),
    ("not_urgent","sports", r"\b(wins?|won|beat|beats|victory|squad|announce[sd]?|preview|record)\b", 200),
    ("urgent",    "entertainment_movies", r"\b(died|dies|death|arrested|banned|postponed|pulled|hospitali[sz]ed|lawsuit|scandal)\b", 200),
]


def load_targeted(seed: int) -> list:
    huff = pd.read_json(hf_hub_download("heegyu/news-category-dataset", "data.json", repo_type="dataset"), lines=True)
    huff = huff[huff.short_description.str.len() > 40]
    huff["text"] = huff.headline + " " + huff.short_description
    ag = pd.read_parquet(hf_hub_download("fancyzhx/ag_news", "data/train-00000-of-00001.parquet", repo_type="dataset"))

    pools = {
        "entertainment_movies": huff[huff.category == "ENTERTAINMENT"],
        "sports": pd.concat([
            huff[huff.category == "SPORTS"][["headline", "short_description", "text"]],
            ag[ag.label == 1].assign(headline="", short_description=ag.text)[["headline", "short_description", "text"]],
        ]),
    }
    out = []
    for name, hint, pattern, n in TARGETED:
        pool = pools[hint]
        pattern = re.sub(r"\((?!\?)", "(?:", pattern)  # non-capturing groups (avoids pandas warning)
        hits = pool[pool.text.str.contains(pattern, case=False, regex=True)]
        for _, r in _sample(hits, n, seed).iterrows():
            out.append(_rec(r.headline, r.short_description, f"targeted:{name}", hint))
    return out


def load_rss() -> list:
    if not RSS_PATH.exists():
        print(f"[warn] {RSS_PATH} not found — run collect_rss.py first for pipeline-style data.")
        return []
    with RSS_PATH.open(encoding="utf-8") as f:
        rows = [json.loads(line) for line in f if line.strip()]
    return [_rec(r["title"], r["body"], r["source"], r["hint_domain"]) for r in rows]


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--seed", type=int, default=42)
    args = p.parse_args()

    records = (
        load_rss()
        + load_ag_news(n_sports=700, n_other=500, seed=args.seed)
        + load_bbc(n_sport=300, n_ent=350, n_other=300, seed=args.seed)
        + load_huffpost(n_sports=500, n_ent=1300, n_other=400, seed=args.seed)
        + load_targeted(seed=args.seed)
    )

    # Drop near-empty items and duplicates (RSS re-runs, overlaps between datasets)
    unique = {}
    for r in records:
        if len(r["title"]) + len(r["body"]) >= 60:
            unique.setdefault(r["id"], r)
    rows = list(unique.values())
    random.Random(args.seed).shuffle(rows)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with OUT_PATH.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    by_hint = pd.Series([r["hint_domain"] for r in rows]).value_counts().to_dict()
    by_src = pd.Series([r["source"].split(":")[0] for r in rows]).value_counts().to_dict()
    print(f"Wrote {len(rows)} candidates to {OUT_PATH}")
    print(f"  by hinted domain: {by_hint}")
    print(f"  by source:        {by_src}")


if __name__ == "__main__":
    main()
