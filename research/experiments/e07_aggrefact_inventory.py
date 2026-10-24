"""
E07 — inventory of LLM-AggreFact (lytang/LLM-AggreFact @ 981dfd0b; CC-BY-ND-4.0, evaluation only).

Checks row counts per split and per dataset, label balance, field names, empty fields and duplicate
(doc, claim) pairs. Writes results/e07_aggrefact_inventory_<tag>.json (counts only, no text).
"""

import argparse
import hashlib
from collections import Counter

import pandas as pd

from _common import DATA, run_metadata, utf8_stdout, write_json

ROOT_DS = DATA / "external" / "llm_aggrefact" / "data"
EXPECTED_ROWS = {"test": 29320, "dev": 30420}          # dataset card, retrieved 2026-10-23
EXPECTED_DATASETS = {"AggreFact-CNN", "AggreFact-XSum", "TofuEval-MediaS", "TofuEval-MeetB", "Wice", "Reveal",
                     "ClaimVerify", "FactCheck-GPT", "ExpertQA", "Lfqa", "RAGTruth"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", required=True)
    args = ap.parse_args()
    utf8_stdout()
    splits = {}
    for split in ("test", "dev"):
        df = pd.read_parquet(ROOT_DS / f"{split}-00000-of-00001.parquet")
        per = {}
        for ds, g in df.groupby("dataset"):
            c = Counter(int(x) for x in g["label"])
            per[ds] = {"n": int(len(g)), "supported": c[1], "unsupported": c[0],
                       "share_supported": round(c[1] / len(g), 4)}
        pairs = df["doc"].str.cat(df["claim"], sep="\x00")
        splits[split] = {
            "rows": int(len(df)), "expected_rows": EXPECTED_ROWS[split],
            "rows_match": int(len(df)) == EXPECTED_ROWS[split],
            "columns": list(df.columns),
            "datasets": sorted(per), "n_datasets": len(per),
            "per_dataset": per,
            "labels": dict(Counter(int(x) for x in df["label"])),
            "empty_doc": int((df["doc"].str.strip() == "").sum()),
            "empty_claim": int((df["claim"].str.strip() == "").sum()),
            "duplicate_doc_claim_pairs": int(pairs.duplicated().sum()),
            "doc_chars_p50": float(df["doc"].str.len().median()),
            "claim_chars_p50": float(df["claim"].str.len().median()),
        }
    names = set(splits["test"]["datasets"])
    payload = {
        "meta": run_metadata("research/experiments/e07_aggrefact_inventory.py", tag=args.tag,
                             dataset="lytang/LLM-AggreFact", revision="981dfd0bd8e58e7238a9ab92b2e6ea44bce918e4",
                             licence="CC-BY-ND-4.0, evaluation only (no training/fine-tuning)"),
        "splits": splits,
        "dataset_names_vs_leaderboard_columns": {
            "found": sorted(names), "missing_from_expected": sorted(EXPECTED_DATASETS - names),
            "unexpected": sorted(names - EXPECTED_DATASETS)},
        "test_dev_doc_claim_overlap": None,
    }
    test = pd.read_parquet(ROOT_DS / "test-00000-of-00001.parquet")
    dev = pd.read_parquet(ROOT_DS / "dev-00000-of-00001.parquet")
    h = lambda df: {hashlib.sha1((d + "\x00" + c).encode("utf-8")).hexdigest() for d, c in zip(df.doc, df.claim)}
    payload["test_dev_doc_claim_overlap"] = len(h(test) & h(dev))
    print(write_json(f"e07_aggrefact_inventory_{args.tag}.json", payload))
    for s, v in splits.items():
        print(s, v["rows"], "match" if v["rows_match"] else "MISMATCH", v["n_datasets"], "datasets", v["labels"],
              "dups", v["duplicate_doc_claim_pairs"])
        for ds, x in v["per_dataset"].items():
            print("   ", ds, x)
    print("names", payload["dataset_names_vs_leaderboard_columns"])
    print("test/dev (doc, claim) overlap", payload["test_dev_doc_claim_overlap"])


if __name__ == "__main__":
    main()
