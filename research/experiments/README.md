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
