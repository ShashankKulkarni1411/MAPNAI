# MAPNAI — Proposed Research Plan (Phase 6)

**Date:** 2026-10-23 · **Status:** PROPOSAL, awaiting approval. Nothing below has been implemented in the application.
**Primary direction:** D3, faithfulness under style personalization (`RESEARCH_OPPORTUNITIES.md`)
**Evidence base:** `PROJECT_AUDIT.md` §6.1; `TECHNICAL_IMPROVEMENT_AUDIT.md` C1/C2; `METRICS_AND_EVALUATION_AUDIT.md` §4.2 (E02)

---

## 6.1 Candidate titles

1. **Conservative:** *Fact-Preservation Gates for Style-Personalized News Rewriting: An Empirical Evaluation*
2. **Ambitious** (justified only if RQ3 succeeds): *Compress, Don't Distort: Compression-Aware Faithfulness Gating for Style-Personalized News*
3. **Evaluation-focused:** *What Breaks When News Is Rewritten for Its Reader? A Style-Factorial Faithfulness Study and Checker Comparison*

## 6.2 Research problem

**Problem.** News apps increasingly rewrite stories for each reader's preferred tone, length and vocabulary. MAPNAI does this in `personalization/render.py`. Because rewriting can introduce errors, a production system needs a cheap gate that decides, per rewrite, whether to serve it or fall back to the source text. Two things are unknown:
- (a) which reader-style choices cause which kinds of faithfulness errors;
- (b) whether cheap gates separate **harmful distortions** (added, changed or reversed facts) from **acceptable compression** (facts dropped because the reader asked for brevity).

**Why it matters.** A gate that is too strict silently removes the personalization the reader asked for (the fallback). A gate that is too lax serves distorted news.

**What existing work does not cover in this setting:**
- Learned consistency checkers are benchmarked on summarization and grounded QA, without a reader-style axis and largely without omissions [Laban2022SummaC; Zha2023AlignScore; Tang2024MiniCheck].
- Simplification factuality was studied for one style and pre-LLM systems [Devaraj2022].
- The closest news study of LLM tone rewriting measures reader perception, with faithfulness rated on 3 articles [Khatiwada2026CHI].
- Personalization-induced hallucination has been studied in QA, not rewriting [Sun2026PersHalluc].
- Omission has labelled data only in dialogue summarization [Zou2023Omission].

**The precise gap.** There is no style-factorial measurement of error types in LLM news rewrites. Lexical fact-retention gates have not been evaluated against learned checkers with **separate accounting of omission vs distortion** under a length budget.

**Why MAPNAI is a good platform:**
- It already has the style triple, the production prompt (r2), the model (gpt-oss-120b via Groq), a deterministic gate, a fallback path, a cache, and 1,843 real source summaries [E02 snapshot].
- It already shows both failure modes on its own data. The gate catches meaning changes 0.2% of the time and rejects 87% of budget-compliant extractive compressions [E02, SYNTHETIC]. In the 12 real cached rewrites, the 4 rejections were omission-driven, and a modality change passed [Phase 1 §6.1].
- Everything runs without users, which MAPNAI does not have.

## 6.3 Research questions and hypotheses

### RQ1: Which style choices cause which errors?

| Item | Specification |
|---|---|
| Question | How do length (short ≤ 50 words / medium ≤ 120), tone (plain / analyst) and jargon (low / high) affect the probability of each error type in LLM rewrites of short news items? |
| Hypothesis H1 | (a) *short* raises the odds of **salient omission** relative to *medium*. (b) *analyst* raises the odds of **unsupported addition** (implications) relative to *plain*. (c) Neither style factor changes the rate of **number/entity distortion** much. |
| Independent variables | tone, length, jargon (2×2×2); generator model (2); source length (≤ 50 / > 50 words) |
| Dependent variables | Per-rewrite binary labels: unsupported addition, distortion (number, entity, role, polarity, modality), salient omission, minor omission; length compliance |
| Baselines | Identity (no rewrite); extractive lead-k compression within the budget |
| Metrics | Error rate per cell with Wilson CIs; odds ratios from mixed-effects logistic regression (random intercept per source article) |
| Data | ~480 sources × 8 cells × 2 models; human labels on a stratified sample of ~1,000 |
| Supports | OR(short vs medium) for salient omission > 1 with 95% CI excluding 1; same for analyst → addition |
| Refutes | CIs include 1, or the effect is in the opposite direction. That is reported as a finding ("style does not drive errors") |

