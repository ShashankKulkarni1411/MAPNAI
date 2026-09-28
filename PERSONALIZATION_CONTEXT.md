# PERSONALIZATION_CONTEXT.md

Snapshot of what exists before the personalization engine is added. Taken 2026-09-29 from the code on
branch `agent-satvik` (8a8b086) plus read-only queries against the live MongoDB Atlas and Neo4j Aura
instances configured in `.env`.

---

## 1. App start, API, scheduler

- **There is no web server.** No FastAPI app, `APIRouter`, `include_router` or uvicorn entrypoint exists.
  `fastapi` and `uvicorn` are installed on the machine but nothing in the repo imports them.
- Entry points (all CLI, batch):
  - `python run_mapnai.py [--limit N] [--check]`: runs ingestion, then Agents 1-4 until the queues drain.
    `--check` only checks services, models and keys.
  - `python ingestion_pipeline.py [--schedule [--interval M]]`: fetch → preprocess → enrich → store
    (Mongo + FAISS + Neo4j).
  - `python pipeline.py [--limit N] [--agents 1,2,3,4] [--article-id ID] [--schedule [MIN]]`: runs Agents 1-4
    on articles already in Mongo.
  - `python -m agents.agent5_query ...` (argparse `main()`), plus `test_query.py`: interactive Q&A (Agent 5).
- **Port:** none. The only ports are the DBs in `docker-compose.yml` (Mongo 27017, Neo4j 7474/7687), and `.env`
  doesn't use them because it points at Atlas and Aura.
- **Scheduler:** the `schedule` library in a blocking `while True` loop: `ingestion_pipeline.run_with_schedule`
  (default 30 min, `INGESTION_INTERVAL_MINUTES`) and `pipeline.run_agent_pipeline_with_schedule` (default 15 min).
  `APScheduler==3.10.4` is listed in `requirements.txt` but never imported. There is no Celery or cron.

## 2. MongoDB

- DB `mapnai` (`MONGO_DB_NAME`) on Atlas (`mongodb+srv://…mapnai-cluster-2…`).
- Collections: `processed_articles` (955 docs), `ingestion_runs` (1 doc). The `articles` collection named in
  the `mongo_store.py` docstring does **not** exist.
- All 955 docs come from one ingestion run on 2026-09-28 (`ingested_at` 19:09 UTC). Source types: rss 909,
  gnews 46. Language: all `en`.

**Field map (`processed_articles`)**

| Concept | Field | Notes |
|---|---|---|
| id | `article_id` | UUID4 string, unique index. `_id` is an ObjectId and isn't used by the code |
| title | `title` | str |
| body | `body` | str (cleaned text; RSS bodies are often only a synopsis) |
| summary | `summary_short`, `summary_long` | str or null; Agent 3; set on 385 docs |
| published | `published_at` | **ISO-8601 string** (e.g. `"2026-09-26T05:03:00+00:00"`), not a BSON Date. Range 2016-08-18 → 2026-09-28 |
| ingested | `ingested_at` | ISO string **without tz** (naive UTC from `datetime.utcnow`) |
| entities | `entities` | list of **objects** `{name, type, salience, domain?}`. `domain` is on 3517/4556 entities. Agent 1 also writes `mention_count` (none stored yet). **No entity id, ticker or alias.** Types: Person 1641, Organization 1580, Location 1164, Event 119, Product/Technology 52 |
| topic/domain | `domain` | preprocess domain, overwritten by Agent 2. Values: other 394, sports 303, entertainment_movies 185, finance 37, supply_chain 10, geopolitics 9, health 9, technology 8 |
| category | `category` | Agent 2 label: sports / entertainment_movies / other / null (174 unclassified) |
| scope | `in_scope` | true 385, false 396, missing 174 |
| other tags | `topic_tags` (list[str], keyword-rule tags), `keywords` (list[str]) | |
| sentiment | `sentiment_score` (float −1..1), `sentiment_label` | |
| urgency | `urgency_flag` | bool |
| A4 risk | `risk_score` (int 0-100), `risk_confidence`, `risk_level` (MONITOR/ALERT/ESCALATE), `risk_reasoning` {event_severity, entity_salience, temporal_urgency, domain_criticality: 0-25 each}, `action_recommendation`, `risk_processed(_at)` | **Min/max are unavailable because `risk_score` is null on all 955 docs** (`risk_processed=true` on 0) |
| A4 facts | none | A4 extracts no event type or magnitude. Its only structured output is the `risk_reasoning` sub-scores above. `action_rec` (model field, always null) is separate from `action_recommendation` (what A4 actually writes) |
| url | `url` | |
| source | `source_name` (e.g. "BBC World"), `source_type` (rss/gnews), `raw_source` (feed URL or API name) | |
| country/locality | none | only indirectly, through `Location` entities |
| dedup/cluster | `dedup_hash` (SimHash hex, indexed) | no cluster or story id. Dedup drops articles at ingest (474 dropped in the last run) instead of grouping them |
| vector ref | `embedding_id` | **null on all 955** (see §5) |
| pipeline flags | `ner_processed` 883, `classification_processed` 781, `summarization_processed` 385, `risk_processed` 0 (+ `*_processed_at` ISO strings), `ner_metadata.model_used` = `ingestion-enrichment-fallback` for all | |

