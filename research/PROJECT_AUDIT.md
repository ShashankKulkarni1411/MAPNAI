# MAPNAI — Project Audit for Research Planning

**Date:** 2026-10-23 · **Branch audited:** `agent-satvik` @ `53f4b12` · **Scope:** Phase 1 of the research plan (no application code was changed)

This audit answers a single question: *what does MAPNAI actually do, and which parts of it could carry a research paper?* It reads the code itself, not only the documentation. Each claim is labelled with how it was established:

| Label | Meaning |
|---|---|
| **[code]** | Read in the source file cited |
| **[ran]** | Executed during this audit, and the output was observed |
| **[live]** | Read-only aggregate queries against the live MongoDB Atlas database on 2026-10-23 (counts and distributions only; no data was written) |
| **[doc]** | Stated in repository documentation (`README.md`, `PERSONALIZATION_CONTEXT.md`, `PERSONALIZATION_PLAN.md`) and not independently re-verified |
| **[unverified]** | Could not be checked (see §9) |

The audit was first run without `.env` or `models/`. After the team added them, the live-data and model checks were re-run and this document was revised. The `[live]` figures supersede the older `[doc]` figures from 2026-09-29.

---

## 1. One-paragraph summary

MAPNAI ("Multi-Agent Personalized News & Action Intelligence") is a news-intelligence backend with a React Native client.

- **Ingestion.** It ingests RSS feeds, news APIs, Reddit, Bluesky and scraped pages. It cleans and deduplicates them (SimHash + MinHash), extracts entities, and writes to MongoDB, FAISS and Neo4j.
- **Agent pipeline.** A chain of "agents" enriches each article:
  - A1: NER.
  - A2: a fine-tuned DistilRoBERTa classifier for {sports, entertainment_movies, other} plus urgency and sentiment.
  - A3: an LLM or extractive summary.
  - A4: an LLM risk score.
  - A5: a LangGraph agentic RAG for question answering.
- **Personalization engine.** The most distinctive and best-tested part. Users declare **typed exposures** to graph entities (`owns`, `depends_on`, `regulated_by`, …). The engine then works in steps:
  - It spreads those exposures over a co-mention graph.
  - It clusters articles into events.
  - It scores each article's **materiality** *m*.
  - It builds a daily digest whose **`must_know`** section is gated by **need = m × exposure**. This is separate from an **interest** model (late fusion over reading history plus Beta topic/entity affinities).
  - Everything else goes through MMR diversification, calibrated topic caps and a Thompson-sampled explore slot. Every served item is logged with its propensity.
- **LLM outputs.** Every LLM-generated text shown to readers (style rewrites, recap overviews, "developing story" insights) passes through a deterministic fact-preservation check before it is served.

**Not available:** there are **no real users.**
- The live database holds 105 feedback events from 9 developer/test personas. These cover 3 weeks (2026-09-28 → 2026-10-18) and are too few, and too non-naturalistic, for evaluation [live].
- The system has never been evaluated against users.
- The only quantitative evaluation artefact is a 63-pair clustering calibration set.

---

## 2. Architecture

```
 Sources                    Ingestion layer                       Storage
 ───────                    ───────────────                       ───────
 RSS (config/sources.py) ┐                                        ┌─ MongoDB  processed_articles (+ personas, feedback,
 NewsAPI/GNews/NewsData  ├─► preprocessing_agent ─► enrichment ─► │           impressions, clusters, digests, alerts, …)
 Reddit (PRAW), Bluesky  │   clean · lang · SimHash/MinHash      ├─ FAISS    data/faiss_index (MiniLM-L6, 384-d, IP)
 Web scraper             ┘   dedup · lexicon sentiment · tags    └─ Neo4j    Article/Entity/Source/Domain,
                              spaCy NER + frequency "salience"               MENTIONS, MENTIONED_WITH{count}
                                                    │
 Agent layer (pipeline.py, run on articles already in Mongo)
 ───────────
 A1 ner_agent (BERT NER, spaCy fallback) → A2 agent2_classifier (DistilRoBERTa multi-task)
   → [in_scope only] A3 agent3_summarizer (Groq LLM | TF-IDF extractive) → A4 agent4_risk_scorer (Groq LLM, 4×0–25)
 A5 agent5_query + query_graph (LangGraph: route→retrieve→grade→rewrite→credibility→generate→check)

 Personalization layer (personalization/*, api/*, scheduled by APScheduler in run_api.py)
 ─────────────────────
 job_cluster (hourly): entity_keys → pers FAISS sync → event clustering → materiality m
 job_pi_topk (nightly): EXPOSED_TO seeds → spread over MENTIONED_WITH → pi_topk
 digest: R1 exposure · R2 material · R3 vector-similar · R4 topic → RRF → interest → need → slate
 feedback → Beta updates + history; job_tau → adaptive τ; job_proposals → suggested exposures
 alerts · render (LLM style rewrite + fact-check) · recaps (daily/weekly) · insights (developing stories)

 Client: mobile/ (Expo / React Native). Default API mode is 'mock' (mobile/src/api/client.ts), with 'hybrid' and 'live' modes
```