### RQ2: What do gates and checkers catch?

| Item | Specification |
|---|---|
| Question | On human-labelled natural rewrites, how do the current lexical gate, entity precision, SummaC-ZS, AlignScore, MiniCheck and a cross-family LLM judge compare in FRR, FAR, per-type recall and cost? |
| Hypothesis H2 | (a) The current gate misses most polarity / modality / role distortions (type recall < 0.3), while at least one learned checker reaches ≥ 0.5 on them. (b) The current gate's FRR on faithful *short* rewrites exceeds its FRR on *medium* rewrites by ≥ 15 points. |
| Independent variables | Checker; checker threshold (tuned on dev) |
| Dependent variables | FRR, FAR, per-type recall, AUROC (score-based checkers), ms and LLM calls per check |
| Baselines | Current gate; always-serve; always-fallback |
| Metrics | As above, with a paired bootstrap over source articles and McNemar's test for paired decisions; Holm correction |
| Data | Test split (70%, grouped by source article) |
| Supports | Pre-registered inequalities hold with CIs excluding the margins |
| Refutes | The gate's type recall is comparable to the checkers', or the FRR gap is < 15 points. The gate would then be adequate, which is publishable as a negative result |

### RQ3: Does a compression-aware cascade gate (CAFG) improve the serve / faithfulness trade-off?

| Item | Specification |
|---|---|
| Question | Does CAFG lower false rejections without raising false acceptances, and how close does it get to a learned checker's recall at what cost? |
| Hypothesis H3 | (a) **CAFG-L** (lexical part only) lowers FRR by ≥ 10 points absolute versus the current gate, with FAR on lexical error types non-inferior (margin 2 points). (b) **CAFG-L+M** (cascade with a small checker) is not dominated on (FRR, FAR) by the checker alone, while running the checker only on rewrites that pass the lexical stage. |
| Independent variables | Gate variant; CAFG components (ablated in EXP-6) |
| Dependent variables | FRR, FAR, per-type recall, serve rate, latency, checker calls |
| Baselines | Current gate; the best single learned checker from RQ2 |
| Metrics | As RQ2; plus cost per 1k rewrites |
| Data | Same test split. **CAFG parameters are tuned on dev only**; the E02 edit generators are never used for tuning |
| Supports | (a) and (b) hold on test with paired CIs |
| Refutes | FRR does not drop, or FAR rises beyond the margin. CAFG is then reported as not helpful, and the paper keeps RQ1 and RQ2 |

### RQ4 (optional extension): Does telling the model which facts are core reduce omissions?

| Item | Specification |
|---|---|
| Hypothesis H4 | A fact-anchored prompt (r3: the core facts are listed) lowers the salient-omission rate in *short* rewrites without raising additions |
| Run only if | RQ1 shows short → omission |

## 6.4 Methodology

### Architecture (research harness; the production path is untouched)

```
data/e02_gate_sources_*.jsonl ─┐
public news abstracts (MIND) ──┼─► e10_select_sources ─► sources.jsonl (stratified, grouped dev/test split)
                               │
                               ▼
               e11_generate_rewrites  (personalization.render.build_messages / parse_response,
                                       utils.groq_client.init_groq_llm; NO render_cache writes)
                               │  rewrites.jsonl  {source_id, cell, model, seed, text, latency}
                               ▼
     ┌──────── e14_score_gates ──────────────────────────────────────────────┐
     │  current gate: personalization.factcheck.verify (unchanged)           │
     │  CAFG-L / CAFG-L+M: research/faithgate/cafg.py                        │
     │  checkers: research/faithgate/checkers.py (SummaC, AlignScore,        │
     │            MiniCheck, LLM judge) → scores.jsonl                       │
     └───────────────────────────────────────────────────────────────────────┘
                               │
e12_export_annotation ─► annotators (blind) ─► e13_import_annotation ─► labels.jsonl (κ report)
                               │
                               ▼
                       e15_analysis → tables, figures (results/), stats JSON
```

