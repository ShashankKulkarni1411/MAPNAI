# MAPNAI — Research Opportunities (Phase 2)

**Date:** 2026-10-23 · **Depends on:** `research/PROJECT_AUDIT.md` (repository + live-data evidence) and `research/SOTA_AND_LITERATURE_REVIEW.md` (literature, novelty checks)

## Ground rules for this document

- A direction appears here only if (a) a concrete MAPNAI component exists for it and (b) it can be tested without a live user base. **MAPNAI has no real users** (105 developer feedback events, [live]), so every direction that needs click logs must rely on public datasets, constructed benchmarks or annotation.
- "Potential novelty" is a hypothesis to be tested against the literature review, not a claim.
- Effort is in person-weeks for a 3-student team that knows the codebase.
- Citation keys (e.g. `[Devaraj2022]`) refer to `research/REFERENCES.bib`.

---

## 1. Candidate directions

### D1 · Need versus interest: exposure-conditioned "must-know" ranking from declared stakeholder exposures

| Field | Content |
|---|---|
| **Research direction** | Users declare *typed exposures* (owns, depends_on, regulated_by, covers, follows) to entities. The question is whether a *need* score, the story's materiality multiplied by the user's propagated exposure, selects the stories that user must not miss, as a target distinct from *interest*. |
| **Relevant implementation** | `personalization/slate.py` (`need` l.44, `pick_must_know`, `build_slate` l.175); `personalization/spread.py` (`hop` l.37, `spread` l.65); `personalization/materiality.py` (`materiality` l.39); `storage/exposure_store.py`; `personalization/service.py` (`compute_digest` l.907); `personalization/feedback.py` (`tau_update` l.40); demo personas in `scripts/seed_demo_personas.py` |
| **Research question** | Given a user's declared typed exposures, does a need-gated section built from materiality × exposure recover the stories that informed judges label "must know for this person" (a) better than interest-based, popularity- or materiality-only, entity-match and LLM-reranker baselines, and (b) without reducing the interest quality of the rest of the slate? |
| **Hypothesis** | H1a: need-gating improves must-know recall@5 over interest-only ranking, because interest models trained or computed on reading history under-rank low-engagement but consequential stories. H1b: most of the gain comes from *declared* exposures. Typed multi-hop propagation helps only when relations are typed (supplier, owner); co-mention propagation does not help. |
| **Existing limitation** | [code + live] Only `MENTIONED_WITH` exists (weight 0.1), so hop exposure can never reach τ = 0.2: must_know is effectively "mentions a declared high/medium entity". Materiality is unscored on 100% of articles (A4 ran on 22 of 3,674), with median m = 0.296. Neo4j is currently unreachable. No ground truth for "need" exists anywhere in the repo. |
| **Proposed contribution** | (1) A persona-conditioned **need benchmark**: personas with typed exposures, daily candidate pools from MAPNAI's corpus, and graded *need* and *interest* labels from humans, with LLM labels validated against them. (2) A controlled comparison of need-gated vs interest-only vs hybrid slates. (3) An ablation of exposure propagation: none, co-mention, and LLM-extracted typed relations. |
| **Potential novelty** | The builders of the POPROX platform report they "have been unable to identify news recommendation research papers that incorporate declared user interests" [Higley2025]. The normative literature names the "duty to inform" vs engagement tension [Lu2020; Stray2024; Higley2025], but we found no benchmark that labels *person-specific need* separately from interest. Knowledge-aware recommenders propagate from *clicked* entities [Wang2018DKN; Liu2020KRED; Wang2018RippleNet], not from declared, typed stakes. |
| **Related research** | Knowledge-aware news recommendation [Iana2024Survey; Wang2018DKN; Liu2020KRED]; preference propagation [Wang2018RippleNet]; editorial values [Lu2020]; normative diversity [Vrijenhoek2022]; value alignment [Stray2024]; newsworthiness [Spangher2024; Welsh2024]; LLM relevance labelling [Thomas2024]. |
| **Required modifications** | Offline harness only, no production change: (a) export candidate pools and π from Mongo (rebuild the co-mention graph from `entities` while Neo4j is down); (b) an annotation tool; (c) an LLM typed-relation extractor feeding `rel_weights` (`SUBSIDIARY_OF`, `SUPPLIES`, … already exist in `config/personalization.py:115`); (d) running A4 on the evaluation window so that m is not uniformly unscored. |
| **Data requirements** | MAPNAI live corpus (3,674 articles, 1,843 with summaries) or a fresh ingestion window. About 30–50 personas × 5–10 days × ~40 candidates. Human labels on ≥ 1,500 (persona, article) pairs (2 annotators, κ reported), plus LLM labels for the rest. No public dataset has declared exposures; MIND and EB-NeRD [Wu2020MIND; Kruse2024EBNeRD] can serve only for the interest side. |
| **Evaluation metrics** | Must-know recall@5 and precision@5; nDCG@10 on need grades; miss rate; interest nDCG@10 on the rest of the slate; persona overlap; for explanations, the share of why-lines whose stated path a judge accepts. |
| **Baselines** | Recency; materiality-only (m); popularity/cluster size; binary entity match; BM25 over exposure names; late-fusion interest (`interest.py`); **an LLM pointwise reranker given the persona card** (the strongest and most dangerous baseline); MAPNAI need; need + typed relations. |
| **Implementation effort** | 8–12 person-weeks: annotation design ≈ 3, benchmark build ≈ 2, typed relations ≈ 3, experiments ≈ 2–3. |
| **Risks** | Circularity, if personas and labels are derived from the same entities the system matches on. Annotator subjectivity about "need" in the sports/film domains. The LLM reranker may dominate. Synthetic personas lack ecological validity. Entity-linking errors. Neo4j availability. |
| **Research potential** | **Highest novelty ceiling and most MAPNAI-specific, but the highest evaluation risk.** It is worth doing only with a carefully specified, independently written labelling protocol. |