### 2.1 End-to-end data flow: from ingestion to what the user sees

1. **Fetch** (`ingestion_pipeline.py`, `agents/rss_fetcher.py`, `api_fetcher.py`, `reddit_fetcher.py`, `bluesky_fetcher.py`, `web_scraper.py`): each fetcher produces `RawArticle` objects (`utils/models.py`). **[code]**
2. **Preprocess** (`agents/preprocessing_agent.py`): **[code]**
   - HTML/URL cleaning, `ftfy`, language detection, quality gates, and timestamp normalization.
   - Deduplication with `utils/deduplicator.py`:
     - SimHash over title + body[:500], Hamming ≤ 3.
     - MinHash LSH with Jaccard ≥ 0.5 and 128 permutations.
   - Duplicates are **dropped, not grouped**.
   - A keyword-rule domain is assigned, plus a lexicon sentiment (`lexicon_sentiment`, about 40 hand-picked words).
3. **Enrich** (`agents/enrichment_agent.py`): spaCy entities. "Salience" is frequency / max frequency (line 93), not a learned salience. **[code]**
4. **Store**:
   - MongoDB `processed_articles`.
   - FAISS `IndexFlatIP` over `all-MiniLM-L6-v2` embeddings of `f"{title}. {body[:300]}"` (`storage/faiss_store.py:110,152`).
   - The Neo4j co-mention graph (`storage/neo4j_store.py`). **[code]**
5. **Agents 1–4** (`pipeline.py`):
   - A2 marks `in_scope=false` for `other` or confidence < 0.5 (`agents/agent2_classifier.py`, `IN_SCOPE_MIN_CONFIDENCE`).
   - Only in-scope articles reach A3 and A4. **[code]**
6. **Personalization jobs**:
   - `job_cluster` assigns `cluster_id` and `materiality`.
   - `job_pi_topk` computes each user's exposure spread. **[code]**
7. **Digest** (`personalization/service.py:907 compute_digest`). **[code]**
   - Candidates come from four retrievers (`_candidate_pool`, line 761) and are merged by RRF.
   - Read items are dropped, and each item gets an interest score and a need score.
   - Clusters are collapsed, a slate is built, and why-lines are added.
   - Served through `/v1/users/{id}/digest`. Impressions are logged on every serve (line 977).
8. **Client**: Expo app tabs (feed, flash, insights, profile). Implicit signals (open, dwell capped at 120 s) and explicit signals (more/less, save, needed/not_needed/missed) post to `/v1/feedback` (`mobile/src/state/feedback.ts`). **[code]**

---

## 3. Component inventory

Status key: **Impl** = implemented and wired · **Impl\*** = implemented and LLM-dependent; the key is present, but no LLM calls were made during this audit, so only code, mocked tests and cached outputs were inspected · **Partial** · **Planned** · **Stub**.

