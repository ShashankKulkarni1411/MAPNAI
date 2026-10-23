# MAPNAI — SOTA and Literature Review, with Novelty Validation (Phase 3)

**Date:** 2026-10-23 · **Covers:** the leading directions from `research/RESEARCH_OPPORTUNITIES.md`: **D3** (faithfulness under style personalization), **D1** (need vs interest from declared exposures, with D8 materiality) and **D2** (event clustering). D4–D7 get short notes.
**Bibliography:** `research/REFERENCES.bib`. Citation keys are given in brackets.

## 0. Method and verification standard

- Searches were run on 2026-10-23 with a web search tool. Each cited 2019–2026 paper was confirmed against at least one primary or official source: ACL Anthology, arXiv abstract page, ACM DL listing, proceedings page, or the authors' institutional page. Titles, authors, venues and page numbers come from those pages.
- **Foundational papers** (before 2019, plus a few classic 2019–2020 papers such as NRMS, LSTUR, SBERT and Maynez et al.) are cited from established bibliographic knowledge and were **not** re-fetched in this session. Their BibTeX entries carry `note = {not re-verified in this session}`.
- **Reported results** are quoted only where a source page showed them. Where the source was secondary, this is stated.
- **Not accessed:** the official MIND leaderboard page; full texts behind ACM DL (403); the full POPROX workshop paper beyond its arXiv HTML; the full USTORY paper.
- **Unverified leads (not cited as evidence):** "Increasing Editor Trust in News Personalization Systems with …" (ACM DOI 10.1145/3774935.3806175; the page returned 403 and no indexed title match was found); "Kopra" (a knowledge-aware news recommender named in a search summary; not confirmed).

---

## 1. D3 · Faithfulness under style personalization

### 1.1 Problem

An LLM rewrites a source news text under reader-style constraints (tone, length, jargon). The rewrite must stay faithful (no unsupported or distorted content) and should keep salient facts. A cheap checker decides whether to serve it.

### 1.2 Established methods and recent advances

- **The problem is real for abstractive generation.** Error taxonomies and human studies established it [Maynez2020]. Entity hallucination can be measured with entity-level precision [Nan2021Entity]; MAPNAI's `factcheck.py` is a stricter, rule-based relative of this.
- **NLI-based checking** became competitive once document/sentence granularity was handled (SummaC) [Laban2022SummaC].
- **Unified alignment models** (AlignScore, 355M) [Zha2023AlignScore] and **small trained fact-checkers** (MiniCheck, 770M, synthetic training data) [Tang2024MiniCheck] report LLM-level detection at a fraction of the cost. MiniCheck also introduced the **LLM-AggreFact** benchmark.
- **Rewriting for readability or simplicity is known to introduce factual errors.** [Devaraj2022] gives an insertion/deletion/substitution taxonomy and shows standard metrics miss these errors. Readability-controlled summarization exists [Ribeiro2023Readability]; we did not verify whether it measures faithfulness.
- **Omission** is a separate error type with its own labelled data, but in dialogue summarization [Zou2023Omission].
- **News-specific LLM generation:** multi-document news summaries can be heavily hallucinated [Belem2025MultiDoc]. Tone and framing rewrites of news change reader trust; there, neutral rewrites were judged generally faithful and extreme-sentiment rewrites drifted [Khatiwada2026CHI].
- **Personalization and factuality:** personalized *headline* generation (PENS) [Ao2021PENS]; personalization-induced hallucination in personalized LLM QA [Sun2026PersHalluc].

### 1.3 Representative papers

