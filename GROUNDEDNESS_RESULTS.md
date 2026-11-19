# MAPNAI: Groundedness and Evaluation Results

**What this is:** the measured values for every check in `GROUNDEDNESS_CHECKS.md`. Each number comes from either a live read-only run on the current database or an earlier research experiment in `research/`. Each row names its source.

**Data snapshot (live checks):** 19 Nov 2026. Local MongoDB (2,506 articles, 1,015 in scope) and local Neo4j (2,506 articles, 14,180 entities). The scripts only read from the databases and wrote nothing back.

**Updated 19 Nov 2026 after pulling commits `c5baf38`–`5dcb1b5`** (offline Agent 4 risk scorer; continuous stream, hotness and push). All live scripts were re-run, and the database numbers were unchanged because no pipeline run happened in between. New in this update:
- §2.6, Agent 4: rewritten for the offline scorer, now the default.
- §2.13: stream, hotness and push benchmarks.
- Test suite: **934 / 934 pass**.

**Notation:** `k/n = rate [95% CI]`. Intervals are Wilson score intervals unless marked "bootstrap". **T1–T7** are the tools defined in `GROUNDEDNESS_CHECKS.md` §1 (T1 rule fact gate, T2 learned NLI checker, T4 verbatim check, T7 human labels, and so on).

---

## 1. Summary at a glance (slide-ready)

| # | Piece | Main check | Result | Verdict |
|---|---|---|---|---|
| 2.1 | Ingestion | Stored-copy duplicates; date fallback; image coverage | 0 duplicate hashes; 0 / 1,557 dates fell back to ingestion time; 88.4% of articles have an image | ✅ Clean |
| 2.2 | Agent 1 · NER | Entity appears verbatim in the article (T4) | **96.8%** [96.6, 97.1] of 17,585 entities | ✅ Grounded |
| 2.3 | Agent 2 · Classifier | Agreement with the source feed's domain (silver label) | **93.0%** [91.3, 94.4] on 1,048 sports and movie feed articles | ✅ Good (silver label) |
| 2.4 | Knowledge graph | Co-occurrence edge traceable to an article's text | **98.8%** of 13,366 edges by text; 71.1% by the article's current entity list | 🟡 Text-grounded; metadata drift |
| 2.5 | Agent 3 · Summaries | LLM (primary) adds no facts (T1); extractive fallback verbatim (T4) | LLM: **70.6%** pass T1 (194 summaries). Extractive fallback: **100%** verbatim (918 articles; fallback fired on 81.7% of logged runs, all Groq rate limits) | 🟡 Primary LLM path is the weak spot |
| 2.6 | Agent 4 · Risk (offline model, default) | Event type vs hand-labelled gold (T7); live coverage; recommendation grounded | Gold: **83.5%** accuracy [74.9, 89.6], macro-F1 **0.80** [0.71, 0.88], high-severity recall **97.1%** (n = 97). Live: 1,015 / 1,015 scored, 100% format-valid and deterministic, 0 recommendations with an outside name | ✅ Event model validated · 🟡 score weights not validated on live articles |
| 2.7 | Agent 5 · Ask (RAG) | Retrieval index covers the corpus | 62.1% of live articles indexed; 4,352 stale rows | 🟡 Index needs a rebuild |
| 2.8 | Style rewrites (personalized summaries) | Gate against human labels (240 items, 2 annotators) | False-rejection rate 37.6%, false-acceptance rate 33.0% | 🟡 Gate catches lexical errors, not semantic ones |
| 2.9 | Recap overview | Full T1 on the generated overview | 2 / 2 generated overviews pass | ✅ (n is tiny) |
| 2.10 | Insights | Surviving claims re-checked with T1 | 7 / 7 pass; all 6 cached analyses are rate-limit fallbacks | ⚪ Not enough data |
| 2.11 | Why lines and alerts | Arithmetic and entity correct | 35 / 35 formulas correct; 38 / 38 entities in the article; 2 / 2 alerts | ✅ Grounded by construction |
| 2.12 | Mobile app | Labels match backend; no mock data in release | Label map correct; default mode is `mock` unless an environment variable is set | 🟡 Configuration risk |
| 2.13 | Stream · hotness · push | Dedup speed; fetch delay; breaking-story replay | Banded dedup **8,646×** faster than the linear scan at 100k stored; adaptive polling: median delay 5.4 min vs 7.3 min (15-min fixed) with 5% fewer requests; hotness replay: no tiers yet (worker not run on this DB) | 🟡 Benchmarks good; live behaviour not measured |

**Learned checker (T2) validated:** MiniCheck-Flan-T5-L reproduces its published LLM-AggreFact score, **75.02** [73.96, 76.09] vs 75.0 published (research S1).