| Component | File paths | Status | Algorithm / model | Input | Output | Existing evaluation | Research potential |
|---|---|---|---|---|---|---|---|
| Source fetchers | `agents/*_fetcher.py`, `agents/web_scraper.py`, `config/sources.py` | Impl | feedparser, REST, PRAW, Bluesky API, BeautifulSoup | Feed/API configs | `RawArticle` | `tests/test_fetchers.py` (mocked) | Low (infrastructure) |
| Cleaning + dedup | `agents/preprocessing_agent.py`, `utils/text_cleaner.py`, `utils/deduplicator.py` | Impl | SimHash (64-bit, Hamming ≤ 3); MinHash LSH (J ≥ 0.5) | Raw text | `ProcessedArticle`; duplicates dropped | `tests/test_preprocessing.py` (unit) | Low–Med: near-duplicate dropping vs event grouping is a known design choice |
| Lexicon sentiment + keyword domain | `agents/preprocessing_agent.py:45`, `utils/text_cleaner.py` | Impl | ~40-word lexicon; keyword rules | Body text | `sentiment_score`, `domain`, `topic_tags` | None | Low (superseded by A2) |
| Ingestion NER | `agents/enrichment_agent.py` | Impl | spaCy `en_core_web_sm`; frequency-based "salience" | Title + body | `entities[{name,type,salience}]` | None | Low; entity quality is a limiting factor for everything downstream ([doc] mis-typing, e.g. "Big Bang" → Location) |
| A1 NER | `agents/ner_agent.py`, `ner_utils.py`, `neo4j_writer.py` | Impl | Fine-tuned `BertForTokenClassification` with CoNLL-style labels (PER/ORG/LOC/MISC, BIO) in `models/mapnai-ner-bert` (412 MB, git-ignored); spaCy fallback | Mongo docs | Entities + Neo4j nodes | None in the repo. [live] 2,664 / 3,674 docs were tagged by `BERT-finetuned`, 1,010 by the fallback | Low–Med |
| A2 classifier | `agents/agent2_classifier.py`, `agents/classifier_model.py`, `config/classifier_taxonomy.py`, `scripts/classifier/*`, `models/classifier/` | Impl | DistilRoBERTa, mean-pooled, 3 heads: domain (3-way CE), urgency (BCE, threshold tuned for F0.5), sentiment (tanh, MSE). Labels made by Qwen2.5-7B-Instruct (LLM distillation). **The installed weights are taxonomy 2.0.0** (with a legacy 14-way category head; urgency threshold 0.97), while the code declares `TAXONOMY_VERSION = "3.0.0"`. The loader tolerates this by ignoring the category head | Title + body (≤ 256 tokens) | domain, urgency, sentiment, confidence; `in_scope` | Notebook has evaluation cells, but **no saved outputs**; the HF model card reports no metrics. [live] median confidence 0.989; 0.4% below 0.5; 35 / 3,674 flagged urgent. **No human-labelled accuracy exists** | Low–Med: LLM-labelled distillation is established; a gold-set evaluation would be needed for any claim |
| Classifier data | `data/classifier/candidates.jsonl` (5,667 rows), `rss_raw.jsonl` (893) | Data | — | — | Unlabelled candidates with `hint_domain` | — | Usable for the evaluation of A2 |
| A3 summarizer | `agents/agent3_summarizer.py`, `utils/extractive_summarizer.py` | Impl\* (LLM) / Impl (extractive) | Groq LLM with domain "persona" prompts; TF-IDF centroid + lead bias + entity/title overlap extractive | In-scope articles | `summary_short`, `summary_long` | None | Low |
| A4 risk scorer | `agents/agent4_risk_scorer.py` | Impl; [live] **run on only 22 of 3,674 articles** (scores 9–31, median 14.5, all `MONITOR`). Materiality is `unscored` on 100% of the 2,063 articles that have it | LLM "ReAct-style" prompt: 4 factors × 0–25 summed; bands MONITOR/ALERT/ESCALATE | Summary, entities, A2 outputs | `risk_score`, `risk_reasoning`, `action_recommendation` | None | Med as a *component* of materiality; the LLM risk score itself is unvalidated |
| A5 query (agentic RAG) | `agents/agent5_query.py`, `agents/query_retriever.py`, `agents/query_graph.py`, `agents/query_llm.py` | Impl\* | Heuristic routing (keyword/semantic/graph); LangGraph loop with grading, rewrite (≤ 2), credibility rerank (relevance × source tier), generation with citations, claim-level grounding check, bounded by budget and deadline; degrade → single pass | Question | Answer, sources, route, `_metadata.graph` | `tests/test_query_graph.py` (mocked LLM), `tests/data/agent5_response_golden.json` (shape only). No QA accuracy evaluation | Low–Med: closely mirrors Self-RAG / CRAG / Adaptive-RAG patterns |
| Pers. vector index | `storage/pers_vector_store.py`, `scripts/rebuild_pers_faiss.py` | Impl | Same MiniLM recipe; separate index synced from Mongo | Mongo docs | Vectors by `article_id` | `tests/test_pers_*` | Infrastructure |
| Entity keys + aliases | `personalization/keys.py`, `scripts/seed_entity_aliases.py`, `config/entity_aliases_seed.json` | Impl | Lower-cased name keys across NER types; hand-seeded aliases | Entity names | `entity_keys`, alias map | `tests/test_pers_keys.py` | Low (crude entity linking is a limitation) |
| **Exposure spread** | `personalization/spread.py` (`hop` l.37, `spread` l.65), `storage/exposure_store.py` | Impl | Seeds = declared `EXPOSED_TO` (role, weight 1–3). Hop score = src × rel_weight × strength / max_strength × factor; best path per entity; hop 2 × 0.5. Only relation available: `MENTIONED_WITH` → `CO_MENTION` (weight 0.1) | User exposures, Neo4j co-mentions | `pi_topk` (≤ 500 entries with an explainable path) | Unit tests (`tests/test_pers_phase2.py`) | **High** idea (declared, typed stakeholder exposure); currently weak signal ([doc] R1: hop scores ≤ 0.1, so they never reach τ) |
| **Event clustering** | `personalization/clustering.py` (`pair_joins` l.96, `assign_clusters` l.107), `service.cluster_articles` | Impl | Online single-pass: join if cos ≥ 0.88, or (cos ≥ 0.77 ∧ \|Δt\| ≤ 36 h ∧ (fuzzy shared entity ≥ 88 ∨ title-Jaccard ≥ 0.25)), with an anti-chaining mean-similarity guard (≥ cos_join − 0.05); never merges clusters | MiniLM neighbours (k = 20), time, entities, title | `cluster_id`, `cluster_size`, `first_report` | **[ran]** `scripts/calibrate_clustering.py` on `tests/data/cluster_pairs.jsonl` (63 hand-labelled pairs, 46 positive): at cos_join 0.77, **P = 0.923, R = 0.522, F1 = 0.667**; no threshold in [0.70, 0.82] reaches P ≥ 0.95. [live] 1,864 clusters over 2,063 articles: **1,729 singletons (92.8%)**, 135 multi-article clusters (334 articles), 7 with ≥ 5 members, max 14 | **Med–High** for a quantitative paper; methodological novelty limited |
| **Materiality m** | `personalization/materiality.py:39`, `config/source_credibility.json` | Impl (risk part inert) | m = weighted mean of risk_norm (0.5), size_score = min(1, ln(1+n)/ln 11) (0.2), first_report (0.15), source tier (0.15); renormalized without risk | Article, cluster size | `m` and its parts | Unit tests only; "not calibrated on real data" (config comment). [live] n = 2,063: min 0.236, **median 0.296**, max 0.865; 6.5% ≥ 0.6; all unscored | **Med–High** as an object of validation (does m track editorial importance?) |
| **Interest model** | `personalization/interest.py` (`late_fusion` l.116, `interest` l.145) | Impl | interest = 0.5·LF + 0.3·θ_topic + 0.2·θ_entity. LF = decay-weighted mean of max(0, cos) over history (short: 72 h, half-life 24 h; long: 60 d, half-life 21 d). θ = Beta posterior mean with declared-weight priors | History vectors, Beta, topics | Score + parts | Unit tests | Med (late fusion is an established method; Beta priors from declarations are less common) |
| Candidate generation | `personalization/candidates.py` (`rrf` l.93, `merge_candidates` l.102, `collapse_clusters` l.122) | Impl | 4 retrievers (exposure, materiality, vector-similar, topic) → RRF (k = 60), with R1/R2 bypassing the top-200 cut | Window docs | Fused candidates | Unit tests | Low–Med |
| **Slate / must_know gate** | `personalization/slate.py` (`need` l.44, `mmr` l.79, `thompson_explore` l.129, `build_slate` l.175) | Impl | need = m × max π; must_know if need ≥ τ (≤ 5, overflow kept); for_you = MMR (λ = 0.7) under calibrated topic caps; 1 explore slot via Thompson sampling over topic Betas; propensity estimated from 200 re-draws with a seeded RNG | Scored candidates | Digest sections | Unit tests | **High** (need-vs-interest separation) |
| Why-lines | `personalization/explain.py`, `service._why` | Impl | Templates built from the actual score components (path, need = m × π, dominant interest part) | Score parts | Text + structured `why_parts` | Unit tests | Med (faithful-by-construction explanations; no user evaluation) |
| Feedback, adaptive τ, proposals | `personalization/feedback.py` (`tau_update` l.40, `engagement_proposals` l.69), `service.record_feedback` | Impl | Beta deltas per event type; τ ← clip(τ − 0.05·(miss_rate − 0.1)); proposals from ≥ 3 engaged articles with θ ≥ 0.7 | Feedback events | Updated Beta/history, τ, proposals | Unit tests; `/admin/metrics` computes must_know precision and miss rate | Low without users |
| Alerts | `personalization/alerts.py`, `service.run_alerts` | Impl | need ≥ 0.5 ∧ m ≥ 0.6, per-cluster dedup, daily cap, quiet hours | Materiality, pi index | Alert docs | Unit tests | Low |
| **Style render + fact-check** | `personalization/render.py` (`render` l.127), `personalization/factcheck.py` (`verify` l.106) | Impl\* (Groq) | LLM rewrite conditioned only on (tone, length, jargon); deterministic check that every number, ISO date, month and verbatim entity name of the source survives, and that no new number appears; failure → serve the source; failures cached | Summary/body, style | `text`, `fallback`, `missing`, `added` | `tests/test_pers_phase7.py` (unit, with fakes). No human faithfulness evaluation. [live] `render_cache`: 12 gpt-oss-120b rewrites (prompt `r2`), **4 fallbacks (33%)**, all `fact_check`; the missing facts are 8 entities and 6 numbers; no added numbers. A manual read of all 12 is in §6.1 | **High** for an empirical faithfulness study |
| Recaps | `personalization/recap.py` | Impl | Stories = clusters (merged on title Jaccard ≥ 0.5) ranked by m with domain quotas; optional LLM overview, dropped if it adds an unsupported number | Window docs | Daily/weekly recap | `tests/test_recap.py` | Low–Med |
| **Insights** | `personalization/insights.py` | Impl\* | Developing stories (≥ 2 outlets); LLM writes "what happened / why it matters / scenarios / actions" as JSON with article-index citations; each claim checked against the cited articles (numbers, months, new capitalized names, odds language); advice filters; one retry, then fallback | Story articles | Cited analysis | `tests/test_insights.py` (unit) | Med–High but hard to evaluate |
| Metrics | `personalization/metrics.py`, `api/admin_router.py` | Impl | Read rate per section, must_know precision, miss rate, τ history, unscored share, vector coverage, render fallbacks | Logs | `/admin/metrics` | — | Enables future online evaluation |
| Impression logging | `service._log_impressions` (l.977) | Impl | Per item: section, slot, need, m and parts, interest and parts, τ, **propensity**, policy/persona version | Served digest | `impressions` collection | — | Enables off-policy evaluation **if** traffic exists |
| API + auth | `api/app.py`, `api/personalization_router.py`, `api/auth_router.py`, `utils/auth.py` | Impl | FastAPI | — | `/v1/*` | `tests/test_pers_app.py`, `tests/test_auth.py` | Infrastructure |
| Mobile client | `mobile/` | Impl (default mock mode) | Expo/React Native; zustand; feedback with a 5 s undo window | API | UI | None | Enables a user study |
| Demo personas | `scripts/seed_demo_personas.py`, `scripts/smoke_test.py` | Impl | 3 synthetic personas | — | Seeded users | Smoke test flags > 30% must_know overlap between personas | Basis for a persona-based offline benchmark |

