# STATE (overwrite each step; history lives in LEDGER.md and git)

**Updated:** 2026-10-23 · **Branch:** `research/sota-push` · **Phase:** 0 done → 1 next

## Done
- Phase 0: `PREFLIGHT.md` (16 discrepancies), pinned venv `~/.venvs/mapnai-research` (CPython 3.11.9 + `requirements.lock`), baseline suite 720/0/0, `.gitignore` extended, E02 news-text JSONL untracked (kept on disk). Tag `pre-phase1`.

## Next
- Phase 1: `research/SOTA_TARGETS.md` (LLM-AggreFact top-5 + protocol from the MiniCheck repo; news subsets CNN/XSum/MediaS; cascade/selective prior art and CAFG novelty; stream clustering data availability, 30-min timebox; optional MIND leaderboard). New bib entries only after opening sources.

## Blockers / pending user decisions
- **H4 (Phase 2B):** `lytang/LLM-AggreFact` is gated on Hugging Face (accept terms + token; CC-BY-ND-4.0, evaluation only). No HF token on this machine.
- **User decision:** third-party news text (`research/experiments/data/e02_gate_sources_2026-10-23.jsonl`) is in pushed history of `origin/agent-satvik` (commit `e642c48`). Not rewritten (R4).
- Bespoke-MiniCheck-7B: local GPU is 6 GB → Colab script only; S5 ceiling PENDING.
- Free RAM was ≈ 0.7 GB at check time; close other apps before checker runs on CPU (GPU path preferred).

## Resume commands
```bash
cd "/c/Workspace/College/KJSCE/MAPNAI - LYPROJECT/MAPNAI"
git checkout research/sota-push && git log --oneline -3 && git tag -l 'pre-phase*'
V="$HOME/.venvs/mapnai-research/Scripts/python.exe"; "$V" --version   # 3.11.9
# baseline suite: see PREFLIGHT.md §4 (env overrides are mandatory)
```
