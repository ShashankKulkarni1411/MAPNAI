# MAPNAI — Technical Improvement and SOTA Audit (Phase 4)

**Date:** 2026-10-23 · **Code:** `agent-satvik` @ `53f4b12` · **Builds on:** `PROJECT_AUDIT.md`, `RESEARCH_OPPORTUNITIES.md`, `SOTA_AND_LITERATURE_REVIEW.md`
**Evidence produced in this phase:** `research/experiments/results/` (E01–E03, described in `METRICS_AND_EVALUATION_AUDIT.md`). **No application code was changed.**

Evidence labels:

| Label | Meaning |
|---|---|
| **[code]** | Read in the source |
| **[E01]/[E02]/[E03]** | Measured in this phase |
| **[live]** | Read-only database statistics |
| **[lit]** | Verified literature, see `REFERENCES.bib` |

Every "stronger alternative" below is a *candidate to test*, not a claim that it would win.

---

## 1. Per-component audit

Each component answers the nine questions of the brief in order:

1. method
2. competitive?
3. limitations
4. alternatives
5. correctly configured?
6. bottleneck
7. improvable without a rebuild?
8. objectively measurable?
9. research or engineering?

### C1 · Render fact-preservation gate (primary research target)

`personalization/factcheck.py` (`verify` l.106, `extract_facts`, `months`, `_MONTH_BY_NUMBER`); called from `personalization/render.py` (`Renderer.render` l.127) and `personalization/service.py` (`render`: entity names = **all** NER names of the article). The same module is used by `recap.py` (overview check) and `insights.py` (`check_claim`).

1. **Method.** Deterministic rules. A rewrite passes iff:
   - every number, ISO date and month of the source survives, and every *article NER entity name* occurring verbatim in the source survives;
   - no number absent from the source appears.
2. **Competitive?**
   - **On lexically visible errors, yes:** macro detection 0.968 over number change, number added, entity substitution and month change [E02].
   - **On meaning changes, no:** macro detection 0.002 over role swap, negation, hedge removal and outcome flip [E02].
   - Learned checkers exist for exactly this gap [lit: Laban2022SummaC, Zha2023AlignScore, Tang2024MiniCheck], but have not been measured on MAPNAI text.
   - Cost: **p50 0.50 ms, p95 3.4 ms per check** on CPU [E02]. Learned checkers were not measured here.
3. **Limitations.**
   - (a) Blind to meaning changes that keep the same tokens.
   - (b) Treats every omission as a failure. An extractive rewrite meeting the "short" ≤ 50-word budget is rejected **87.3%** of the time [E02], and 47% of `summary_short` sources exceed 50 words [E02].
   - (c) Entity fragments with a possessive (e.g. "Formula 1's") become required facts. Stripping the possessive is rejected **100%** (n = 197) [E02].
   - (d) Checks added *numbers* only, not added *names* [code]. `insights.new_names` already exists for that [code].
   - (e) It is count-insensitive: changing one of two occurrences of a number can pass (2.4% of number changes passed) [E02].
4. **Alternatives.** Entity-precision checks [Nan2021Entity]; NLI sentence-level checks (SummaC); alignment models (AlignScore); small fact-checkers (MiniCheck-Flan-T5-L, Bespoke-MiniCheck-7B on LLM-AggreFact [lit]); an LLM judge from a different model family; cascades (cheap rules first).
5. **Correctly configured?** **No: there is a verified bug.** In `_MONTH_BY_NUMBER` the "number + month" branch has no trailing word boundary, so "65 *mar*kets" and "1981 *nov*el" read as months on the source side only. Two of 1,843 sources therefore fail even an **identical** rewrite [E02 identity pass rate 0.9989]. Separately, passing every NER name as a required fact is a configuration choice that the data shows is too strict.
6. **Bottleneck.** The *algorithm* (lexical only) plus the *specification* (omission = error), compounded by entity-data quality (fragments).
7. **Improvable without a rebuild?** Yes. The gate is a pure function behind one call site; a new variant can sit behind a config flag.
8. **Measurable?** Yes: false-rejection rate (FRR) and false-acceptance rate (FAR) against human labels on natural rewrites, plus per-type sensitivity on synthetic edits.
9. **Research or engineering?** The bug fix and fragment normalization are **engineering**. A compression-aware cascade gate, evaluated against learned checkers on human-labelled, style-stratified rewrites, is **research** (D3).