| Paper | Year · Venue | DOI / URL | Relevance to MAPNAI | Limitation / gap for us |
|---|---|---|---|---|
| *On Faithfulness and Factuality in Abstractive Summarization*, Maynez, Narayan, Bohnet, McDonald [Maynez2020] | 2020 · ACL | 10.18653/v1/2020.acl-main.173 | Defines intrinsic and extrinsic hallucination; the error-typing basis | Pre-LLM summarizers; no style control |
| *Entity-level Factual Consistency of Abstractive Text Summarization*, Nan et al. [Nan2021Entity] | 2021 · EACL, pp. 2727–2733 | 2021.eacl-main.235 | Entity-precision metric ≈ the "entity" part of MAPNAI's gate | Catches entity hallucination only |
| *SummaC: Re-Visiting NLI-based Models for Inconsistency Detection in Summarization*, Laban, Schnabel, Bennett, Hearst [Laban2022SummaC] | 2022 · TACL 10:163–177 | 10.1162/tacl_a_00453 | Off-the-shelf NLI checker baseline; SummaC benchmark | Summaries of long documents; no style axis |
| *Evaluating Factuality in Text Simplification*, Devaraj, Sheffield, Wallace, Li [Devaraj2022] | 2022 · ACL, pp. 7331–7345 | 10.18653/v1/2022.acl-long.506 | Closest error taxonomy (insertion/deletion/substitution) for "plain / low-jargon" rewriting | Simplification only; pre-LLM-era systems; no gate evaluation |
| *AlignScore: Evaluating Factual Consistency with a Unified Alignment Function*, Zha, Yang, Li, Hu [Zha2023AlignScore] | 2023 · ACL, pp. 11328–11348 | 10.18653/v1/2023.acl-long.634 | Strong mid-size checker baseline | Not tuned for omission-vs-compression |
| *Generating Summaries with Controllable Readability Levels*, Ribeiro, Bansal, Dreyer [Ribeiro2023Readability] | 2023 · EMNLP, pp. 11669–11687 | 2023.emnlp-main.714 | Style (readability) control on CNN/DM news | Focuses on control accuracy; faithfulness trade-off not verified by us |
| *Towards Understanding Omission in Dialogue Summarization*, Zou et al. [Zou2023Omission] | 2023 · ACL, pp. 14268–14286 | 2023.acl-long.798 | Omission as a measurable error, with labels | Dialogue, not news; no length-budget interaction |
| *MiniCheck: Efficient Fact-Checking of LLMs on Grounding Documents*, Tang, Laban, Durrett [Tang2024MiniCheck] | 2024 · EMNLP, pp. 8818–8847 | 2024.emnlp-main.499 | Cheapest strong learned checker; LLM-AggreFact benchmark | Checks unsupported claims, not omissions; benchmark not style-stratified |
| *From Single to Multi: How LLMs Hallucinate in Multi-Document Summarization*, Belém et al. [Belem2025MultiDoc] | 2025 · Findings of NAACL, pp. 5291–5324 | 10.18653/v1/2025.findings-naacl.293 | Evidence that LLM news summaries hallucinate substantially; relevant to recaps and insights (D5) | Multi-document; no reader styles |
| *When AI Rewrites the News: How Sentiment, Framing, and LLM Disclosure Shape Perceptions*, Khatiwada, Pappu, Bagozzi, Mauriello [Khatiwada2026CHI] | 2026 · CHI | 10.1145/3772318.3791527 | The closest study of LLM *tone* rewriting of news | Measures reader perception (≈180 participants). Faithfulness is a Likert rating on 3 articles, not a systematic error analysis |
| *PENS: A Dataset and Generic Framework for Personalized News Headline Generation*, Ao et al. [Ao2021PENS] | 2021 · ACL, pp. 82–92 | 10.18653/v1/2021.acl-long.7 | Personalized news *generation* benchmark | Headlines, from click behaviour; not reader-declared style; factuality not central |
| *When Personalization Misleads: Understanding and Mitigating Hallucinations in Personalized LLMs*, Sun et al. [Sun2026PersHalluc] | 2026 · arXiv preprint | arXiv:2601.11000 | Shows personalization can induce factual errors | QA setting, not news rewriting; not peer-reviewed |

### 1.4 Datasets, metrics and baselines used in this area

- **Benchmarks:** SummaC benchmark (6 datasets) [Laban2022SummaC]; LLM-AggreFact (11 datasets, per its leaderboard page) [Tang2024MiniCheck]; simplification factuality annotations [Devaraj2022]; OLDS for omission [Zou2023Omission]. **None is stratified by reader style.**
- **Metrics:** balanced accuracy and AUROC for checkers; per-error-type rates for generators; human error annotation with an agreement statistic.
- **Practical baselines:** lexical/entity checks; SummaC; AlignScore; MiniCheck-Flan-T5-L; Bespoke-MiniCheck-7B; an LLM judge from a family different from the generator (self-preference is a documented concern, raised e.g. in [Khatiwada2026CHI]).

