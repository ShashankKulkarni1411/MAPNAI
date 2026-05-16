# Graph Report - .  (2026-05-16)

## Corpus Check
- Corpus is ~18,382 words - fits in a single context window. You may not need a graph.

## Summary
- 485 nodes · 857 edges · 27 communities (16 shown, 11 thin omitted)
- Extraction: 64% EXTRACTED · 36% INFERRED · 0% AMBIGUOUS · INFERRED: 306 edges (avg confidence: 0.66)
- Token cost: 0 input · 0 output

## Community Hubs (Navigation)
- [[_COMMUNITY_FAISS Vector Storage|FAISS Vector Storage]]
- [[_COMMUNITY_Text Cleaning Tests|Text Cleaning Tests]]
- [[_COMMUNITY_RSS & News Fetchers|RSS & News Fetchers]]
- [[_COMMUNITY_Deduplication Engine|Deduplication Engine]]
- [[_COMMUNITY_NER Pipeline & Mongo|NER Pipeline & Mongo]]
- [[_COMMUNITY_Preprocessing Agent|Preprocessing Agent]]
- [[_COMMUNITY_NER Agent & Entities|NER Agent & Entities]]
- [[_COMMUNITY_Neo4j Graph Storage|Neo4j Graph Storage]]
- [[_COMMUNITY_News API Client|News API Client]]
- [[_COMMUNITY_README Architecture|README Architecture]]
- [[_COMMUNITY_Main Ingestion Pipeline|Main Ingestion Pipeline]]
- [[_COMMUNITY_Enrichment Agent|Enrichment Agent]]
- [[_COMMUNITY_Web Scraper|Web Scraper]]
- [[_COMMUNITY_Reddit Fetcher|Reddit Fetcher]]
- [[_COMMUNITY_Configuration Settings|Configuration Settings]]
- [[_COMMUNITY_Project Overview|Project Overview]]
- [[_COMMUNITY_Centralized Logging|Centralized Logging]]
- [[_COMMUNITY_Fetcher Test Notes|Fetcher Test Notes]]
- [[_COMMUNITY_Fetcher Test Notes|Fetcher Test Notes]]
- [[_COMMUNITY_Fetcher Test Notes|Fetcher Test Notes]]
- [[_COMMUNITY_Fetcher Test Notes|Fetcher Test Notes]]
- [[_COMMUNITY_Storage Test Notes|Storage Test Notes]]
- [[_COMMUNITY_Storage Test Notes|Storage Test Notes]]
- [[_COMMUNITY_Storage Test Notes|Storage Test Notes]]
- [[_COMMUNITY_Storage Test Notes|Storage Test Notes]]
- [[_COMMUNITY_Storage Test Notes|Storage Test Notes]]
- [[_COMMUNITY_Storage Test Notes|Storage Test Notes]]

## God Nodes (most connected - your core abstractions)
1. `Domain` - 42 edges
2. `PreprocessingAgent` - 35 edges
3. `SourceType` - 32 edges
4. `MongoStore` - 29 edges
5. `RawArticle` - 29 edges
6. `Neo4jStore` - 25 edges
7. `ArticleDeduplicator` - 25 edges
8. `ProcessedArticle` - 20 edges
9. `FAISSStore` - 19 edges
10. `NewsAPIFetcher` - 18 edges

## Surprising Connections (you probably didn't know these)
- `_get_mongo()` --calls--> `MongoStore`  [INFERRED]
  ingestion_pipeline.py → storage/mongo_store.py
- `_get_faiss()` --calls--> `FAISSStore`  [INFERRED]
  ingestion_pipeline.py → storage/faiss_store.py
- `_get_neo4j()` --calls--> `Neo4jStore`  [INFERRED]
  ingestion_pipeline.py → storage/neo4j_store.py
- `_fetch_phase()` --calls--> `fetch_all_rss_sources()`  [INFERRED]
  ingestion_pipeline.py → agents/rss_fetcher.py
- `_fetch_phase()` --calls--> `fetch_all_apis()`  [INFERRED]
  ingestion_pipeline.py → agents/api_fetcher.py

## Hyperedges (group relationships)
- **Ingestion Source Fetchers** — readme_rss_fetcher, readme_api_fetcher, readme_reddit_fetcher, readme_web_scraper [EXTRACTED 1.00]
- **Triple Storage Backends** — readme_mongodb, readme_faiss, readme_neo4j [EXTRACTED 1.00]

## Communities (27 total, 11 thin omitted)