### C2 · Render generation (prompt and style rules)

`personalization/render.py` (`STYLE_RULES`, `SYSTEM_PROMPT`, `build_messages`, `source_text`); `config/personalization.py` (`render_model = "openai/gpt-oss-120b"`, `render_temperature = 0.2`, `render_max_tokens = 800`, `render_prompt_version = "r2"`).

1. **Method.** One LLM call with the style triple and "keep every number, date and name".
2. **Competitive?** Unknown; nothing has been measured beyond 12 cached rewrites (4 rejected) [live].
3. **Limitations.** The rules conflict: "≤ 50 words" for short versus "keep every … name". 47% of short sources are > 50 words [E02]. The prompt gives no salience guidance, so the model cannot know which facts the gate requires.
4. **Alternatives.** Fact-anchored prompting (give the model the required-fact list, cf. NER-guided news summarization reported in a 2026 AAAI student abstract we did **not** verify); constrained generation; extractive-first compression then light rewording.
5. **Correctly configured?** Mostly, but the length budget is not reconciled with the gate.
6. **Bottleneck.** The specification conflict, not the model.
7. **Improvable without a rebuild?** Yes, through a prompt version bump.
8. **Measurable?** Yes: the same labels as C1, plus length compliance.
9. **Research or engineering?** Prompting changes alone are **engineering**. They become an ablation inside D3.

### C3 · Event clustering

`personalization/clustering.py` (`pair_joins` l.96, `assign_clusters` l.107); `service.cluster_articles` (l.1933); config `cos_join 0.77`, `cos_strong 0.88`, `cluster_time_h 36`, `fuzzy_entity_min 88`, `title_jaccard_min 0.25`, `chain_margin 0.05`, `cluster_nn 20`.

1. **Method.** Single-pass online assignment. A cosine threshold on MiniLM embeddings plus an entity/title evidence gate, with an anti-chaining mean check.
2. **Competitive?**
   - **Not demonstrated.** In-sample on 63 pairs: P 0.923 [Wilson 0.76–0.98], R 0.522 [0.38–0.66], F1 0.667 [bootstrap 0.53–0.78] [E01].
   - The *threshold-selection procedure* under leave-one-out gives P 0.857, R 0.261, F1 0.40 [E01]: the configured calibration is over-fitted to the 63 pairs.
   - Published stream clustering reaches B³ F1 ≈ 92–95 on the standard English benchmark [lit: Saravanakumar2021]. This is a different metric and different data, so **not comparable**.
3. **Limitations.**
   - **The evidence gate adds nothing over plain cosine on these pairs.** Cosine only at 0.77 gives P 0.929, R 0.565, F1 0.703, against 0.923 / 0.522 / 0.667 for the full rule [E01].
   - **Evidence alone (ignoring cosine) has higher F1:** 0.820 (P 0.759, R 0.891) [E01].
   - **Discrimination is weak.** Within the sampled band, AUROC is 0.714 for cosine and 0.737 for title Jaccard [E01].
   - **Candidate generation is post-filtered.** A global top-21 FAISS search is filtered to the 48 h window afterwards (`service.py` cluster_articles), so in-window neighbours will be crowded out as the index grows [code].
   - **Clusters are fragmented live:** 92.8% of clusters are singletons, and only 16.2% of clustered articles are in multi-article clusters [live/E03].
4. **Alternatives.** Stronger sentence encoders; entity-aware embeddings and a time kernel [Saravanakumar2021]; LLM adjudication of the 0.70–0.88 band; continual story discovery [Yoon2023SCStory]; window-restricted search (FAISS ID selector or a per-window index).
5. **Correctly configured?** The threshold was tuned on the same data it is reported on, with no held-out set. The pairs come from the cosine band 0.68–0.89 only [E01], so precision/recall are band-conditional.
6. **Bottleneck.** The *embedding* (weak separation), the *evaluation* (63 non-random pairs, 17 negatives) and the *implementation* (post-filtered neighbours).
7. **Improvable without a rebuild?** Yes. `clustering.py` is pure; the embedder and neighbour search sit behind `PersVectorStore`.
8. **Measurable?** Yes, given a held-out pair set (≥ 500 pairs) and the public benchmark.
9. **Research or engineering?** Mostly **engineering / empirical evaluation** (D2).

