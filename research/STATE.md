# STATE (overwrite each step; history lives in LEDGER.md and git)

**Updated:** 2026-10-24 · **Branch:** `research/sota-push` · **Phase:** 2 done (Gate 2 PASS) → 3 next

## Done
- Phase 0: `PREFLIGHT.md` (16 discrepancies), pinned venv `~/.venvs/mapnai-research` (CPython 3.11.9 + `requirements.lock`), baseline suite 720/0/0, `.gitignore` extended, E02 news-text JSONL untracked (kept on disk). Tag `pre-phase1`.

- Phase 1: `SOTA_TARGETS.md` (Gate 1 PASS), `PREREG.md` v0 (scorecard + protocols, committed before any data), 11 new bib entries, leaderboard snapshot `results/p1_aggrefact_leaderboard_2026-10-23.json`. CAFG re-scoped (cascade not novel; prior art arXiv 2610.20634). Tag `pre-phase2`.

- Phase 2 (partial): MIND-small acquired (Azure 409 → official-linked HF mirror gated → `Recommenders/MIND` @ 2115068f), validated (8 columns), `mind_sources_120.jsonl` (120 rows). Checker venv `~/.venvs/mapnai-checkers` (CPython 3.11.9, torch 2.6.0+cu124, transformers 4.57.6, minicheck @ b58b9fa, pyarrow 18.1.0). MiniCheck FT5 + DeBERTa at pinned commits in `models/ckpts` (sha256-verified, kept as upstream `.bin`, loaded with transformers' weights_only path; no third-party safetensors). Smoke tests pass (`e05_checker_smoke_2026-10-23b.json`). Colab script for Bespoke-7B written and its remote code reviewed. `data/MANIFEST.json`.
- Phase 2B (2026-10-24): LLM-AggreFact @ 981dfd0b acquired after the user's HF login; sha256-verified; 29,320 test / 30,420 dev, 11 datasets (`results/e07_aggrefact_inventory_2026-10-24.json`). Parquet needs the checker venv (pyarrow). Tag `pre-phase3`.

## Next
- Phase 3: F1 → F2 → F5 → F6 → F8 → F7 → F9–F11 (failing test first; full suite + E02 under a new tag after each fix).

## Blockers / pending user decisions
- H4 (Phase 2B): RESOLVED 2026-10-24 (user HF login; token in ~/.cache/huggingface, outside the repo).
- **Upcoming licence question (Phase 7, EXP-7):** rewriting MIND abstracts means sending them to Groq (third-party API); the MSR licence forbids distribution. Needs the user's decision before EXP-7 runs.
- **User decision:** third-party news text (`research/experiments/data/e02_gate_sources_2026-10-23.jsonl`) is in pushed history of `origin/agent-satvik` (commit `e642c48`). Not rewritten (R4).
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
# baseline suite: see PREFLIGHT.md §4 (env overrides are mandatory)
```