### D2 · Online event clustering of short news synopses with entity, time and title evidence

| Field | Content |
|---|---|
| **Research direction** | Online clustering of short RSS items into events, where embedding similarity is gated by entity, time and title evidence and an anti-chaining guard. |
| **Relevant implementation** | `personalization/clustering.py` (`pair_joins` l.96, `assign_clusters` l.107, `fuzzy_shared_entities`, `title_jaccard`); `service.cluster_articles`; `scripts/calibrate_clustering.py`; `tests/data/cluster_pairs.jsonl`; `storage/pers_vector_store.py` (MiniLM over `title + body[:300]`) |
| **Research question** | On short news synopses (median 209 characters [live]), how much do (a) stronger embeddings, (b) entity, time and title evidence gates, and (c) LLM adjudication of borderline pairs improve event-clustering recall at fixed high precision, compared with the evidence-free threshold and published stream-clustering systems? |
| **Hypothesis** | MiniLM on synopses is the bottleneck: recall is 0.52 at precision 0.92 [ran], and 92.8% of live clusters are singletons [live]. A stronger embedder plus LLM adjudication only for 0.70 ≤ cos < 0.88 pairs should raise recall substantially at ≥ 0.9 precision, at a bounded LLM cost. |
| **Existing limitation** | 63 labelled pairs give wide confidence intervals; cos_join was tuned on those same pairs (no held-out set); cluster merges are never performed; there is no comparison on any public benchmark. |
| **Proposed contribution** | An empirical study: MAPNAI's rules vs strong baselines on the standard multilingual news-stream benchmark (English subset) [Miranda2018] and on an expanded, held-out MAPNAI pair set of ≥ 500 pairs; a cost-aware LLM-adjudication cascade. |
| **Potential novelty** | Low to moderate. Entity-aware and time-aware stream clustering exists [Saravanakumar2021], as do continual and story-discovery methods [Yoon2023SCStory; Yoon2023USTORY] and LLM-enhanced event clustering [Tarekegn2024]. What might differ: very short synopses and the cost and precision of LLM adjudication. This is primarily an **empirical evaluation contribution**. |
| **Related research** | [Miranda2018; Saravanakumar2021; Yoon2023SCStory; Yoon2023USTORY; Chen2022SemEval; Charikar2002; Reimers2019SBERT] |
| **Required modifications** | A replay harness that feeds the benchmark stream through `assign_clusters` with a pluggable `sim`; an embedding swap; an LLM adjudicator behind a flag; a B³ scorer. `clustering.py` is pure, so no service change is needed. |
| **Data requirements** | Miranda et al. English stream (public; we did not verify the current download location) [Miranda2018]; MAPNAI live corpus; ~500–1,000 new labelled pairs (2 annotators). |
| **Evaluation metrics** | B³ precision, recall and F1, plus cluster count (benchmark convention [Saravanakumar2021]); pairwise P/R/F1 with bootstrap CIs on MAPNAI pairs; LLM calls and latency per 1,000 articles. |
| **Baselines** | Published numbers (B³ F1: Miranda 92.36, Staykovski 94.41, Saravanakumar 94.76; see the literature review §3.2); the evidence-free cosine threshold; SimHash/MinHash near-duplicate grouping (`utils/deduplicator.py`); HDBSCAN on embeddings. |
| **Implementation effort** | 3–5 person-weeks. |
| **Risks** | Published systems already reach about 95 B³ F1 on the benchmark, so MAPNAI's simple rules may simply lose. The benchmark has full-length articles, unlike MAPNAI's synopses, so results may not transfer. Low novelty. |
| **Research potential** | **The quickest credible paper**, and it fixes a real weakness. On its own it is likely a workshop or short-paper contribution. |

