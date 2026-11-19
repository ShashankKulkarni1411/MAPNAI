# MAPNAI: Groundedness Checks

How to check, piece by piece, that what MAPNAI stores and shows is supported by its source articles. This is the plan. The measured values are in `GROUNDEDNESS_RESULTS.md`, and the read-only scripts that produce them are in `research/groundedness/`.

**Grounded** means every fact the system states (a name, number, date, event or claim) can be traced to a source article it cites or was built from. Pieces that only extract or classify (NER, the classifier) are checked for faithful extraction instead.

**Status key:** ✅ a check already runs in the app · 🟡 partial · ❌ none

---

## 1. Shared toolkit

Every per-piece check below is built from these seven tools. Most already exist in the codebase.

| # | Tool | What it catches | Where it lives |
|---|---|---|---|
| T1 | **Rule fact gate** | Numbers, ISO dates, months and capitalized names that are not in the source; odds phrasing | `personalization/factcheck.py` (`verify`, `months`, `new_names`) and `insights.check_claim` |
| T2 | **Learned checker (NLI)** | Meaning-level errors the rules miss: a wrong event, a swapped subject, a claim that is never said | MiniCheck-FT5 / DeBERTa, already pinned for research (E05, E23) |
| T3 | **LLM judge** | Claim-by-claim support against cited articles | The pattern of `_check_answer` in `agents/query_graph.py` |
| T4 | **Verbatim check** | Text that should be copied from the source but isn't | A plain substring or normalized match |
| T5 | **Citation validity** | `[n]` or `sources` pointing to a missing or wrong article | Index-range check plus T1/T2 on the cited article only |
| T6 | **Stability / agreement** | Outputs that change on re-run, or between Groq and Ollama | Re-run on a fixed sample; Spearman or Cohen's κ |
| T7 | **Human labels** | Ground truth for all of the above | Two annotators on 50–100 items, inter-annotator κ |

**Rule of thumb:** T1 is cheap and runs on everything, T2 runs on a sample, T3 costs LLM calls, and T7 is the evidence a reviewer trusts most.

---

## 2. Per piece of the project

### 2.1 Ingestion (fetchers, preprocessing, dedup, images): 🟡

This layer generates no text, so the question is whether the stored article matches the real one.

| Check | How | Metric |
|---|---|---|
| Body and title match the source page | Sample 50 stored articles, re-fetch each URL, T4 on the title and the first paragraph | % match |
| Publish date is correct | Compare `published_at` with the page; `date_source` already flags articles that fell back to their ingestion time | % within 1 h; % ingested-fallback |
| Dedup doesn't merge different stories | Sample 50 merged pairs and label same or different (T7) | False-merge rate |
| Fallback image shows the right subject | `utils/image_fallback.py` picks a Wikipedia image of the main entity; sample 50 and label correct or wrong (T7) | % correct image |

### 2.2 Agent 1: NER (BERT): 🟡

| Check | How | Metric |
|---|---|---|
| Every entity actually appears in the text | T4: each entity `name` (normalized) is in the title or body | % entities found verbatim (target ≈ 100%) |
| Entity types are right | Label a sample (T7); note that the MISC label is stored as `Product` by default (`NER_MISC_LABEL`) | Precision per type |
| No important entity is missed | Label 50 articles fully (T7) | Recall |

### 2.3 Agent 2: classifier: ✅ (accuracy, not grounding)

| Check | How | Metric |
|---|---|---|
| Domain is correct | Held-out labelled set (already used in training) | Accuracy, F1 per class |
| Out-of-scope stories don't leak in | Sample stored `sports` and `entertainment_movies` articles (T7) | % truly in scope |
| Confidence threshold is sensible | Accuracy above and below `IN_SCOPE_MIN_CONFIDENCE` | Calibration curve |

### 2.4 Knowledge graph (Neo4j): ❌

| Check | How | Metric |
|---|---|---|
| Every `MENTIONED_WITH` edge has a real co-occurrence | Sample 100 edges and find an article whose entities contain both ends | % edges traceable |
| Mention counts are right | Compare `frequency` with a count from MongoDB. Known issue: Agent 1 and the ingestion writer both add to it (see STREAMLINING_PROPOSALS §3) | Ratio stored ÷ recounted |

