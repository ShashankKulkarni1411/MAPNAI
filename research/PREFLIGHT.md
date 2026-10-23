# PREFLIGHT (Phase 0)

**Date:** 2026-10-23 · **Branch:** `research/sota-push`, cut from `agent-satvik` @ `e642c48` ("PRESOTA") · **Author:** Claude (agent run)

## 0. Gate 0 result

| Gate item | Status | Evidence |
|---|---|---|
| All `research/*.md` + `REFERENCES.bib` read; quoted numbers re-verified | PASS (16 discrepancies listed in §1) | §1, `LEDGER.md` L0001–L0014 |
| `envs/` and `models/` inspected and git-ignored | PASS (`envs/` **does not exist**; ignore rule added anyway) | §2 |
| Machine facts recorded | PASS | §3 |
| Full test suite baseline | PASS: **720 passed, 0 failed, 0 skipped** | `research/experiments/results/baseline_pytest_2026-10-23.txt` (sha256 `b6174f57…f4e8`) |
| Branch exists, tag `pre-phase1` | PASS (tag set on the commit that adds this file) | `git tag -l pre-phase1` |

## 1. Re-verification of the earlier summary

### 1.1 Numbers that match their results file

E02 (`e02_gate_perturbation_2026-10-23.json`): identity pass rate 0.9989 (4 failing checks from 2 articles, `2b12616f…` and `7960644b…`, both fields, reason `month`); lexically visible macro 0.9683; semantic macro 0.0022; balanced accuracy 0.5744; number_change 0.9764; number_added 1.0; entity_substitution 0.9997; month_change 0.8969; role_swap 0.0007; negation 0.0015; hedge 0.0; outcome_flip 0.0064; possessive_stripped 1.0 (197/197); lead_50_words 0.8726; drop_last_sentence 0.5758 (short 0.6746 / long 0.4771); latency p50 501 µs, p95 3,419 µs; `summary_short` > 50 words 0.4748; `summary_long` p50 56 words.
E01 (`e01_cluster_pairs_2026-10-23.json`): P/R/F1 0.923/0.522/0.667; LOOCV F1 0.400; cosine-only F1 0.703; evidence-only F1 0.820; AUROC cosine 0.714, title-Jaccard 0.737; SimHash 0/46; MinHash 4/46.
E03 (`e03_live_descriptives_2026-10-23.json`): 1,864 clusters, singleton share 0.9276; materiality unscored 1.0, p50 0.2956; render fallback 4/12; classifier silver agreement 0.9391.

### 1.2 Discrepancies and corrections

