"""
E21 (S2) — MAPNAI's current fact gate on LLM-AggreFact, with the two wrappers pre-registered in research/PREREG.md §3:
  (a) v1-as-is       factcheck.verify(source=doc, rewrite=claim, entity_names=NER(doc))  → pred = passes
  (b) additions-only reject iff verify reports an added number                           → pred = no added number
NER(doc) = the production Agent 1 path: models/mapnai-ner-bert token-classification pipeline (aggregation "first",
stride 128, max length 512) → agents.ner_utils.deduplicate_and_merge_entities; when BERT returns nothing, the
ingestion spaCy entities (agents.enrichment_agent.extract_entities, first 1,000 characters), as NERAgent.process.

Step 1a (--step ner, checker venv, GPU): BERT names per unique document → cache/e21_ner_<split>.jsonl (resumable).
Step 1b (--step ner-fallback, app venv): spaCy names for the documents BERT left empty.
Step 2 (--step gate): both wrappers on every row; the same metrics as e20 (per-dataset BAcc with 95% bootstrap CIs,
News-3, all 11). Output: results/e21_gate_<wrapper>_<split>_<tag>.json + _preds.jsonl.gz (no text).
"""

import argparse
import gzip
import hashlib
import json
import time

from _common import EXP_DIR, ROOT, run_metadata, utf8_stdout, write_json

DATA = EXP_DIR / "data" / "external" / "llm_aggrefact" / "data"
CACHE = EXP_DIR / "cache"


def load_split(split: str):
    """The parquet split, or its jsonl.gz export (same rows and order) where pandas has no parquet engine (the pinned
    app environment has none; the export is written once from the checker environment)."""
    import pandas as pd
    try:
        return pd.read_parquet(DATA / f"{split}-00000-of-00001.parquet")
    except ImportError:
        return pd.read_json(DATA.parent / f"{split}.jsonl.gz", lines=True, compression="gzip")


def doc_key(doc: str) -> str:
    return hashlib.sha1(doc.encode("utf-8")).hexdigest()


# agents.ner_agent.label_map() with its default (production) MISC label; inlined so the GPU step can run in the checker
# environment, which cannot import ner_agent. tests/test_ner_labels.py asserts the two stay equal.
LABEL_MAP = {"PER": "Person", "ORG": "Organization", "LOC": "Location", "MISC": "Product"}


def step_ner(split: str):
    """BERT pass (checker venv, GPU). Documents where BERT finds nothing are written with names None, ner
    "needs-fallback"; step ner-fallback fills them from spaCy in the app environment, as NERAgent.process does."""
    from transformers import AutoTokenizer, pipeline
    from agents.ner_utils import deduplicate_and_merge_entities

    df = load_split(split)
    docs = {doc_key(d): d for d in df.doc}
    out = CACHE / f"e21_ner_{split}.jsonl"
    done = {json.loads(l)["key"] for l in out.open(encoding="utf-8")} if out.exists() else set()
    todo = [k for k in sorted(docs) if k not in done]
    print(f"{len(done)} cached, {len(todo)} documents to tag", flush=True)
    path = str(ROOT / "models" / "mapnai-ner-bert")
    tok = AutoTokenizer.from_pretrained(path)
    if tok.model_max_length > 512:
        tok.model_max_length = 512
    import torch
    ner = pipeline("token-classification", model=path, tokenizer=tok, aggregation_strategy="first", stride=128,
                   device=0 if torch.cuda.is_available() else -1)
    t0 = time.time()
    with out.open("a", encoding="utf-8") as fh:
        for n, k in enumerate(todo, 1):
            text = docs[k]
            raw = []
            for ent in ner(text):
                group = ent.get("entity_group") or ent.get("entity") or ""
                mapped = LABEL_MAP.get(group.replace("B-", "").replace("I-", ""), LABEL_MAP.get(group))
                if mapped:
                    raw.append({"text": ent.get("word", "").strip(), "label": mapped, "start": ent.get("start", 0),
                                "end": ent.get("end", 0)})
            names = [e["name"] for e in deduplicate_and_merge_entities(raw, len(text), "other")] if raw else None
            fh.write(json.dumps({"key": k, "names": names, "ner": "bert" if raw else "needs-fallback",
                                 "device": str(ner.device)}, ensure_ascii=False) + "\n")
            if n % 500 == 0:
                print(f"  {n}/{len(todo)}  {n / (time.time() - t0):.1f} docs/s", flush=True)