### Community 0 - "FAISS Vector Storage"
Cohesion: 0.06
Nodes (38): BaseModel, Enum, FAISSStore, _get_faiss(), _get_model(), _load_faiss(), _load_sentence_transformer(), MAPNAI — storage/faiss_store.py FAISS Vector Store Stores article embeddings for (+30 more)

### Community 1 - "Text Cleaning Tests"
Cohesion: 0.05
Nodes (29): MAPNAI — tests/test_preprocessing.py Unit tests for preprocessing agent, text cl, TestCleanText, TestDomainClassification, TestLanguageDetection, TestNormalizeWhitespace, TestQualityGates, TestRemoveURLs, TestStripHTML (+21 more)

### Community 2 - "RSS & News Fetchers"
Cohesion: 0.06
Nodes (34): GNewsFetcher, NewsAPIFetcher, Wraps https://gnews.io/api/v4/search     Docs: https://gnews.io/docs/     Free t, Wraps https://newsapi.org/v2/everything     Docs: https://newsapi.org/docs/endpo, _extract_body(), fetch_all_rss_sources(), _fetch_feed(), fetch_rss_source() (+26 more)

### Community 3 - "Deduplication Engine"
Cohesion: 0.07
Nodes (20): TestArticleDeduplicator, TestSimHash, ArticleDeduplicator, compute_simhash(), is_near_duplicate_simhash(), MinHashDeduplicator, MAPNAI — utils/deduplicator.py Cross-source deduplication using SimHash (primary, Reset LSH index (e.g., between ingestion runs if memory is a concern). (+12 more)

### Community 4 - "NER Pipeline & Mongo"
Cohesion: 0.06
Nodes (23): MAPNAI — pipeline.py Agent 1 Pipeline: NER & Entity Extraction  Runs AFTER the i, Fetch articles pending NER from MongoDB and process them through Agent 1.     Re, Poll for new ingested articles and run NER on each interval., run_ner_pipeline(), run_ner_with_schedule(), db(), MongoStore, MAPNAI — storage/mongo_store.py MongoDB Storage Layer Handles all read/write ope (+15 more)

### Community 5 - "Preprocessing Agent"
Cohesion: 0.11
Nodes (19): extract_keywords(), extract_topic_tags(), lexicon_sentiment(), PreprocessingAgent, MAPNAI — agents/preprocessing_agent.py Agent 2: Preprocessing Agent Receives raw, Stateful agent that holds deduplication state across a batch.     One instance p, Process a single RawArticle.         Returns (ProcessedArticle, "ok") or (None,, Process a batch of raw articles.         Logs per-batch statistics on completion (+11 more)

### Community 6 - "NER Agent & Entities"
Cohesion: 0.08
Nodes (24): _build_output(), mongo_doc_to_article_input(), mongo_doc_to_processed_article(), NERAgent, _normalize_domain(), MAPNAI — agents/ner_agent.py Agent 1: Named Entity Recognition & Entity Extracti, Agent 1 — NER & entity extraction.      Typical usage after ingestion:         a, Lazy-load spaCy model (trf preferred, sm fallback). (+16 more)

### Community 7 - "Neo4j Graph Storage"
Cohesion: 0.08
Nodes (15): Neo4jWriter, MAPNAI — agents/neo4j_writer.py Backward-compatible wrapper around storage.neo4j, Delegates entity upserts to the ingestion layer Neo4jStore., driver(), Neo4jStore, MAPNAI — storage/neo4j_store.py Neo4j Knowledge Graph Storage Layer Stores artic, Create :Entity nodes and (Article)-[:MENTIONS]->(Entity) edges.         Also bui, For each article, create MENTIONED_WITH edges between all entity pairs. (+7 more)

### Community 8 - "News API Client"
Cohesion: 0.11
Nodes (13): fetch_all_apis(), _get_json(), NewsDataFetcher, MAPNAI — agents/api_fetcher.py Agent 1b: News API Fetcher Fetches from NewsAPI,, Wraps https://newsdata.io/api/1/news     Docs: https://newsdata.io/documentation, Make a GET request and return JSON, with retry logic., Fetch from all three news APIs and combine results., test_rate_limit_429_raises() (+5 more)

### Community 9 - "README Architecture"
Cohesion: 0.09
Nodes (24): API Fetcher, Enrichment Agent, FAISS Vector Store, GraphRAG, MinHash LSH Deduplication, MongoDB Storage, Neo4j Knowledge Graph, Preprocessing Agent (+16 more)

### Community 10 - "Main Ingestion Pipeline"
Cohesion: 0.12
Nodes (21): _decode_frame(), fetch_all_bluesky(), fetch_bluesky_firehose(), MAPNAI — agents/bluesky_fetcher.py Agent 1c: Bluesky Firehose Social Signal Fetc, Fetch a batch of Bluesky Firehose posts.     Drop-in replacement for fetch_all_r, Decode a single firehose WebSocket frame.      Each frame is a CBOR-encoded enve, Connect to the Bluesky Firehose and collect up to *max_posts* posts.      Args:, _fetch_phase() (+13 more)

### Community 11 - "Enrichment Agent"
Cohesion: 0.2
Nodes (10): EnrichmentAgent, extract_entities(), _get_nlp(), _load_spacy_model(), MAPNAI — agents/enrichment_agent.py Agent 3: Enrichment Agent (Ingestion Layer), Adds entity annotations to ProcessedArticle objects in-place.     Designed to ru, Enrich a single article with entity data.         Returns the same article objec, Enrich a batch of articles with entities.         Returns enriched article list. (+2 more)

### Community 12 - "Web Scraper"
Cohesion: 0.27
Nodes (9): _fetch_page(), _normalize_url(), MAPNAI — agents/web_scraper.py Agent 1d: Web Scraper Scrapes non-RSS news source, Run all scraper targets. Failures in one don't stop others., Fetch an HTML page and return BeautifulSoup object., Convert relative URLs to absolute., Scrape a single target site.     1. Fetch listing page → extract article URLs, scrape_all_targets() (+1 more)

### Community 13 - "Reddit Fetcher"
Cohesion: 0.32
Nodes (7): fetch_all_reddit(), fetch_subreddit(), _get_reddit_client(), MAPNAI — agents/reddit_fetcher.py Agent 1c: Reddit Social Signals Fetcher Uses P, Fetch all configured subreddits.     Returns combined list of RawArticle objects, Initialize PRAW Reddit client. Returns None if credentials missing., Fetch hot+top posts from a subreddit.     Filters for posts with meaningful text

### Community 14 - "Configuration Settings"
Cohesion: 0.33
Nodes (6): BaseSettings, Config, get_settings(), MAPNAI — config/settings.py Central configuration loaded from .env via pydantic-, Cached singleton settings instance., Settings

### Community 15 - "Project Overview"
Cohesion: 0.67
Nodes (3): AutoGen Agent Pattern, MAPNAI Ingestion Layer, Multi-Agent Personalized News Intelligence

## Knowledge Gaps
- **18 isolated node(s):** `Config`, `ScraperTarget`, `Multi-Agent Personalized News Intelligence`, `API Fetcher`, `Web Scraper` (+13 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **11 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `Domain` connect `Preprocessing Agent` to `FAISS Vector Storage`, `Text Cleaning Tests`, `RSS & News Fetchers`, `Deduplication Engine`, `NER Agent & Entities`, `News API Client`, `Web Scraper`, `Reddit Fetcher`?**
  _High betweenness centrality (0.248) - this node is a cross-community bridge._
- **Why does `ProcessedArticle` connect `FAISS Vector Storage` to `NER Pipeline & Mongo`, `Preprocessing Agent`, `NER Agent & Entities`, `Neo4j Graph Storage`, `Enrichment Agent`?**
  _High betweenness centrality (0.163) - this node is a cross-community bridge._
- **Why does `MongoStore` connect `NER Pipeline & Mongo` to `FAISS Vector Storage`, `Main Ingestion Pipeline`, `NER Agent & Entities`?**
  _High betweenness centrality (0.128) - this node is a cross-community bridge._
- **Are the 39 inferred relationships involving `Domain` (e.g. with `NewsAPIFetcher` and `GNewsFetcher`) actually correct?**
  _`Domain` has 39 INFERRED edges - model-reasoned connections that need verification._
- **Are the 29 inferred relationships involving `PreprocessingAgent` (e.g. with `RawArticle` and `ProcessedArticle`) actually correct?**
  _`PreprocessingAgent` has 29 INFERRED edges - model-reasoned connections that need verification._
- **Are the 29 inferred relationships involving `SourceType` (e.g. with `NewsAPIFetcher` and `GNewsFetcher`) actually correct?**
  _`SourceType` has 29 INFERRED edges - model-reasoned connections that need verification._
- **Are the 13 inferred relationships involving `MongoStore` (e.g. with `NERAgent` and `ProcessedArticle`) actually correct?**
  _`MongoStore` has 13 INFERRED edges - model-reasoned connections that need verification._