### C4 · Ingestion near-duplicate detection

`utils/deduplicator.py` (SimHash Hamming ≤ 3 on title + body[:500]; MinHash LSH J ≥ 0.5, 128 permutations).

1. **Method.** Two-stage near-duplicate drop at ingestion.
2. **Competitive?** Fit for near-verbatim duplicates. On same-*event* pairs it catches SimHash 0/46 and MinHash 4/46 [E01], so it is no substitute for event clustering (and is not meant to be).
3. **Limitations.** Duplicates are *dropped*, which loses "how many outlets covered this", a signal materiality needs.
4. **Alternatives.** Keep duplicates as cluster members flagged `near_duplicate`.
5. **Correctly configured?** Yes, for its purpose.
6. **Bottleneck.** The design choice (drop vs group).
7. **Improvable without a rebuild?** Partly; it touches ingestion.
8. **Measurable?** Duplicate-detection rate needs labelled duplicate pairs (not available).
9. **Research or engineering?** **Engineering.**

### C5 · Text embeddings (MiniLM)

`storage/faiss_store.py:152` and `storage/pers_vector_store.py`: `all-MiniLM-L6-v2` over `f"{title}. {body[:300]}"`, `IndexFlatIP`.

1. **Method.** Off-the-shelf 384-d sentence embeddings with exact inner-product search.
2. **Competitive?** MiniLM is a fast baseline, not the strongest encoder. Its effect on MAPNAI tasks is unmeasured.
3. **Limitations.** Shared by clustering, interest, R3 retrieval and MMR, so one weakness propagates everywhere. Agent 5's pipeline index covers **2,719 / 3,674 (74%)** live articles, and 687 of its 3,406 rows are stale [E03 check].
4. **Alternatives.** Larger general encoders (to be chosen and *benchmarked*, not assumed); keep MiniLM if a stronger model does not help on short synopses.
5. **Correctly configured?** The pipeline index is out of sync with Mongo (Agent 5 semantic recall is capped at 74%).
6. **Bottleneck.** Data synchronisation (index coverage) first, model second.
7. **Improvable without a rebuild?** Yes: re-index (`scripts/rebuild_pers_faiss.py` exists for the personalization index).
8. **Measurable?** Clustering pair F1, retrieval recall@k (needs QA labels).
9. **Research or engineering?** **Engineering**, or an ablation inside D2.

### C6 · Materiality m

`personalization/materiality.py:39`; weights `w_risk .5, w_size .2, w_first .15, w_cred .15`; `config/source_credibility.json`.

1. **Method.** Hand-weighted mean of LLM risk, log cluster size, first-report flag and source tier.
2. **Competitive?** Unvalidated against any importance label.
3. **Limitations.**
   - Risk is missing on 99.4% of articles, so m is renormalized over the other three components [live].
   - Median m is 0.296, and size_score is at its floor (0.289) for most articles [E03].
   - Because clusters are mostly singletons, m is effectively source tier plus a constant.
4. **Alternatives.** Coverage-based importance [lit: Welsh2024 as a possible label source]; learned weights.
5. **Correctly configured?** The design is fine, but the inputs are missing (A4 not run).
6. **Bottleneck.** Data (no risk scores, fragmented clusters).
7. **Improvable without a rebuild?** Yes: run A4 over the window and fix clustering.
8. **Measurable?** Only with importance labels (none available).
9. **Research or engineering?** Validation would be modest research (D8). Running A4 is engineering.

### C7 · Exposure spread and need

`personalization/spread.py` (`hop` l.37, `spread` l.65); `personalization/slate.py` (`need` l.44); `rel_weights` with only `CO_MENTION 0.1` in use.