### D3 · Faithfulness under style personalization: what style-controlled LLM rewriting of news breaks, and what cheap fact gates catch

| Field | Content |
|---|---|
| **Research direction** | MAPNAI rewrites each story for the reader's (tone, length, jargon) and serves the rewrite only if a deterministic fact-preservation gate passes. The direction measures the faithfulness cost of each style dimension and the detection quality of cheap and learned checkers. |
| **Relevant implementation** | `personalization/render.py` (`STYLE_RULES`, `SYSTEM_PROMPT`, `Renderer.render` l.127); `personalization/factcheck.py` (`verify` l.106: numbers, ISO dates, months, verbatim entity names, added numbers); the same gate is reused in `personalization/recap.py` (overview) and `personalization/insights.py` (`check_claim`, `fact_check`); live `render_cache` |
| **Research question** | RQ1: How do tone, length and jargon controls change the rate and type of faithfulness errors (unsupported addition, distortion of number, role, modality or negation, omission of salient facts) in LLM rewrites of short news items? RQ2: How well do a lexical fact-retention gate, entity-level precision, NLI- and alignment-based checkers, small fact-checkers and an LLM judge detect each error type, at what cost? RQ3: Does a **compression-aware gate**, one that separates *omission* (expected under a length budget) from *addition or distortion*, cut false rejections without raising false acceptances? |
| **Hypothesis** | H3a: "short" length and "plain/low-jargon" increase omissions and distortions; "analyst/high" increases unsupported implications (the reason `render_prompt_version` was bumped to r2, `config/personalization.py`). H3b: the lexical gate catches added numbers and dropped entities well, but misses modality, negation and attribution changes, and it over-rejects compression omissions. H3c: a cascade of lexical gate → small checker (e.g. MiniCheck-class) dominates either alone on the cost–accuracy frontier. |
| **Existing limitation** | [live] 4 of 12 cached rewrites (33%) were rejected. All rejections were omission-driven, including at least one apparent false rejection (the only missing item was "US"). At least one passed rewrite changed modality ("appears to have been made" → "has been issued"), and one misspelled a name ("Ravie Dubey"). n = 12 is anecdotal. No human faithfulness labels exist. |
| **Proposed contribution** | (1) **StyleFaith-News** (working name): a labelled set of style-conditioned rewrites (MAPNAI sources plus a public news source set for reproducibility), with an error taxonomy adapted from text simplification [Devaraj2022]. (2) A per-style error analysis across 2–3 LLMs. (3) A checker comparison on the same items. (4) A compression-aware gate, validated on held-out items. |
| **Potential novelty** | Moderate. Factuality metrics are mature [Laban2022SummaC; Zha2023AlignScore; Tang2024MiniCheck], and simplification is known to introduce factual errors [Devaraj2022]. The closest news-rewrite study [Khatiwada2026CHI] measures *reader perception* of tone and framing shifts, and rates faithfulness on a Likert scale for only 3 articles. Personalization-induced hallucination is studied for QA [Sun2026PersHalluc], and personalized *headline* generation adds factuality losses [Ao2021PENS]. **We found no systematic study of faithfulness across reader-style controls in news rewriting, nor any evaluation of deterministic fact-retention gates against learned checkers in that setting.** The omission-vs-compression conflict is under-treated: most consistency benchmarks target unsupported content, and omission work is mostly in dialogue summarization [Zou2023Omission]. |
| **Related research** | [Maynez2020; Nan2021Entity; Laban2022SummaC; Zha2023AlignScore; Tang2024MiniCheck; Devaraj2022; Ribeiro2023Readability; Zou2023Omission; Belem2025MultiDoc; Khatiwada2026CHI; Sun2026PersHalluc; Ao2021PENS] |
| **Required modifications** | An offline generation harness reusing `render.build_messages` and `render.parse_response` (no cache writes); checker adapters; an annotation UI (spreadsheet suffices); a `verify_compression_aware()` variant in a research module. **No production change is needed.** |
| **Data requirements** | ~300 source texts (MAPNAI summaries, median ~200 characters, plus ~100 longer public news leads) × 8 style triples × 2–3 models ≈ 5–7k rewrites. A human annotation sample of ~800–1,000 rewrites, stratified by style and gate outcome, with 2 annotators. Groq access (key present). Public checkers are open-weight. |
| **Evaluation metrics** | Error rate per style cell, with CIs and a logistic regression on the style factors; per-checker balanced accuracy, AUROC, and precision/recall per error type; false-rejection rate (faithful rewrites rejected) and false-acceptance rate; cost and latency per 1,000 checks; style-adherence scores (length compliance, readability) as the other side of the trade-off. |
| **Baselines** | MAPNAI lexical gate (as is); entity precision [Nan2021Entity]; SummaC [Laban2022SummaC]; AlignScore [Zha2023AlignScore]; MiniCheck [Tang2024MiniCheck]; an LLM judge (a model family different from the generator, to avoid self-preference); a "no gate" upper bound on serving. |
| **Implementation effort** | 5–7 person-weeks: harness 1, generation 0.5, annotation 2–3, checkers 1, analysis 1–1.5. |
| **Risks** | "Lexical checks miss semantic errors" is unsurprising, so the paper must stand on the *style-axis analysis* and the *compression-aware gate*. Short sources contain few checkable facts. Annotation agreement on omissions is hard. Model drift on Groq. The error rate may be very low for strong models. A search snippet attributed a ~3% hallucination rate to a 2025 LLM news-rewriting study [Cheng2025Balancing], but that figure is not in its abstract and was **not verified**. |
| **Research potential** | **The strongest overall balance** of novelty, feasibility and measurability. It uses a component that is implemented and already produces live evidence of the problem. |