---

## 4. Personalization logic in detail

The scoring path for one article *a* and user *u* (all module-level functions are pure: no DB, no clock, RNG injected):

1. **Exposure** (`spread.py`). Seeds score weight/3 (high = 1.0, medium = 0.67, low = 0.33). Each hop multiplies by the relation weight (only `CO_MENTION` = 0.1 exists), the neighbour's strength relative to the source's strongest neighbour, and 0.5 for hop 2.
   - π(e) is therefore ≤ 0.1 for hop-1 entities and ≤ 0.05 for hop-2 entities.
2. **Materiality** (`materiality.py`): m(a) ∈ [0, 1].
   - While A4 has not scored *a*, m is a renormalized mean of size_score, first_report and source tier.
   - [doc] Its range is then roughly 0.27–0.53 for singleton clusters.
3. **Need** (`slate.need`): need(a, u) = m(a) · max over the entities of *a* of π_u(e). The argmax entity's path becomes the explanation.
4. **Interest** (`interest.interest`): 0.5·LF + 0.3·θ_topic + 0.2·θ_entity, where:
   - LF is late fusion of cosine similarities to the reading history (short and long windows);
   - the θ values are Beta posterior means whose priors come from declared topic weights (α = 1 + 3w, β = 1 + 3(1 − w)).
