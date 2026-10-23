# STATE (overwrite each step; history lives in LEDGER.md and git)

**Updated:** 2026-10-23 · **Branch:** `research/sota-push` · **Phase:** 1 done → 2 next

## Done
- Phase 0: `PREFLIGHT.md` (16 discrepancies), pinned venv `~/.venvs/mapnai-research` (CPython 3.11.9 + `requirements.lock`), baseline suite 720/0/0, `.gitignore` extended, E02 news-text JSONL untracked (kept on disk). Tag `pre-phase1`.

- Phase 1: `SOTA_TARGETS.md` (Gate 1 PASS), `PREREG.md` v0 (scorecard + protocols, committed before any data), 11 new bib entries, leaderboard snapshot `results/p1_aggrefact_leaderboard_2026-10-23.json`. CAFG re-scoped (cascade not novel; prior art arXiv 2610.20634). Tag `pre-phase2`.

## Next
- Phase 2: separate checker venv `~/.venvs/mapnai-checkers` (torch ≥ 2.6 CUDA, pinned transformers, `minicheck @ b58b9fa`); MIND-small (2A); LLM-AggreFact (2B, **gated → H4**); MiniCheck FT5 + DeBERTa at pinned shas, `.bin` → local safetensors (2C); smoke tests; `data/MANIFEST.json`.

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