**Sample article** (real doc, trimmed):
```json
{
  "article_id": "0a0afffd-983d-40da-ad9d-1658ba4435fc",
  "title": "Before BTS and Blackpink, there was Big Bang: Now the Kings of K-pop are back",
  "summary_short": "Big Bang played London's Tottenham Hotspur Stadium, marking a long-awaited return for the group that helped build the blueprint for modern K-pop.",
  "published_at": "2026-09-27T03:21:23+00:00",
  "ingested_at": "2026-09-28T19:09:16.310939",
  "domain": "entertainment_movies", "category": "entertainment_movies",
  "classification_confidence": 0.972, "in_scope": true, "taxonomy_version": "2.0.0",
  "entities": [
    {"name": "Big Bang", "type": "Location", "salience": 1.0, "domain": "geopolitics"},
    {"name": "BTS", "type": "Organization", "salience": 0.5, "domain": "geopolitics"},
    {"name": "London", "type": "Location", "salience": 0.5, "domain": "geopolitics"}
  ],
  "topic_tags": ["Technology"], "sentiment_score": 0.699, "sentiment_label": "positive",
  "urgency_flag": false, "risk_score": null, "embedding_id": null,
  "dedup_hash": "a1c1995265233ec1",
  "source_name": "BBC World", "source_type": "rss",
  "raw_source": "http://feeds.bbci.co.uk/news/world/rss.xml",
  "url": "https://www.bbc.co.uk/news/articles/cq39me84zrkdo?..."
}
```
Data quality in this sample: `entities[].domain` holds the preprocess domain, so it disagrees with the article's
`domain`. The fallback NER also mis-types entities ("Big Bang" is tagged as a Location).

- Indexes: `article_id` (unique), `dedup_hash`, `domain`, `published_at`, `ingested_at`, `source_name`,
  `language`, the 4 `*_processed` flags, and a text index on `title`+`body`.

## 3. User / persona collections

**None.** There is no users, profiles, personas, interactions or feedback collection, and no user model in the code.
The only "persona" is Agent 3's tone switch keyed on article `domain` (`agents/agent3_summarizer.py:43-58`),
which doesn't depend on the reader.

## 4. Neo4j

- `.env` → `neo4j+s://87c28f45.databases.neo4j.io` (Aura). The credentials were updated today and the old
  instance `387a7a7b` no longer resolves in DNS.
- **The live instance is empty.** `db.labels()`, `db.relationshipTypes()` and `db.propertyKeys()` return `[]`.
  There are 0 nodes, 0 relationships and 0 constraints. The Mongo data was never written to this instance.
- The schema the code *would* write:
  - `storage/neo4j_store.py` (ingestion):
    - `(:Article {article_id, title, domain, source_name, published_at, ingested_at, url})`
    - `(:Entity {name, type, first_seen, last_seen, frequency})`, where node key = `(name, type)`
    - `(:Domain {name})`, `(:Source {name})`
    - `(Article)-[:BELONGS_TO]->(Domain)`, `(Article)-[:PUBLISHED_BY]->(Source)`
    - `(Article)-[:MENTIONS {salience}]->(Entity)`
    - `(Entity)-[:MENTIONED_WITH {count, article_ids[]}]-(Entity)`: co-occurrence, merged undirected
      and capped at 5000 pairs per batch
  - `agents/neo4j_writer.py` (Agent 1): MERGE `(:Entity {name, type})` and set `domain`, `article_ids[]` and
    `frequency` (+= mention_count). It creates **no** relationships.
- Entities live on `:Entity`, keyed by `name`+`type`. There is no id, ticker or alias property. The only edge weight
  is `MENTIONED_WITH.count` (raw co-occurrence). No weight or PMI is stored.
- Existing read helpers: `get_entity_neighbors` (MENTIONED_WITH 1..depth), `get_articles_by_entity`,
  `get_top_entities`, `get_graph_stats`. No agent calls them.
- The per-relationship-type `MATCH (a)-[r]->(b) LIMIT 5` samples returned nothing because the graph has no types.

## 5. FAISS

- Path: `data/faiss_index` + `data/faiss_metadata.pkl` (`FAISS_INDEX_PATH`/`FAISS_METADATA_PATH`). **Both are
  tracked in git.**
- `IndexFlatIP`, dim 384, metric IP. `ntotal` = 687. Vectors are L2-normalized, so IP equals cosine.
- Embedding model: `sentence-transformers` `all-MiniLM-L6-v2` (`EMBEDDING_MODEL`). The embedded text is
  `f"{title}. {body[:300]}"`.