### D4 · A training-free, decomposable news recommender with declared-preference priors: offline benchmarking

| Field | Content |
|---|---|
| **Research direction** | MAPNAI's interest model needs no trained user encoder (late fusion, Beta affinities with priors from declared topics, RRF, MMR, calibration). How does it compare with neural recommenders, on accuracy and beyond-accuracy? |
| **Relevant implementation** | `personalization/interest.py` (`late_fusion` l.116, `interest` l.145, `prior`); `personalization/candidates.py` (`rrf` l.93); `personalization/slate.py` (`mmr` l.79, `calibration_caps` l.67) |
| **Research question** | On MIND and EB-NeRD, how close does the training-free composite scorer come to NRMS/LSTUR-class models on AUC and nDCG@10? Does it yield better normative-diversity (RADio) and calibration? How much does a declared-topic prior help users with ≤ 3 clicks? |
| **Hypothesis** | Lower accuracy than trained models, but competitive in cold start, with better calibration and diversity. |
| **Existing limitation** | All weights are hand-set and never evaluated on any click data. |
| **Proposed contribution** | A reproducible offline benchmark of the MAPNAI scorer, with ablations. |
| **Potential novelty** | **Low.** Late fusion is established [Iana2023Simplifying]; calibration [Steck2018] and MMR [Carbonell1998] are classic; RADio exists [Vrijenhoek2022]. Neither dataset has declared preferences, so the "declared prior" would be simulated from early clicks, which weakens the claim. |
| **Related research** | [Wu2020MIND; Kruse2024EBNeRD; Wu2019NRMS; An2019LSTUR; Iana2023Simplifying; Wu2023Survey; Vrijenhoek2022; Liu2024ONCE] |
| **Required modifications** | A dataset loader and evaluation harness; MiniLM embeddings for MIND/EB-NeRD articles; no production change. |
| **Data requirements** | MIND (English) and EB-NeRD (Danish, which needs a multilingual embedder); both public under research licences. |
| **Evaluation metrics** | AUC, MRR, nDCG@5/10; RADio metrics; calibration KL; cold-start slices. |
| **Baselines** | NRMS, LSTUR, NAML via NewsRecLib; popularity; recency. |
| **Implementation effort** | 4–6 person-weeks. |
| **Risks** | Likely to lose on accuracy with little new to say; the scorer's distinctive parts (need, exposures) cannot be tested on these datasets. |
| **Research potential** | Clear numbers, low novelty. Best used as a **sanity section** inside D1 or D3, not as a paper on its own. |