**Human labels (T7):** two annotators, 240 test items, Cohen's κ(faithful) **0.557** [0.427, 0.680], moderate agreement. 60 disagreements were adjudicated jointly.

---

## 2. Results per piece

### 2.1 Ingestion (fetchers, preprocessing, dedup, images)

| Check | Result | Source |
|---|---|---|
| Articles stored | 2,506 (RSS 2,385, GNews 121) | live |
| Dedup removal rate at ingestion | 1,643 of 4,149 fetched removed (**39.6%**) over 3 runs | live `ingestion_runs` |
| Duplicate `dedup_hash` left in the store | **0** | live |
| Duplicate URL left in the store | 13 (0.5%) | live |
| Duplicate exact title left in the store | 3 | live |
| `published_at` present | 2,506 / 2,506 = **100%** | live |
| Date fell back to ingestion time (`date_source` ≠ published) | **0 / 1,557 = 0.0%** [0.0, 0.25] (949 older articles predate the field) | live |
| Article has a primary image | 2,214 / 2,506 = **88.4%** [87.0, 89.6] | live |
| Image comes from the Wikipedia entity fallback | 61 (2.4%) | live |
| Body under 20 words (feed snippet only) | 373 / 2,506 = 14.9% | live |
| Body identical to the title | 21 / 2,506 = 0.8% | live |
| Body and title match the live web page (re-fetch, T4) | **Not measured.** Needs 50 URL re-fetches. | — |
| Dedup false-merge rate; fallback image correct | **Not measured.** Needs human labels (T7). | — |

**Reading:** the store holds no duplicate hashes and no date fallbacks, so the stored metadata is clean. One limit affects everything downstream: the median body is only **32 words**, because many feeds give a snippet rather than the full text. Short bodies give the LLM agents little source text to stay grounded in (see §2.5).

### 2.2 Agent 1: NER (fine-tuned BERT)