### 2.5 Agent 3: summaries: ❌ (biggest gap)

`summary_short` and `summary_long` are the most widely shown text in the app (feed, story page, recap, Ask context), and nothing checks them.

| Check | How | Metric |
|---|---|---|
| Extractive path is verbatim | T4: every sentence occurs in the body (true by design, so this is a sanity test) | % verbatim |
| LLM path adds no facts | T1 summary vs. body, then T2 per sentence | % summaries fully supported; % unsupported sentences |
| The persona prompt doesn't invent stakes | T2/T3 on "why it matters" style sentences | Same as above |

**Caution:** the LLM also receives `similar_articles`, so a summary can legitimately contain a fact from a related story. Check against the body first, then against body plus similar articles, and report both numbers.

### 2.6 Agent 4: risk / priority scorer: 🟡

Since commit `6f8ca19` the default is `RISK_BACKEND=model`: an offline DistilRoBERTa event classifier (falling back to TF-IDF, then keyword rules) plus three formula factors, with no LLM calls (`agents/risk_model.py`, `AGENT4_RISK_ARCHITECTURE.md`). The Groq and Ollama LLM backends are still available through `auto`, `groq` and `ollama`.

| Output | Check | Metric |
|---|---|---|
| Event type (offline model) | T7: hand-labelled gold set `data/risk/gold_key.csv` (97 articles, never trained on); each tier with and without the keyword severity guard | Accuracy, macro-F1 (bootstrap CI), high-severity recall, severity MAE |
| `action_recommendation` | Offline: a template filled with the event type, the matched keyword and the top entity, so check that every name and number comes from the article. LLM backends: T1 via `insights.check_claim` against title + body, then T2 | % supported |
| Sub-scores and `risk_score` | Format (four factors in 0–25 that sum to the score). Offline: T6 is a determinism check (re-score gives identical output). LLM backends: re-score 3–5× and compare Groq vs. Ollama on the same sample | Score SD; level-flip rate; Spearman |
| Offline vs. stored LLM scores | Paired, on the same live articles | Spearman; level agreement |
| Score follows the evidence | Entity salience vs. Agent 1 salience; temporal urgency vs. `urgency_flag`; perturbation (title-only body, swapped entity) should lower the score | Correlations; % lowered |
| Score matches human judgement | T7: label 50 *live* articles MONITOR / ALERT / ESCALATE (the gold set covers event type only, and comes from public datasets, not the live feed) | Cohen's κ, Spearman |
| Reasoning | Offline: each factor is a visible formula, so nothing to check. LLM backends: not stored (`normalize_risk` drops it) | n/a |

### 2.7 Agent 5: Ask (RAG): 🟡

| Path | Today | Check to add |
|---|---|---|
| Graph path (LangGraph) | ✅ `_check_answer`: each claim must be supported by its cited articles; one regeneration, then `UNSUPPORTED_ANSWER` | Measure it: on a fixed set of 50–100 questions, re-check the final answers with T2 and T7 |
| Single-pass path (no graph, or graph failed) | ❌ no check | T5 + T2 on each `[n]` sentence |
| No-LLM fallback (`extractive_answer`) | ✅ copies summary sentences | T4 sanity check |
| Retrieval | ❌ | Label whether the top-5 contain the answer (T7) |

**Metrics:** answer support rate, citation precision (cited article supports the sentence), citation coverage (% factual sentences that cite something), retrieval hit@5, and % honest "can't answer" on questions that have no answer in the database. `tests/data/agent5_response_golden.json` already pins the response format.

### 2.8 Personalization: style rewrites (`render.py`): ✅

| Today | Check to add |
|---|---|
| Every rewrite goes through the T1 gate (`render_gate_version` v1 / v2); a failure serves the source text | Track the fallback rate per gate version in production; spot-check passes with T2 on a sample. Research experiments E02 and E21–E23 already measure the gate offline, so cite them rather than repeat them |