### D5 · Grounded "developing story" analysis: cited scenarios with claim-level checks

| Field | Content |
|---|---|
| **Research direction** | Multi-document LLM analysis of a developing story (what happened, why it matters, 2–4 scenarios with likelihood labels, actions), with every claim citing article indices and passing deterministic checks. |
| **Relevant implementation** | `personalization/insights.py` (`parse`, `check_claim`, `fact_check`, `usable`, `advice`, `fallback_actions`); `service._analyse_story`, `get_insights`; live `insights_cache` (2 analyses, one with 2 dropped claims) |
| **Research question** | Do claim-level citation plus lexical checks make multi-document news analyses faithful (citation precision and recall, unsupported-claim rate)? Are "likely" scenarios borne out more often than "unlikely" ones over the following 1–2 weeks? |
| **Hypothesis** | The checks remove most unsupported names and numbers but not unsupported causal claims; likelihood labels are weakly calibrated. |
| **Existing limitation** | 2 cached analyses; no evaluation; scenario outcomes are unobserved. |
| **Proposed contribution** | A citation-faithfulness evaluation, plus a small retrospective calibration study of scenario labels. |
| **Potential novelty** | Moderate but hard to defend. Multi-document hallucination is documented [Belem2025MultiDoc]; RAG with self-critique exists [Asai2024SelfRAG]. Retrospective scenario verification is less common, but needs months of data. |
| **Related research** | [Belem2025MultiDoc; Asai2024SelfRAG; Tang2024MiniCheck; Spangher2024] |
| **Required modifications** | A story-sampling harness, outcome annotation after N days, and checker adapters. |
| **Data requirements** | Continuous ingestion for ≥ 2–3 months; annotated outcomes. |
| **Evaluation metrics** | Citation precision and recall, unsupported-claim rate, Brier-style calibration of likelihood labels. |
| **Baselines** | An LLM without citations or checks; a checks-only ablation; MiniCheck-based filtering. |
| **Implementation effort** | 8–10 person-weeks plus calendar time. |
| **Risks** | Small n; scenarios are vague and hard to score; ingestion must run continuously. |
| **Research potential** | Ambitious and interesting, but **not achievable with rigour inside a semester**. |

### D6 · Agentic RAG for news QA: grading, rewriting, credibility reranking and grounding loops