1. **Method.** Declared seeds plus 2-hop co-mention spread; need = m × max π.
2. **Competitive?** No benchmark exists for this task, so it cannot be answered.
3. **Limitations.** Hop scores are ≤ 0.1 < τ = 0.2, so the spread never affects must_know [code]. Neo4j is currently unreachable [live], and spread falls back to nothing.
4. **Alternatives.** Typed relations (LLM-extracted); KG propagation [Wang2018RippleNet]; an LLM reranker conditioned on a persona.
5. **Correctly configured?** Consistent with its documented design.
6. **Bottleneck.** Relations (co-mention only) and evaluation (no labels).
7. **Improvable without a rebuild?** Partly: relation extraction is a new job.
8. **Measurable?** Only after building a need benchmark (D1).
9. **Research or engineering?** **Research (D1)**, but with high evaluation risk.

### C8 · Interest model

`personalization/interest.py` (`late_fusion` l.116, `interest` l.145); weights `w_lf .5, w_topic .3, w_entity .2`, windows of 72 h / 60 d.

1. **Method.** Late fusion of history similarities plus Beta affinities.
2. **Competitive?** Late fusion is reported to be competitive with heavy user encoders [lit: Iana2023Simplifying]. MAPNAI's instance is unevaluated.
3. **Limitations.** Hand weights; no click data to learn them.
4. **Alternatives.** NRMS/LSTUR-class models (these need click logs); learning-to-rank (needs labels).
5. **Correctly configured?** Yes, as documented.
6. **Bottleneck.** Data: there are no users.
7. **Improvable without a rebuild?** Yes, but improvement cannot be shown without data.
8. **Measurable?** Only offline on MIND/EB-NeRD (D4).
9. **Research or engineering?** Low research value now.

### C9 · Candidate generation

`personalization/candidates.py` (`rrf` l.93, `merge_candidates` l.102); `service._candidate_pool` (l.761); R3 = `search_vector(hist, r3_per_item*3)` then filtered to the 48 h window.

1. **Method.** RRF over 4 retrievers.
2. **Competitive?** Unmeasured.
3. **Limitations.** R3 has the same post-filter problem as C3 [code].
4. **Alternatives.** Window-restricted ANN.
5. **Correctly configured?** Yes, apart from the post-filter.
6. **Bottleneck.** Implementation.
7. **Improvable without a rebuild?** Yes.
8. **Measurable?** Candidate recall needs relevance labels.
9. **Research or engineering?** **Engineering.**

### C10 · Slate: MMR, calibration and explore

`personalization/slate.py` (`mmr` l.79, `calibration_caps` l.67, `thompson_explore` l.129).

1. **Method.** MMR (λ = 0.7), topic caps, a Thompson explore slot with logged propensities.
2. **Competitive?** These are standard techniques [Carbonell1998; Steck2018; Chapelle2011].
3. **Limitations.** Only the explore slot is stochastic. 5 explore impressions exist in total [E03].
4. **Alternatives.** None needed now.
5. **Correctly configured?** Yes.
6. **Bottleneck.** Traffic.
7. **Improvable without a rebuild?** Not meaningfully, without users.
8. **Measurable?** Intra-list diversity and topic entropy can be computed (median 1.57 bits per developer digest [E03]); user value cannot.
9. **Research or engineering?** Not worth pursuing now.

### C11 · Agent 2 classifier

`agents/agent2_classifier.py`, `agents/classifier_model.py`, `models/classifier/` (taxonomy 2.0.0; the code declares 3.0.0).

1. **Method.** Multi-task DistilRoBERTa distilled from Qwen2.5-7B labels.
2. **Competitive?** **Silver proxy only:** 93.9% agreement [Wilson 92.7–94.9] with the feed domain on sports and movie feeds, and 3.4% of off-taxonomy feed items labelled in-scope [E03]. There is no gold accuracy.
3. **Limitations.** Version mismatch; no human test set; the notebook was saved without outputs.
4. **Alternatives.** Not needed until a gold set exists.
5. **Correctly configured?** Taxonomy mismatch (loader-tolerated) [code].
6. **Bottleneck.** Evaluation.
7. **Improvable without a rebuild?** Yes.
8. **Measurable?** Macro-F1 after a 300-item gold set (procedure already in the notebook).
9. **Research or engineering?** **Engineering** (LLM-distilled classifiers are established).