### 2.9 Personalization: recap overview: 🟡

| Today | Check to add |
|---|---|
| `overview_check` rejects only **new numbers** | Also run months and `new_names` (T1, as `check_claim` does), then T2 against the recap's source lines. Log how many overviews would newly fail before tightening anything in the app |

### 2.10 Personalization: Insights: ✅

| Today | Check to add |
|---|---|
| Every claim (what happened, why it matters, scenarios, watch next, actions) is checked with T1 against the articles it cites; failing claims are dropped, advice is blocked, and status is `partial` or `fallback` when too little survives | Report the dropped-claim rate and the ok / partial / fallback split (already stored in `analysis.status` and `analysis.dropped`). Run T2 on surviving claims. Scenarios are speculation by design: check that their **premises** are cited, and that the disclaimer is always present |

### 2.11 Personalization: why lines, profile text, alerts (`explain.py`, `alerts.py`): ✅ by construction

These are templates, not LLM output, so they're grounded if their inputs are right.

| Check | How |
|---|---|
| The entity named in a why line is in that article's `entity_keys` and in the user's exposures | Property test over generated digests |
| Numbers in the why line ("Need 0.30 = materiality 0.30 × exposure 1.00") equal the computed values | Property test |
| An alert's entity really appears in the story | Same check on alert rows |

### 2.12 Mobile app: 🟡

| Check | How |
|---|---|
| Each claim links to the article it cites | UI test on the story and insight screens |
| Labels match backend values ("Impact: Major / High impact / Routine" ↔ `risk_level`) | Review the mapping in `story/[id].tsx` |
| Mock data never ships | Confirm mock mode is off in release builds (`mockServer.ts` / `fixtures.ts`) |

### 2.13 Continuous stream, hotness and push (`stream_worker.py`, `personalization/hotness.py`, `personalization/push.py`): 🟡

Added in commit `c5baf38`. These pieces don't generate text, so the checks are about correctness and timing, not groundedness.

| Output | Check | Metric |
|---|---|---|
| Stream dedup (banded SimHash index) | Same matches as the linear scan (`tests/test_stream_dedup.py`); speed (`scripts/stream_benchmark.py dedup`) | Agreement; ms per lookup |
| Adaptive polling | `scripts/stream_benchmark.py polling` (simulated feeds) | Requests per day; minutes from publication to fetch |
| Hotness tiers and breaking alerts | `scripts/replay_hotness.py` over stored sightings; T7 on a sample of "breaking" stories | Stories per tier; minutes from first report to flag; precision of "breaking" |
| Push notification text | The alert names an entity that is in the story (as in §2.11) | % correct |

---

## 3. How to run this without changing the app

1. **Read-only evaluation scripts**, for example `scripts/eval/eval_<piece>.py`. Each reads MongoDB and Neo4j, calls the pieces' pure or no-write entry points (`factcheck.verify`, `insights.check_claim`, `RiskScoringAgent.score`, `QueryAgent.process`), and writes a JSON or CSV report. Nothing writes to the database.
2. **Fixed samples:** freeze the article and question IDs once (seeded random draw), so before/after comparisons use the same items.
3. **Learned checker (T2)** runs in its own virtual environment, as the research experiments already do. The app's environment stays untouched.
4. **Human labels (T7):** export a CSV with source text and output side by side; two people label it; compute κ before trusting the labels.

## 4. Suggested order

1. **Agent 3 summaries** (T1 + T2): no check exists, and the most visible text depends on them.
2. **Agent 5 single-pass path** (T5 + T2), plus a measurement of the graph path.
3. **Agent 4 recommendation and stability** (T1, T6, T7).
4. **Recap overview:** measure what a full T1 would reject.
5. **Agent 1 verbatim and graph traceability** (T4): cheap, quick wins.
6. **Insights and render metrics:** they already have gates, so just report their rates.

## 5. What to report

One table per piece: **sample size · check used · pass rate · 95% CI · top failure types**, plus inter-annotator κ wherever human labels were used.