| Field | Content |
|---|---|
| **Research direction** | Ablating MAPNAI's LangGraph Agent 5 (grade → rewrite → credibility → generate → claim check) on news QA. |
| **Relevant implementation** | `agents/query_graph.py` (`_grade_docs` l.379, `_credibility`, `_check_answer`); `agents/query_retriever.py`; `agents/agent5_query.py` |
| **Research question** | Which loop components improve answer accuracy and groundedness on recent-news questions, at what LLM-call cost? |
| **Hypothesis** | Grading and the grounding check reduce unsupported answers; credibility reranking has little effect when sources are mostly tier 0.6–0.8. |
| **Existing limitation** | Only mocked tests; same-family self-verification. |
| **Proposed contribution** | A component ablation and a small news-QA set built from the corpus. |
| **Potential novelty** | **Low:** the design mirrors Self-RAG, CRAG and Adaptive-RAG [Asai2024SelfRAG; Yan2024CRAG; Jeong2024AdaptiveRAG], plus credibility-aware generation [Pan2024CAG]. This is an engineering contribution. |
| **Related research** | As above; [Edge2024GraphRAG] |
| **Required modifications** | A QA-set construction and evaluation harness. |
| **Data requirements** | ~300 QA pairs over the MAPNAI corpus (annotation needed). |
| **Evaluation metrics** | EM/F1 or judged correctness, citation precision, abstention rate, LLM calls. |
| **Baselines** | Single-pass RAG (already the fallback path), CRAG-style. |
| **Implementation effort** | 4–6 person-weeks. |
| **Risks** | A crowded area; results would mostly confirm known findings. |
| **Research potential** | Low as a paper; fine as a system-description section. |

### D7 · Adaptive must-know threshold and logged-propensity exploration

| Field | Content |
|---|---|
| **Research direction** | Feedback control of τ from `needed` / `missed` labels; off-policy evaluation of digest policies using logged propensities. |
| **Relevant implementation** | `personalization/feedback.py` (`tau_update` l.40); `slate.thompson_explore` l.129; `service._log_impressions` l.977; `personalization/metrics.py` (`must_know`) |
| **Research question** | Does the τ controller converge to the target miss rate, and can logged propensities support unbiased evaluation of alternative slates? |
| **Hypothesis** | n/a without traffic. |
| **Existing limitation** | [live] 2 `needed` and 1 `missed` events in total; only the explore slot is stochastic (propensity 1.0 elsewhere), so off-policy estimates for the other 9 slots are undefined. |
| **Proposed contribution** | A simulation study at most. |
| **Potential novelty** | Low. Bandit news recommendation and replay evaluation are classic [Li2010; Li2011]. |
| **Related research** | [Li2010; Li2011; Chapelle2011] |
| **Required modifications** | A user simulator. |
| **Data requirements** | Real traffic (unavailable) or a simulator (weak validity). |
| **Evaluation metrics** | Convergence, regret, OPE error. |
| **Baselines** | Fixed τ, ε-greedy. |
| **Implementation effort** | 3–4 person-weeks for a simulator. |
| **Risks** | A simulator can be built to confirm almost anything. |
| **Research potential** | **The weakest.** Not recommended. |

### D8 · Is "materiality" a valid importance signal? Validating m against editorial prioritization

| Field | Content |
|---|---|
| **Research direction** | Test the hand-weighted materiality m (LLM risk, cluster size, first report, source tier) as a predictor of editorial importance. |
| **Relevant implementation** | `personalization/materiality.py`; `agents/agent4_risk_scorer.py`; `config/source_credibility.json`; the recap ranking in `personalization/recap.py` |
| **Research question** | Do m and its components predict which stories outlets prioritize (homepage prominence, multi-outlet coverage), and does LLM-scored risk add signal beyond coverage? |
| **Hypothesis** | Cluster size (cross-outlet coverage) dominates; the LLM risk score adds little in sports and film. |
| **Existing limitation** | Weights are uncalibrated; risk is missing on 99.4% of articles [live]; recap_min_m is "not calibrated on real data yet" (config comment). |
| **Proposed contribution** | A validation study and learned weights. This would feed D1 directly. |
| **Potential novelty** | Low to moderate. Newsworthiness prediction [Spangher2024] and homepage prioritization data [Welsh2024] exist; their use to validate a personalization importance prior is less common. |
| **Related research** | [Spangher2024; Welsh2024; Lu2020] |
| **Required modifications** | Run A4 on a window; match MAPNAI stories to homepage snapshots (overlap of outlets to be checked). |
| **Data requirements** | NewsHomepages [Welsh2024] (availability and outlet overlap with MAPNAI not verified), or MAPNAI's own cross-outlet coverage. |
| **Evaluation metrics** | Pairwise ranking accuracy, Spearman ρ, AUC for "top-of-homepage". |
| **Baselines** | Cluster size alone, source tier alone, recency. |
| **Implementation effort** | 3–5 person-weeks. |
| **Risks** | Weak outlet overlap; homepage prominence ≠ importance to a specific person. |
| **Research potential** | **Best as a component study inside D1.** |