### C12 · Agent 1 NER

`agents/ner_agent.py` (`LABEL_MAP`: `"MISC": "Product"` l.29); BERT with CoNLL labels.

1. **Method.** Fine-tuned BERT token classifier.
2. **Competitive?** Unmeasured.
3. **Limitations.** CoNLL `MISC` (nationalities, events, works) is stored as **Product**, giving 3,382 "Product" entities in the gate snapshot [E02 data]. Possessive fragments are stored as entity names, which feeds C1's false rejections.
4. **Alternatives.** Entity normalization; a richer label set.
5. **Correctly configured?** **No:** the type mapping is semantically wrong for MISC.
6. **Bottleneck.** Implementation (label map, normalization).
7. **Improvable without a rebuild?** Yes.
8. **Measurable?** Entity-level F1 needs labelled spans.
9. **Research or engineering?** **Engineering.**

### C13 · Agent 4 risk

`agents/agent4_risk_scorer.py`.

1. **Method.** LLM 4-factor score.
2. **Competitive?** Unvalidated.
3. **Limitations.** Run on 22 of 3,674 articles (all `MONITOR`) [live].
4. **Alternatives.** Coverage-based importance (C6).
5. **Correctly configured?** Not run at scale.
6. **Bottleneck.** Operations.
7. **Improvable without a rebuild?** Yes.
8. **Measurable?** Only against importance labels.
9. **Research or engineering?** Engineering, or part of D8.

### C14 · Agent 5 agentic RAG

`agents/query_graph.py`, `agents/query_retriever.py`.

1. **Method.** LangGraph grade → rewrite → credibility → generate → check.
2. **Competitive?** Unmeasured. The pattern mirrors Self-RAG, CRAG and Adaptive-RAG [lit].
3. **Limitations.** The semantic index covers 74% of articles [E03 check]; the generator and checker are the same model family.
4. **Alternatives.** Re-index; a checker from a different model family (e.g. MiniCheck).
5. **Correctly configured?** The index is out of sync.
6. **Bottleneck.** Data synchronisation.
7. **Improvable without a rebuild?** Yes.
8. **Measurable?** Needs a QA set.
9. **Research or engineering?** **Engineering.**

---

## 2. Component improvement matrix

