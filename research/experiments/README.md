# research/experiments

Reproducible evaluation scripts for the MAPNAI research plan. These scripts **never write to MongoDB or Neo4j** and **never modify application code**. They import MAPNAI's pure modules (`personalization/*`, `utils/deduplicator.py`), and the live-data scripts only read.

## Layout

| Path | Content |
|---|---|
| `_common.py` | Provenance metadata, write-once result writers (they refuse to overwrite), Wilson intervals, the read-only Mongo handle |
| `e01_cluster_pairs_eval.py` | Event-clustering pair rule: CIs, leave-one-out threshold selection, ablations, near-duplicate baseline |
| `e02_export_gate_sources.py` | Read-only snapshot of the summaries that `render` rewrites → `data/` |
| `e02_gate_perturbation.py` | **Synthetic** stress test of `personalization/factcheck.py:verify` by edit type |
| `e03_live_descriptives.py` | Descriptive live-system metrics (clusters, materiality, render fallbacks, serving on developer accounts, classifier silver proxy) |
| `data/` | Input snapshots. `e02_gate_sources_2026-10-23.jsonl` contains third-party news summaries: **internal research use only, do not redistribute** |
| `results/` | One JSON (plus optional CSV) per run, named `<experiment>_<tag>.*` and never overwritten |

## Runs executed (2026-10-23, git `53f4b12`)

| Experiment | Command | Output |
|---|---|---|
| E01 | `python e01_cluster_pairs_eval.py --tag 2026-10-23` | `results/e01_cluster_pairs_2026-10-23.json`, `results/e01_cluster_pairs_sweep_2026-10-23.csv` |
| E02a | `python e02_export_gate_sources.py --tag 2026-10-23` | `data/e02_gate_sources_2026-10-23.jsonl` (1,843 rows) + `.meta.json` |
| E02b | `python e02_gate_perturbation.py --snapshot 2026-10-23 --tag 2026-10-23` | `results/e02_gate_perturbation_2026-10-23.json`, `results/e02_gate_perturbation_items_2026-10-23.csv` |
| E03 | `python e03_live_descriptives.py --tag 2026-10-23` | `results/e03_live_descriptives_2026-10-23.json` |

E02b was first run under a scratch tag while debugging the edit rules. Those files were deleted. The final E02b files were regenerated once more after a regex in the experiment script (not the application) was corrected. Only the final outputs are kept.

## Environment

The runs used Python 3.12.10 in a throwaway virtual environment outside the repo, with unpinned recent versions of `pydantic`, `pydantic-settings`, `rapidfuzz`, `numpy`, `pymongo`, `dnspython`, `python-dotenv`, `loguru`, `simhash`, `datasketch` and `pypdf`. This is **not** the project's pinned Python 3.11 / Docker environment, because Docker was not running. None of these scripts depends on torch, transformers or an LLM.

To reproduce, run from the **repo root**. MAPNAI's logger (`utils/logger.py`) writes `logs/ingestion.log` relative to the working directory, so running from the root keeps that file in the git-ignored root `logs/`.

```bash
pip install pydantic pydantic-settings rapidfuzz numpy pymongo dnspython python-dotenv loguru simhash datasketch
python research/experiments/e01_cluster_pairs_eval.py --tag <new-tag>
```

The runs listed above were launched from inside `research/experiments/`. The stray `logs/` and `__pycache__/` folders this created were removed.

E02a and E03 need a `.env` with `MONGO_URI` in the repo root.

## Environments from 2026-10-24 (F11)

The 2026-10-23 runs above used a throwaway Python 3.12 environment. Everything since runs in two pinned environments outside the repo:

| Environment | Python | Contents | Used for |
|---|---|---|---|
| `~/.venvs/mapnai-research` | CPython **3.11.9** (python-build-standalone via `uv 0.12.24`, the Dockerfile's version) | `pip 24.2`, `pip install -r requirements.txt -c requirements.lock --extra-index-url https://download.pytorch.org/whl/cpu`, plus the `en_core_web_sm-3.8.0` wheel, exactly as the Dockerfile. Freeze: `results/env_freeze_mapnai-research_2026-10-23.txt` | The app test suite, E01–E04, E06, E08, E09, F10, the scripts in `scripts/` |
| `~/.venvs/mapnai-checkers` | CPython 3.11.9 | `torch 2.6.0+cu124`, `transformers 4.57.6`, `datasets 3.6.0`, `pyarrow 18.1.0`, `nltk 3.9.1`, `minicheck @ b58b9fa` (no-deps). Freeze: `results/env_freeze_mapnai-checkers_2026-10-23.txt` | Learned checkers (E05), parquet (E07) |

Reproducibility check: E02 re-run on the unchanged gate in `mapnai-research` gives the same 29,067 per-item decisions as the 3.12 run (`results/e02_gate_perturbation_2026-10-24-v1-pinnedenv.*`). The only difference is a rounding tie in one macro (0.96825), because Python 3.12's `sum()` uses compensated float summation.

Rebuild:

```bash
~/.venvs/uv-bootstrap/Scripts/uv python install 3.11.9
"<uv python dir>/cpython-3.11.9-windows-x86_64-none/python.exe" -m venv ~/.venvs/mapnai-research
V=~/.venvs/mapnai-research/Scripts/python.exe
"$V" -m pip install "pip==24.2"
"$V" -m pip install -r requirements.txt -c requirements.lock --extra-index-url https://download.pytorch.org/whl/cpu
"$V" -m pip install https://github.com/explosion/spacy-models/releases/download/en_core_web_sm-3.8.0/en_core_web_sm-3.8.0-py3-none-any.whl
```

Test suite: `bash research/experiments/run_suite_isolated.sh <log>` (a mirror without `.env`; see `research/PREFLIGHT.md` §5). Docker was still not running on 2026-10-24, so the Docker image itself is not re-verified.