- Row → article: `metadata[i]` (a pickled list of dicts) is parallel to row `i`:
  `{faiss_idx: i, article_id, title, domain, url, source, published}`. `faiss_idx == position` for all 687 rows,
  with no duplicate ids. Mongo `embedding_id` is meant to hold `str(i)`, but `_store_phase` upserts Mongo *before*
  FAISS assigns it, so it is always null. **The only reliable mapping is `metadata[i]["article_id"]`.**
- `reconstruct(i)` works: it returns a (384,) vector with norm 1.0.
- Updates: append-only in `ingestion_pipeline._store_phase` (`add_articles` then `save()`) on every ingestion
  run. Nothing is ever deleted or re-embedded, and ids are not checked, so duplicates are possible.
- **The index is stale. None of its 687 `article_id`s exist in Mongo (0/687).** It holds May 2026 articles
  (published up to 2026-05-16; domains technology, geopolitics, finance, health, supply_chain). The 2026-09-28
  ingestion into Atlas did not update the local index (git shows the file unchanged since commit 9ebfad4).

## 6. Agents

| Agent | File | Output / storage | LLM |
|---|---|---|---|
| Ingestion enrichment | `agents/enrichment_agent.py` | spaCy entities `{name,type,salience}` → `entities` | none |
| A1 NER | `agents/ner_agent.py` (+`ner_utils.py`, `neo4j_writer.py`) | `entities`, `ner_processed`, `ner_metadata` in Mongo; Entity nodes in Neo4j | local BERT `models/mapnai-ner-bert`, spaCy fallback (every stored doc used the fallback) |
| A2 classifier | `agents/agent2_classifier.py`, `classifier_model.py` | `domain`, `category`, `in_scope`, `classification_confidence`, sentiment | own HF model `satvik4577/mapnai-classifier` → `models/classifier` (auto-downloads; not present locally now) |
| A3 summarizer | `agents/agent3_summarizer.py`, `extractive_summarizer.py` | `summary_short`, `summary_long` | Groq when `SUMMARIZER_BACKEND=auto` and a key is set, otherwise extractive TF-IDF |
| A4 risk | `agents/agent4_risk_scorer.py` | `MongoStore.update_article_risk` → `$set` on `processed_articles` (fields in §2) | Groq (OpenAI client with the Groq base URL), `GROQ_MODEL` default `llama-3.3-70b-versatile`, JSON mode |
| A5 query | `agents/agent5_query.py`, `query_retriever.py`, `query_llm.py` | answers only (not stored); hybrid Mongo keyword + FAISS retrieval | Groq (`groq` SDK), offline fallback; `CustomModelQueryLLM` placeholder |
| **A6** | **does not exist** | there is no rendering/rewrite agent and no reference to "Agent 6" anywhere in the code | n/a |

## 7. Python and dependencies

- Dependency file: `requirements.txt` (pinned). There is no pyproject, poetry or venv in the repo.
- Two interpreters are installed, and **neither has the full requirements**:
  - Python 3.13.3 (default `python`): sentence-transformers, apscheduler, faiss, pymongo, neo4j and groq are
    **missing**. scipy 1.15.2, fastapi 0.116.1, uvicorn 0.35.0, celery 5.4.0, schedule 1.2.2, torch 2.12.1 and
    transformers 5.8.1 are present. numpy 1.26.4 is an experimental build on 3.13 and **segfaults** on import in
    some combinations.
  - Python 3.10 (`py -3.10`): sentence-transformers 5.3.0, faiss-cpu 1.13.2, scipy 1.15.3, numpy 2.2.6 and
    openai 2.44.0 are present. **apscheduler, pymongo, neo4j and groq are missing.**
- Installed versions don't match the pins (e.g. requirements say sentence-transformers 3.0.1, faiss-cpu 1.8.0,
  numpy 1.26.4).
- The DB queries for this doc used pymongo and neo4j installed into a temporary scratch directory, outside the
  project.

## 8. Open questions

1. Which interpreter/venv actually runs the pipeline? Neither local Python has `pymongo` and `neo4j`, yet the
   2026-09-28 run wrote to Atlas.
2. Why the 2026-09-28 run didn't update `data/faiss_index`: it may have run on another machine, or FAISS was
   unavailable. Should the index move out of git and be rebuilt from Mongo?
3. Neo4j is empty. Should the graph be backfilled from Mongo `entities`, and should the old instance `387a7a7b`
   be restored?
4. A4 has never run on this data (0 scored), so the real distribution of `risk_score`, `risk_level` and
   `action_recommendation` is unknown.
5. Is entity quality from the spaCy fallback (wrong types, fragments like "Synopsis Upcoming") good enough to key
   user interests on, or should the BERT model (present in `models/mapnai-ner-bert` but unused in the stored
   run) be fixed first?
6. Target domains: the classifier covers sports and entertainment_movies, plus `other`. Legacy domains
   (finance, geopolitics, …) remain on older rows and in FAISS metadata.
7. There's no API surface, so the delivery channel for personalization is undecided (new FastAPI service or CLI).
8. `published_at` is a string, and `ingested_at` is a naive string. Should recency logic parse them, or should
   they be migrated to BSON Date?
