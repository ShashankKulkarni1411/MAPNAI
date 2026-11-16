# S4: what you have to do (human gold labels)

**Written:** 2026-11-01 · **Rules this follows:** `research/PREREG.md` §3 (S4), §5, §8 · **Guideline annotators use:** `research/annotation/GUIDELINES_D3.md` v1

---

> **Changed 2026-11-07 (PREREG v4, §11): back to two human annotators.** The 2026-11-05 plan (Claude judge + an 80-item human check) is withdrawn. Claude's labels are **not** used for S4. Steps 3–8 below apply again (Steps 1–2 are done).
>
> **What to send.** Everything is in `research/annotation/export/to_annotators/`:
>
> | Send to | When | Files |
> |---|---|---|
> | **A1** | now | `A1/pilot_A1_gold-2026-11-01.xlsx` (120 items) + `A1/annotator_guidelines.pdf` |
> | **A2** | now | `A2/pilot_A2_gold-2026-11-01.xlsx` (120 items) + `A2/annotator_guidelines.pdf` |
> | **A1** | after the pilot passes (κ ≥ 0.55, PREREG v5 §12) | `A1/main_A1_gold-2026-11-01.xlsx` (240 items) |
> | **A2** | after the pilot passes | `A2/main_A2_gold-2026-11-01.xlsx` (240 items) |
>
> Don't send anything else: not the CSVs, `humancheck_*`, `key_*.json` or `research/annotation/llm/`. Each annotator gets only their own folder.
>
> **Pre-filled sheets.** Each row starts as "nothing wrong" (addition 0, distortion 0, omission none, faithful 1). Annotators change only what is wrong, and changed cells turn orange. `confidence` starts blank and must be picked on every row. That shows the row was actually read, and a sheet returned with blank confidences gets sent back. Tell annotators plainly that leaving a default without reading the row produces a wrong label.
>
> **When a file comes back:** save it and tell Claude where it is. Claude reads it back with `e16_annotator_workbooks.py --to-csv <file>`, which checks that no row was sorted, deleted or edited and that every row has a confidence.

## 1. What S4 is, in plain words

MAPNAI rewrites a news summary for a reader (shorter, simpler, more "analyst" style). Before a rewrite is shown, a **gate** checks it. The gate either **serves** the rewrite or **falls back** to the original text.

A gate can be wrong in two ways:

| Error | Meaning | Name |
|---|---|---|
| Throws away a **good** rewrite | the reader gets the fallback when the rewrite was fine | **FRR** (false-reject rate) |
| Lets a **bad** rewrite through | the reader sees an invented number, wrong name, missing outcome… | **FAR** (false-accept rate) |

**S4 asks:** does the new gate (CAFG) wrongly reject at least **10 points fewer** good rewrites than the current gate, without letting through more than **2 points** more bad ones with number or name errors?

To measure that, we need to know which rewrites are actually good or bad. Only **humans** can decide that for the paper. The pre-registration forbids using AI labels (ChatGPT, Claude, etc.) for S4. That is why this part needs you and other people.

---

## 2. Who you need

| Role | How many | What they do | Time each |
|---|---|---|---|
| **Annotator** | **2** (call them A1 and A2) | Read a source and a rewrite and fill in 7 columns. Each works alone. | about **6–9 hours** in total (≈ 360 items × 1–1.5 min), split into sessions of up to 1 hour |
| **Adjudicator** | **1** (it can be you) | Settles the items where A1 and A2 disagree, after both have finished | about 1–2 hours (expect 50–80 disagreements) |

What makes a good annotator:
- Reads English news comfortably. They don't need to know anything about AI.
- Has **not** seen MAPNAI's rewrites or gate decisions before. A classmate or teammate who hasn't worked on the personalization code is ideal.
- Can commit the hours in roughly **one or two weeks**, so the labels are made under the same conditions.

You can be the **adjudicator**, since you understand the rules. If you also annotate, you must never open the key file (see §6).

---

## 3. The whole process at a glance

```
 Step 1  Finish generating the rewrites            Claude (needs internet + Groq)       ~1–2 h, unattended
 Step 2  Score the gate, export blind sheets       Claude                               minutes
 Step 3  Brief the annotators                      you                                  30 min meeting
 Step 4  PILOT: both label the pilot sheet         A1, A2 (separately)                  ~2–3 h each
 Step 5  Agreement check (kappa ≥ 0.55?)           Claude                               minutes
            ├─ yes → Step 6
            └─ no  → guideline revised ONCE, fresh pilot, back to Step 4
 Step 6  MAIN: both label the main sheet           A1, A2 (separately)                  ~4–6 h each
 Step 7  Adjudicate disagreements                  adjudicator (you)                    1–2 h
 Step 8  Compute S4 (FRR / FAR, CIs)               Claude                               minutes
```

---

## 4. Step by step

### Step 1: Finish the rewrites (Claude does this; you just say "go")

Only **628 of 1,920** rewrites exist. The run was stopped on 2026-10-24 by a low-memory kill on this laptop. It needs to finish first, because the main batch is drawn from all four styles on the test articles.

- It resumes the same run (tag `main-2026-10-24`) and skips what is already done.
- It sends about **1,300 more calls** to Groq (model `openai/gpt-oss-120b`). The project's self-imposed cap is 4,000 calls, and 636 are used, so there is room.
- It needs the laptop on, online, with `GROQ_API_KEY` in `.env` (already set). Close heavy apps.

Tell Claude: **"resume the main generation"**.

### Step 2: Export the sheets (Claude)

Claude runs the gate scoring (`e14`) and the blind export (`e12`). What comes out:

