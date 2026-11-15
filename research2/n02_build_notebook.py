"""n02: write kaggle/nv_kaggle_scoring.ipynb from the shared prompt block in nv_common.py.

The notebook embeds the prompt/parser block verbatim plus the expected prompt hash and
the expected input-file hash (from n01), so a stale prompt or input fails loudly on Kaggle.

Usage:  python research2/n02_build_notebook.py --prep-tag 2026-11-15 --run-tag kaggle-2026-11-15
"""
from __future__ import annotations

import argparse
import json

from nv_common import ROOT, RESULTS, prompt_sha256


def shared_block() -> str:
    src = (ROOT / "nv_common.py").read_text(encoding="utf-8")
    start = src.index("# --- BEGIN SHARED ---")
    end = src.index("# --- END SHARED ---") + len("# --- END SHARED ---")
    return src[start:end]


def md(text: str) -> dict:
    return {"cell_type": "markdown", "metadata": {}, "source": text.strip("\n").splitlines(keepends=True)}


def code(text: str) -> dict:
    return {"cell_type": "code", "metadata": {}, "execution_count": None, "outputs": [],
            "source": text.strip("\n").splitlines(keepends=True)}


def build(prep_tag: str, run_tag: str) -> dict:
    prep = json.loads((RESULTS / f"n01_prepare_{prep_tag}.json").read_text(encoding="utf-8"))
    input_sha = prep["files"]["data/articles_to_score.jsonl"]
    n_expected = prep["candidate_articles"]
    psha = prompt_sha256()
    assert prep["prompt_sha256"] == psha, "prompt changed after n01: rerun n01 first"

    cells = [
        md(f"""
# research2 — news-value scoring of MIND articles (Kaggle, GPU T4 x2)

Scores every MIND-small candidate article ({n_expected:,}) on seven news values with
`Qwen/Qwen2.5-7B-Instruct`, greedy decoding, using the prompt from `research2/nv_common.py`
(prompt sha256 `{psha[:16]}…`). Input: `articles_to_score.jsonl` (sha256 `{input_sha[:16]}…`).

**Settings before running:** Accelerator **GPU T4 x2** · Internet **on** · Add Input → your private
dataset holding `articles_to_score.jsonl`. Then **Save Version → Save & Run All (Commit)**.
The pilot cell stops the run if fewer than 95% of the first 50 outputs parse.

**Output:** `/kaggle/working/nv_scores_{run_tag}.jsonl` (one line per attempt) and
`nv_summary_{run_tag}.json`. Download both from the version's Output tab.

**Resume:** if a run dies, add that version's output as an input and run again; finished ids are skipped.
"""),
        code(f"""
import os, sys, glob, json, time, math, hashlib, random
from datetime import datetime, timezone

MODEL_ID = os.environ.get("NV_MODEL", "Qwen/Qwen2.5-7B-Instruct")
BATCH_SIZE = int(os.environ.get("NV_BATCH", "32"))
MAX_NEW_TOKENS = 64
RETRY_MAX_NEW_TOKENS = 128
PILOT_N = 50
PILOT_MIN_PARSE = float(os.environ.get("NV_PILOT_MIN_PARSE", "0.95"))
LIMIT = int(os.environ.get("NV_LIMIT", "0"))          # 0 = all rows (testing only)
INPUT_GLOB = os.environ.get("NV_INPUT_GLOB", "/kaggle/input/**/articles_to_score.jsonl")
RESUME_GLOB = os.environ.get("NV_RESUME_GLOB", "/kaggle/input/**/nv_scores_*.jsonl")
OUT_DIR = os.environ.get("NV_OUT_DIR", "/kaggle/working")
RUN_TAG = "{run_tag}"
EXPECTED_PROMPT_SHA = "{psha}"
EXPECTED_INPUT_SHA = "{input_sha}"
EXPECTED_N = {n_expected}
OUT_PATH = os.path.join(OUT_DIR, f"nv_scores_{{RUN_TAG}}.jsonl")
SUMMARY_PATH = os.path.join(OUT_DIR, f"nv_summary_{{RUN_TAG}}.json")
os.makedirs(OUT_DIR, exist_ok=True)
print("model", MODEL_ID, "| batch", BATCH_SIZE, "| out", OUT_PATH)
"""),
        code("""
import torch, transformers
print("python", sys.version.split()[0], "| torch", torch.__version__, "| transformers", transformers.__version__)
assert torch.cuda.is_available(), "No GPU: set Accelerator to GPU T4 x2"
gpus = [torch.cuda.get_device_properties(i) for i in range(torch.cuda.device_count())]
for i, g in enumerate(gpus):
    print(f"cuda:{i}", g.name, round(g.total_memory / 2**30, 1), "GiB")
total_gib = sum(g.total_memory for g in gpus) / 2**30
if not os.environ.get("NV_ALLOW_ANY_GPU"):
    assert total_gib >= 28, f"Need ~30 GiB of GPU memory for a 7B fp16 model (have {total_gib:.1f}); choose GPU T4 x2"
"""),
        code(shared_block() + """

assert prompt_sha256() == EXPECTED_PROMPT_SHA, "prompt differs from research2/nv_common.py: rebuild the notebook"
print("prompt sha256 OK", EXPECTED_PROMPT_SHA[:16])
"""),
        code("""
def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()

found = sorted(glob.glob(INPUT_GLOB, recursive=True))
assert len(found) == 1, f"expected exactly one articles_to_score.jsonl, found {found}"
INPUT_PATH = found[0]
input_sha = sha256_file(INPUT_PATH)
assert input_sha == EXPECTED_INPUT_SHA, f"input file differs from n01 output ({input_sha[:16]})"
with open(INPUT_PATH, encoding="utf-8") as f:
    rows = [json.loads(l) for l in f if l.strip()]
assert len(rows) == EXPECTED_N and len({r["id"] for r in rows}) == EXPECTED_N, len(rows)
if LIMIT:
    rows = rows[:LIMIT]
print("input", INPUT_PATH, "|", len(rows), "rows")

# resume: earlier outputs (attached inputs or this run's own file)
done = {}
prev_files = sorted(set(glob.glob(RESUME_GLOB, recursive=True)) | ({OUT_PATH} if os.path.exists(OUT_PATH) else set()))
for p in prev_files:
    with open(p, encoding="utf-8") as f:
        for l in f:
            if not l.strip():
                continue
            try:
                rec = json.loads(l)
            except ValueError:
                continue                      # a line cut off by a crash
            if rec.get("ok") and rec.get("prompt_sha256") == EXPECTED_PROMPT_SHA and rec.get("model") == MODEL_ID:
                done[rec["id"]] = rec
print("resumed ok records:", len(done), "from", prev_files)
if prev_files and OUT_PATH not in prev_files:
    with open(OUT_PATH, "a", encoding="utf-8") as out:   # carry finished records into this run's file
        for rec in done.values():
            out.write(json.dumps(rec, ensure_ascii=False) + "\\n")
"""),
        code("""
from transformers import AutoModelForCausalLM, AutoTokenizer
tok = AutoTokenizer.from_pretrained(MODEL_ID)
tok.padding_side = "left"
if tok.pad_token_id is None:
    tok.pad_token = tok.eos_token
dtype_kw = {"dtype": torch.float16} if tuple(int(x) for x in transformers.__version__.split(".")[:2]) >= (4, 56) else {"torch_dtype": torch.float16}
t0 = time.time()
model = AutoModelForCausalLM.from_pretrained(MODEL_ID, device_map="auto", **dtype_kw)
model.eval()
FIRST_DEVICE = next(model.parameters()).device
print("loaded in", round(time.time() - t0), "s | device map:", getattr(model, "hf_device_map", None) and sorted(set(model.hf_device_map.values())))
"""),
        code("""
def generate(batch_rows, max_new):
    texts = [tok.apply_chat_template(build_messages(r["title"], r["abstract"]), tokenize=False,
                                     add_generation_prompt=True) for r in batch_rows]
    enc = tok(texts, return_tensors="pt", padding=True).to(FIRST_DEVICE)
    with torch.inference_mode():
        out = model.generate(**enc, max_new_tokens=max_new, do_sample=False, temperature=None, top_p=None,
                             top_k=None, repetition_penalty=1.0,   # Qwen's default 1.05 would penalise repeated digits
                             pad_token_id=tok.pad_token_id)
    gen = out[:, enc["input_ids"].shape[1]:]
    return [tok.decode(g, skip_special_tokens=True) for g in gen]


def safe_generate(batch_rows, max_new):
    try:
        return generate(batch_rows, max_new)
    except torch.cuda.OutOfMemoryError:
        torch.cuda.empty_cache()
        if len(batch_rows) == 1:
            raise
        half = len(batch_rows) // 2
        print(f"OOM at batch {len(batch_rows)} -> splitting")
        return safe_generate(batch_rows[:half], max_new) + safe_generate(batch_rows[half:], max_new)


def score_rows(todo, batch_size, max_new, label):
    todo = sorted(todo, key=lambda r: len(r["title"]) + len(r["abstract"]))   # less padding per batch
    n_ok, t0 = 0, time.time()
    with open(OUT_PATH, "a", encoding="utf-8") as out:
        for b in range(0, len(todo), batch_size):
            chunk = todo[b:b + batch_size]
            for r, raw in zip(chunk, safe_generate(chunk, max_new)):
                scores = parse_scores(raw)
                rec = {"id": r["id"], "ok": scores is not None, "scores": scores, "raw": raw,
                       "model": MODEL_ID, "prompt_sha256": EXPECTED_PROMPT_SHA, "max_new_tokens": max_new,
                       "run_tag": RUN_TAG, "ts": datetime.now(timezone.utc).isoformat(timespec="seconds")}
                out.write(json.dumps(rec, ensure_ascii=False) + "\\n")
                if scores is not None:
                    done[r["id"]] = rec
                    n_ok += 1
            out.flush()
            k = b + len(chunk)
            if (b // batch_size) % 20 == 0 or k == len(todo):
                rate = k / max(time.time() - t0, 1e-9)
                print(f"[{label}] {k}/{len(todo)} | ok {n_ok} | {rate:.2f} items/s | ETA {(len(todo) - k) / max(rate, 1e-9) / 60:.1f} min", flush=True)
    return n_ok
"""),
        code("""
# PILOT: first 50 input rows (a random sample fixed by n01). Stops the run if parsing is unreliable.
pilot_rows = rows[:PILOT_N]
todo = [r for r in pilot_rows if r["id"] not in done]
t0 = time.time()
if todo:
    score_rows(todo, BATCH_SIZE, MAX_NEW_TOKENS, "pilot")
pilot_secs = time.time() - t0
ok = [done[r["id"]] for r in pilot_rows if r["id"] in done]
rate = len(ok) / len(pilot_rows)
print(f"pilot parse rate {rate:.3f} ({len(ok)}/{len(pilot_rows)}) in {pilot_secs:.0f}s")
for v in VALUES:
    dist = [sum(1 for rec in ok if rec["scores"][v] == s) for s in range(1, 6)]
    flag = "  <-- one score dominates" if ok and max(dist) > 0.9 * len(ok) else ""
    print(f"  {v:13s} 1..5 = {dist}{flag}")
for r in pilot_rows[:5]:
    print("-", r["title"][:90], "->", done.get(r["id"], {}).get("scores"))
assert rate >= PILOT_MIN_PARSE, f"pilot parse rate {rate:.3f} < {PILOT_MIN_PARSE}: stop and send the output file back"
if todo:
    print(f"rough ETA for the full run: {(len(rows) - len(done)) * pilot_secs / len(todo) / 3600:.1f} h (batches get longer late in the run)")
"""),
        code("""
# FULL RUN
todo = [r for r in rows if r["id"] not in done]
print("to score:", len(todo))
score_rows(todo, BATCH_SIZE, MAX_NEW_TOKENS, "full")
"""),
        code("""
# RETRY items that did not parse: smaller batches, longer output allowance
todo = [r for r in rows if r["id"] not in done]
print("retrying:", len(todo))
if todo:
    score_rows(todo, 8, RETRY_MAX_NEW_TOKENS, "retry")
"""),
        code("""
failed = [r["id"] for r in rows if r["id"] not in done]
summary = {"run_tag": RUN_TAG, "model": MODEL_ID, "prompt_sha256": EXPECTED_PROMPT_SHA, "input_sha256": input_sha,
           "rows": len(rows), "ok": len(rows) - len(failed), "failed": len(failed), "failed_ids": failed[:200],
           "batch_size": BATCH_SIZE, "max_new_tokens": MAX_NEW_TOKENS, "decoding": "greedy, repetition_penalty 1.0",
           "torch": torch.__version__, "transformers": transformers.__version__,
           "gpus": [g.name for g in gpus], "finished_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "output_sha256": sha256_file(OUT_PATH)}
with open(SUMMARY_PATH, "w") as f:
    json.dump(summary, f, indent=2)
print(json.dumps({k: v for k, v in summary.items() if k != "failed_ids"}, indent=1))
print("Download:", OUT_PATH, "and", SUMMARY_PATH)
"""),
    ]
    return {"cells": cells, "metadata": {"kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
                                          "language_info": {"name": "python"}},
            "nbformat": 4, "nbformat_minor": 5}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--prep-tag", required=True)
    ap.add_argument("--run-tag", required=True)
    args = ap.parse_args()
    nb = build(args.prep_tag, args.run_tag)
    out = ROOT / "kaggle" / "nv_kaggle_scoring.ipynb"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(nb, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print("wrote", out)


if __name__ == "__main__":
    main()
