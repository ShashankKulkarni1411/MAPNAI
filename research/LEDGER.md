# LEDGER (append-only)

One row per claim. Never edit or delete a row; corrections are new rows that reference the old row ID.
Columns: ID · date · phase · claim · number · file · command · git SHA (code state that produced the number).
Groq calls are logged in the "Groq budget" table at the bottom (cap: 4,000 total, R9).

| ID | Date | Phase | Claim | Number | File | Command | SHA |
|---|---|---|---|---|---|---|---|
| L0001 | 2026-10-23 | 0 | E02 identity pass rate (re-read from JSON) | 0.9989 (4/3,686 checks fail; 2 articles × 2 fields) | `research/experiments/results/e02_gate_perturbation_2026-10-23.json`, `..._items_2026-10-23.csv` | `python e02_gate_perturbation.py --snapshot 2026-10-23 --tag 2026-10-23` (original run) | 53f4b12 |
| L0002 | 2026-10-23 | 0 | E02 macro detection, lexically visible edits | 0.9683 | same JSON `summary` | same | 53f4b12 |
| L0003 | 2026-10-23 | 0 | E02 macro detection, semantic edits | 0.0022 | same JSON `summary` | same | 53f4b12 |
| L0004 | 2026-10-23 | 0 | E02 macro acceptance of benign edits (identity EXCLUDED by script design: reformat, possessive, reorder) | 0.6635 | same JSON; definition `e02_gate_perturbation.py:270` | same | 53f4b12 |
| L0005 | 2026-10-23 | 0 | E02 lead_50_words rejection rate | 0.8726 (1,617/1,853) | same JSON | same | 53f4b12 |
| L0006 | 2026-10-23 | 0 | E02 possessive_stripped rejection rate | 1.000 (197/197) | same JSON | same | 53f4b12 |
| L0007 | 2026-10-23 | 0 | Share of `summary_short` sources > 50 words | 0.4748 | same JSON `source_length` | same | 53f4b12 |
| L0008 | 2026-10-23 | 0 | E01 current rule in-sample P/R/F1 | 0.923 / 0.522 / 0.667 | `research/experiments/results/e01_cluster_pairs_2026-10-23.json` | `python e01_cluster_pairs_eval.py --tag 2026-10-23` | 53f4b12 |
| L0009 | 2026-10-23 | 0 | E01 LOOCV (min-precision-0.95 selection) F1 | 0.400 | same | same | 53f4b12 |
| L0010 | 2026-10-23 | 0 | E03 singleton-cluster share | 0.9276 (1,729/1,864) | `research/experiments/results/e03_live_descriptives_2026-10-23.json` | `python e03_live_descriptives.py --tag 2026-10-23` | 53f4b12 |
| L0011 | 2026-10-23 | 0 | E03 materiality unscored share | 1.0 (n = 2,063) | same | same | 53f4b12 |
| L0012 | 2026-10-23 | 0 | Entities typed `Product` in the E02 snapshot (F6 input) | 3,382 of 14,705 entity mentions | `research/experiments/data/e02_gate_sources_2026-10-23.jsonl` (recount) | inline recount, see PREFLIGHT §1.3 | e642c48 (data unchanged since 53f4b12) |
| L0013 | 2026-10-23 | 0 | Sources with `summary_short == summary_long` (F9 input) | 1,160 / 1,843 = 0.629 (in-scope snapshot only, not all articles) | same JSONL (recount) | inline recount, see PREFLIGHT §1.3 | e642c48 |
| L0014 | 2026-10-23 | 0 | Agent 5 index coverage 2,719/3,674 (74%), 687 stale | **NOT TRACEABLE**: absent from every results file; re-measure in F7 | — | — | — |
| L0015 | 2026-10-23 | 0 | Full test-suite baseline, pinned CPython 3.11.9 + requirements.lock | 720 passed / 0 failed / 0 skipped (196.6 s) | `research/experiments/results/baseline_pytest_2026-10-23.txt` (sha256 b6174f57…f4e8) | PREFLIGHT.md §4 | e642c48 (app code = 53f4b12) |
| L0016 | 2026-10-23 | 0 | LLM-AggreFact HF row counts (card, not yet downloaded) | test 29,320 · dev 30,420 | https://huggingface.co/datasets/lytang/LLM-AggreFact (retrieved 2026-10-23) | WebFetch | — |
| L0017 | 2026-10-23 | 0 | Leaderboard average, MiniCheck-Flan-T5-L / Bespoke-MiniCheck-7B (default view, 14 of 42 models) | 75.0 / 77.4 | https://llm-aggrefact.github.io/ (retrieved 2026-10-23) | WebFetch | — |

## Groq budget (R9: cap 4,000 calls)

| Date | Phase | Script / tag | Calls this run | Cumulative |
|---|---|---|---|---|
| 2026-10-23 | 0 | — | 0 | 0 |
