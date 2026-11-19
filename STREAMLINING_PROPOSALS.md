# MAPNAI: Streamlining Proposals

A short list of every proposed cleanup and what each one does.

**Status (checked 19 Nov 2026 on the `cleanup` branch):** section 2 is fully applied, and rows marked **✅ Done** below are applied. Everything else is still a proposal.

> **Kept on purpose:** the project's own trained models (the Agent 1 BERT NER model, the Agent 2 classifier, the extractive summarizer, the offline Agent 4 DistilRoBERTa event model, which is now the default risk backend, the older local Ollama risk model, and the `CustomModelQueryLLM` hook for a trained Agent 5 model). They exist because the project brief asks us to train our own models, so none of them are proposed for removal.

---

## 1. Scope: ingestion vs. what the classifier keeps

The Agent 2 classifier (taxonomy v3) only keeps `sports` and `entertainment_movies`; everything else becomes `other` and stops before Agents 3–4.

| Change | What it does |
|---|---|
| Trim off-topic RSS feeds | Removes the ~36 finance, geopolitics, tech, health, supply-chain and government feeds from `config/sources.py`, keeping a few only as classifier negatives if wanted. |
| Retarget or drop the news APIs | `DOMAIN_QUERIES` in `agents/api_fetcher.py` has no sports or film query, so NewsAPI, GNews and NewsData add nothing in scope. Replace with sports/film queries or remove. |
| Retarget or drop the scraper targets | All 3 targets in `agents/web_scraper.py` are finance, politics or tech. |
| Review the Bluesky firehose | Random posts, all tagged `technology` by default; mostly discarded. |
| Trim old-domain leftovers | Agent 3 persona prompts, Agent 4 risk-factor examples, `DOMAIN_KEYWORDS`, the `Domain` enum, `topics_universe`, and the demo personas' finance/tech topics. |

## 2. Safe deletions (no behaviour change): ✅ Done

All rows below were applied in commits `ff63744` and `13f943d`.

| Delete | Why |
|---|---|
| `agents/reddit_fetcher.py` and the Reddit settings, `praw` dependency and README sections | Broken import (`REDDIT_SOURCES` no longer exists); replaced by Bluesky. |
| Root `test.py`, `test_ner.py`, `test_query.py` | Duplicate `pipeline.py` and `agents/agent5_query.py`; `test_query.py` writes fake articles into the live DB. |
| `personalization.zip` | Stale snapshot of `personalization/`, including `__pycache__`. |
| `research/TECHNICAL_IMPROVEMENT_AUDIT - Copy.md` | Identical copy. |
| `research2/paper/ICIP2027_news_values_draft_PREV.docx` (and older drafts) | `_PREV` is identical to `_draft`; keep only the latest. |
| `research/colab/download.txt` | Identical to `notebookebc06e1721.log`. |
| `research/colab/Cache Backup/` and the duplicate `Results` zip or folder | Duplicate or partial copies of `Results/`. |
| `mapnai_kaggle_gpu_runs (1).ipynb` | Download duplicate; keep one version. |
| `PERSONALIZATION_PLAN.v1.md` | Superseded by `PERSONALIZATION_PLAN.md`. |
| `graphify-out/` (add to `.gitignore`) | Generated tool cache committed to git. |
| Dead functions | `MongoStore.get_articles_by_domain`, `get_recent_articles`; `Neo4jStore.get_entity_neighbors`, `get_articles_by_entity`, `get_top_entities`; `ner_utils.extract_entities_fallback`; `ArticleDeduplicator.seen_count`; `pipeline.run_ner_pipeline` and `run_ner_with_schedule`; `ScraperTarget`; `SourceType.GOVERNMENT`. |
| Unused settings | `openai_api_key`, `max_retries`, `reddit_*`, and the ignored `Field(env=...)` arguments. |
| Unused dependencies | Scrapy, nltk, html2text, chardet, motor, psycopg2-binary, aiohttp, asyncio-throttle, rich, pytz, uuid6, praw. Pick one scheduler (`schedule` or APScheduler). |
| `__main__` test blocks in Agents 2, 3 and 4, and `termcolor` | Covered by `pipeline.py --agents N --article-id X`. |

## 3. Merge duplicated code