### 1.5 Open questions relevant to MAPNAI

1. Which style dimension (length budget, tone, jargon) drives which error type in LLM news rewrites?
2. Can a gate tell *compression omissions* (acceptable, or graded by salience) apart from *distortions*? Do learned checkers, trained to flag unsupported content, simply ignore omissions?
3. On short news items (median ~200 characters in MAPNAI), is a lexical gate already near the cost–accuracy frontier, or does a small learned checker dominate?

---

## 2. D1 · Need vs interest from declared stakeholder exposures (with D8 materiality)

### 2.1 Problem

Rank news for a person by what they *need* to know given their stakes (holdings, dependencies, regulators, coverage beat). This differs from what they *like* to read. Surface the needed items without destroying engagement.

### 2.2 Established methods and recent advances

- **Neural content-based recommenders** learn interest from click histories [Wu2019NRMS; An2019LSTUR]; see the survey [Wu2023Survey]. Benchmarks: MIND [Wu2020MIND], EB-NeRD [Kruse2024EBNeRD]. Late fusion of candidate–history similarities is competitive with heavy user encoders [Iana2023Simplifying]. LLM-augmented content encoders are a recent advance [Liu2024ONCE].
- **Knowledge-aware recommenders** inject KG entities into representations [Wang2018DKN; Liu2020KRED] or propagate user preferences over a KG from *interacted* items [Wang2018RippleNet]; see the survey [Iana2024Survey].
- **The normative and editorial line** argues that click optimization under-serves editorial and public-interest goals:
  - editorial values in a deployed recommender [Lu2020];
  - normative diversity metrics [Vrijenhoek2022];
  - value-alignment synthesis [Stray2024];
  - stakeholder preference differences [Kolb2025].
- **Importance and newsworthiness signals:** newsworthiness prediction of policy items [Spangher2024]; homepage layouts as a proxy for prioritization [Welsh2024].
- **Practice gap:** the POPROX team, building a live research recommender, reports that they "have been unable to identify news recommendation research papers that incorporate declared user interests". They also note the "tension between user engagement and the duty to inform", and found no "good empirical evidence for the relative effectiveness of different preference elicitation strategies" [Higley2025] (quotes from the arXiv HTML).
- **Label construction at scale:** LLM-generated relevance labels can match human labellers when the prompt is validated against real preferences [Thomas2024].

### 2.3 Representative papers