5. **Relevance** rel = interest + 0.3·need. `rank` adds 1.0 when need ≥ τ, so must-know members win the cluster collapse.
6. **Slate** (`slate.build_slate`, k = 10):
   - `must_know`: the top 5 by need with need ≥ τ (τ_init = 0.2); the overflow goes to `more_you_need`.
   - `for_you`: MMR (λ = 0.7, cosine or entity Jaccard) under topic caps of round(share_t·k) + 1.
   - 1 `explore` item, from a topic not yet in the slate, chosen by Thompson sampling.
7. **Feedback**:
   - `more` +1α, `less` +1β, `open` and `dwell ≥ 15 s` +0.5α on the topic and the top 3 entities.
   - `needed` / `missed` drive τ.
   - Engagement proposes new `follows` exposures.

**Consequences, derived from the code and noted in the plan's risk table:**
- With the co-mention graph, **only directly declared entities can trigger `must_know`**. For a hop-1 entity, need ≤ m·0.1 ≤ 0.1 < τ = 0.2.
- With A4 unscored, m rarely reaches 0.6. [live] 6.5% of articles do, all through cluster size, first report and source tier; the live `alerts` collection holds 10 alerts.
- [live] Median m is 0.296. A declared *high* exposure (π = 1) therefore clears τ = 0.2, while a *low* exposure (π = 0.33) needs m ≥ 0.6. In practice, **must_know ≈ "mentions an entity I declared at high or medium weight"**.