---

## 2. Ranking

Scores run from 1 (poor) to 5 (strong) and are judgements based on the evidence above and in the literature review. "Effort" is scored inversely (5 = least effort).

| Criterion | D1 Need | D2 Cluster | **D3 Faith** | D4 Offline rec | D5 Insights | D6 RAG | D7 τ/OPE | D8 Materiality |
|---|---|---|---|---|---|---|---|---|
| Potential novelty | **4** | 2 | 3 | 1 | 3 | 1 | 2 | 3 |
| Technical depth | 4 | 3 | 3 | 2 | 4 | 3 | 2 | 3 |
| Relevance to MAPNAI | 5 | 4 | 5 | 3 | 4 | 3 | 4 | 4 |
| Experimental feasibility | 2 | 5 | 5 | 4 | 2 | 4 | 1 | 3 |
| Dataset availability | 2 | 5 | 4 | 5 | 2 | 3 | 1 | 3 |
| Meaningful baselines | 3 | 5 | 5 | 5 | 2 | 4 | 2 | 2 |
| Effort (inverse) | 2 | 5 | 4 | 3 | 2 | 3 | 4 | 3 |
| Measurable results | 3 | 5 | 5 | 5 | 2 | 4 | 1 | 4 |
| Community value | 4 | 3 | 4 | 2 | 3 | 2 | 2 | 3 |
| **Total (/45)** | 29 | 37 | **38** | 30 | 24 | 27 | 19 | 28 |

An unweighted sum hides trade-offs, so the picks below are argued, not read off the table.

### 2.1 The five requested picks

1. **Strongest overall: D3, faithfulness under style personalization.** The component is implemented and on the live serving path, and it already shows both failure modes (§6.1 of the audit). It can be studied with data the team controls, a Groq key it already has, open-weight checkers, and a few weeks of annotation. Its novelty claim is narrow but defensible: we found no systematic, style-factorial faithfulness study of personalized news rewriting, and no evaluation of fact-retention gates against learned checkers in that setting. It does not depend on users, Neo4j or A4.
2. **Quickest credible: D2, event clustering.** The module is pure, a calibration script exists, a public benchmark with published B³ numbers exists, and the weakness is measured (recall 0.52; 92.8% singletons). It could be finished in about a month, but it is mainly an empirical comparison.
3. **Most technically ambitious: D1, need vs interest** (with D8 as its importance component and typed-relation extraction). It requires designing a new labelled benchmark, a relation extractor, A4 scoring at scale, and careful anti-circularity controls. It also has the highest novelty ceiling and is the idea that makes MAPNAI distinctive.
4. **Clearest path to quantitative evidence: D4 (offline MIND/EB-NeRD)**, closely followed by D2. Both are fully automatic, use standard metrics and have many published baselines. D4's numbers would be clear but say little that is new.
5. **Weakest / least defensible: D7 (adaptive τ and propensity-based exploration).** It has no traffic (3 need-related feedback events in total), only one stochastic slot, and its only path is a self-built simulator. D6 (agentic RAG) is the second weakest: feasible, but it re-implements published patterns.

### 2.2 Trade-offs

- **D3 vs D1.** D3 is lower-risk and finishes with real numbers. D1 is the bigger idea, but rests entirely on whether "need" can be labelled reliably by people who are not the target user. If the team wants one paper this semester, D3. If it wants the thesis-defining contribution and can accept a longer timeline, D1, with D3 as a separable chapter.
- **D2 is complementary, not competing.** Better clusters improve materiality (cluster size, first report), recaps, insights and D1's candidate pools. It can be a 2–3 week "enabling" study whatever the main choice.
- **Combining D1 + D4 + D8 into a "MAPNAI system paper" is tempting, but weak.** A combination of established parts is engineering, not research novelty (see the literature review §4).
- **Every direction except D7 avoids depending on real users.** That is deliberate: building a user base and running a field study (e.g. via a platform like POPROX [Higley2025]) is the only route to online claims, and would be a separate, longer project.