def step_ner_fallback(split: str):
    """spaCy entities (agents.enrichment_agent.extract_entities, first 1,000 characters) for the documents BERT left
    empty; rewrites the cache with them (app environment)."""
    from agents.enrichment_agent import extract_entities
    df = load_split(split)
    docs = {doc_key(d): d for d in df.doc}
    path = CACHE / f"e21_ner_{split}.jsonl"
    rows = [json.loads(l) for l in path.open(encoding="utf-8")]
    filled = 0
    for r in rows:
        if r["ner"] == "needs-fallback":
            r["names"], r["ner"] = [e["name"] for e in extract_entities(docs[r["key"]])], "spacy-fallback"
            filled += 1
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    print(f"{filled} documents filled from spaCy")


def step_gate(split: str, tag: str):
    import pandas as pd
    from e20_aggrefact_eval import NEWS3, REVISION, summarize
    from personalization import factcheck

    df = load_split(split)
    ner = {}
    for line in (CACHE / f"e21_ner_{split}.jsonl").open(encoding="utf-8"):
        r = json.loads(line)
        ner[r["key"]] = r
    missing_ner = sum(doc_key(d) not in ner or ner[doc_key(d)]["names"] is None for d in df.doc.unique())
    if missing_ner:
        raise SystemExit(f"{missing_ner} documents have no NER yet: run --step ner first")
    preds = {"v1_as_is": [], "additions_only": []}
    t0 = time.time()
    for i, (doc, claim, label, ds) in enumerate(zip(df.doc, df.claim, df.label, df.dataset)):
        ok, missing, added = factcheck.verify(doc, claim, ner[doc_key(doc)]["names"])
        preds["v1_as_is"].append({"row": i, "dataset": ds, "label": int(label), "pred": int(ok)})
        preds["additions_only"].append({"row": i, "dataset": ds, "label": int(label), "pred": int(not added)})
    ms = (time.time() - t0) * 1000 / len(df)
    ner_sources = {}
    for k in {doc_key(d) for d in df.doc}:
        ner_sources[ner[k]["ner"]] = ner_sources.get(ner[k]["ner"], 0) + 1
    for wrapper, rows in preds.items():
        name = f"e21_gate_{wrapper}_{split}_{tag}"
        payload = {"meta": run_metadata("research/experiments/e21_gate_aggrefact.py", wrapper=wrapper, split=split,
                                        tag=tag, dataset_revision=REVISION, gate="factcheck v1 (production default)",
                                        ner_sources_unique_docs=ner_sources, ms_per_row_both_wrappers=round(ms, 3)),
                   "n": len(rows), "serve_rate": round(sum(r["pred"] for r in rows) / len(rows), 4),
                   **summarize(rows)}
        print(write_json(f"{name}.json", payload))
        with gzip.open(EXP_DIR / "results" / f"{name}_preds.jsonl.gz", "wt", encoding="utf-8") as fh:
            for r in rows:
                fh.write(json.dumps(r) + "\n")
        print(wrapper, "serve", payload["serve_rate"], "avg", payload["avg_all"]["bacc"], payload["avg_all"]["ci95"],
              "news3", payload["news3"]["bacc"], payload["news3"]["ci95"])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--step", required=True, choices=["ner", "ner-fallback", "gate"])
    ap.add_argument("--split", default="test", choices=["test", "dev"])
    ap.add_argument("--tag", default=None)
    args = ap.parse_args()
    utf8_stdout()
    if args.step == "ner":
        step_ner(args.split)
    elif args.step == "ner-fallback":
        step_ner_fallback(args.split)
    else:
        step_gate(args.split, args.tag or time.strftime("%Y-%m-%d"))


if __name__ == "__main__":
    main()
