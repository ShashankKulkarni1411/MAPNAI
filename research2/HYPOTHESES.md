# research2 — hypotheses and analysis plan (v1)

**Written 2026-11-15, before any news-value score or human label existed.** Commit this file before the Kaggle run, so the commit time shows the plan came first. Any later change goes in a dated section at the end and is disclosed in the paper.

## Study

**Question:** do LLM-annotated news values in a MIND article's headline and abstract predict whether readers click it, and how far does **public importance** diverge from **engagement**?

**Data:** MIND-small (train and dev). 22,771 candidate articles. 156,965 train and 73,152 dev impressions (`results/n01_prepare_2026-11-15.json`).

**Scores:**
- **Values:** seven news values on a 1–5 scale: conflict, magnitude, prominence, surprise, utility, entertainment, importance (`CODEBOOK.md`).
- **Model:** `Qwen/Qwen2.5-7B-Instruct`, greedy decoding, prompt sha256 `2550d607…` (`nv_common.py`).
- **Input:** headline plus abstract only. The category is withheld from the model.

## Validity of the scores (gate, run before any click analysis)

- **Labelling:** two humans independently label the same 100 articles (`data/human_sample.json`, stratified by category, ≥ 50 impressions each).
- **Human reliability per value:** quadratic-weighted Cohen's κ between the two labellers.
- **LLM validity per value:** Spearman ρ between the LLM score and the mean of the two human scores, with a 95% bootstrap CI (2,000 resamples, seed 13).
- **Gate:** a value enters the confirmatory tests (H1–H3) only if LLM–human ρ ≥ 0.40 and human κ ≥ 0.40. A value that fails is still reported, but it is labelled exploratory.

## Primary analysis: within-impression AUC (A1)

- **Unit:** the impression. Primary data is the **dev** split. The train split is a replication, reported separately.
- **Calculation:** for impression *i* and value *v*, compute the AUC of score *v* separating clicked from non-clicked candidates within *i*, with ties counted as 0.5. Only impressions with at least one clicked and one non-clicked scored candidate are used. Report the mean over impressions (the same convention as MIND's AUC metric).
- **Why within-impression:** comparing only items shown together in the same impression removes exposure differences between articles, the main known bias of raw CTR.
- **Uncertainty:** 95% CI from 1,000 bootstrap resamples of **users** (seed 13).

## Hypotheses

- **H1.** Entertainment, prominence and surprise each have a dev within-impression AUC above 0.5. Test: the 95% CI excludes 0.5, with Holm correction across the three.
- **H2.** Importance predicts clicks less well than entertainment: AUC(importance) < AUC(entertainment). Test: paired bootstrap over users; the 95% CI of the difference lies below 0.
- **H3.** Among articles with ≥ 50 impressions (train and dev pooled; click rate = clicks ÷ impressions), Spearman ρ(importance, click rate) < ρ(entertainment, click rate). Test: paired bootstrap over articles; the 95% CI of the difference lies below 0.

## Exploratory (reported as such)

- **E1:** AUC of conflict, magnitude and utility. The literature's negativity-bias evidence is mixed, so no direction is predicted.
- **E2:** a conditional logistic regression of click on all seven standardised values, grouped by impression (dev), with coefficients and CIs.
- **E3:** per-category AUC and ρ (importance vs click rate), and "important but ignored" vs "clicked but unimportant" quadrants with examples (headlines quoted only briefly).
- **E4 (baseline):** within-impression AUC on dev of the article's train-period click rate (with coverage reported), compared against the best news value and a simple sum of values.
- **E5:** sensitivity checks: values the gate excluded; impressions with ≤ 10 candidates; empty-abstract articles removed.

## Not claimed

- **Causality:** values are observational correlates.
- **Screen position:** MIND has no position data, so layout effects can't be controlled.
- **Generality:** results cover one platform (MSN, Oct–Nov 2019) and one LLM.

## Changes after this version
(none yet)

## Gate outcome (2026-11-16): the rule above applied, not a change to it
Source: `results/n04_validity_2026-11-16.json` (`n04_validity.py`). 99 items: A1 left item 84 (N20331) blank.

- **Pass (ρ ≥ 0.40 and κ ≥ 0.40):** conflict, magnitude, prominence, surprise, utility, importance.
- **Fail:** entertainment. Human κ = 0.199 [0.068, 0.335], though LLM–human ρ = 0.706. Labeller A1 gave 67 of 99 items a 3 and none a 1; ρ(LLM, A2) = 0.815, ρ(LLM, A1) = 0.130.
- **What follows, per the rule:**
  - H1 stays confirmatory for **prominence and surprise**. Its entertainment part is reported as exploratory. Holm correction stays over m = 3 as written (conservative).
  - **H2 and H3 both involve entertainment, so they become exploratory.** They are still run and reported, labelled as such.
  - Labels are not revised after seeing the gate. Any re-labelling of entertainment would be a disclosed post-hoc change and analysed separately.
- **Process note:** the first A2 file received shared five columns with A1 exactly (a file mix-up). The labeller sent the correct file the same day, and only that file was used. Hashes are in the result file.
