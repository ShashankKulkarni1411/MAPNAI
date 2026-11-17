# STATE (overwrite each step; history lives in LEDGER.md and git)

**Updated:** 2026-11-15 · **Branch:** `research/sota-push` · **Phase:** 4 complete (S1 PASS; S2 measured; **S3 FAIL**; **S4 FAIL**); S5 pending (Colab)

## Done
- Phase 0: `PREFLIGHT.md` (16 discrepancies), pinned venv `~/.venvs/mapnai-research` (CPython 3.11.9 + `requirements.lock`), baseline suite 720/0/0, `.gitignore` extended, E02 news-text JSONL untracked (kept on disk). Tag `pre-phase1`.

- Phase 1: `SOTA_TARGETS.md` (Gate 1 PASS), `PREREG.md` v0 (scorecard + protocols, committed before any data), 11 new bib entries, leaderboard snapshot `results/p1_aggrefact_leaderboard_2026-10-23.json`. CAFG re-scoped (cascade not novel; prior art arXiv 2610.20634). Tag `pre-phase2`.

- Phase 2 (partial): MIND-small acquired (Azure 409 → official-linked HF mirror gated → `Recommenders/MIND` @ 2115068f), validated (8 columns), `mind_sources_120.jsonl` (120 rows). Checker venv `~/.venvs/mapnai-checkers` (CPython 3.11.9, torch 2.6.0+cu124, transformers 4.57.6, minicheck @ b58b9fa, pyarrow 18.1.0). MiniCheck FT5 + DeBERTa at pinned commits in `models/ckpts` (sha256-verified, kept as upstream `.bin`, loaded with transformers' weights_only path; no third-party safetensors). Smoke tests pass (`e05_checker_smoke_2026-10-23b.json`). Colab script for Bespoke-7B written and its remote code reviewed. `data/MANIFEST.json`.
- Phase 2B (2026-10-24): LLM-AggreFact @ 981dfd0b acquired after the user's HF login; sha256-verified; 29,320 test / 30,420 dev, 11 datasets (`results/e07_aggrefact_inventory_2026-10-24.json`). Parquet needs the checker venv (pyarrow). Tag `pre-phase3`.

- Phase 3 (2026-10-24): F1 fix (identity 1.0); F2 normalization FAILED its criterion alone (entity_sub 0.9997→0.9972), passes combined with F5 as gate `v2` (render_gate_version, default v1); F5 found a latent insights.new_names bug (opt-in fix); F6 NER_MISC_LABEL + migration dry run (5,192 entities; not applied, H2); F8 window search (no measurable effect at current scale; held-out pairs need H1); F7 new index 100% coverage (live untouched); F9/F10 root causes reported; F11 pinned envs documented. Safety correction: suite now runs via run_suite_isolated.sh (PREFLIGHT §5). Suite 793/0. Tag `pre-phase4`.

- Phase 4 S1 (2026-11-01, L0074–L0077): FT5 test + dev scored on Kaggle T4 (tag `kaggle-2026-10-31`; run 1 OOM'd at dev row 4,608, run 2 `mapnai_kaggle_gpu_runs.ipynb` (formerly `mapnai_kaggle_gpu_runs (1).ipynb`) resumed with an OOM-retry, never triggered). Caches complete and clean; Kaggle torch 2.11 vs local torch 2.6 on 2,560 shared rows: max |Δp| 1e-05, 0 flips. **Gate 4 PASS:** avg11 75.02 [73.96, 76.09] vs 75.0 (gap +0.02); avg10 74.72 vs 74.7; all 11 datasets within ±0.22 of the leaderboard. Dev avg11 72.69 (News-3 67.38). Harness is validated: downstream AggreFact comparisons need no "unvalidated" label.

- Phase 4 S2/S3 (2026-11-01, L0078–L0085): PREREG v2 §9 (S3 mechanics, before any CAFG evaluation). S3 dev grid: no pre-declared point reaches ≤ 50% calls (0.755–0.943); frozen names-on τ 0.80 @ `da9b525` (sha256 260e9410…). **S3 test, scored once: FAIL** — News-3 diff −2.39 [−3.74, −1.00] (margin −2.0), call rate 0.754 (cap 0.50); beats the random-escalation control (70.21 vs 68.32 [66.83, 69.64]); XSum −5.73 from the added-name rule. **S2 test:** v1-as-is News-3 50.04 (serve 2%: retention rule ≈ chance on claims), additions-only News-3 53.31 / avg11 55.24.

- Phase 4 S4 (2026-11-15, L0097–L0102): main batch labelled (A2 re-labelled once after pattern-only feedback, disclosed in PREREG v6 §13), 60 items adjudicated → gold 182 faithful / 58 unfaithful. CAFG tuned on human pilot labels (dev grid, idx 21: names off, budget-core retention, τ 0.90, θ 0.3), frozen @ 922b659 (sha256 fa5028dd…). **S4 test FAIL:** FRR v1 0.376 → CAFG 0.326 (−5.0 pts [−1.3, +11.8]; needs −10), FAR rises 0.330 → 0.447; lexical non-inferiority and semantic target not met. Main κ(faithful) 0.557 (both rounds). Note: Windows Smart App Control blocked the uv Python once on 2026-11-15 (cleared on retry); the research venv has no openpyxl, so e23 `--step labels` runs under system Python.

## Stopped / moved to Colab (2026-10-24)
- Local FT5 run (2,560 / 29,320 test rows cached, tag s1-2026-10-24) and the main generation (628 / 1,920 rewrites, 636 Groq calls total) were stopped by Claude Code's low-memory reaper. Not restarted (user decision).
- All GPU work moved to `research/colab/mapnai_gpu_runs.ipynb` (tag colab-2026-10-24): FT5 test (S1) + dev, optional DeBERTa; Bespoke-7B (S5, A100 only, optional) split out to `research/colab/mapnai_bespoke_7b.ipynb`. The user runs it and returns `mapnai_colab_results_colab-2026-10-24.zip`; then summarize locally with e20 `--scored-on` (README).
- Generation can resume locally (same command, same tag) when memory allows; it is network-bound.

## Ready for the user (2026-11-01)
- **S4 back to two human annotators (PREREG v4 §11, 2026-11-07; L0093–L0094):** judge labels (L0092) excluded from S4. Pre-filled workbooks built in `research/annotation/export/to_annotators/{A1,A2}/`. **Pilot done 2026-11-15 (L0095–L0096):** κ(faithful) 0.576 [0.359, 0.754] on the 80 shared items; passes the gate as lowered post hoc to 0.55 (PREREG v5 §12, disclosure required; would fail 0.6). Pilot labels = the `*_Shaunak_be.xlsx` / `*_Satvik_be.xlsx` workbooks only. **User's task now:** send `A1/main_A1_gold-2026-11-01.xlsx` to A1 and `A2/main_A2_gold-2026-11-01.xlsx` to A2 (240 items each, guideline v1 unchanged); don't discuss pilot items with them until both main files are back (`research/S4_instructions.md` Step 6). Read-back: `uv run --no-project --with openpyxl python research/experiments/e16_annotator_workbooks.py --to-csv <file>`.

## Next (in order)
1. DONE 2026-11-01 (L0087–L0089): After generation: `"$V" research/experiments/e14_score_gates.py --rewrites main-2026-10-24 --tag main-2026-10-24`; extend e12 to write per-annotator pilot/main sheets (`research/S4_instructions.md` §4 Step 2), then export `--tag gold-<date>` → user hands sheets to annotators (H1).
2. Silver labels (Claude, two prompts) on MAPNAI dev items; CAFG tuning on MAPNAI dev (compression-aware stages: retention with budget/core_k, added names on/off); freeze + commit before S4 is computed.
3. DONE 2026-11-15 (L0102): S4 computed once — FAIL (reported as a miss).
4. Colab: Bespoke-7B (S5), A100 only. Optional DeBERTa (Part 2b) with the OOM-retry notebook.
5. Paper (next): negative-results framing — S1 reproduced, S2 gate ≈ chance on AggreFact, S3 and S4 pre-registered misses, human-labelled 240-item rewrite set; disclose PREREG §12 (post-hoc κ gate) and §13 (A2 re-label). S3 is a reported miss; the AggreFact story is "lexical routing beats random routing but cannot halve checker calls on abstractive claims".

## Blockers / pending user decisions
- H4 (Phase 2B): RESOLVED 2026-10-24 (user HF login; token in ~/.cache/huggingface, outside the repo).
- **Upcoming licence question (Phase 7, EXP-7):** rewriting MIND abstracts means sending them to Groq (third-party API); the MSR licence forbids distribution. Needs the user's decision before EXP-7 runs.
- **User decision:** third-party news text (`research/experiments/data/e02_gate_sources_2026-10-23.jsonl`) is in pushed history of `origin/agent-satvik` (commit `e642c48`). Not rewritten (R4).
- Pending user approvals (not blocking): unflagged insights.new_names possessive fix; F6 migration --apply (H2); switching Agent 5 to the rebuilt index (H2); F9 Agent 3 rule (H2).
- **H1 (raised 2026-10-24):** gold labels need two independent human annotators (PREREG §8: 160 pilot items, 240 test items). Silver proceeds meanwhile.
- Bespoke-MiniCheck-7B: local GPU is 6 GB → Colab script only; S5 ceiling PENDING.
- Free RAM was ≈ 0.7 GB at check time; close other apps before checker runs on CPU (GPU path preferred).

## Resume commands
```bash
cd "/c/Workspace/College/KJSCE/MAPNAI - LYPROJECT/MAPNAI"
git checkout research/sota-push && git log --oneline -3 && git tag -l 'pre-phase*'
V="$HOME/.venvs/mapnai-research/Scripts/python.exe"; "$V" --version   # 3.11.9 (app + harness)
C="$HOME/.venvs/mapnai-checkers/Scripts/python.exe"; "$C" --version   # 3.11.9 (checkers, CUDA)
"$C" research/experiments/e05_checker_smoke.py --tag <new-tag>         # offline; uses models/ckpts + models/nltk_data
"$V" research/experiments/e06_manifest.py                              # refresh data/MANIFEST.json
bash research/experiments/run_suite_isolated.sh <log>                    # full suite in a mirror without .env (PREFLIGHT §5)
```