| Change | What it does |
|---|---|
| One extractive summarizer | Keep either `agents/` or `utils/extractive_summarizer.py` (two different algorithms today), so the pipeline and the recap fallback give the same summary. |
| One LLM client library | Use the `openai` SDK for Groq and Ollama everywhere; drop the native `groq` SDK path; merge `groq_client.py` and `ollama_client.py`; read keys only from `settings`. Agent 4 no longer needs an LLM by default (`RISK_BACKEND=model`), so this now matters only for Agent 3, Agent 5 and personalization. |
| One LLM JSON-call helper for personalization | Replace the three copies in render, recap overview and insights, plus the identical `parse_response` and `parse_overview`. |
| One FAISS index | The pipeline and personalization indexes use the same model and text; keep one, with one rebuild script and an atomic save. |
| Merge `Neo4jWriter` into `Neo4jStore` | Removes duplicate connection code; stops the double `frequency` count; gives Agent 1's entities `MENTIONS` edges. |
| Set `name_lower` when writing entities | Removes the hourly `sync_name_lower` scan and the `coalesce(...)` fallbacks. |
| One payload-merge helper | Replace `_agent3_payload_from_doc`, `mongo_doc_to_agent4_payload` and the two `_resolve_article_fields`. |
| One FAISS similar-article search per article in `pipeline.py` | Currently runs twice; Agent 2 doesn't use the first result. |
| Table-driven MongoStore queue methods | Replace four pending-query/count pairs and four `update_article_*` methods with one table and one helper. |
| One windowed-date query | Replace three copies (`get_articles_published_since`, `PersArticleStore.window`, `backfill_media.py`). |
| Base class for store index setup | Replace the copy-pasted "create indexes once" pattern in four stores. |
| One entity-names/keys helper | Replace about eight similar loops across service, query graph, insights, Agent 5, the retriever and the summarizer. |
| Shared prompt helpers | One small module for `_escape`, `_clip` and article formatting, used by both `query_graph` and `insights`. |
| Shared text utilities | One stopword list, one name normalizer, one timestamp parser, one HH:MM parser, one `EPOCH` constant. |
| Shared JSON-LD and meta-tag reader | Used by both `web_scraper` and `image_extractor`. |
| Personalization helper merges | `topic_theta`/`topic_beta`, `entity_theta`/`best_entity_theta`, the alias-resolve helpers, `TOPIC_WORDS` and `span_days`, the why-line builder (4 copies), and the need/rel scoring loop (digest and feed). |
| Fix the `factcheck` ↔ `insights` circular import | **✅ Done** (`24b3287`): `new_names` now lives in `factcheck`. |
| Base class for the three news-API fetchers | Replace three near-identical classes with one class and a per-API field map. |
| Drop preprocessing's lexicon sentiment and the second language check | Agent 2 overwrites the sentiment; language is detected twice. |
| Shared doc → `ProcessedArticle` helper for scripts | Used by both `backfill_neo4j.py` and `rebuild_agent5_faiss.py`. |
| Public `score(payload)` on Agent 4 | **✅ Done** (`24b3287`): `backfill_a4.py` calls `agent.score(payload)`. |
| Move one-off migrations to `scripts/migrations/` | `backfill_dates`, `migrate_ner_misc_types`, `backfill_neo4j`. |
| One job table in `jobs.py` | Merge the parallel `JOBS` and `SCHEDULED` dicts and the repeated per-user loop. |
| `tests/conftest.py` and `tests/fakes.py` | **Partly done** (`24b3287`): both files exist. `test_agent4_backends.py` and the new `test_agent4_model.py` still define their own `FakeMongo`. |
| Shared stats helpers in research2 | One copy of `ci`, `rho`, `rel`, `write_json` and `sha256_file`. |
| Mobile: `useDwell` hook | Replaces the copy-pasted dwell tracking in `flash.tsx` and `recap/[kind].tsx`. |
| Mobile: one endpoint wrapper | Replaces the `built ? http(...) : mock.x(...)` repeated in every function. |
| Mobile: decide on mock mode | `mockServer.ts` and `fixtures.ts` (~970 lines) re-implement the engine; keep them only if offline demos are needed. |
| Mobile: one source of role wording | The backend and the app word roles differently ("own" vs "have a stake in"). |

## 4. Structure

| Change | What it does |
|---|---|
| Split `personalization/service.py` (2,503 lines after the stream and push work) | One module per section: profile, digest/feed, alerts, render, recaps, insights, app views, clustering. |
| Move the Insight models | From `utils/models.py` into `personalization/`. |
| Move `parse_ts` out of `personalization` | So `storage/` no longer depends on personalization. |
| Switch Agent 1 and `neo4j_writer` to loguru | **✅ Done** (`5342b07`): both use `utils.logger`. |
| Consolidate docs | Merge or archive the ~15 planning and audit files in `research/`. The README no longer mentions Reddit. The root now also holds `AGENT4_RISK_ARCHITECTURE.md`, `agent4_explanation.md`, `CONTINUOUS_STREAM_PLAN.md` and `continousexplanation.md`, which overlap in pairs. |

## 5. Small fixes found along the way

| Fix | What it does |
|---|---|
| `.gitignore` ignores `.env.example` | **✅ Done** (`13f943d`). |
| Pick one action-recommendation field name | **✅ Done in code** (`5342b07`). Older MongoDB documents still carry a stale `action_rec` field, which nothing reads. |
| Agent 4 model path on a fresh checkout | The shared zip unpacks to `models/mapnai_risk_event_model/risk_event/`, but `RISK_EVENT_MODEL_DIR` defaults to `models/risk_event`. If the folder isn't moved, Agent 4 silently drops to TF-IDF or the keyword rules. Make `run_mapnai.py --check` fail loudly, or set the path in `.env`. |

---

## Suggested order
1. ~~Safe deletions and dependency cleanup (section 2).~~ Done.
2. One summarizer, one LLM client, one FAISS index.
3. Fix the Neo4j double write.
4. Decide the ingestion scope (section 1), then trim to match.
5. Shared helpers, MongoStore tables, test fakes, and splitting `service.py`.
