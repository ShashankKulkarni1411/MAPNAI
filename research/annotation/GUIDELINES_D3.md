# Annotation guideline D3: faithfulness of style rewrites

**Version:** v1 · **Frozen:** 2026-10-24, before any item was labelled · Changes after the EXP-2 pilot are made only once (R12/PREREG) and are versioned here.

## What you see

Each row has a **source** (a short news summary) and a **rewrite** of it produced for a reader. You do **not** see which model, which style or what MAPNAI's gate decided. Rewrites are allowed to be shorter, simpler or more formal than the source. Judge only whether the rewrite tells the reader the truth **according to the source**. Do not use outside knowledge: if the source is wrong, a rewrite that repeats it is still faithful.

## Labels (fill every column)

| Column | Values | Meaning |
|---|---|---|
| `addition` | 0 / 1 | The rewrite states something the source does not support: a new fact, number, name, cause, consequence, quote, or opinion. Rephrasing and generic connectives ("meanwhile", "in other news") are not additions |
| `distortion` | 0 / 1 | The rewrite changes something the source says |
| `distortion_type` | `number`, `entity`, `role`, `polarity`, `modality`, `other`, or blank | number = a value, date or unit changed; entity = a person/team/place/title replaced or misspelled; role = who did what to whom swapped (winner/loser, buyer/seller); polarity = negation or outcome reversed; modality = certainty changed ("may", "reportedly", "appears to" removed or added); other = any other change of meaning |
| `omission` | `none`, `minor`, `salient` | A fact of the source is missing. **Salient** = a reader of the rewrite would come away with a materially different or incomplete understanding of the main event (who, what happened, the outcome, a headline number). **Minor** = a detail the reader can do without (secondary names, a second statistic, background). Shortening is expected for short styles: judge salience, not length |
| `faithful` | 0 / 1 | **1 only if** addition = 0, distortion = 0 and omission ≠ salient |
| `confidence` | 1–3 | 1 = guessing, 3 = certain |
| `note` | free text | Required when faithful = 0: quote the offending words |

## Decision rules and examples (invented examples)

1. Source: "The club **appears to have** sacked its coach." Rewrite: "The club sacked its coach." → distortion, modality; faithful 0.
2. Source: "Arsenal beat Chelsea 2-1." Rewrite: "Chelsea lost to Arsenal 2-1." → faithful 1 (same meaning).
3. Source: "Ravi Dubey and Sargun Mehta launched the show." Rewrite: "Ravie Dubey and Sargun Mehta launched the show." → distortion, entity (misspelled name).
4. Source: "The film earned ₹120 crore in its first week, a record for the director." Rewrite (short): "The film earned ₹120 crore in its first week." → omission minor; faithful 1.
5. Source: "Verstappen won in Baku after Norris crashed." Rewrite (short): "Norris crashed in Baku." → omission salient (the outcome is gone); faithful 0.
6. Source: "Five people were injured." Rewrite: "Several people were injured." → omission minor (vaguer, not wrong); faithful 1. "Fifteen people were injured." → distortion, number.
7. Rewrite adds "which is expected to boost ticket sales" → addition (unsupported consequence).
8. Unparseable or empty rewrite → faithful 0, note "empty".

When unsure between minor and salient, ask: "would a reader who saw only the rewrite answer *what happened?* differently?" If yes, salient.

## Procedure

- Two annotators label every item **independently**, without discussing items until both have finished.
- Do not search the web. Spend about 1–2 minutes per item.
- EXP-2 pilot: the first 80 items (marked `batch = pilot`). Agreement (Cohen's κ on `faithful`) is computed before the main batch. If κ < 0.6, this guideline is revised **once** (v2), and a fresh pilot is labelled.
- Disagreements in the main batch are adjudicated by a third person who sees both labels.