| # | Claim as previously summarised / in the mission | What the primary file or source says | Consequence |
|---|---|---|---|
| D1 | Code state is `agent-satvik` @ `53f4b12` | HEAD was `e642c48` ("PRESOTA"), one commit later. `git diff 53f4b12 e642c48 -- . ':(exclude)research'` changes only `personalization.zip` (a 40-file copy of `personalization/`). **Application code = `53f4b12`.** | Branch cut from `e642c48`; result files keep their recorded `53f4b12` |
| D2 | "the `envs/` … folders the user just added" | No `envs/` directory exists in the repo, its parent, or `~`. `models/` exists (§2) | `envs/` added to `.gitignore` pre-emptively |
| D3 | "macro acceptance of benign edits 0.664" (reads as including identity) | The script defines benign **excluding identity** (`e02_gate_perturbation.py:270`): mean of reformat 1.0, possessive 0.0, reorder 0.9904 = 0.6635 | Wording fix only |
| D4 | F6: "3,382 spurious entities" | 3,382 entity **mentions** typed `Product` (of 14,705) in the 1,843-row E02 snapshot; plus 38 `Product/Technology`. Whether each is spurious is **UNVERIFIED** (no labelled sample). The 3,382 is not in any results file; recounted from `data/e02_gate_sources_2026-10-23.jsonl` | Re-measure in F6 dry-run |
| D5 | F9: "63% of articles have identical short and long summaries" | 1,160 / 1,843 = 62.9% of the **in-scope, summarised snapshot**, not of all 3,674 articles. Not in any results file before this recount | Re-measure in F9 |
| D6 | F7: "Agent 5 FAISS index ≈ 74% coverage (955 missing, 687 stale)" | The figures (2,719/3,674; 687 stale) appear in `METRICS_AND_EVALUATION_AUDIT.md` §4.3 as "E03 check", but **no results file contains them**; `e03_live_descriptives.py` has no coverage code. 3,674 − 2,719 = 955 and 3,406 − 2,719 = 687 are arithmetic only | **UNVERIFIED** until re-measured in F7 |
| D7 | Earlier test baseline "331 passed, 25 failed (environmental)" | Pinned Python 3.11.9 + `requirements.lock`: **720 passed, 0 failed, 0 skipped** across all 21 test files (196.6 s). The 25 failures were indeed environmental (unpinned mongomock/pymongo) | New baseline = 720/0/0 |
| D8 | Phase 3 literature table listed 6 top leaderboard rows | The live leaderboard default view (14 of 42 models) also shows Jev 1.1.3.0 (78.7), nimble-v4 9B (77.8), Granite Guardian 3.3 8B (76.5), Mistral-Large 2 (76.5), Qwen2.5-72B (75.6), which the earlier table omitted | Full table goes into `SOTA_TARGETS.md` (Phase 1) |
| D9 | MiniCheck-Flan-T5-L "≈ 74.7 avg (paper)" | Leaderboard (retrieved 2026-10-23): **75.0** average. The paper figure is not yet checked against the PDF | Phase 1 records both; S1 tolerance is applied against the protocol-matched number |
| D10 | LLM-AggreFact "~13k test instances across 11 datasets" | HF card `lytang/LLM-AggreFact`: **test 29,320, dev 30,420** rows; 11 datasets listed (the field description still says "10"); RAGTruth added 2024-09-08. The MiniCheck README also says "29K test set" | ~13k is outdated (probably the pre-RAGTruth version). Verify per-dataset counts in Phase 2 |
| D11 | LLM-AggreFact is a plain download | The dataset is **gated** ("agree to share your Hugging Face information"), licence **CC-BY-ND-4.0**, evaluation only; not to be used for pre-training or fine-tuning. No HF token exists on this machine | Requires the user to log in and accept the terms: **H4 stop in Phase 2** |
| D12 | F8: "global top-21 FAISS search, filtered afterwards" | Confirmed in code: `personalization/service.py:1974` `search_vector(vec, c.cluster_nn + 1)`, then `b in meta` (window) filter at l.1975 | Confirmed [code] |
| D13 | F11: pinned env is Python 3.11 | `requirements.lock` targets 3.11; Dockerfile `python:3.11.9-slim-bookworm`, pip 24.2. The lock **omits** `fastapi`, `uvicorn`, `rapidfuzz` (pinned only in `requirements.txt`) and **`starlette`** (resolved to 0.38.6, unpinned anywhere) | Lock gap recorded; not changed |
| D14 | R7: third-party news text stays out of git | `research/experiments/data/e02_gate_sources_2026-10-23.jsonl` (1,843 rows of publisher summaries: BBC, ESPN, …) was **committed in `e642c48` and is already on `origin/agent-satvik`**. History is not rewritten (R4) | Untracked on this branch (`git rm --cached`) and git-ignored; the local file is kept. **Purging it from the pushed history is the user's decision** |
| D15 | E02 items CSV may contain text | It contains ids, edit type, decision, counts and word counts only, no text | No action |
| D16 | MIND docs list "seven" columns | Not checked yet | Phase 2A |

### 1.3 Recount commands (inline, read-only)

```bash
python -I -c "import json,collections; rows=[json.loads(l) for l in open('research/experiments/data/e02_gate_sources_2026-10-23.jsonl',encoding='utf-8')]; print(collections.Counter(e['type'] for r in rows for e in r['entities'])); print(sum(r['summary_short'].strip()==r['summary_long'].strip() for r in rows), len(rows))"
```

Output: `Person 6183, Product 3382, Organization 2931, Location 2068, Event 103, Product/Technology 38`; `1160 1843`.

## 2. `models/` and `envs/`

| Path | Content | Size | sha256 (weights) | Tracked by git? |
|---|---|---|---|---|
| `models/classifier/` | Agent 2 DistilRoBERTa (`model.safetensors`, tokenizer, `label_config.json`, HF download cache metadata, commit `45a81478…`) | 314 MB weights | `32703a6a…1ff63f` | No (`.gitignore: models/`) |
| `models/mapnai-ner-bert/` | Agent 1 BERT NER (`model.safetensors`, tokenizer, `training_args.bin`) | 411 MB weights | `3f7752a6…af4` | No |
| `models.zip` | Zip of the two folders above (26 entries) | 706 MB | `98a4ef66…07a` | No (`.gitignore: models.zip`) |
| `envs/` | **Does not exist** | — | — | `envs/` added to `.gitignore` |

