# Colab: GPU runs for LLM-AggreFact

`mapnai_gpu_runs.ipynb` runs all GPU work that does not fit on the project laptop (RTX 3050 6 GB, 11.6 GB RAM):

| Part | Run | Scorecard | GPU |
|---|---|---|---|
| 1 | MiniCheck-Flan-T5-Large, test (29,320 pairs) | S1 harness validity (target 75.0 ± 2.0) | T4 or better |
| 2 | MiniCheck-Flan-T5-Large, dev (30,420 pairs) | CAFG tuning (S3) | T4 or better |
| 2b | MiniCheck-DeBERTa-v3-Large, test + dev (optional) | cheaper baseline | T4 or better |
| 3 | Bespoke-MiniCheck-7B, test | S5 ceiling (published 77.4) | **A100 only** |

## Steps

1. Open https://colab.research.google.com → **File → Upload notebook** → choose `research/colab/mapnai_gpu_runs.ipynb`.
2. **Runtime → Change runtime type → GPU**: T4 for Parts 1–2 (free tier works, slowly); **A100** for Part 3 (Colab Pro / compute units). If you have an A100 session, you can do everything in it.
3. Run **Part 0** top to bottom (cells 0.1–0.6). Approve the Google Drive pop-up in 0.2, paste a Hugging Face **read** token in 0.4 (the account that accepted the LLM-AggreFact terms). Cell 0.5 must print `dataset OK` and `checkpoints OK`; if an `assert` fails, stop and report it.
4. Run **Part 1**, then **Part 2** (and **2b** if you want). Each prints progress every 256 rows and a summary at the end.
   **If Colab disconnects:** reconnect, run 0.1–0.6 again, then re-run the part you were in. Finished rows are kept on Drive and skipped.
5. Run **Part 4**. It writes `mapnai_colab_results_colab-2026-10-24.zip` to `My Drive/mapnai_colab/`.
6. For **Part 3**: switch to an A100, **Runtime → Restart session**, run 0.1, 0.2, 0.4, 0.5, 0.6 (skip 0.3), then 3.1–3.3, then Part 4 again.
7. Download the zip from Google Drive and put it anywhere on this laptop; tell Claude the path.

## What happens with the zip

Claude unpacks `cache/*.jsonl` into `research/experiments/cache/` and produces the official, write-once result files locally (no model is loaded when the cache is complete):

```bash
C="$HOME/.venvs/mapnai-checkers/Scripts/python.exe"
"$C" -W ignore research/experiments/e20_aggrefact_eval.py --checker minicheck-ft5 --split test --tag colab-2026-10-24 --scored-on "Colab <GPU>"
"$C" -W ignore research/experiments/e20_aggrefact_eval.py --checker minicheck-ft5 --split dev  --tag colab-2026-10-24 --scored-on "Colab <GPU>"
"$C" -W ignore research/experiments/e20_aggrefact_eval.py --checker bespoke-7b    --split test --tag colab-2026-10-24 --scored-on "Colab A100"
```

The notebook's own printed numbers are a preview; the reported numbers are the ones these commands write to `research/experiments/results/`.

## Pins and checks

- Code: `minicheck @ b58b9fa69acbd1015ec970fa65dd752413a053d2`, `transformers 4.57.6`, `datasets 3.6.0`, `nltk 3.9.1` (punkt_tab; the pickle-based punkt is blocked).
- Data: `lytang/LLM-AggreFact @ 981dfd0b`, parquet sha256 checked.
- Checkpoints: MiniCheck-Flan-T5-Large @ `96eafd01` and DeBERTa @ `2f2d01a5` (the `pytorch_model.bin` sha256 is checked; minicheck loads them at `main`, so the notebook first asserts that `main` is still the pinned commit).
- Bespoke-MiniCheck-7B @ `1ed7786b` (CC BY-NC 4.0). It needs `trust_remote_code`; the four code files were reviewed on 2026-10-23 and their sha256 is checked before loading:

| File | Lines | sha256 |
|---|---|---|
| `configuration_internlm2.py` | 180 | `89863f76…fd856` |
| `modeling_internlm2.py` | 1,800 | `1b781ec7…bad005` |
| `tokenization_internlm2.py` | 236 | `444d4c2b…5eef` |
| `tokenization_internlm2_fast.py` | 214 | `1fe5f033…ae10` |

  The review found only torch/transformers/einops/sentencepiece/tokenizers imports (plus optional flash_attn and the stdlib modules `math`, `queue`, `threading`, `os`, `shutil.copyfile`), no network calls, exec/eval, subprocess, pickle or `torch.load`, and the standard `save_vocabulary` as the only file write. `config.json` `auto_map["AutoModel"]` points at an unpinned third-party repository; the notebook loads through minicheck/vLLM only, never `AutoModel`.

`run_bespoke.py` is the earlier stand-alone version of Part 3, kept for reference.