The "need" mechanism is therefore, in practice, *declared-entity matching × materiality*. The graph spread currently contributes only to interest ranking and explanations.

---

## 5. NLP / ML components: model inventory

| Model | Where | Trained by the team? | Weights in repo? |
|---|---|---|---|
| `all-MiniLM-L6-v2` (sentence-transformers) | FAISS indexes, clustering, interest, MMR | No (off the shelf) | No (downloaded) |
| spaCy `en_core_web_sm` | Ingestion NER | No | No |
| BERT NER (`models/mapnai-ner-bert`) | A1 | Yes (per README; training data and metrics not in the repo) | Local only, git-ignored (412 MB; `BertForTokenClassification`, 9 BIO labels over PER/ORG/LOC/MISC) |
| DistilRoBERTa multi-task classifier | A2 | Yes (Colab notebook; LLM-distilled labels from Qwen2.5-7B; per the model card, training data = RSS + AG News + BBC News + HuffPost News Category) | Local only, git-ignored (317 MB; taxonomy 2.0.0) |
| Groq `openai/gpt-oss-120b` (default; `GROQ_MODEL`, `PERS_RENDER_MODEL`) | A3, A4, A5, render, recap overview, insights | No (API) | n/a |
| Extractive TF-IDF summarizer | A3 offline | Rule-based | n/a |

---

## 6. Data and evaluation infrastructure that actually exists