No checker model (MiniCheck, AlignScore, SummaC) and no dataset (MIND, LLM-AggreFact) is present yet. Nothing in `models/` was modified.

Ignore rules added in this phase: `envs/`, `research/experiments/data/external/`, `research/experiments/data/e02_gate_sources_*.jsonl`, `research/experiments/cache/`, `research/colab/outputs/`.

## 3. Machine and repository state

| Item | Value |
|---|---|
| `git status` at start | clean, `agent-satvik`, up to date with `origin/agent-satvik` |
| `git log -1` at start | `e642c48c0d8976f053befbada61aa89e40b8bfc8 PRESOTA` (2026-10-23 19:59 +0530) |
| OS | Windows 11 Home Single Language 10.0.26200 (build 26200.9711); Git Bash MINGW64 3.6.10 |
| CPU | Intel Core i5-14500HX, 20 logical processors |
| RAM | 11.6 GB total; **≈ 0.7 GB free** at check time (other apps open), a risk for loading Flan-T5-Large on CPU |
| Free disk (C:) | 376 GB free of 476 GB (≥ 15 GB required: PASS) |
| GPU | **NVIDIA GeForce RTX 3050 6GB Laptop GPU**, 6,144 MiB VRAM, driver 617.42, CUDA UMD 13.4 |
| GPU verdict | Adequate for MiniCheck-Flan-T5-Large / DeBERTa-L (≤ 0.8B). **Not adequate for Bespoke-MiniCheck-7B** (bf16 weights ≈ 15 GB; vLLM path is Linux-only per the MiniCheck README) → Colab, ceiling **PENDING** |
| System Python | 3.12.10 only (no 3.11 installed) |
| Research venv | `~/.venvs/mapnai-research`: **CPython 3.11.9** (python-build-standalone via `uv 0.12.24` in `~/.venvs/uv-bootstrap`), pip 24.2, `pip install -r requirements.txt -c requirements.lock --extra-index-url https://download.pytorch.org/whl/cpu` + `en_core_web_sm-3.8.0` wheel, exactly as the Dockerfile. 170 packages; every lock entry matched (freeze: `research/experiments/results/env_freeze_mapnai-research_2026-10-23.txt`) |
| Docker | Client 29.9.1; **daemon not running** (`npipe:////./pipe/docker_engine` not found) |
| Hugging Face token | None on this machine |

## 4. Test baseline (R6)

Command (repo root; every DB/LLM endpoint overridden to a dead local address so `.env` cannot reach live services; FAISS paths and log file redirected to the scratchpad; no pytest cache):

```bash
MONGO_URI="mongodb://127.0.0.1:9/" MONGO_DB_NAME=sandbox_never NEO4J_URI="bolt://127.0.0.1:9" NEO4J_USERNAME=x NEO4J_PASSWORD=x \
GROQ_API_KEY="" NEWSAPI_KEY="" GNEWS_API_KEY="" NEWSDATA_API_KEY="" \
FAISS_INDEX_PATH="$SCRATCH/faiss_index" FAISS_METADATA_PATH="$SCRATCH/faiss_metadata.pkl" LOG_FILE="$SCRATCH/test.log" \
PYTHONDONTWRITEBYTECODE=1 ~/.venvs/mapnai-research/Scripts/python.exe -m pytest -p no:cacheprovider -rfEs
```

Result: **720 passed, 0 failed, 0 skipped, 0 errors** in 196.6 s. Per file: agents_offline 5, auth 18, classifier 17, fetchers 20, insights 34, media 20, pers_app 23, pers_keys 22, pers_phase2 64, phase3 34, phase4 125, phase5 40, phase6 39, phase7 32, phase8 20, pers_profile 28, pipeline 6, preprocessing 55, query_graph 48, recap 55, storage 15.
`sha256` of `data/faiss_index` and `data/faiss_metadata.pkl` identical before and after the run (no index write).

Pre-existing failures: **none**. Gate 3 therefore requires ≥ 720 passing and 0 failing.