### Algorithms

**Current gate** (baseline, unchanged): `factcheck.verify(source, rewrite, ner_names)`.

**CAFG** (`research/faithgate/cafg.py`, new, pure):

```text
inputs: source S, rewrite R, ner_names E, title T, length budget B (words), params P (tuned on dev)

0  normalize
   E' = {strip_possessive(e) for e in E if whole_token_in(S, strip_possessive(e))}
   collapse names contained in a longer name of E'; record aliases (surname for Person if unique in S)
   month regex with a trailing word boundary   (the bug fix, applied in the research copy)

1  additions → hard reject
   added_numbers = factcheck.verify(...)[2]        (existing logic)
   added_names   = insights.new_names(S, R)         (existing helper, unused by render today)
   added_months  = months(R) − months(S)
   if any → REJECT("addition")

2  required facts
   F = facts(S) with E'                           (numbers, dates, months, entities)
   if words(S) > B:                               (the budget forces compression)
       C = core(F; S, T, P)                       core = facts in the first sentence ∪ facts in T
                                                  ∪ top-k salient entities (k in P)
   else:
       C = F
   missing = {f ∈ C : not satisfied(f, R, aliases)}
   if missing → REJECT("core_omission")           non-core omissions are allowed and logged

3  (CAFG-L+M only) semantic check on what passed
   for sentence r in split(R):
       p = checker.support_prob(S, r)             (small learned checker, θ in P)
       if p < θ → REJECT("unsupported_or_distorted")

ACCEPT
```

`satisfied(f, R, aliases)`: a number is satisfied by its normalized forms; a month by its name or abbreviation; an entity by its normalized name or a recorded alias.

**Design notes:**
- Step 1 makes omission relaxation safe against substitution. Today, substitution is caught only because the original name goes missing (E02), so once non-core omissions are allowed, *added* names must be checked.
- Step 2's `core` is deliberately simple and has few parameters, to limit dev overfitting.

### Data flow and procedure

1. **Sources.**
   - 480 MAPNAI sources from the 2026-10-23 snapshot, stratified by domain (sports / movies) × source length (≤ 50 / > 50 words). The field follows production: short → `summary_short`, medium → `summary_long`.
   - **Generalization set:** 120 MIND news abstracts [Wu2020MIND]. The download is to be approved; MIND's research licence applies.
   - Grouped split by source: dev 30% / test 70%. Seed fixed.
2. **Generation.**
   - 8 style cells × 2 models: the production `openai/gpt-oss-120b` and one other-family model served by Groq, chosen when the experiment runs and recorded.
   - Temperature 0.2, prompt r2, `render_max_tokens` 800.
   - A 20% subset is regenerated with a second seed.
   - Every request is logged: model, latency, tokens, errors.
3. **Annotation.**
   - **Guideline:** `research/annotation/GUIDELINES_D3.md`, written and frozen first. Taxonomy: addition; distortion by sub-type (number, entity, role, polarity, modality, other); salient omission; minor omission; faithful.
   - **Pilot:** 80 items, double-annotated. Continue if κ(faithful vs unfaithful) ≥ 0.6; otherwise revise the guideline and repeat the pilot.
   - **Main:** ~1,000 rewrites, stratified by cell × model, plus an oversample of gate-rejected items with inverse-probability weights. 30% double-annotated; disagreements adjudicated by a third annotator (the guide, or the third student).
   - Annotators see the source and the rewrite, but not the model, style cell or gate decision.
4. **Scoring.** All gates and checkers run on all rewrites. Thresholds and CAFG parameters are tuned on dev, then frozen.
5. **Analysis.** The statistics in `METRICS_AND_EVALUATION_AUDIT.md` §6.

