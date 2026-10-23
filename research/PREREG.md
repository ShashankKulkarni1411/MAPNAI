# PRE-REGISTRATION

**Version:** v0 · **Date:** 2026-10-23 · **Branch:** `research/sota-push`
**State when committed:** no LLM-AggreFact, MIND or checker file has been downloaded; no MAPNAI rewrite has been generated; no label (gold or silver) exists; no test split has been scored. Sources for every reference number: `research/SOTA_TARGETS.md`.

**Change rule (R3).** Sections may be **added** before the data they govern is seen. An existing criterion may be changed only before any test result for it exists, by a new dated entry in the changelog at the bottom that keeps the old text. Missed targets are reported as missed.

---

## 1. Scope and re-scoping of CAFG (from Phase 1c)

Cheap-first cascading is established [Chen2023FrugalGPT; Dekoninck2025Cascade], and a confidence-gated small-verifier → LLM cascade has already been evaluated on LLM-AggreFact [DoRosario2026Jev]. **CAFG is therefore not claimed as a new cascade method.** Its claimed contribution is limited to: (i) a deterministic lexical stage that makes hard reject decisions before any learned checker; (ii) compression awareness (omission under a reader's length budget handled separately from addition/distortion) in a serve-or-fallback gate; (iii) evaluation on style-personalized news rewrites. Contribution type: application/combination + empirical evaluation, not a novel algorithm.

## 2. LLM-AggreFact protocols

- **P-fixed (primary):** the MiniCheck/leaderboard protocol recorded in `SOTA_TARGETS.md` §1a. Test split, threshold 0.5 (`prob > 0.5`), NLTK sentence chunking (500 tokens for Flan-T5, 400 for DeBERTa), max over chunks, `balanced_accuracy_score × 100` per dataset.
- **P-tuned (secondary, reported separately, never mixed with P-fixed):** a single global threshold per checker, tuned on the **dev** split for macro BAcc, then frozen.
- **Subsets.** **Primary: the News-3 mean** = unweighted mean of AggreFact-CNN, AggreFact-XSum and TofuEval-MediaS. **Secondary: all 11 datasets**, always reported in full, including the unfavourable ones.
- **Uncertainty.** 95% percentile bootstrap over instances, stratified by dataset, 2,000 resamples, seed 13. Differences between systems use the paired bootstrap on the same instances. Holm correction across the S2 + S3 comparison family.
- **Leakage.** The dev split is used for every threshold and parameter. Each frozen configuration (config file sha256 + git commit recorded in `LEDGER.md` before scoring) scores test **once**. LLM-AggreFact is CC-BY-ND-4.0 and evaluation-only, so no model is trained or fine-tuned on it.

## 3. Scorecard

| ID | Target | Criterion (decided now) | If missed |
|---|---|---|---|
| **S1** harness validity | Reproduce MiniCheck-Flan-T5-L under P-fixed | \|our 11-dataset average − **75.0**\| ≤ 2.0. Cross-check: 10-dataset average without RAGTruth vs the paper's **74.7**. Checkpoint `lytang/MiniCheck-Flan-T5-Large` @ `96eafd01cee2d16cf81aaa2fb226b14f422a37b3` | Two debug attempts (input format, chunking, max length, threshold, checkpoint). Then every downstream LLM-AggreFact comparison is labelled **"harness unvalidated"** |
| **S2** current gate on LLM-AggreFact | Measured baseline, **no target** | Two wrappers, both reported: **(a) v1-as-is**: `factcheck.verify(source=doc, rewrite=claim, entity_names=NER(doc))`, NER = the production entity path (A1 BERT model `models/mapnai-ner-bert`, spaCy fallback as in production); **(b) additions-only**: reject iff `verify` reports added numbers. News-3 primary, all 11 reported, with CIs | Reported as measured |
| **S3** CAFG-L+M vs MiniCheck-FT5 alone | Non-inferiority at reduced checker use | On test, News-3 mean: the **lower 95% bound of BAcc(CAFG-L+M) − BAcc(FT5)** > **−2.0**, **and** learned-checker invocations ≤ **50%** of items (every learned-model call counts). Also reported: the 11-dataset result and a **random-escalation control** at the same call rate (20 seeds; mean and 95% interval), as required by [DoRosario2026Jev]. Pareto curve of BAcc vs call rate on the pre-declared grid: on dev (used for selection) and on test (descriptive only; only the frozen point supports the claim) | Reported as missed, with the Pareto curve |
| **S4** MAPNAI rewrites (human gold only) | FRR and FAR vs the current gate | FRR lower by ≥ **10 points** absolute; FAR on lexical error types non-inferior with a **2-point** margin (lower bound of the paired difference); semantic-edit detection target **set after S3 and before the S4 test run**, by a dated changelog entry | Reported as missed. Silver labels can never satisfy S4 |
| **S5** ceiling | Bespoke-MiniCheck-7B under P-fixed | Reported number with CI as the reference ceiling (published 77.4). Runs on Colab (local GPU 6 GB); until then **PENDING** | PENDING is reported as such |
| **S6** clustering (optional) | Held-out pair F1 | Pair F1 with 95% CI on a new held-out set (≥ 500 pairs: random + band) per D2-1. B³ vs the published 92.36–94.76 **only if** the dataset download is approved and its data terms are confirmed | Dropped from the public-benchmark claim |

## 4. CAFG configuration space for S3 (LLM-AggreFact)

LLM-AggreFact claims are not compressions of their documents, so **Stage 2 (core-fact relaxation) is OFF** on this benchmark. The stages used:

1. Stage 0: entity normalization (F2 logic: possessives, punctuation, case, leading "the", whitespace).
2. Stage 1, hard reject: a number in the claim that is absent from the document (existing `verify` logic); an added capitalized name absent from the document (`insights.new_names`).
3. Stage 1b, lexical accept: accept without a learned call iff the claim's content tokens are covered by a single document sentence at coverage ≥ τ_acc.
4. Stage 3: everything else → MiniCheck-Flan-T5-L under P-fixed (threshold 0.5, not tuned).

**Tuned parameters (≤ 3, dev only):** τ_acc ∈ {0.80, 0.85, 0.90, 0.95, 1.00, off}; the added-name rule ∈ {on, off}. No third parameter.
**Selection rule (dev):** the configuration with the lowest learned-call rate whose dev News-3 BAcc ≥ dev News-3 BAcc of FT5 alone − 1.0. Ties → higher dev BAcc. If no configuration qualifies → the one with the highest dev BAcc, and S3 is expected to fail; it is still run once and reported.
**Equivalence requirement:** with every relaxation off and no learned stage, CAFG reproduces `factcheck.verify` bit-for-bit on every E02 item (Phase 6 gate).

## 5. Label rules

- **Gold** = two independent human annotators under `research/annotation/GUIDELINES_D3.md` (frozen before labelling), with κ reported. **Silver** = LLM-judge labels (two independent prompts, cross-family), used for dev tuning and trend analysis only, tagged `silver` on every row, and never described as human.
- E02 (synthetic) is a regression check only; it is never used for tuning and never supports a claim.

## 6. Allowed and forbidden claims

- Allowed: "within X BAcc of [system] on [benchmark] under [protocol], at Y% of its compute".
- Forbidden: "SOTA", "state-of-the-art", or any claim from an unvalidated harness, a silver-only label set, or E02.

## 7. To be added in Phase 5 (before any label is viewed)

MAPNAI split file (grouped by source article, seed 13) and its sha256; RQ1/H1 margins for the style factorial; S4 dev/test sizes; annotation sample design and weights.

## Changelog

| Date | Version | Change |
|---|---|---|
| 2026-10-23 | v0 | Initial registration (scorecard, protocols, CAFG configuration space for LLM-AggreFact) |