| Asset | Size / content | Verified |
|---|---|---|
| `tests/data/cluster_pairs.jsonl` | 63 article pairs, hand-labelled `same_event` (46 true / 17 false), with cosine, Δt, titles, entity keys, snippets and notes | **[ran]** |
| `scripts/calibrate_clustering.py` | Threshold sweep; reproduced P 0.923 / R 0.522 at 0.77 | **[ran]** |
| `data/faiss_metadata.pkl` (git-tracked) | **3,406** rows `{article_id, title, domain, url, source, published}`. Domains: sports 828, geopolitics 653, technology 576, entertainment_movies 569, finance 505, health 182, supply_chain 93. Published 2019-08 → 2026-10-18. Vectors are reconstructible from `data/faiss_index`. **No article bodies** | **[ran]** |
| `data/classifier/candidates.jsonl` | 5,667 unlabelled candidate articles (some appear to come from a legacy BBC-style corpus, lower-cased) | [code] |
| `data/classifier/rss_raw.jsonl` | 893 RSS items | [code] |
| `tests/data/agent5_response_golden.json` | Response-shape golden file (fake LLM), not accuracy data | [code] |
| Unit/integration tests | 21 test files under `tests/`. **[ran]** 7 personalization test files in a scratch venv with unpinned deps: **331 passed, 25 failed**. The failures trace to the environment (a mongomock/pymongo version mismatch: `add_update() got an unexpected keyword argument 'sort'`), not to logic. `test_recap.py` / `test_insights.py` were not run (they need the full ingestion stack) | **[ran]** |
| `/admin/metrics` | Online metrics for must_know precision, miss rate, read rate per section, render fallback rate | [code]; no data |
| Live MongoDB Atlas `processed_articles` | **3,674 articles**:<br>• 6 ingestion runs, 2026-09-28 → 2026-10-18<br>• 148 sources (rss 3,458, gnews 216)<br>• domain: other 1,821, sports 1,098, entertainment_movies 755<br>• in_scope: 1,843<br>• **median body length 209 characters** (p10 113, p90 1,431), so most items are RSS synopses<br>• summaries on 1,843 (all in-scope)<br>• 6.55 entities/doc<br>• `published_at` spans 2016-08 → 2026-10-18 (median 2026-10-02)<br>• the `published_ts` / `date_source` backfill fields are absent | **[live]** |
| Live MongoDB, other collections | personas 13 · feedback 105 (more 59, dwell 19, open 13, less 8, needed 2, save 2, missed 1, share 1; 9 users) · impressions 1,043 (more_you_need 534, for_you 369, must_know 135, explore 5; 11 users, 53 digests) · digests 11 · clusters 1,864 · alerts 10 · proposals 2 · thresholds 1 · render_cache 12 · insights_cache 2 · recaps 2 · job_runs 301 · accounts 1. Persona names show these are demo/developer accounts | **[live]** |
| Neo4j Aura | `neo4j+s://…` host in `.env` **fails DNS resolution** (`ServiceUnavailable`). The instance is probably paused or deleted. [doc] On 2026-09-29: 3,144 entities and 12,467 co-mention edges (mean count 1.07) | **[unverified]** |
| User interaction data | **No real users.** 13 personas (3 seeded demos, the rest phase-test and developer accounts); 105 feedback events | **[live]** |

### 6.1 Manual read of the live `render_cache` (n = 12, anecdotal)

This sample is far too small for any rate estimate. It is recorded because it shows *both* failure modes of the lexical gate in `personalization/factcheck.py`.

| Observation | Count | Example (paraphrased) |
|---|---|---|
| Rejected for **omission forced by the length budget** | 3 of 4 rejections | A "short" rewrite of an F1 crash story drops "Baku", "McLaren" and "Formula 1's". A "short" rewrite of an NFL recap drops 6 box-score numbers. Neither adds anything false |
| Rejected although the rewrite looks faithful (**false rejection**) | ≥ 1 | The only "missing" fact was the entity "US" in a film-restoration story |
| Passed although **meaning changed** (**false acceptance**) | ≥ 1 | Hedge removed: "a judgement *appears to have been* made" → "a judgement has been issued" |
| Passed with a **misspelled name** | 1 | "Ravi Dubey" → "Ravie Dubey"; the gate only checks names on the article's entity list |
| Passed, apparently faithful | ~7 | Light paraphrases |

Conclusion for research planning: the gate optimizes *fact retention*, which conflicts with the *length* style control. It is also blind to modality, negation and attribution changes. Whether these anecdotes generalize is exactly what direction **D3** in `RESEARCH_OPPORTUNITIES.md` would measure.

**What has never been measured:**
- A2 classifier accuracy against human labels;
- A3 summary quality;
- A4 risk validity;
- A5 answer accuracy;
- render or insight faithfulness against human judgement;
- recommendation accuracy or beyond-accuracy metrics;
- any user outcome.