### Computational requirements

| Item | Need | Note |
|---|---|---|
| Generation | ~7,700 Groq chat calls of ~300 input / ≤ 800 output tokens | Within reach of the existing key; the rate limits and cost of the account tier must be checked before running |
| LLM judge | ~7,700 calls (cross-family model) | Same |
| SummaC-ZS, AlignScore-large (355M), MiniCheck-Flan-T5-L (0.8B) | CPU possible (hours); Colab T4 preferred | Needs torch + checkpoints (≈ 1.5–3 GB of downloads), **to be approved** |
| Bespoke-MiniCheck-7B (optional) | GPU (Colab) | Optional |
| Current gate / CAFG-L | ≈ 0.5 ms per check on CPU [E02] | — |

### Code changes

**New files** (research only; no production behaviour change):

| File | Purpose |
|---|---|
| `research/faithgate/__init__.py`, `research/faithgate/cafg.py` | CAFG (pure) |
| `research/faithgate/checkers.py` | Lazy-import adapters: SummaC, AlignScore, MiniCheck, LLM judge |
| `research/faithgate/test_cafg.py` | Unit tests: CAFG-L must equal the current gate when `B = ∞` and normalization is off (equivalence), plus a test per rule |
| `research/annotation/GUIDELINES_D3.md` | Frozen guideline + examples |
| `research/experiments/e10_select_sources.py` … `e15_analysis.py` | The harness described above |

**Existing files read or imported, not modified:**
- `personalization/render.py` (`build_messages`, `parse_response`, `STYLE_RULES`);
- `personalization/factcheck.py`;
- `personalization/insights.py` (`new_names`);
- `utils/groq_client.py`;
- `config/personalization.py`.

**Production changes, only after the results and a separate approval:**
- `personalization/factcheck.py`: the month-regex boundary fix (an independent bug fix; could be approved earlier);
- `personalization/render.py` + `config/personalization.py`: a `render_gate` setting ∈ {`v1`, `cafg_l`, `cafg_lm`}, default `v1`;
- `personalization/service.py`: pass the title and length budget to the gate;
- `tests/test_pers_phase7.py`: extended tests.

## 6.5 Contributions

| Category | Intended contribution | Status |
|---|---|---|
| Empirical finding | Error-type rates of LLM news rewrites across a 2×2×2 reader-style design and 2 models (RQ1) | **Proposed**, not measured |
| Analysis of an underexplored problem | How lexical gates and learned checkers handle *omission vs distortion* under a length budget (RQ2) | **Proposed**. Only a synthetic sensitivity profile of the current gate exists (E02) |
| Method (modest) | CAFG: compression-aware, addition-checked cascade gate (RQ3) | **Proposed**. Its benefit is a hypothesis |
| Dataset / annotation resource | ~1,000 style-stratified rewrites with typed faithfulness labels (release depends on source-text licensing; MIND-based items may be releasable under its licence) | **Proposed** |
| Reproducible evaluation framework | The `research/experiments` harness, including the synthetic gate stress test | **Partially done** (E02 exists) |
| Efficiency | Checker calls saved by the cascade | **Proposed** |

**Already demonstrated (this phase):**
- (1) The current gate detects 96.8% of lexically visible synthetic errors and 0.2% of meaning-changing synthetic edits.
- (2) It rejects 87.3% of budget-compliant extractive compressions and 100% of possessive-stripped entity mentions.
- (3) A month-regex bug makes identical text fail on 2 of 1,843 sources.
- (4) The gate costs about 0.5 ms (median).

**Not demonstrated:** anything about real LLM rewrites beyond 12 anecdotal cases, and any benefit of CAFG.

**What would weaken the paper:**
- Strong models make almost no errors in any cell, which leaves RQ1 thin.
- An off-the-shelf checker already handles omission vs distortion well, which leaves RQ3 thin.
- Annotator κ stays below 0.6 after revision, which undermines the ground truth.

Each outcome is still reportable, but the paper becomes primarily an evaluation note.