| Component | Current method | Verified weakness | Proposed improvement | Baseline | Expected benefit (hypothesis, not a result) | Required experiment | Research value |
|---|---|---|---|---|---|---|---|
| C1 gate · `factcheck.verify` | Lexical fact retention; numbers-added check | Meaning changes detected at 0.2%; compression omissions rejected 87%; possessive fragments rejected 100%; month-regex bug [E02] | **Compression-aware cascade gate (CAFG):** normalized entities, core-fact requirement under a length budget, added-*name* check (reuse `insights.new_names`), then a small learned checker on what passes | Current `verify`; MiniCheck / AlignScore / SummaC alone; LLM judge | Lower FRR at equal or lower FAR; most of a learned checker's recall at a fraction of the calls | EXP-3 → EXP-6 (`EXPERIMENT_BACKLOG.md`) on human-labelled natural rewrites | **High** |
| C1 · `_MONTH_BY_NUMBER` | Regex | Identical text rejected (2 / 1,843) [E02] | Add a word boundary after the month word | Current regex | Identity pass rate 1.0 | Re-run E02 identity | Engineering (bug fix) |
| C1 · entity list (`service.render`) | All NER names required | Fragments ("X's") required verbatim [E02] | Normalize names; require only salient entities | Current | Lower FRR | E02 benign + EXP-5 | Part of CAFG |
| C2 render prompt | Style triple, "keep all facts" | Conflicts with ≤ 50 words for 47% of short sources [E02] | Fact-anchored prompt (core facts listed) | Prompt r2 | Fewer salient omissions | EXP-7 ablation | Medium (ablation) |
| C3 clustering rule | cos ≥ 0.77 ∧ evidence | Evidence gate ≤ cosine-only on 63 pairs; LOOCV F1 0.40; AUROC 0.71 [E01] | Held-out pair set; compare cosine-only, evidence-first, a stronger encoder, LLM adjudication in 0.70–0.88 | Current rule; cosine-only | Higher recall at P ≥ 0.9 (unproven) | D2 suite (secondary track) | Medium (empirical) |
| C3 neighbour search | Global top-21, then window filter | Window crowd-out as the corpus grows [code] | Window-restricted search | Current | Stable candidate recall | Replay test on growing index | Engineering |
| C4 dedup | Drop near-duplicates | Removes coverage signal | Keep as flagged cluster members | Current | Better size_score | — | Engineering |
| C5 index sync | Pipeline FAISS index (git-tracked) | 74% coverage, 687 stale rows [E03 check] | Rebuild from Mongo | Current | Agent 5 semantic recall ceiling → 100% | Coverage count | Engineering |
| C6 materiality | Hand weights | Risk missing 99.4%; m ≈ tier + constant [E03] | Run A4 on the window; validate against importance labels | Current m | Meaningful m | D8 | Low–medium |
| C7 spread / need | Co-mention 0.1 | Hops can never reach τ [code] | Typed relations + need benchmark | Declared-entity match | Unknown | D1 suite | High, but risky |
| C8 interest | Late fusion + Beta | No data | — (offline benchmark only) | NRMS / LSTUR | — | D4 | Low |
| C9 R3 retrieval | Global search, then filter | Same as C3 | Window-restricted search | Current | — | — | Engineering |
| C10 slate | MMR, caps, Thompson | No traffic | None now | — | — | — | Not worth pursuing |
| C11 classifier | DistilRoBERTa (v2.0.0) | Silver agreement only; version mismatch | 300-item gold set | Current | A real macro-F1 | Notebook cell 18 | Engineering |
| C12 NER | BERT, `MISC → Product` | Wrong type; possessive fragments | Fix the map; normalize | Current | Cleaner entities for C1/C3/C7 | Spot-check sample | Engineering |
| C13 A4 | LLM risk | Run on 22 articles | Batch-run on the evaluation window | — | Feeds C6 | — | Engineering |
| C14 A5 | LangGraph RAG | Index coverage 74%; same-family self-check | Re-index; cross-family checker | Current | — | QA set (not available) | Low |

## 3. Classification

**High value, low effort** (engineering; each can ship as a separate, approved change):
- The month-regex boundary fix (C1).
- Entity normalization for the gate: possessives, and only names that exist as whole tokens (C1, C12).
- Fix `MISC → Product` (C12).
- Rebuild the pipeline FAISS index from Mongo (C5).
- Batch-run A4 over the current window (C13).
- Restore Neo4j (C7 prerequisite).
- Window-restricted neighbour search (C3, C9).

**Substantial, research-oriented:**
- **D3, the compression-aware cascade gate with a style-stratified human evaluation** (C1 + C2): the primary direction (`PROPOSED_RESEARCH_PLAN.md`).
- D2, a clustering evaluation on held-out and public data (C3): the secondary, enabling track.

**Exploratory / high-risk:**
- The D1 need benchmark with typed relations (C7).
- D8 materiality validation (C6).
- LLM adjudication for clustering (C3).

**Not worth pursuing now:**
- Neural interest models without click data (C8).
- Off-policy evaluation or τ tuning without traffic (C10).
- More agentic loops in Agent 5 (C14).
- A larger encoder "because it is newer" without a measured gain (C5).

## 4. Why the primary choice holds after Phase 4

E02 converts the Phase 1–3 anecdote (n = 12) into a controlled finding:
- the gate catches lexically visible errors (≈ 97%) and almost none of the meaning-changing edits (≈ 0.2%);
- it rejects most budget-compliant compressions (87%).

Both weaknesses are measurable, both have literature-backed alternatives with published benchmarks [Tang2024MiniCheck; Zha2023AlignScore; Laban2022SummaC], and the fix lives in one pure module. What E02 **cannot** show is how often *real* LLM rewrites contain each error type, or whether CAFG helps on them. That requires the human-labelled natural rewrites planned in `EXPERIMENT_BACKLOG.md`.