| File | Rows | Who gets it |
|---|---|---|
| `pilot_A1.csv` / `pilot_A2.csv` | 120 each: the 80 shared items (used for the agreement check) + 40 of the remaining 80 pilot items each | A1 / A2 |
| `main_A1.csv` / `main_A2.csv` | 240 each (the same 240 items, in a different random order) | A1 / A2 |
| `key_<tag>.json` | which item is which article/style/gate decision | **nobody**. It stays on this laptop. |

> The current export script writes one combined sheet. Before Step 2, Claude will split it into the pilot and main files per annotator above, so nobody has to filter rows. This doesn't change which items are sampled.

These files contain third-party news text. They are kept out of git (`research/annotation/export/`). Share them **privately**, e.g. a Google Sheet shared only with that one person, or the CSV by direct message. **Never** put them in a public place.

### Step 3: Brief the annotators (you, ~30 min)

1. Send them `GUIDELINES_D3.md`. Read it together, including the 8 examples.
2. Explain the rules (copy this list to them):
   - Work **alone**. Don't discuss any item with the other annotator until both have finished **everything**.
   - **No web search, and no AI tools** (ChatGPT, Gemini, Claude, Copilot…). Labels made with AI help are not human labels and would invalidate S4.
   - Judge only against the **source** shown, never against what you know about the news.
   - Shorter is allowed. Ask "is anything **wrong, added or importantly missing**?", not "is it as good as the source?".
   - About 1–2 minutes per item. Take breaks; don't do more than about 60 items in one sitting.
   - Fill **every** column. Write a `note` (quote the bad words) whenever `faithful = 0`.
3. Tell them what **not** to change: don't edit `item_id`, `source` or `rewrite`, don't sort or delete rows, and save as CSV (UTF-8).

### Step 4: Pilot (A1 and A2, separately)

Each labels their `pilot_*.csv` and sends it back to you. Save the files as they arrive, then tell Claude where they are.

### Step 5: Agreement check (Claude)

Claude checks that every row is filled with valid values, then computes **Cohen's kappa** on `faithful` over the 80 items both labelled.

- **κ ≥ 0.55** (lowered from 0.6 after the pilot, PREREG v5 §12): good enough, go to Step 6. Don't discuss the pilot items with the annotators until after Step 6, so the main batch isn't influenced.
- **κ < 0.55:** the guideline gets revised **once** (v2), based on where they disagreed. Then a fresh pilot on new dev items is labelled. This is allowed only once (PREREG). If agreement is still low, S4 is reported with a secondary label as pre-registered (§8).

### Step 6: Main batch (A1 and A2, separately)

Each labels all 240 rows of `main_*.csv` and returns it. Same rules as the pilot.

### Step 7: Adjudication (you, or another third person)

Claude makes `adjudication.csv` with only the items where A1 and A2 disagree on `faithful`, showing both labels and notes. For each one, the adjudicator decides the final `faithful` (and the type), following the guideline, and returns the file. Don't change items where they agreed.

### Step 8: S4 numbers (Claude)

Claude computes, on the 240 test items:
- FRR and FAR for the current gate (v1) and for the new gate (CAFG, frozen before this step), weighted for the sampling design, with 95% confidence intervals (bootstrap over articles)
- κ for the main batch
- the pass/fail of S4 exactly as pre-registered. A miss is reported as a miss.

---

## 5. What a row looks like (for the annotators)

| item_id | batch | source | rewrite | addition | distortion | distortion_type | omission | faithful | confidence | note |
|---|---|---|---|---|---|---|---|---|---|---|
| 3fa9c01b2e | A | *(news summary)* | *(rewrite)* | 0 | 1 | number | none | 0 | 3 | "15 people" vs source "five" |

Allowed values: `addition` 0/1 · `distortion` 0/1 · `distortion_type` number / entity / role / polarity / modality / other / blank · `omission` none / minor / salient · `faithful` 0/1 (1 **only if** no addition, no distortion, omission not salient) · `confidence` 1/2/3.

---

## 6. Rules that keep the labels valid (please don't break these)

1. **Nobody opens `key_*.json`** (it reveals the style and the gate's decision). It stays on this laptop.
2. **No AI tools** for labelling, not even to "double-check".
3. **No discussion** between annotators until both have finished the batch.
4. **Don't relabel** after seeing the agreement score or the other person's labels. The adjudicator settles disagreements; annotators don't change their own files.
5. **The guideline is frozen.** It can be revised only once, and only after the pilot.
6. **Don't tell annotators** which gate is "ours" or what result we hope for.

If something goes wrong (a file gets sorted, someone used ChatGPT, someone saw the key), **tell Claude rather than fixing it quietly**. It gets recorded in `LEDGER.md` and handled honestly.

---

## 7. Checklist

- [ ] Two annotators found (names noted privately, not in the repo); adjudicator decided
- [ ] Step 1: "resume the main generation" → done (1,920 rewrites)
- [ ] Step 2: sheets exported; pilot files sent privately
- [ ] Step 3: briefing done; rules list sent
- [x] Step 4: both pilot files back
- [x] Step 5: κ = 0.576 ≥ 0.55 (PREREG v5 §12, gate lowered post hoc from 0.6; L0095–L0096)
- [ ] Step 6: both main files back
- [ ] Step 7: adjudication file back
- [ ] Step 8: S4 computed and recorded

**While you do this, Claude does the parts that don't need people:** S2 and S3 on LLM-AggreFact, silver labels for tuning CAFG on MAPNAI dev, and freezing the CAFG configuration before Step 8.