---

## 7. Strengths

1. **Clear separation of "need" from "interest"** at the slate level, with a configurable threshold and an overflow section that never silently drops a must-know item. The POPROX team reports finding no news-recommendation papers that use declared user interests (see the literature review), so this is uncommon.
2. **Typed, declared exposures** (`owns`, `depends_on`, `regulated_by`, …) with provenance (`declared` / `proposed` / `confirmed`). This is richer than topic checkboxes.
3. **Pure, deterministic scoring modules** with injected clocks and RNGs, so offline replay and ablations are cheap. Nearly every score component is returned in `*_parts` and logged.
4. **Faithful-by-construction explanations.** Why-lines are generated from the same numbers that rank the item.
5. **Logged propensities** for the stochastic explore slot, which is a prerequisite for unbiased off-policy evaluation.
6. **Defence-in-depth for LLM text.** Every user-facing generation has a deterministic factual gate, a cached fallback and prompt versioning.
7. **A small but real labelled clustering set** and a reproducible calibration script.

## 8. Technical limitations relevant to research claims

1. **No real users:** 105 developer feedback events and 1,043 impressions are not an evaluation dataset. No online or offline accuracy claim is possible from MAPNAI data today.
2. **Short texts:** the median article body is 209 characters [live]. This limits clustering evidence, summarization, and any article-level NLP claim.
3. **The graph store is currently unreachable** (Neo4j DNS failure), so exposure spread falls back to "no π" (`service._candidate_pool` catches the error).
4. **Entity quality** (spaCy fallback, mis-typed and fragmentary entities, name-only keys, hand-seeded aliases) caps the quality of exposures, need and clustering evidence.
5. **The co-mention graph is the only relation** (mean count 1.07 [doc]). Hop-propagated exposure is numerically unable to reach `must_know`.
6. **Materiality is uncalibrated.** Its strongest component (A4 risk, weight 0.5) is missing on 3,652 of 3,674 articles [live], and the source tiers are hand-assigned.
7. **Clustering recall is low** (0.52 at P 0.92 on 63 pairs). The labelled set is too small for reliable estimates; a 95% CI on recall from 46 positives is roughly ±0.15.
8. **Embeddings come from MiniLM over title + 300 characters.** Median body length is 209 characters [live].
9. **The A2 taxonomy is narrow** (sports, movies, other): 1,821 / 3,674 (49.6%) of documents are `other` [live].
10. **Weights are hand-set throughout** (0.5/0.3/0.2, 0.5/0.2/0.15/0.15, τ = 0.2, λ = 0.7), and none is learned or tuned on outcome data.
11. **The fact-check is lexical.** It cannot detect meaning-changing errors that keep every number and name (negation, swapped roles, unsupported causal claims), and it may reject valid paraphrases (unit changes, rounding).
12. **The A5 LLM grader and grounding checker are the same model family** as the generator (self-verification bias).

## 9. What could not be inspected or verified

| Item | Reason |
|---|---|
| Neo4j Aura graph | The host in `.env` does not resolve in DNS (2026-10-23); graph statistics are **[doc]** only. MongoDB Atlas **was** reachable (read-only aggregates, §6) |
| Accuracy of A1 NER / A2 classifier | Weights are present, but no human-labelled test set or saved metrics exist; the models were not re-evaluated (torch/transformers not installed in the scratch environment, and there are no gold labels to score against) |
| Classifier training/evaluation results | Notebook saved without outputs; no metrics in the repo or the HF model card |
| Groq-dependent behaviour (A3/A4/A5 LLM paths, render, recap overview, insights) | `GROQ_API_KEY` is now present, but **no LLM calls were made** during this audit (to avoid cost and side effects on caches). Only cached outputs in Mongo (§6.1) and the code were read |
| Docker / pinned Python 3.11 environment | Docker daemon not running |
| Full test suite in the project's pinned environment | Pinned Python 3.11 / Docker environment unavailable; partial run in a scratch venv only (see §6) |
| `graphify-out/` | Auto-generated code-graph artefacts; skimmed, not audited |
| Mobile app runtime behaviour | Not run; read for the feedback signal path only |
