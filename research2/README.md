# research2 — Importance vs engagement: LLM-annotated news values and clicks in MIND

**Question:** do the qualities journalists call newsworthy predict what readers click? And where do *public importance* and *engagement* split?

- **Plan:** `HYPOTHESES.md`. Commit it before scoring.
- **Codebook:** `CODEBOOK.md`. Humans and the LLM get the same definitions.
- **Literature check:** `LITERATURE.md`.

## Status (2026-11-15)

| Step | Who | State |
|---|---|---|
| 0 Setup: data, stats, human sample | Claude | ✅ `n01_prepare.py` → `results/n01_prepare_2026-11-15.json` |
| 1 Codebook and prompt | Claude | ✅ `CODEBOOK.md`, `nv_common.py` (prompt sha256 `2550d607…`), 11 parser tests pass |
| 2 Kaggle notebook | Claude builds, **you run** | ✅ built: `kaggle/nv_kaggle_scoring.ipynb`. Smoke-tested locally with Qwen2.5-1.5B on 75 items (100% parsed, all three resume paths) |
| 2b Kaggle run | you | ✅ 22,771/22,771 parsed → `results/nv_summary_kaggle-2026-11-15.json` (scores in git-ignored `data/`) |
| 3 Human labels | **Two of you** | ✅ returned: `nv_labels_A1_completed.xlsx` (item 84 blank), `nv_labels_A2_complete (1).xlsx` |
| 4a Validity gate | Claude | ✅ `n04_validity.py` → `results/n04_validity_2026-11-16.json`: 6/7 pass, entertainment fails (κ 0.20) |
| 4b Click analysis (A1/H1–H3, E1–E5) | Claude | ✅ `n05_clicks.py` (as planned) → `results/n05_clicks_2026-11-16.json`; failed its random-score check, so `n06_twoway.py` (Change 1: two-way bootstrap and permutation) → `results/n06_twoway_2026-11-16.json`. H1 not supported; utility −, conflict +, importance null |
| 6 Paper | Claude drafted, **you verify and submit** | ✅ draft: `paper/main.tex` (+ `sections/`, `refs.bib`); Overleaf upload: `paper_overleaf.zip` (git-ignored) |
| 5 Literature | Claude read the 4 PDFs; **you check two references** | ✅ `LITERATURE.md` |
| 6 Paper (IEEEtran, 6 pages) | Claude drafts, **you verify and submit** | after step 4 |

## Your steps

### A. Kaggle scoring (about 15 minutes of your time, then a few hours of background GPU)
1. **Upload the input.** kaggle.com → Create → **New Dataset** → upload `research2/data/articles_to_score.jsonl` → set **Private** → name it, e.g. `nv-articles`. It holds MIND text, so it must stay private.
2. **Import the notebook.** Create → **New Notebook** → File → **Import Notebook** → `research2/kaggle/nv_kaggle_scoring.ipynb`.
3. **Settings** (right panel):
   - **Accelerator: GPU T4 x2**
   - **Internet: On** (needs a phone-verified account)
   - **Add Input** → your `nv-articles` dataset
4. **Run.** **Save Version → Save & Run All (Commit)**. It runs in the background; you can close the tab.
5. **After about 15 minutes**, open the version's log. The pilot cell prints a parse rate (it should be ≥ 0.95) and an ETA. If the pilot fails, the run stops on its own; send me the log.
6. **When it finishes**, open the Output tab → download `nv_scores_kaggle-2026-11-15.jsonl` and `nv_summary_kaggle-2026-11-15.json` → put both in `research2/data/`.
7. **If the run dies part-way:** Add Input → *Your Work* → the failed version's output → Save & Run All again. Finished articles are skipped.

### B. Human labels (about 1.5 hours each, done in parallel)
- Send `annotation/nv_labels_A1.xlsx` to labeller 1 and `nv_labels_A2.xlsx` to labeller 2. Both files have the same 100 items.
- Each person reads the **Instructions** sheet first, then fills the **Labels** sheet (scores 1–5; the *done* column shows ✓ when a row is complete).
- **No discussing items until both files are back.** Don't look at the LLM scores before labelling.
- Return the files to `research2/annotation/`. Claude checks them with `python research2/n03_annotation_workbook.py read <file>`.

### C. Before scoring starts
Commit `research2/` (the `.gitignore` keeps out MIND text, workbooks and PDFs). The commit time shows the hypotheses were written first.

## Reproduce
```bash
cd "<repo>"   # system Python 3.12 (has openpyxl); no other dependencies for steps 0–3
python research2/test_nv_common.py
python research2/n01_prepare.py --tag 2026-11-15
python research2/n02_build_notebook.py --prep-tag 2026-11-15 --run-tag kaggle-2026-11-15
python research2/n03_annotation_workbook.py build --tag 2026-11-15
# after labelling (system Python), then the gate (~/.venvs/mapnai-research: numpy, scipy, sklearn)
python research2/n03_annotation_workbook.py read research2/annotation/nv_labels_A1_completed.xlsx
python research2/n03_annotation_workbook.py read "research2/annotation/nv_labels_A2_complete (1).xlsx"
~/.venvs/mapnai-research/Scripts/python research2/test_n04.py
~/.venvs/mapnai-research/Scripts/python research2/n04_validity.py --a1 research2/annotation/nv_labels_A1_completed.csv \
  --a2 "research2/annotation/nv_labels_A2_complete (1).csv" --scores research2/data/nv_scores_kaggle-2026-11-15.jsonl --tag 2026-11-16
```

## Data handling
- MIND text stays in `data/` and `annotation/`. Both are git-ignored, because the MIND licence forbids redistribution.
- `results/` holds counts and hashes only.
- The paper quotes at most a few headlines, briefly, as examples.
