# Kaggle (free, recommended): `mapnai_kaggle_gpu_runs.ipynb`

Same runs as the Colab notebook (Parts 1 and 2; 2b optional). It runs in the background, so you can close the browser.

**One time (about 5 minutes):**

1. Make a Kaggle account at https://www.kaggle.com and **verify your phone number** (Settings → Phone verification). Kaggle doesn't give you a GPU or internet access without it.
2. Get a Hugging Face **Read** token (see "Before you start" below).

**Run it:**

1. Kaggle → **Create → New Notebook** → **File → Import Notebook** → upload `research/colab/mapnai_kaggle_gpu_runs.ipynb`.
2. Right-hand panel → **Session options**: Accelerator **GPU T4 x2** (not P100), Internet **On**.
3. **Add-ons → Secrets → Add secret**: label `HF_TOKEN`, value = your HF Read token. Tick the box so it's attached to this notebook.
4. Optional: to also run DeBERTa (Part 2b), change `RUN_DEBERTA = False` to `True` in cell 0.2.
5. Click **Save Version** → **Save & Run All (Commit)** → Save. You can close the tab now.
6. Check progress any time: open the notebook → **View Versions** → the running version → Logs. Expect about 4 to 8 hours for Parts 1 and 2.
7. When it finishes: the version's **Output** tab → download `mapnai_kaggle_results_kaggle-2026-10-31.zip`.
8. Tell Claude: *"Kaggle results are at `<path to zip>`, GPU was T4"*.

**If it stopped before everything was scored** (the log says `time budget ... reached`, or the summary shows `missing` rows above 0):
open the notebook → **Add Input** → **Your Work** → pick this notebook's output → then **Save & Run All** again. It skips the rows it already scored and continues.

**If something fails:** `AssertionError ... P100` → change the accelerator to T4 x2. `401`/`403`/"gated repo" → check the secret is attached and the HF account accepted the dataset terms. Any other `AssertionError` → stop and send Claude the error text.

---

# What you have to do (Colab GPU runs)

You run two notebooks on Google Colab. You don't upload any data files. The notebooks download everything themselves.
You give them two things: a **Hugging Face token** and **Google Drive access**. At the end you bring **one zip file** back to the laptop.

| Notebook | When | GPU |
|---|---|---|
| `mapnai_gpu_runs.ipynb` | **Now** | T4 (free tier works) |
| `mapnai_bespoke_7b.ipynb` | Later, **optional**, when you have an A100 | A100 only |

---

## Before you start (one time, about 2 minutes)

1. Log in to https://huggingface.co with the account that already accepted the terms of
   [lytang/LLM-AggreFact](https://huggingface.co/datasets/lytang/LLM-AggreFact). Open the page once and check that it doesn't ask you to accept again.
2. Go to https://huggingface.co/settings/tokens → **Create new token** → type **Read** → copy it.
   Keep it somewhere private. Don't paste it into a notebook cell or a file.

---

## Notebook 1: `mapnai_gpu_runs.ipynb` (do this now)

1. Open https://colab.research.google.com → **File → Upload notebook** → choose
   `research/colab/mapnai_gpu_runs.ipynb` from this repo.
2. **Runtime → Change runtime type** → **T4 GPU** → Save.
3. Run the **Part 0** cells one by one (0.1 → 0.6):
   - **0.2**: a Google Drive pop-up appears → allow it (use the Google account whose Drive has free space, about 1 GB).
   - **0.3**: if Colab says *"Restart session"*, click it, then run Part 0 again from 0.1.
   - **0.4**: paste your Hugging Face **Read** token in the box and press Login.
   - **0.5**: must print `dataset OK` and `checkpoints OK`. If you see an `AssertionError`, **stop** and send Claude the error text.
   - **0.6**: prints `ready`.
4. Run **Part 1** (FT5 on the test split). On a T4 this takes several hours. Keep the tab open.
5. Run **Part 2** (FT5 on the dev split). It also takes several hours.
6. *(Optional)* Run **Part 2b** (DeBERTa). It takes about half as long.
7. Run **Part 3 — Package the results**. It prints a path ending in `mapnai_colab_results_colab-2026-10-24.zip`.

**If Colab disconnects or times out** (normal on the free tier): reconnect, run **0.1 → 0.6** again, then run the part you were in again.
The finished rows are saved on Drive and skipped, so you don't lose progress. You can spread the work over several days.

**Bring the results back:**

1. Open https://drive.google.com → **My Drive → mapnai_colab** → download `mapnai_colab_results_colab-2026-10-24.zip`.
2. Save it anywhere on the laptop, for example `Downloads`.
3. Tell Claude: *"Colab results are at `<path to zip>`, GPU was T4"*. Claude will unpack it and write the official result files.

---

## Notebook 2: `mapnai_bespoke_7b.ipynb` (optional, needs an A100)

Do this only when you have Colab Pro or compute units and can get an **A100**. You can run it before or after Notebook 1.

1. Colab → **File → Upload notebook** → `research/colab/mapnai_bespoke_7b.ipynb`.
2. **Runtime → Change runtime type** → **A100 GPU** → Save.
3. Run every cell from top to bottom:
   - **0.1** stops with an error if you didn't get an A100. Change the runtime type and try again.
   - **0.2**: allow Google Drive. Use the **same Google account** as Notebook 1.
   - **0.3**: installs vLLM (several minutes). If Colab says *"Restart session"*, click it, then run everything again from 0.1.
   - **0.4**: paste the same Hugging Face Read token.
   - **1.1**: must print `Bespoke-MiniCheck-7B OK`. If you see an `AssertionError`, **stop** and send Claude the error text.
   - **1.2**: scoring takes about 1 hour.
   - **Part 2**: packages the results.
4. Download `mapnai_colab_results_colab-2026-10-24.zip` from **My Drive → mapnai_colab** again. This newer zip also contains Notebook 1's results.
5. Tell Claude: *"Colab results are at `<path to zip>`, Bespoke run done on A100"*.

---

## Quick troubleshooting

| You see | Do this |
|---|---|
| `401` / `403` / "gated repo" in 0.5 | The token is wrong, or the account hasn't accepted the dataset terms. Fix it, then re-run 0.4 and 0.5. |
| `AssertionError ... stop and tell Claude` | Stop. Send Claude the full error. A pinned file changed upstream. |
| `CUDA out of memory` in Notebook 1 | Re-run Part 0. If it happens again, tell Claude (the batch size can be lowered). |
| "You cannot currently connect to a GPU" | Free-tier GPU limit reached. Try again later. Your progress is saved on Drive. |