| Check | Result | Source |
|---|---|---|
| Articles processed | 1,976 / 2,506 (78.9%); BERT 1,942, enrichment fallback 34 | live |
| Entities | 17,585 (median 5 per article, mean 8.9) | live |
| **Entity found verbatim in title or body (T4, word boundary)** | **17,027 / 17,585 = 96.8%** [96.6, 97.1] | live |
| …case-insensitive | 97.0% [96.8, 97.3] | live |
| By type: Person | 98.2% (5,738) | live |
| By type: Organization | 98.2% (4,210) | live |
| By type: Location | 97.2% (2,884) | live |
| By type: Product (BERT's MISC label) | **93.8%** (4,751) | live |
| MISC entities labelled "Product" | 5,192 in the full store; top: "Indian", "Office", "Premier League", "Formula 1" (nationalities and events, not products) | research F6 (L0051) |
| Type precision; recall | **Not measured.** Needs span labels (T7). | — |

**Reading:** NER is grounded: about 97 of every 100 entities appear in the text word for word. The 3% that don't are mostly sub-word merges and normalizations. The type labels are less reliable: "Product" is a catch-all for BERT's MISC class, so type-level claims should not be made.

### 2.3 Agent 2: Classifier (DistilRoBERTa, multi-task)

| Check | Result | Source |
|---|---|---|
| Classified | 1,976; in scope 1,015 (51.4%) | live |
| Out-of-scope reasons | off-topic 956, low confidence 5 | live |
| Confidence | median 0.990; 89.1% ≥ 0.9; 0.5% < 0.5 (the in-scope threshold) | live |
| **Agreement with the source feed's domain** (silver) | **975 / 1,048 = 93.0%** [91.3, 94.4] | live (re-run of E03; 93.9% on the 23 Oct snapshot) |
| …sports feeds | 579 / 621 = 93.2% | live |
| …movie feeds | 396 / 427 = 92.7% | live |
| Off-topic feed articles labelled in scope (leakage) | 30 / 848 = **3.5%** [2.5, 5.0] | live |
| Calibration (silver agreement by confidence band) | <0.5: 37.5% (n=8) · 0.5–0.7: 69.2% · 0.7–0.9: 80.6% · 0.9–0.97: 95.7% · ≥0.97: 97.4% | live |
| Confusion (feed → prediction) | sports feeds: 579 sports, 29 other, 13 movies · movie feeds: 396 movies, 29 other, 2 sports | live |
| Accuracy / macro-F1 on a gold set | **Not available.** The training notebook's outputs were not saved and no gold file exists. | — |

**Reading:** agreement rises steadily with confidence, so the confidence score is meaningful and the 0.5 threshold sits where accuracy collapses. Caveat: feed domain is a *weak* label, since a movie feed also carries TV and music news. Present this as a proxy, not as accuracy.

### 2.4 Knowledge graph (Neo4j)

| Check | Result | Source |
|---|---|---|
| Articles in Neo4j vs MongoDB | 2,506 vs 2,506, all matched | live |
| Graph size | 14,180 entities · 11,766 MENTIONS · 13,366 MENTIONED_WITH | live |
| **MENTIONED_WITH edge: both entity names occur in a cited article's text** | **13,204 / 13,366 = 98.8%** [98.6, 99.0] | live |
| …in the article's text or its current entity list | 99.4% | live |
| …all cited articles' current entity lists contain both ends | 9,506 / 13,366 = 71.1% [70.4, 71.9] | live |
| MENTIONS edge entity in the article's current entity list | 9,539 / 11,766 = 81.1% | live |
| Edge `count` equals its number of article IDs | 100% | live |
| Edges citing an article missing from MongoDB | 0 | live |
| **Entity `frequency` vs a MongoDB recount** | exact for 54.2%; **overcounted for 45.8%**; mean ratio 1.61 (p90 2.5) | live |

**Reading:** every edge is real: 98.8% of co-occurrences can be traced to an article that names both entities. The 71% figure is lower because Agent 1 later replaces the entity list that the ingestion writer used to build the edges. The edges are grounded, but the stored metadata has drifted from them. `frequency` is overcounted for almost half the entities, which confirms the double-count noted in `STREAMLINING_PROPOSALS.md` §3: Agent 1 and the ingestion writer both increment it. Any feature that ranks by `frequency` is inflated.

### 2.5 Agent 3: Summaries (the plan's "biggest gap")

**Which path is primary:** with `SUMMARIZER_BACKEND=auto` (the default; `.env` doesn't override it), Agent 3 calls the **Groq LLM first**. It falls back to the **extractive** summarizer (verbatim body sentences) when there is no LLM client, the API call fails, or the reply is not valid JSON with both summaries (`agents/agent3_summarizer.py`, `_call_llm_summarization`). Setting `SUMMARIZER_BACKEND=extractive` uses the extractive path only.

**How often the fallback fires:** `logs/ingestion.log` records 530 Agent 3 runs. **433 fell back (81.7%)**, every one after a Groq **429 rate-limit** error; 97 got an LLM summary. So most stored summaries are extractive because the primary path was rate-limited, not because extractive was the design choice.

| Path | In-scope articles | Share |
|---|---|---|
| Extractive **fallback** (verbatim body sentences) | 918 | 90.4% [88.5, 92.1] |
| LLM **primary** (abstractive; all generated 17–18 Nov 2026) | 97 | 9.6% [7.9, 11.5] |

| Check | Result | Source |
|---|---|---|
| In-scope articles with summaries | 1,015 / 1,015 = 100% | live |
| **Extractive: every sentence verbatim in the body (T4)** | 918 / 918 articles, **100%** | live |
| Extractive: T1 (no added numbers, months or names) | 1,835 / 1,836 = **99.9%** | live |
| **LLM: T1 passes** (summary vs title + body) | **137 / 194 = 70.6%** [63.9, 76.6] | live |
| …LLM `summary_short` | 89 / 97 = 91.8% [84.6, 95.8] | live |
| …LLM `summary_long` | **48 / 97 = 49.5%** [39.7, 59.3] | live |
| What T1 flagged in LLM summaries | added names 73, added numbers 12 (e.g. "Bollywood", "US", "UK", "Tollywood", figures absent from the body) | live |
| LLM `summary_long` **longer than its source body** | **45 / 97 = 46.4%** [36.8, 56.3] | live |
| Content words not found in title or body | LLM: median **36.9%** (IQR 25.5–56.6%) vs 4.4% mean over all in-scope summaries | live |
| LLM summaries with more than 20% novel content words | 88 / 97 (90.7%) | live |
| All summaries combined: T1 pass | 1,972 / 2,030 = **97.1%** [96.3, 97.8] | live |
| `summary_short` identical to `summary_long` | 598 / 1,015 = 58.9% (bodies of 3 sentences or fewer return the whole body: research F9) | live; research L0063 |
| Short summaries over 50 words | 45.3% | live |
| Production path on 24 Oct (earlier snapshot) | 1,819 / 1,843 summaries equal to the extractive output, so the LLM path was effectively unused then | research E09 (L0062) |
| Meaning-level support (T2) of LLM summaries | **Not run.** The checker checkpoints are not on this machine. | — |

**Reading (key finding):**
- The extractive fallback is grounded by construction, and the measurements confirm it.
- The **primary LLM path is not**. Half of the long LLM summaries add a name or number that isn't in the article, and almost half are *longer than the article body they summarize*. When the source is a 1–2 sentence feed snippet, the model elaborates. Example: a one-sentence IndieWire teaser became a paragraph about AI in filmmaking.
- Part of the cause is the prompt itself. It asks for a **5–8 sentence** `summary_long` whatever the body length, so a one-sentence body can only be "summarized" by adding material. The "Do not invent facts" rule in the same prompt can't hold.
- **Recommendation:**
  - Use the extractive path when the body is short, for example under 4 sentences.
  - Cap the summary length relative to the body.
  - Gate LLM output with T1 and fall back to extractive on failure, the way `render.py` already does.
- **Caution:** the LLM also receives `similar_articles`, so some "novel" content may come from a related story. These figures are measured against the article's own body, which is the strict reading.

### 2.6 Agent 4: Risk / priority scorer

**What changed:** the default is now `RISK_BACKEND=model`, an **offline** scorer with no LLM calls (`agents/risk_model.py`). A DistilRoBERTa model classifies the event type into one of 8 classes. If it is missing, TF-IDF + logistic regression takes over, and keyword rules are the last resort. A keyword "severity guard" can raise the event type to a more severe one when the model gives that type at least 0.20 probability. Three formula factors (salience, urgency, domain) complete the 0–100 score. The 247 scores stored in MongoDB were produced earlier by the LLM backends; they are reported in (c) below.

**(a) Event classifier on the hand-labelled gold set** (`data/risk/gold_key.csv`, 97 articles held out from training; Wilson CI for accuracy, 2,000-resample bootstrap for macro-F1):

| Tier | Accuracy | Macro-F1 | High-severity recall (legal and above) | Severity MAE (0–25) |
|---|---|---|---|---|
| **DistilRoBERTa + guard (production path)** | **83.5%** [74.9, 89.6] | **0.799** [0.712, 0.875] | **68 / 70 = 97.1%** | **1.06** |
| DistilRoBERTa alone | 81.4% [72.6, 87.9] | 0.781 [0.688, 0.858] | 66 / 70 = 94.3% | 1.46 |
| TF-IDF + LR + guard (fallback) | 80.4% [71.4, 87.1] | 0.794 [0.695, 0.866] | 63 / 70 = 90.0% | 1.79 |
| TF-IDF + LR alone | 72.2% [62.5, 80.1] | 0.703 [0.594, 0.788] | 59 / 70 = 84.3% | 2.75 |
| Keyword rules (last resort) | 78.4% [69.2, 85.4] | 0.740 [0.641, 0.824] | 69 / 70 = 98.6% | 1.57 |

Per-class F1 (production path): death_tragedy 0.97 · cancellation 0.96 · injury 0.96 · integrity 0.83 · ban_suspension 0.80 · legal 0.76 · routine 0.73 · **controversy 0.40** (the weak class).

TF-IDF cross-validation on the LLM training labels (5,054 rows): accuracy 83.1%, macro-F1 0.733.

Source: `research/groundedness/agent4_gold_eval.py` → `agent4_gold_eval.json`.

**Caveats for (a):**
- **This doesn't match `AGENT4_RISK_ARCHITECTURE.md` §8** (73.3% / 0.677 on 86 "in-scope" items, measured on Kaggle). This run scores all 97 rows of `gold_key.csv`, because the key has no in-scope column, and it includes the keyword guard that production applies. Use one definition consistently in the report.
- **The gold set is stratified toward rare severe events** (70 of 97 are legal or worse; only 8 are routine). So the accuracy figure isn't the live-feed accuracy, and high-severity recall is the meaningful headline.
- **The gold articles come from public datasets** (AG News, BBC, HuffPost), not from MAPNAI's own feeds.
- **The keyword rules score close to the models.** If the rules were written with the gold set in view, their score is optimistic. That can't be checked from the repo.

**(b) Offline scorer on the live in-scope articles** (read-only re-score; nothing written back):

| Check | Result | Source |
|---|---|---|
| Coverage | **1,015 / 1,015 = 100%** (vs 24.3% for the LLM backends); all on the DistilRoBERTa tier | live |
| Event type | routine 849 (83.6%) · controversy 54 · injury 37 · death_tragedy 31 · legal 19 · ban_suspension 15 · cancellation 7 · integrity 3 | live |
| Risk level | MONITOR 879 · ALERT 134 (13.2%) · ESCALATE 2 | live |
| Risk score | median 27, mean 30.0, range 18–73 | live |
| Format: 4 factors in 0–25 that sum to `risk_score` | 1,015 / 1,015 = **100%** | live |
| Re-score gives identical output (T6) | 1,015 / 1,015 = **100%** (deterministic by construction) | live |
| Recommendation names a capitalised word or number not in the title or body | **0 / 1,015** | live |
| **Paired vs the stored LLM score (same 247 articles)** | Spearman ρ = **0.08**; level agreement 210 / 247 = 85.0% (mostly both MONITOR); mean 28.9 vs 17.4; ALERT 26 vs 17 | live |
| Agreement of score or level with human judgement on live articles | **Not measured.** Needs T7 labels. | — |

Source: `research/groundedness/agent4_live_offline.py` → `agent4_live_offline.json`.

**Reading:**
- **Event type is now validated against human labels.** On the hand-labelled gold set the production path finds 97% of serious events.
- **The text is grounded by construction:** the recommendation is a template filled from the article, and none of the 1,015 adds an outside name.
- **The final score is not yet validated.** The factor weights are "starting values" (architecture doc §5), and they have never been tuned against analyst triage of live articles.
- **The new and old backends disagree.** Offline and LLM scores barely correlate (ρ ≈ 0.08) on the same articles, so switching backends changes the ranking. This is now a paired comparison, unlike the old Groq-vs-Ollama one.
- **Not every 18+ score means something happened.** The minimum score is 18 because domain and urgency give every article a base value; on routine articles the score mostly reflects salience and recency.

**(c) Stored scores from the earlier LLM backends** (`auto` / `groq` / `ollama`; no longer the default):

| Check | Result | Source |
|---|---|---|
| In-scope coverage | 247 / 1,015 = **24.3%** [21.8, 27.1] | live |
| Model | unrecorded 139 · Groq gpt-oss-120b 76 · Ollama `mapnai-risk` 32 | live |
| Risk level | MONITOR 230 · ALERT 17 (6.9%) | live |
| Risk score (0–100) | median 14, mean 17.4, range 0–55 | live |
| Format: 4 sub-scores in 0–25 that sum to `risk_score` | 247 / 247 = **100%** | live |
| **`action_recommendation` adds no facts (T1 vs title + body)** | **245 / 247 = 99.2%** [97.1, 99.8] | live |
| …the 2 flags | "Arsenal-related", "PR": both benign (false positives of the name rule) | live |
| Entity-salience sub-score vs Agent 1's max salience | Spearman ρ = **−0.18** (n = 245) | live |
| Temporal-urgency sub-score vs Agent 2's `urgency_flag` | flagged mean 12.0 (n = 4) vs not flagged 2.3 (n = 243) | live |
| Groq vs Ollama score (different articles, unpaired) | mean 13.2 vs **32.2**; ALERT share 0% vs **46.9%** | live |
| Re-score stability (SD, level flips); paired Groq vs Ollama | **Not run.** Needs 3–5 LLM re-scores per article. | — |
| Agreement with human judgement | **Not measured.** Needs T7 labels. | — |

**Reading (LLM backends):**
- The recommendation text is grounded: it almost never brings in an outside fact.
- The *scores* are a different matter:
  - The salience sub-score does not follow Agent 1's evidence (ρ ≈ −0.18).
  - The two back-ends score very differently.
- These comparisons are unpaired (different articles), so they do not prove the back-ends disagree, but they show that a paired stability test (T6) is the next experiment.
- Coverage is low: most in-scope articles have never been risk-scored, so materiality falls back to "unscored" (research F10).

### 2.7 Agent 5: Ask (RAG)

| Check | Result | Source |
|---|---|---|
| Live articles in the Agent 5 FAISS index | 1,557 / 2,506 = **62.1%** [60.2, 64.0] | live |
| In-scope articles indexed | 530 / 1,015 = 52.2% | live |
| Stale index rows (article no longer in MongoDB) | **4,352** of 5,909 rows | live |
| Rebuilt index (research F7, not deployed) | 100% coverage, 0 stale; pinned MiniLM reproduces production vectors (cosine 1.000 on 2,719 articles) | research L0059–L0060 |
| Graph-path answer check (`_check_answer`) | Exists in code; **not measured** | — |
| Answer support rate, citation precision and coverage, retrieval hit@5, honest-refusal rate | **Not measured.** Needs a fixed set of 50–100 questions with labels. | — |
| Response format | Pinned by `tests/data/agent5_response_golden.json`; passed in the 24 Oct research test run (793 / 0) | research L0061 |

**Reading:** before answer grounding can be measured, the retrieval index has to cover the corpus. Today about half the in-scope articles cannot be retrieved at all. The rebuilt index from research F7 fixes this and is ready to switch in.

### 2.8 Personalization: style rewrites (`render.py`)

This is the "summarizer" work in `research/`: the LLM rewrites an article summary into the reader's style (tone × length × jargon), and the T1 gate decides whether to serve the rewrite or fall back to the source.

**(a) Gate sensitivity on synthetic edits** (E02, 29,067 gate calls on 1,843 articles):

| Edit type | Gate catches it |
|---|---|
| Number added | **100.0%** [99.9, 100] |
| Entity substituted | **100.0%** [99.8, 100] |
| Number changed | 97.6% [96.9, 98.2] |
| Month changed | 89.7% [85.9, 92.6] |
| Entity roles swapped | **0.1%** |
| Negation inserted | **0.2%** |
| Hedge removed | **0.0%** |
| Outcome flipped | **0.6%** |

| Summary | Value |
|---|---|
| Lexical errors caught (macro) | **96.8%** |
| Semantic errors caught (macro) | **0.2%** |
| Latency per check | mean 0.98 ms, p95 3.4 ms (CPU) |

**(b) Real rewrites** (E11/E14, 1,919 rewrites by gpt-oss-120b over 8 style cells, 480 articles):

| Check | Result |
|---|---|
| Serve rate, gate v1 | **55.9%** [53.6, 58.1] (short 52.5%, medium 59.3%) |
| Serve rate, gate v2 (normalized names) | 59.7% |
| Fallback reasons (v1) | missing entity 795, missing number 237, added number 21, month 6 |
| Length compliance | short 945 / 954, medium 946 / 953 (99.1%) |
| Gate determinism | 0 nondeterministic decisions |

**(c) Gate vs human labels** (S4: 240 test items, two annotators, adjudicated: 182 faithful / 58 unfaithful; 2,000 bootstrap resamples over articles):

| Metric | Gate v1 (production) | CAFG (research cascade) |
|---|---|---|
| False-rejection rate (faithful rewrite refused) | **37.6%** [30.4, 45.4] | 32.6% [25.3, 39.9] |
| False-acceptance rate (unfaithful rewrite served) | **33.0%** [18.5, 46.9] | 44.7% [30.0, 58.3] |
| FAR on semantic errors (47 items) | 30.4% | 39.0% |
| Serve rate | 55.8% | 62.3% |
| Pre-registered target (FRR −10 points with no FAR loss) | — | **Not met** (−5.0 points [−1.3, +11.8]) |

| Label quality | Value |
|---|---|
| Pilot κ(faithful), 80 shared items | 0.576 [0.359, 0.754], raw agreement 83.8% |
| Main κ(faithful), 240 items | 0.557 [0.427, 0.680] |
| Error-type κ (pilot) | addition 0.737 · distortion 0.692 · omission 0.669 |

The S4 sample was stratified by gate decision (30 accepted + 30 rejected per cell), so 58/240 is *not* the generator's population error rate.

**(d) Live** (`render_cache`, 6 items): 5 / 6 served; a re-run of the gate reproduces all 6 stored decisions.

**Reading:** the gate is a strong, sub-millisecond filter for lexical errors (numbers, names, months). It is blind to meaning-level errors (role swaps, negation, hedges). Against human labels it refuses about 38% of faithful rewrites and serves about 33% of unfaithful ones. The research cascade that adds a learned checker (CAFG) lowered false rejections but raised false acceptances, and missed its pre-registered target. This is reported as a negative result.

### 2.9 Recap overview

| Check | Result | Source |
|---|---|---|
| Recaps stored | 4 (1 weekly, 3 daily) | live |
| Overview generated | 2 / 4; 2 failed with a Groq `RateLimitError` (no overview shown) | live |
| In-app check (`overview_check`: numbers only) | 2 / 2 pass | live |
| **Full T1** (numbers + months + new names), as `check_claim` does | **2 / 2 pass**, so tightening would have rejected none | live |

**Reading:** the stricter check would not have rejected either generated overview. With n = 2 this is a smoke test, not a rate.

### 2.10 Insights

| Check | Result | Source |
|---|---|---|
| Cached analyses | 6, all status `fallback` (reason: `llm_error: RateLimitError`) | live |
| Claims dropped by the fact check | 0 (no LLM analysis reached the check) | live |
| Fallback claims re-checked with T1 against their cited articles | 7 / 7 pass | live |

**Reading:** no LLM-generated insight exists in the current store, so the ok / partial / fallback split and the dropped-claim rate can't be reported yet. Rate limits blocked every attempt. The fallback content is copied from article summaries and passes T1.

### 2.11 Why lines, profile text, alerts (`explain.py`, `alerts.py`)

| Check | Result | Source |
|---|---|---|
| Why-line arithmetic ("Need = materiality × exposure", and printed values equal stored values) | **35 / 35 = 100%** [90.1, 100] | live `digests` |
| Entity named in the why line is in that article's entities | **38 / 38 = 100%** [90.8, 100] | live |
| Alert entity appears in the story | 2 / 2 | live |
| Alert arithmetic | 2 / 2 | live |

**Reading:** these lines are templates filled from computed values, and every one checked is correct.

### 2.12 Mobile app

| Check | Result | Source |
|---|---|---|
| Impact label ↔ backend `risk_level` | `ESCALATE` → "Major", `ALERT` → "High impact", otherwise "Routine"; unscored → "Impact not scored yet" (`story/[id].tsx:181`) | code review |
| Mock data in release builds | `API_MODE` **defaults to `mock`** when `EXPO_PUBLIC_API_MODE` is unset (`src/api/client.ts:7-10`). `.env.local` sets `hybrid`. A release build must set `live` explicitly. | code review |
| Each claim links to its cited article | **Not tested** (needs a UI test) | — |

### 2.13 Continuous stream, hotness and push (new)

Added in commit `c5baf38`: `stream_worker.py`, `stream/polling.py`, the banded SimHash index in `utils/deduplicator.py`, `personalization/hotness.py`, `personalization/push.py` and `agents/social_signal.py`. These pieces don't generate text, so the measurements are about speed, timeliness and correctness.

| Check | Result | Source |
|---|---|---|
| Unit tests for stream, dedup, polling, hotness, push, breaking alerts and social signal (11 new test files) | All pass, part of **934 / 934** | `pytest` |
| Duplicate lookup, linear SimHash scan vs banded index (ms per article) | 1k stored: 0.866 vs 0.0020 (435×) · 10k: 8.35 vs 0.0026 (3,267×) · **100k: 92.3 vs 0.0107 (8,646×)** | `scripts/stream_benchmark.py dedup` |
| Banded index finds the same near-duplicates as the linear scan | Covered by `tests/test_stream_dedup.py` (passes); not measured on live data | tests |
| Polling, simulated day (70 feeds, 2,647 items) | Every 15 min: 6,790 requests, median delay 7.3 min (p90 13.5) · every 30 min: 3,430 requests, 14.6 min (p90 26.7) · **adaptive: 6,443 requests, 5.4 min (p90 14.2)** | `scripts/stream_benchmark.py polling` |
| Hotness replay, last 7 days (1,343 stories, 15-min steps) | **No story reached trending or breaking.** The stream worker has not run on this database, so there are no sightings or front-page signals to score. | `scripts/replay_hotness.py --days 7` |
| Precision of "breaking"; push text names an entity in the story | **Not measured.** Needs the worker to run for a few days, then T7 labels on the flagged stories. | — |

**Reading:**
- **Adaptive polling is faster and slightly cheaper than a fixed schedule.** Against a fixed 15-minute schedule it cuts the median fetch delay by about 26% (7.3 → 5.4 min) and makes 5% fewer requests.
- **The banded dedup index makes duplicate lookup effectively constant-time.** That matters for a continuous stream.
- **These results come from simulations and unit tests.** The live hotness and breaking-alert behaviour can't be judged until the worker has collected data.

---

## 3. Learned checker and benchmark results (research)

| Experiment | Result |
|---|---|
| **S1:** MiniCheck-Flan-T5-L on LLM-AggreFact test (29,320 claims, 11 datasets) | Avg BAcc **75.02** [73.96, 76.09] vs 75.0 published (gap +0.02); every dataset within ±0.22. News-3 72.60. Kaggle T4 vs local GPU: 0 prediction flips on 2,560 shared rows. |
| **S2:** MAPNAI gate v1 on LLM-AggreFact | As-is 50.45 BAcc (chance: it demands every source fact in a one-sentence claim); additions-only 55.24 |
| **S3:** CAFG cascade vs checker alone on AggreFact | News-3 70.21 vs 72.60 (−2.39 [−3.74, −1.00]); checker call rate 75% (target ≤ 50%), so **fail**. It beats random routing at the same call rate (68.32). |
| **E01:** event clustering rule (63 labelled pairs) | In-sample P 0.923, R 0.522, F1 0.667; leave-one-out F1 0.400. Cosine AUROC 0.714. |

## 4. LLM scoring vs humans (research2, MIND news values)

This is a separate study, but it is the closest evidence on whether an LLM's 1–5 news scores track human judgement, which is the question behind Agent 4's scores. Qwen2.5-7B scored 22,771 articles (100% parsed); two humans labelled 99.

| News value | Human κ (quadratic) | LLM vs human ρ |
|---|---|---|
| Conflict | 0.81 | 0.73 |
| Utility | 0.73 | 0.78 |
| Prominence | 0.68 | 0.74 |
| Importance | 0.68 | 0.66 |
| Magnitude | 0.67 | 0.46 |
| Surprise | 0.61 | 0.54 |
| Entertainment | **0.20** (fails the gate) | 0.71 |

6 of 7 values pass the validity gate (κ ≥ 0.4 and ρ ≥ 0.4). None predicts clicks strongly (AUC 0.43–0.54).

---

## 5. Not measured yet, and what each needs

| Metric | Blocker | Effort |
|---|---|---|
| T2 (MiniCheck) on the 194 LLM summaries | Checker checkpoints (~3 GB) not on this machine; CPU-only torch here | ~1 hour on Kaggle or Colab |
| Agent 4 score and level vs human judgement on **live** articles; factor-weight tuning | T7 labels (MONITOR / ALERT / ESCALATE) on about 50 live articles. Stability is no longer needed for the default backend, which is deterministic. | 1 day |
| Agent 4 LLM-backend stability (score SD, level flips, paired Groq vs Ollama) | Only if the LLM backends stay in use: 3–5 re-scores × 50 articles (~250 calls) | Half a day |
| Hotness tiers, breaking-alert precision and lead time; push text | Run `stream_worker.py` for a few days, then replay and label the flagged stories | Several days of running + 1 day of labels |
| Agent 5 answer support, citation precision, hit@5 | 50–100 fixed questions with labels | 2–3 days |
| NER type precision and recall; classifier gold accuracy and F1 | Human labels on 50–300 items | 1–3 days each |
| Ingestion re-fetch match; dedup false merges; image correctness | 50-item samples, re-fetch plus labels | 1 day |
| Insights dropped-claim rate | LLM analyses that are not rate-limited | Re-run when quota allows |

## 6. Limitations

- Live counts describe a **developer-run corpus** (about 6 weeks of feeds) and developer accounts. They are not user-study results.
- T1 is a lexical rule. It catches added numbers, months and names, but not changed meaning, so a T1 pass is an *upper bound* on groundedness. It also flags some benign words (e.g. "Indian" when the source says "India" in a different form, or "Arsenal-related").
- The classifier figure is agreement with a *weak* label (feed domain), not accuracy.
- The Groq vs Ollama comparison (§2.6c) is unpaired. The offline vs LLM comparison (§2.6b) is paired.
- The Agent 4 gold set is small (97), stratified toward severe events, and drawn from public datasets rather than MAPNAI's feeds.
- Stream and polling numbers come from simulations and unit tests, not live traffic.
- n is very small for recaps (2), insights (7 claims), alerts (2) and the live render cache (6). Report these as smoke tests.
- S4 human labels have moderate agreement (κ 0.56). The κ gate was lowered from 0.6 to 0.55 after the pilot, and annotator A2 re-labelled once after feedback. Both are disclosed in `research/PREREG.md` §12–13.

## 7. Reproduce

```bash
cd MAPNAI   # local MongoDB + Neo4j running (docker compose up -d mongo neo4j)
venv/Scripts/python research/groundedness/eval_groundedness.py "$(pwd)" research/groundedness/groundedness_live.json
PYTHONIOENCODING=utf-8 venv/Scripts/python research/groundedness/llm_summary_and_kg_probe.py   # LLM-summary proxies, KG text check
PYTHONIOENCODING=utf-8 venv/Scripts/python research/groundedness/summary_t1_by_path.py          # T1 by summary path

# Agent 4 offline scorer (models/ is not in git; see AGENT4_RISK_ARCHITECTURE.md §10)
venv/Scripts/python -m scripts.risk.train_event_model                                           # TF-IDF fallback, < 1 min
PYTHONIOENCODING=utf-8 venv/Scripts/python research/groundedness/agent4_gold_eval.py   models/risk_event   # gold set, all tiers
PYTHONIOENCODING=utf-8 venv/Scripts/python research/groundedness/agent4_live_offline.py models/risk_event   # live re-score, read-only

# Stream
venv/Scripts/python scripts/stream_benchmark.py dedup --sizes 1000 10000 100000
venv/Scripts/python scripts/stream_benchmark.py polling --feeds 70 --fixed 15 30
venv/Scripts/python scripts/replay_hotness.py --days 7
```

In this checkout the DistilRoBERTa weights are at `models/mapnai_risk_event_model/risk_event`, so pass that path instead of `models/risk_event`.

Raw output of the live run: `research/groundedness/groundedness_live_2026-11-19.json`. Research numbers: `research/LEDGER.md` (entries L0001–L0102) and `research2/results/`.