| Paper | Year · Venue | DOI / URL | Relevance | Limitation / gap for us |
|---|---|---|---|---|
| *MIND: A Large-scale Dataset for News Recommendation*, Wu et al. [Wu2020MIND] | 2020 · ACL, pp. 3597–3606 | 10.18653/v1/2020.acl-main.331 | Standard interest benchmark (~1M users, 160k articles) | Clicks only; no declared stakes; no need labels |
| *EB-NeRD: A Large-Scale Dataset for News Recommendation*, Kruse et al. [Kruse2024EBNeRD] | 2024 · RecSys Challenge '24 | 10.1145/3687151.3687152 | Recent benchmark with bodies and metadata (Danish) | Same; Danish language |
| *Simplifying Content-Based Neural News Recommendation: On User Modeling and Training Objectives*, Iana, Glavaš, Paulheim [Iana2023Simplifying] | 2023 · SIGIR, pp. 2384–2388 | arXiv:2304.03112 | Late fusion = MAPNAI's `interest.late_fusion` | Interest only |
| *A Survey on Knowledge-Aware News Recommender Systems*, Iana, Alam, Paulheim [Iana2024Survey] | 2024 · Semantic Web 15(1):21–82 | semantic-web-journal.net | Taxonomy of KG-based news recommendation | KG use is for representation and interest, not declared stakes |
| *DKN*, Wang, Zhang, Xie, Guo [Wang2018DKN] · *KRED*, Liu et al. [Liu2020KRED] · *RippleNet*, Wang et al. [Wang2018RippleNet] | 2018 WWW · 2020 RecSys · 2018 CIKM | see bib | Entity and KG-based recommendation; propagation with explainable paths | Seeds come from clicked items; no typed user roles; optimize clicks |
| *Beyond Optimizing for Clicks: Incorporating Editorial Values in News Recommendation*, Lu, Dumitrache, Graus [Lu2020] | 2020 · UMAP, pp. 145–153 | 10.1145/3340631.3394864 | Online study (>1,200 users, ~6 weeks) of editorial values in ranking | Values are newsroom-level, not person-specific need |
| *RADio – Rank-Aware Divergence Metrics to Measure Normative Diversity in News Recommendations*, Vrijenhoek et al. [Vrijenhoek2022] | 2022 · RecSys, pp. 208–219 | arXiv:2209.13520 | Normative metric family for beyond-accuracy evaluation | Measures diversity, not need |
| *Building Human Values into Recommender Systems: An Interdisciplinary Synthesis*, Stray et al. [Stray2024] | 2024 · ACM TORS 2(3):20 | 10.1145/3632297 | Frames well-being and informational needs as recommendation targets | No benchmark |
| *Tracking the Newsworthiness of Public Documents*, Spangher et al. [Spangher2024] | 2024 · ACL | 2024.acl-long.763 | Newsworthiness as a prediction task | City-policy domain; not personalization |
| *NewsHomepages: Homepage Layouts Capture Information Prioritization Decisions*, Welsh, Zhou, Kaz, Vu, Spangher [Welsh2024] | 2024 · arXiv preprint | arXiv:2501.00004 | >3,000 homepages, twice daily over 3 years: a possible ground truth for D8 | Outlet overlap with MAPNAI unknown; general importance ≠ personal need |
| *What News Recommendation Research Did (But Mostly Didn't) Teach Us About Building A News Recommender*, Higley, Burke, Ekstrand, Knijnenburg [Higley2025] | 2025 · BEYOND workshop (arXiv) | arXiv:2509.12361 | **Documents the declared-interest and duty-to-inform gap** | A practitioner report, not an empirical comparison |
| *Bridging Preferences: Multi-Stakeholder Insights on Ideal News Recommendations*, Kolb, Nalis, Neidhardt [Kolb2025] | 2025 · UMAP, pp. 268–272 | 10.1145/3699682.3728355 | Stakeholders (journalists, readers) differ on beyond-accuracy preferences | Full text not read by us |
| *Large Language Models Can Accurately Predict Searcher Preferences*, Thomas, Spielman, Craswell, Mitra [Thomas2024] | 2024 · SIGIR | arXiv:2309.10621 | Method for validated LLM labelling, needed to scale need labels | Search relevance, not need; needs real preferences to validate against |

### 2.4 Datasets, metrics and baselines

- **Datasets:** no public dataset contains declared typed exposures or person-specific need labels. This was found by search, not proven absent. MIND and EB-NeRD cover interest only. NewsHomepages offers outlet-level importance.
- **Metrics:** AUC, MRR and nDCG@5/10 for interest; RADio for normative diversity. A need benchmark would need new metrics: must-know recall@k, miss rate, and need-graded nDCG.
- **Baselines:** NRMS, LSTUR and NAML (e.g. via NewsRecLib); late fusion; materiality/popularity; entity match; an LLM reranker conditioned on a persona card.

### 2.5 Open questions relevant to MAPNAI

1. Can third-party judges label "this person needs to know this" reliably enough (κ) to serve as ground truth?
2. Does *declared, typed* exposure beat *inferred* interest at surfacing needed items, and at what cost to interest?
3. Does propagation over typed relations (supplier, owner) help where co-mention propagation provably cannot (MAPNAI's hop scores ≤ 0.1 < τ)?
4. Is a hand-weighted importance prior (materiality) valid, given that cross-outlet coverage and LLM risk are its main ingredients?

---

## 3. D2 · Online news event clustering

### 3.1 Problem

Assign each arriving article to an existing story/event cluster or start a new one, so that each story is represented once and its size can serve as an importance signal.

### 3.2 Established methods and recent advances

- **Online multilingual stream clustering** with a growing number of clusters [Miranda2018].
- **Entity-aware contextual embeddings + TF-IDF + a Gaussian time feature**, with a learned cluster-assignment classifier [Saravanakumar2021].
- **Unsupervised story discovery** with self-supervised continual embeddings [Yoon2023SCStory] and scalable thematic embedding [Yoon2023USTORY].
- **LLM-enhanced clustering** of GDELT news [Tarekegn2024] (single-author preprint).
- **Article-pair similarity** benchmark, multilingual, with 7 similarity dimensions [Chen2022SemEval].
- **Near-duplicate detection** by SimHash [Charikar2002]. MAPNAI uses it to *drop* duplicates, not to group them.

### 3.3 Verified benchmark results (SOTA claims)

| Benchmark / dataset | Metric | Method | Reported result | Source | Comparable to MAPNAI? |
|---|---|---|---|---|---|
| Miranda et al. news stream, **English** subset (20,959 docs; 222 test clusters) | B³ F1 (P / R) | TF-IDF + entity-aware S-BERT + time [Saravanakumar2021] | **94.76** (94.28 / 95.25); 276 clusters; 94.75 ± 0.59 over 5 runs | [Saravanakumar2021], Table 1 (via ar5iv) | Partly: full-length articles vs MAPNAI's ~200-character synopses; offline batch replay of a stream |
| same | B³ F1 | Staykovski et al. 2019 | 94.41 (P 95.16 / R 93.66) | as reported in [Saravanakumar2021] | same caveat |
| same | B³ F1 | Miranda et al. 2018 | 92.36 (P 94.27 / R 90.25) | as reported in [Saravanakumar2021] | same caveat |
| TDT Pilot (680 test docs, 25 events) | B³ F1 | [Saravanakumar2021] best model | 88.18 (P 81.62 / R 95.89) | [Saravanakumar2021] | Old newswire |
| SemEval-2022 Task 8 (≈10k multilingual pairs) | Pearson correlation with gold similarity | Best submitted system | up to **0.818** (humans reach higher) | [Chen2022SemEval] | Pair-level similarity, not clustering; useful for choosing embeddings |
| MAPNAI `cluster_pairs.jsonl` (63 pairs) | Pairwise P / R / F1 | MAPNAI rules @ cos_join 0.77 | **0.923 / 0.522 / 0.667** | **[ran]** in this audit | Same data the threshold was tuned on: **not a held-out result** |

*Interpretation (ours):* published stream-clustering systems report B³ F1 around 92–95 on the standard English benchmark. MAPNAI has never been evaluated on it, and its pairwise recall of 0.52 on its own (small, non-held-out) set suggests it would trail. SCStory and USTORY report gains over earlier unsupervised methods, but on their own datasets; we did not verify their numbers, so no cross-benchmark "SOTA" claim is made here.

### 3.4 Open questions relevant to MAPNAI

1. How does performance change when the text is a ~200-character RSS synopsis?
2. Is LLM adjudication of borderline pairs worth its cost?
3. Which embedding is the bottleneck (MiniLM vs stronger encoders)?

---

## 4. Novelty gap analysis

Contribution types: **E** = engineering, **A** = application of an existing method, **EE** = empirical evaluation, **EF** = evaluation framework/benchmark, **M** = methodological, **N** = potentially novel algorithmic contribution.

### 4.1 D3: faithfulness under style personalization

1. **What existing research already does.** It detects unsupported content in summaries and grounded generations with NLI, alignment and small-checker models [Laban2022SummaC; Zha2023AlignScore; Tang2024MiniCheck]. It types factual errors in simplification [Devaraj2022], labels omissions in dialogue summaries [Zou2023Omission], studies reader perception of LLM tone rewrites of news [Khatiwada2026CHI], and studies personalization-induced hallucination in QA [Sun2026PersHalluc].
2. **What MAPNAI implements.** Style-conditioned rewriting (2 tones × 2 lengths × 2 jargon levels) with a deterministic fact-retention gate. A failure serves the source text. The same gate family is reused for recap overviews and insight claims (`personalization/{render,factcheck,recap,insights}.py`).
3. **What the proposed approach would change.**
   - Measure error rates per style cell, by error type, across models.
   - Evaluate the gate and learned checkers on the same human-labelled items.
   - Introduce a compression-aware gate: treat omissions of low-salience facts under a length budget differently from additions and distortions, and add a cheap modality/negation check.
4. **What closely related work might already have done.** LLM-AggreFact-style evaluations of checkers. They are not style-stratified and do not target omission (per its listed datasets). Simplification factuality [Devaraj2022] covers a "plain language" style, but with pre-LLM systems and no gate evaluation. [Khatiwada2026CHI] rates faithfulness on 3 articles. **Residual risk:** a 2025–2026 paper on "personalized summarization faithfulness" that our searches missed. A further targeted search (Semantic Scholar, ACL Anthology full-text) is recommended before writing.
5. **Why it could be meaningfully different.** (a) Reader-declared style is a deployment reality in news apps, and its faithfulness cost has not, to our knowledge, been measured factorially. (b) It frames gating as a *serve / fall back* decision with a measured false-rejection cost (the user gets the unpersonalized text), which differs from a pure detection benchmark. (c) It separates omission from distortion under a length budget.
6. **Experiments needed to establish the difference.** A factorial generation (style × model); human annotation with κ; checker comparison with bootstrap CIs; a held-out evaluation of the compression-aware gate showing lower false rejection at equal or lower false acceptance; a cost/latency table.
7. **Results that would undermine it.**
   - Near-zero error rates for strong models in every style cell. Then the paper becomes "gates are unnecessary", still publishable but weaker.
   - An off-the-shelf checker (e.g. MiniCheck) that already separates omissions from distortions with no adaptation.
   - Low annotator agreement on omission salience.
   - Discovery of a prior style-factorial study.

**Contribution type:** **EF + EE**, with a modest **M** (compression-aware gate). **Not N.** Combining a rewriter with a checker is engineering. The research value lies in the measurement and the omission/distortion separation.

### 4.2 D1: need vs interest from declared stakeholder exposures

1. **What existing research already does.** It learns interest from clicks (neural, late fusion) [Wu2019NRMS; Iana2023Simplifying]. It propagates from *clicked* entities over KGs, with path explanations [Wang2018RippleNet; Liu2020KRED]. It advocates editorial and public-interest values and measures normative diversity [Lu2020; Vrijenhoek2022; Stray2024]. It predicts general newsworthiness and prioritization [Spangher2024; Welsh2024].
2. **What MAPNAI implements.**
   - Declared, typed exposures with provenance.
   - Spreading over a co-mention graph (weight 0.1).
   - Hand-weighted materiality.
   - need = m × max π, gated by an adaptive τ into a separate `must_know` section.
   - Faithful why-lines.
   - In practice (audit §4), must_know ≈ "mentions a declared high/medium entity".
3. **What the proposed approach would change.** Create the first (to our knowledge) person-conditioned *need* labels. Compare need-gating with interest and LLM-reranker baselines. Replace co-mention with typed relations. Validate materiality against prioritization data.
4. **What closely related work might already have done.** Entity-based "follow" features and alerting are common in industry products, but are unpublished as research. Portfolio- or KG-based financial news relevance appears in vendor write-ups and preprints (not peer-reviewed; not cited). The POPROX authors report no papers using declared interests [Higley2025]. That is strong but not exhaustive evidence.
5. **Why it could be meaningfully different.** It separates *need* from *interest* as distinct ranking targets with separate labels. It conditions on *declared, typed* stakes rather than inferred interest. Its explanations are tied to the stake ("You own X").
6. **Experiments needed.** Annotation protocol and κ; need-recall@5 and need-nDCG against all baselines; ablations (no propagation / co-mention / typed); a materiality-component ablation; LLM-label validation against the human subset [Thomas2024]; and a check that interest metrics on the remaining slate are not degraded.
7. **Results that would undermine it.**
   - An LLM reranker given the persona card beats need-gating on need-recall. Then the contribution shrinks to the benchmark (**EF**).
   - Need labels collapse into "mentions a declared entity". Then the task is trivial entity matching.
   - Inter-annotator agreement is low. Then there is no reliable ground truth.

**Contribution type:** **EF** (need benchmark) + **M** (need/interest separation as an evaluated ranking design). It is **N** only if typed-relation propagation shows a robust, novel gain. As currently implemented (co-mention spread + hand weights), it is **A/E**: an application of KG propagation and weighted scoring.

### 4.3 D2: event clustering

1. **Existing:** online stream clustering with entity-aware embeddings and time features at about 95 B³ F1 on the standard English benchmark [Saravanakumar2021]; continual story discovery [Yoon2023SCStory; Yoon2023USTORY]; LLM-assisted event clustering [Tarekegn2024].
2. **MAPNAI:** a single-pass cosine threshold with entity, time and title evidence gates and an anti-chaining guard; 63 labelled pairs.
3. **Change:** a benchmark evaluation, a stronger embedder, LLM adjudication of borderline pairs, and a held-out MAPNAI pair set.
4. **Close prior work:** entity and time features [Saravanakumar2021]; evidence gating is a variant.
5. **Possible difference:** behaviour on very short synopses, and the cost-aware LLM adjudication band.
6. **Experiments:** B³ on [Miranda2018] English; pairwise P/R with CIs on ≥ 500 held-out MAPNAI pairs; cost per 1,000 articles.
7. **Undermining results:** if MAPNAI's rules trail published systems and LLM adjudication adds little, the contribution reduces to engineering guidance.

**Contribution type:** **EE** (+ **A**). Useful engineering; **insufficient novelty for a standalone main-track paper**.

### 4.4 Short notes on the other directions

- **D4 (offline recommendation):** late fusion is already published [Iana2023Simplifying]. MAPNAI's composite scorer would be an **A** with **EE**. Reported MIND-large numbers for strong systems come from secondary sources only; for example, an ensemble leaderboard entry was reported at AUC 72.68 / nDCG@10 41.51, and NRMS at around AUC 67–69. **We could not retrieve the official leaderboard**, so these must be re-verified before any comparison.
- **D5 (insights):** related to multi-document hallucination [Belem2025MultiDoc] and self-critiquing RAG [Asai2024SelfRAG]. Potentially **EE + M**, but it needs months of data.
- **D6 (agentic RAG):** mirrors Self-RAG, CRAG, Adaptive-RAG and credibility-aware generation [Asai2024SelfRAG; Yan2024CRAG; Jeong2024AdaptiveRAG; Pan2024CAG]. **E**: not a research contribution on its own.
- **D7 (τ / exploration):** bandit news recommendation and unbiased replay evaluation are classic [Li2010; Li2011; Chapelle2011]. Without traffic it is not testable. **E**.

### 4.5 Verified checker results for D3 (LLM-AggreFact leaderboard)

Source: the official leaderboard page `llm-aggrefact.github.io`, retrieved 2026-10-23. The page shows no update date and lists 14 of 42 models by default. The column is labelled "Average"; the paper describes balanced accuracy.

| Model | Size | Average |
|---|---|---|
| nimble-v4-max | 27B | 79.5 |
| Bespoke-MiniCheck-7B | 7B | 77.4 |
| Claude-3.5 Sonnet | – | 77.2 |
| gpt-4o-2024-05-13 | – | 75.9 |
| FactCG-DeBERTa-L | 0.4B | 75.6 |
| MiniCheck-Flan-T5-L | 0.8B | 75.0 |

*Comparability:* LLM-AggreFact covers summarization and grounded QA/claim datasets (CNN, XSum, MediaSum, MeetingBank, WiCE, REVEAL, ClaimVerify, FactCheck, ExpertQA, LFQA, RAGTruth). It contains no reader-style rewrites, and it targets unsupported content rather than omissions. These numbers tell us which checkers are strong in general, **not** how they behave on MAPNAI's rewrites. AlignScore was not in the default view. SummaC's own benchmark reports 74.4% balanced accuracy for SummaCConv [Laban2022SummaC].

---

## 5. The most promising research gap

**A measured account of what reader-style personalization does to the faithfulness of LLM-rewritten news, and of whether the cheap gates that production systems use can tell harmful distortions from acceptable compression.**

The evidence for this gap:

- Faithfulness checkers are mature but benchmarked without a style axis, and largely without omissions [Tang2024MiniCheck; Laban2022SummaC].
- Simplification is known to introduce errors, but that evidence predates current LLMs and covers one style [Devaraj2022].
- The closest news-rewriting study measures reader perception, not error rates [Khatiwada2026CHI].
- MAPNAI's own cache already shows both gate failure modes: omission-driven rejections and modality changes that pass (audit §6.1, n = 12).

The **largest but riskier gap** is the declared-stake need target (D1). It is documented by practitioners [Higley2025] and normatively motivated [Lu2020; Stray2024], but it has no benchmark yet. Building that benchmark is a multi-month undertaking.

**No publication or acceptance is implied by this review.** The novelty statements above are bounded by the searches run on 2026-10-23.
