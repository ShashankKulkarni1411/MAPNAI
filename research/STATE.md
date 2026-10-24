# STATE (overwrite each step; history lives in LEDGER.md and git)

**Updated:** 2026-10-24 · **Branch:** `research/sota-push` · **Phase:** 4 in progress (EXP-1 pilot done; S1 running) · 6 started (CAFG equivalence PASS)

## Done
- Phase 0: `PREFLIGHT.md` (16 discrepancies), pinned venv `~/.venvs/mapnai-research` (CPython 3.11.9 + `requirements.lock`), baseline suite 720/0/0, `.gitignore` extended, E02 news-text JSONL untracked (kept on disk). Tag `pre-phase1`.

- Phase 1: `SOTA_TARGETS.md` (Gate 1 PASS), `PREREG.md` v0 (scorecard + protocols, committed before any data), 11 new bib entries, leaderboard snapshot `results/p1_aggrefact_leaderboard_2026-10-23.json`. CAFG re-scoped (cascade not novel; prior art arXiv 2610.20634). Tag `pre-phase2`.

- Phase 2 (partial): MIND-small acquired (Azure 409 → official-linked HF mirror gated → `Recommenders/MIND` @ 2115068f), validated (8 columns), `mind_sources_120.jsonl` (120 rows). Checker venv `~/.venvs/mapnai-checkers` (CPython 3.11.9, torch 2.6.0+cu124, transformers 4.57.6, minicheck @ b58b9fa, pyarrow 18.1.0). MiniCheck FT5 + DeBERTa at pinned commits in `models/ckpts` (sha256-verified, kept as upstream `.bin`, loaded with transformers' weights_only path; no third-party safetensors). Smoke tests pass (`e05_checker_smoke_2026-10-23b.json`). Colab script for Bespoke-7B written and its remote code reviewed. `data/MANIFEST.json`.
- Phase 2B (2026-10-24): LLM-AggreFact @ 981dfd0b acquired after the user's HF login; sha256-verified; 29,320 test / 30,420 dev, 11 datasets (`results/e07_aggrefact_inventory_2026-10-24.json`). Parquet needs the checker venv (pyarrow). Tag `pre-phase3`.

- Phase 3 (2026-10-24): F1 fix (identity 1.0); F2 normalization FAILED its criterion alone (entity_sub 0.9997→0.9972), passes combined with F5 as gate `v2` (render_gate_version, default v1); F5 found a latent insights.new_names bug (opt-in fix); F6 NER_MISC_LABEL + migration dry run (5,192 entities; not applied, H2); F8 window search (no measurable effect at current scale; held-out pairs need H1); F7 new index 100% coverage (live untouched); F9/F10 root causes reported; F11 pinned envs documented. Safety correction: suite now runs via run_suite_isolated.sh (PREFLIGHT §5). Suite 793/0. Tag `pre-phase4`.

## Stopped / moved to Colab (2026-10-24)
- Local FT5 run (2,560 / 29,320 test rows cached, tag s1-2026-10-24) and the main generation (628 / 1,920 rewrites, 636 Groq calls total) were stopped by Claude Code's low-memory reaper. Not restarted (user decision).
- All GPU work moved to `research/colab/mapnai_gpu_runs.ipynb` (tag colab-2026-10-24): FT5 test (S1) + dev, optional DeBERTa, Bespoke-7B (S5). The user runs it and returns `mapnai_colab_results_colab-2026-10-24.zip`; then summarize locally with e20 `--scored-on` (README).
- Generation can resume locally (same command, same tag) when memory allows; it is network-bound.

## Next (in order)
1. After the FT5 test run: Gate 4 (S1 = |avg11 − 75.0| ≤ 2.0). Then S2 NER on the GPU: `"$C" research/experiments/e21_gate_aggrefact.py --step ner --split test` (and dev), `"$V" ... --step ner-fallback`, `"$V" ... --step gate --split test --tag s2-2026-10-24`.
2. After generation: `"$V" research/experiments/e14_score_gates.py --rewrites main-2026-10-24 --tag main-2026-10-24`, then `"$V" research/experiments/e12_export_annotation.py --tag gold-2026-10-24` → hand the sheet to annotators (H1).
3. Silver labels (Claude, two prompts) on dev items; CAFG dev tuning (AggreFact dev FT5 probabilities + MAPNAI dev silver); freeze config + sha256 + commit; score test once (CAFG-L+M on AggreFact test reuses the cached FT5 test probabilities for escalated rows).
4. Colab: Bespoke-7B (S5) by the user, `research/colab/README.md`.

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
