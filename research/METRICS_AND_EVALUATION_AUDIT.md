# MAPNAI — Metrics, Baselines and Experimental Evidence (Phase 5)

**Date:** 2026-10-23 · **Code:** `53f4b12` · **Scripts and outputs:** `research/experiments/` (see its `README.md`)
**Rule followed:** nothing here is inferred from intuition alone. Each metric is either (a) computed, with its script, data and configuration given; or (b) marked unavailable, with the exact missing input. No user interactions, labels or benchmark results were fabricated. Synthetic experiments are labelled **SYNTHETIC**.

---

## 1. Metric selection

### 1.1 Primary direction D3: faithfulness of style-personalized rewrites and gate quality

| Metric | What it measures | How it is computed | Why it fits | Data required | Limitations |
|---|---|---|---|---|---|
| **Gate false-rejection rate (FRR)** | Share of *faithful* rewrites the gate refuses to serve (the reader loses personalization) | rejected ∧ faithful / faithful | The cost side of a serve/fall-back gate | Human faithfulness label per rewrite | Depends on what "faithful" means for omissions; needs a written guideline |
| **Gate false-acceptance rate (FAR)** | Share of *unfaithful* rewrites served | passed ∧ unfaithful / unfaithful | The harm side | Same | Few positives if models are good; needs enough unfaithful items |
| **Per-error-type recall** | Detection by type (addition, number, entity, role, polarity/negation, modality/hedge, salient omission) | Recall within each human-labelled type | The gate's blind spots are type-specific [E02] | Typed human labels | Small n per type; use exact (Wilson) CIs |
| **Balanced accuracy / AUROC** (score-based checkers) | Threshold-free separability | AUROC by Mann–Whitney; balanced accuracy at a threshold tuned on dev | Standard on SummaC / LLM-AggreFact [Laban2022SummaC; Tang2024MiniCheck], so results can be put in context | Labels + checker scores | The lexical gate is binary, so only balanced accuracy applies to it |
| **Unsupported-content rate** of the generator | How often rewrites add or distort facts, per style cell | Unfaithful / total per cell | RQ1 | Labels on a stratified sample | Annotation cost |
| **Salient-omission rate** | Missing facts the annotator judges essential | Per cell | Separates compression from distortion | Labels + guideline for "salient" | Subjective; report agreement |
| **Personalization serve rate** | Share of requests where a rewrite (not the fallback) is served | 1 − fallback rate | The product-side outcome | Gate decisions (no labels) | Says nothing about faithfulness on its own |
| **Length compliance** | Rewrite ≤ the style's word budget | Word count ≤ 50 (short) / 120 (medium) | Style adherence, the other side of the trade-off | Rewrites only | Proxy for "style quality" |
| **Latency and cost per 1k checks** | Efficiency | Wall clock per check; LLM calls and tokens | Cheap gates are the point of the design | Timing harness | Hardware-dependent; report the machine |
| **Inter-annotator agreement** (Cohen's κ) | Label reliability | κ on doubly-annotated items | Validates the ground truth | 2 annotators per item | κ is prevalence-sensitive; also report raw agreement |

Not selected: **ROUGE and BERTScore** do not measure faithfulness and correlate poorly with factual errors [Devaraj2022; Maynez2020]. **Recommendation metrics** do not apply to D3.

### 1.2 Secondary direction D2: event clustering

| Metric | Definition | Fit | Data | Limitation |
|---|---|---|---|---|
| Pairwise precision / recall / F1 | Over labelled article pairs | Matches the existing pair rule and labels | `tests/data/cluster_pairs.jsonl` (63) → needs ≥ 500 held-out pairs | Pairs are not a clustering; band-sampled |
| B³ precision / recall / F1 + cluster count | Item-level clustering agreement | The benchmark convention [Saravanakumar2021] | Gold clusters (public stream benchmark [Miranda2018]) | Full articles, not synopses |
| ARI / NMI | Partition agreement | Complements B³ | Gold clusters | Sensitive to the number of clusters |
| False-merge / false-split rate | Operational errors | Interpretable for materiality | Gold clusters | — |
| AUROC of a similarity signal | Separability of same-event pairs | Choosing embeddings and evidence | Pair labels | Band-conditional |

### 1.3 System descriptives (not evaluation claims)

Singleton-cluster share, materiality distribution, render fallback rate, catalog coverage and topic entropy of served digests, and section read rates. These describe the **system**, never user satisfaction.

---

## 2. Existing evaluation infrastructure (inventory)

| Asset | Path | What it supports | Status |
|---|---|---|---|
| Clustering calibration script | `scripts/calibrate_clustering.py` | Pairwise P/R/F1 sweep | Runs; reproduced [Phase 1] |
| Labelled clustering pairs | `tests/data/cluster_pairs.jsonl` | Pair labels (63; 46 positive) | Exists; band-sampled 0.68–0.89, 94 articles [E01] |
| Agent 5 golden file | `tests/data/agent5_response_golden.json` | Response *shape* only | Not accuracy data |
| Unit/integration tests | `tests/` (21 files) | Correctness of logic | 331 pass / 25 fail in an unpinned environment (failures environmental) [Phase 1] |
| Online metrics | `personalization/metrics.py`, `GET /admin/metrics` | Serving, read rate, must_know precision / miss rate, render fallbacks | Implemented; only developer data |
| Impression logs | Mongo `impressions` (1,043) | Exposure, propensity, score parts | Developer accounts only [live] |
| Feedback logs | Mongo `feedback` (105) | Engagement events | 9 developer/demo users [live] |
| Render cache | Mongo `render_cache` (12) | Gate decisions on real rewrites | Tiny; no labels |
| Insights cache | Mongo `insights_cache` (2) | Dropped-claim counts | Tiny |
| Job telemetry | Mongo `job_runs` (301) | Job durations / statistics | Available, not analysed |
| Classifier evaluation notebook | `scripts/classifier/train_colab.ipynb` | Classification report, gold-set procedure | **No saved outputs**; no gold file in the repo |
| Classifier candidates | `data/classifier/candidates.jsonl` (5,667) | Unlabelled inputs | No labels in the repo |
| Relevance judgments / need labels / faithfulness labels / QA pairs | — | — | **None exist** |

---

## 3. Metric availability

Status values: **Available and verified** · **Available but unverified** · **Partially available** · **Not available** · **Not applicable**.

| Metric | Availability | Evidence | Missing inputs | Can calculate now? | Next step |
|---|---|---|---|---|---|
| Gate sensitivity by synthetic edit type | Available and verified | E02 (29,067 checks) | — | **Done** | Re-run after any gate change |
| Gate latency | Available and verified | E02 | — | **Done** | Add learned-checker latency |
| Gate FRR / FAR on *natural* rewrites | Not available | 12 cached rewrites, no labels | Human labels on ~1,000 rewrites | No | EXP-1, EXP-2, EXP-3 |
| Per-error-type recall (natural) | Not available | — | Typed labels | No | EXP-3 |
| Learned-checker AUROC / balanced accuracy on MAPNAI | Not available | Checkers not installed | Model downloads (torch + checkpoints) + labels | No | EXP-4 (needs approval for downloads) |
| Generator error rate per style cell | Not available | — | Generated rewrites + labels | No | EXP-3 |
| Render fallback rate (live) | Available but unverified as representative | E03: 4/12 = 0.333 [Wilson 0.138–0.609] | A larger, non-developer sample | **Done** (descriptive) | EXP-1 produces a proper sample |
| Personalization serve rate | Partially available | E03 (12 items) | Volume | Descriptive only | EXP-1 |
| Clustering pairwise P/R/F1 (in-sample) | Available and verified | E01 | — | **Done** | — |
| Clustering pairwise P/R/F1 (held-out) | Partially available | E01 leave-one-out of the selection procedure | Independent labelled pairs | Partial (LOOCV only) | D2-1: label ≥ 500 random + band pairs |
| B³ / ARI / NMI | Not available | — | Gold clusters (public benchmark download) | No | D2-2 (download approval) |
| Similarity AUROC (cosine, title Jaccard) | Available and verified (band-conditional) | E01 | — | **Done** | — |
| Near-duplicate detection rate | Not available | E01 shows recall on *same-event* pairs only | Labelled duplicate pairs | No | Not needed for the paper |
| Singleton-cluster share, cluster sizes | Available and verified | E03 | — | **Done** | — |
| Materiality distribution | Available and verified | E03 | — | **Done** | — |
| Materiality validity (vs importance) | Not available | — | Importance labels | No | D8 (not in the primary plan) |
| Classifier macro-F1 | Not available | Notebook without outputs | 300-item gold set | No | Notebook cell 18 procedure |
| Classifier silver agreement | Available and verified (as a proxy) | E03 | — | **Done** | Report only as a proxy |
| Classifier calibration (ECE) | Not available | — | Gold labels | No | With the gold set |
| NER entity F1 | Not available | — | Span labels | No | Not needed for D3 |
| Recommendation P@K, R@K, nDCG, MRR, Hit@K, AUC | Not available | 105 developer feedback events | Real user interactions **or** a public log dataset | No (MAPNAI); yes offline on MIND/EB-NeRD after download | D4 (deprioritised) |
| Catalog coverage, topic entropy (served digests) | Available but unverified | E03 (developer usage): coverage 0.065, entropy p50 1.57 bits | Real users | Descriptive only | — |
| Intra-list diversity (embedding) | Partially available | Personalization FAISS index not in the repo | Rebuild the pers index locally | After rebuild | Not needed for D3 |
| Novelty / serendipity / exposure diversity | Not available | — | User histories + a definition + users | No | Out of scope |
| must_know precision / miss rate | Available but unverified | `metrics.must_know`; 2 needed / 1 missed | Real users | No (meaningless n) | D1 benchmark |
| Agent 5 retrieval recall@k / MRR | Not available | Index coverage 74% (E03 check) | QA set with gold articles | No | Not in the primary plan |
| Agent 5 answer accuracy / unsupported-claim rate | Not available | Mocked tests only | QA set + labels | No | Not in the primary plan |
| Summaries: ROUGE, factual consistency | Not applicable / not available | No reference summaries | References or labels | No | Not needed |

---

## 4. Metrics calculated in this phase

All runs used git `53f4b12`, Python 3.12.10 in a scratch virtual environment, and unpinned dependencies (see `research/experiments/README.md`). No LLM calls were made, and nothing was written to any database.

### 4.1 E01: clustering pair rule

`research/experiments/e01_cluster_pairs_eval.py` → `results/e01_cluster_pairs_2026-10-23.json`, `results/e01_cluster_pairs_sweep_2026-10-23.csv`

- **Data:** 63 labelled pairs (46 positive, 17 negative); 94 distinct articles; cosine range 0.681–0.892; Δt ≤ 27.7 h.
- **Configuration:** `config/personalization.py` defaults (`_env_file=None`); seed 13; 5,000 bootstrap resamples.
- **Sanity check:** the re-implemented rule equals `clustering.pair_joins` on all 63 pairs × 25 thresholds.

| Measurement | Value |
|---|---|
| Current rule @ 0.77 (in-sample) | P **0.923** (Wilson 0.759–0.979) · R **0.522** (0.381–0.659) · F1 **0.667** (pair bootstrap 0.529–0.784) · TP 24, FP 2, FN 22, TN 15 |
| Leave-one-out of the configured selection procedure (lowest t with P ≥ 0.95, else max precision) | P 0.857 · R **0.261** · F1 **0.400**; threshold chosen 0.77 (51×) / 0.82 (12×) |
| Leave-one-out, max-F1 selection | P 0.765 · R 0.848 · F1 0.804; always picks 0.70 (the grid edge) |
| Cosine only @ 0.77 | P 0.929 · R 0.565 · F1 **0.703** |
| Evidence only (time ≤ 36 h ∧ (entity ∨ title-Jaccard)), cosine ignored | P 0.759 · R 0.891 · F1 **0.820** |
| No title-Jaccard / no entity evidence / exact entities only | F1 0.648 / 0.554 / 0.667 |
| AUROC same_event (within the band) | cosine **0.714** · title Jaccard **0.737** |
| SimHash (Hamming ≤ 3) on same-event pairs | 0 / 46 detected (Hamming min 12, median 25) |
| MinHash LSH (J ≥ 0.5) on same-event pairs | 4 / 46 detected, 0 false positives |

**Interpretation and limits:**
- The configured threshold looks good only in-sample.
- Within this band, cosine is a weak separator, and the evidence gate does not add precision.
- With 17 negatives, precision is fragile: one extra FP moves it by about 4 points.
- The pairs were **not randomly sampled** (all cos ≥ 0.68) and share articles, so pairs are not independent.
- None of this is a population estimate.

### 4.2 E02: fact gate under SYNTHETIC edits

Scripts: `e02_export_gate_sources.py` (read-only snapshot) → `data/e02_gate_sources_2026-10-23.jsonl` (1,843 in-scope articles with both summaries: 1,093 sports / 750 movies). Then `e02_gate_perturbation.py` → `results/e02_gate_perturbation_2026-10-23.json` (+ per-item CSV).

**Configuration:**
- The gate is `personalization/factcheck.py:verify`, unchanged.
- Its entity input is the article's NER names, as in `service.render`.
- Strata: `summary_short` and `summary_long`. Seed 13.
- 29,067 gate calls in total.

| Edit (expected decision) | n | Gate rejection rate [Wilson 95%] |
|---|---|---|
| number_change (reject) | 2,076 | 0.976 [0.969, 0.982] |
| number_added (reject) | 3,686 | 1.000 [0.999, 1.000] |
| entity_substitution (reject) | 3,554 | 1.000 [0.998, 1.000] |
| month_change (reject) | 320 | 0.897 [0.859, 0.926] |
| entity_role_swap (reject) | 2,985 | **0.001** [0.000, 0.002] |
| negation_inserted (reject) | 2,665 | **0.002** [0.001, 0.004] |
| hedge_removed (reject) | 407 | **0.000** [0.000, 0.009] |
| outcome_flipped (reject) | 467 | **0.006** [0.002, 0.019] |
| identity (accept) | 3,686 | 0.001 [0.000, 0.003], **a bug, see below** |
| number_reformat (accept) | 138 | 0.000 [0.000, 0.027] |
| possessive_stripped (accept) | 197 | **1.000** [0.981, 1.000] |
| sentence_reorder (accept) | 2,183 | 0.010 [0.006, 0.015] (upper bound; partly splitter artifacts) |
| surname_only (contestable) | 2,667 | 0.998 |
| drop_last_sentence (omission) | 2,183 | 0.576 (short source 0.675, long 0.477) |
| lead_50_words (omission; extractive, meets the "short" budget) | 1,853 | **0.873** |

**Summaries:**
- Macro detection of lexically visible errors: **0.968**.
- Macro detection of semantic edits: **0.002**.
- Macro acceptance of benign edits: **0.664**.
- Macro balanced accuracy: **0.574**.
- Latency per `verify`: mean 0.98 ms, p50 0.50 ms, p95 3.42 ms (n = 29,067, laptop CPU).
- Source length: `summary_short` p50 47 words, 47.5% over 50 words; `summary_long` p50 56 words, 53.1% over 50.

**Bug found:** the 4 identity failures come from 2 articles. `_MONTH_BY_NUMBER` matches "65 *mar*kets" and "1981 *nov*el" as months on the source side only.

**Limits:**
- These are rule-generated edits whose ground truth is known by construction. They show the gate's *sensitivity by type*, **not** how often real LLM rewrites contain these errors.
- Macro averages weight the edit types equally, which is an arbitrary choice.
- The edit generators must **not** be used to tune any new gate (that would be overfitting to the generator).

### 4.3 E03: live descriptives (read-only)

`e03_live_descriptives.py` → `results/e03_live_descriptives_2026-10-23.json`

| Measurement | Value |
|---|---|
| Clusters | 1,864 over 2,063 articles; **92.8%** singletons; 16.2% of clustered articles are in multi-article clusters |
| Materiality m | p10 0.236 · p50 0.296 · p90 0.449 · max 0.865; 6.5% ≥ 0.6; 100% unscored; first_report 6.6% |
| Render fallback | 4/12 = 0.333 [Wilson 0.138, 0.609]; short 3/7, medium 1/5 |
| Serving (developer accounts) | 53 digests, 1,043 impressions, 11 users; catalog coverage 0.065; topic entropy p50 1.57 bits; read rate must_know 0.070 · for_you 0.162 · explore 0.25 (n = 5) |
| Classifier silver proxy | 93.9% [92.7, 94.9] agreement with feed domain on 1,888 sports/movie-feed articles; 3.4% of off-taxonomy-feed articles labelled in-scope |
| Agent 5 index coverage | 2,719 / 3,674 live articles (74%) in `data/faiss_index`; 687 stale rows |

**Limits:** the serving and feedback figures come from developers testing the app, so they are **not** evidence about users. The classifier proxy uses feed domain as a weak label.

### 4.4 Earlier phase (carried over)

`scripts/calibrate_clustering.py` reproduced the documented P 0.923 / R 0.522 at 0.77. The test suite ran with 331 passed / 25 failed (environmental).

---

## 5. Metrics that cannot be calculated: blockers

Category codes:

| Code | Meaning |
|---|---|
| **I** | Calculable immediately |
| **N** | Calculable after instrumentation |
| **L** | Needs labelled data |
| **H** | Needs human evaluation |
| **U** | Needs a live or longitudinal user study |

| Metric | Category | (1) Missing | (2) Why current data is insufficient | (3) What to collect | (4) Public data? | (5) Manual annotation? | (6) Synthetic OK? | (7) Script / experiment | (8) Effort | (9) Blocks the paper? |
|---|---|---|---|---|---|---|---|---|---|---|
| Gate FRR / FAR on natural rewrites | L, H | Faithfulness labels on real LLM rewrites | 12 unlabelled cached rewrites | ~1,000 rewrites (8 style cells × 2 models), 2 annotators | No style-stratified set exists (none found) | **Yes** | Only as a sensitivity check (E02), not as the estimate | EXP-1, EXP-2, EXP-3 | ~3 person-weeks | **Yes: the core result** |
| Per-type recall (natural) | L, H | Typed labels | Same | Typed labels (taxonomy after [Devaraj2022]) | No | Yes | Partial | EXP-3 | Included above | Yes |
| Learned-checker scores | N | Model runtime + checkpoints | Not installed | Install torch + checkers (≈ 1.5–3 GB downloads) | Checkpoints are public | No | — | EXP-4 adapters | 1 person-week | Yes, for RQ2 |
| Generator error rates by style | L, H | Rewrites + labels | None generated | Generate with the production prompt (Groq key present) | No | Yes | No | EXP-3 | Included | Yes (RQ1) |
| Clustering held-out P/R/F1 | L | Independent pairs | 63 band-sampled, used for tuning | ≥ 500 pairs (random + band), 2 annotators | Benchmark for B³ only | Yes | No | D2-1 | 1.5 person-weeks | No (secondary track) |
| B³ / ARI / NMI | L | Gold clusters | — | Download the public news-stream benchmark [Miranda2018] | Yes | No | — | D2-2 | 1 person-week + download approval | No |
| Recommendation accuracy (P@K, nDCG, …) | U (or public logs) | Real interactions | 105 developer events | A user study, or MIND/EB-NeRD offline | Yes (offline, interest only) | No | Synthetic users are not acceptable as evidence | D4 harness | 4–6 person-weeks | No (not the primary direction) |
| Need recall / must_know precision | L, H | Need labels | No benchmark | Persona-conditioned labels | No | Yes | No | D1 | 8–12 person-weeks | No (deferred) |
| Classifier macro-F1, calibration | L | Gold labels | Notebook outputs not saved | 300 hand-checked items | No | Yes | No | Notebook cell 18 | 3–4 person-days | No |
| Materiality validity | L | Importance labels | — | Homepage prominence or editor ranks | Possibly [Welsh2024] (overlap unverified) | Maybe | No | D8 | 3–5 person-weeks | No |
| Agent 5 QA accuracy, retrieval recall | L | QA set | — | ~300 QA pairs | No | Yes | No | — | 2–3 person-weeks | No |
| Novelty, serendipity, user exposure diversity | U | Real users | — | Longitudinal study | No | — | No | — | Large | No |

---

## 6. Fair baselines and statistics (for the primary plan)

**Same data for all methods.**
- Every checker and gate variant is scored on the **identical** set of human-labelled rewrites, with the same split.
- Splits are **grouped by source article**: all 8 style rewrites of one article fall in the same split, so a tuned threshold never sees test-article text.
- Dev (30%) is used for thresholds and CAFG parameters; test (70%) is touched once.

**Baselines.**
- (i) The current gate.
- (ii) Each learned checker alone, with its threshold tuned on dev.
- (iii) An LLM judge from a model family different from the generator.
- (iv) "Always serve" and "always fall back" as bounds.

**Paired tests.**
- On the same items, compare accept/reject decisions with **McNemar's test** (assumes paired binary outcomes; use the exact binomial version when discordant pairs are < 25).
- Compare AUROC with a paired bootstrap over source articles (2,000 resamples), since the items are clustered by article.
- Holm-correct across the checker comparisons.

**Style effects (RQ1).** Logistic regression of the error indicator on tone × length × jargon × model, with a **random intercept per source article** (or cluster-robust standard errors). Report odds ratios with 95% CIs. With about 120 unfaithful items expected (unknown in advance), interactions beyond two-way are not estimable; pre-register the main effects.

**Multiple seeds.**
- Generation runs at temperature 0.2. A **second generation seed** on a 20% subset estimates generation variance.
- Checkers are deterministic, so they need no seeds.

**Leakage guards.**
- E02 edit generators are never used for tuning.
- The annotation guideline is frozen before labelling.
- Annotators are blind to gate decisions and to which model or style produced the rewrite.

**Statistics are not appropriate for:** the 12 cached rewrites, the developer feedback logs, or any per-type cell with fewer than ~10 positives. These are reported descriptively with exact CIs.
