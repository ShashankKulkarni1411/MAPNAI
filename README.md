# MAPNAI — Ingestion Layer
### Multi-Agent Personalized News & Action Intelligence
**K.J. Somaiya School of Engineering, Mumbai-77 | Dept. of Computer Engineering | 2025–27**
*Satvik R Gupta · Shashank A Kulkarni · Shaunak M Khandkar | Guide: Dr. Jyoti Joglekar*

---

## Overview

This is the complete **Layer 1 (Ingestion Layer)** of the MAPNAI system. It ingests news from **30+ RSS feeds, 3 news APIs, 12 subreddits, and 3 scraper targets**, cleans and deduplicates them, enriches with named entities, and writes to **3 storage backends simultaneously**: MongoDB, FAISS, and Neo4j.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                        INGESTION PIPELINE                           │
│                                                                     │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌────────┐  │
│  │  RSS Fetcher │  │  API Fetcher │  │Reddit Fetcher│  │Scraper │  │
│  │  (30+ feeds) │  │(NewsAPI/GNews│  │(12 subreddits│  │(3 sites│  │
│  │              │  │  /NewsData)  │  │              │  │        │  │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘  └───┬────┘  │
│         └─────────────────┴─────────────────┴──────────────┘       │
│                                    │                                │
│                                    ▼                                │
│                    ┌───────────────────────────┐                    │
│                    │   PREPROCESSING AGENT      │                   │
│                    │  • HTML/URL removal        │                   │
│                    │  • Encoding fix (ftfy)     │                   │
│                    │  • Language detection      │                   │
│                    │  • SimHash deduplication   │                   │
│                    │  • MinHash deduplication   │                   │
│                    │  • Timestamp → UTC ISO8601 │                   │
│                    │  • Domain classification   │                   │
│                    │  • Sentiment scoring       │                   │
│                    │  • Keyword extraction      │                   │
│                    └───────────────────────────┘                    │
│                                    │                                │
│                                    ▼                                │
│                    ┌───────────────────────────┐                    │
│                    │    ENRICHMENT AGENT        │                   │
│                    │  • spaCy NER               │                   │
│                    │  • Entity salience scoring │                   │
│                    │  • Topic tag extraction    │                   │
│                    └───────────────────────────┘                    │
│                                    │                                │
│              ┌─────────────────────┼──────────────────────┐        │
│              ▼                     ▼                       ▼        │
│     ┌────────────────┐  ┌──────────────────┐  ┌─────────────────┐  │
│     │    MongoDB     │  │  FAISS Vector    │  │  Neo4j Graph    │  │
│     │  (full text +  │  │  (semantic       │  │  (entities +    │  │
│     │   metadata)    │  │   embeddings)    │  │   relationships)│  │
│     └────────────────┘  └──────────────────┘  └─────────────────┘  │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Project Structure

```
mapnai_ingestion/
│
├── ingestion_pipeline.py        ← MAIN ENTRY POINT — run this
│
├── agents/
│   ├── rss_fetcher.py           ← RSS feed fetcher (feedparser)
│   ├── api_fetcher.py           ← NewsAPI / GNews / NewsData.io
│   ├── reddit_fetcher.py        ← Reddit via PRAW
│   ├── web_scraper.py           ← BeautifulSoup scraper
│   ├── preprocessing_agent.py  ← Cleaning, dedup, normalization
│   └── enrichment_agent.py     ← spaCy NER enrichment
│
├── config/
│   ├── settings.py              ← Pydantic settings (loads from .env)
│   └── sources.py               ← ALL source definitions (RSS, Reddit, etc.)
│
├── storage/
│   ├── mongo_store.py           ← MongoDB read/write layer
│   ├── faiss_store.py           ← FAISS vector store
│   └── neo4j_store.py           ← Neo4j knowledge graph
│
├── utils/
│   ├── models.py                ← Pydantic data models
│   ├── text_cleaner.py          ← Cleaning, language, timestamp utils
│   ├── deduplicator.py          ← SimHash + MinHash deduplication
│   └── logger.py                ← Loguru centralized logging
│
├── tests/
│   ├── test_preprocessing.py    ← Preprocessing + dedup unit tests
│   ├── test_storage.py          ← Storage layer tests (mocked)
│   └── test_fetchers.py         ← Fetcher + config tests (mocked)
│
├── data/                        ← FAISS index persisted here
├── logs/                        ← Log files
├── .env.example                 ← Environment template
├── pytest.ini
└── requirements.txt
```

---

## Quick Start

### 1. Install dependencies

```bash
cd mapnai_ingestion
pip install -r requirements.txt
```

Install spaCy model for NER enrichment:
```bash
python -m spacy download en_core_web_sm
```

### 2. Configure environment

```bash
cp .env.example .env
# Edit .env and add your API keys
```

Minimum required to run (at least one news source):
```env
NEWSAPI_KEY=your_key_here          # or leave blank to use only RSS
MONGO_URI=mongodb://localhost:27017
NEO4J_URI=bolt://localhost:7687
NEO4J_PASSWORD=your_password
```

### 3. Run a single ingestion cycle

```bash
python ingestion_pipeline.py
```

Expected output:
```
2026-04-19 10:00:00 | INFO     | [Pipeline] INGESTION RUN STARTED — a1b2c3d4
2026-04-19 10:00:01 | INFO     | [RSS] Fetched 12 articles from Reuters Business
2026-04-19 10:00:02 | INFO     | [RSS] Fetched 9 articles from BBC World
...
2026-04-19 10:00:45 | INFO     | [Pipeline] FETCH PHASE COMPLETE — Total raw: 847
2026-04-19 10:01:10 | INFO     | [Preprocessing] Batch complete | Input=847 | Processed=612 | Dupes=198 | QualityFail=37
2026-04-19 10:01:15 | INFO     | [Enrichment] Enriched 589/612 articles with entities.
2026-04-19 10:01:20 | INFO     | [MongoDB] Upserted 612 new + 0 updated articles.
2026-04-19 10:01:35 | INFO     | [FAISS] Added 612 vectors. Total index size: 612
2026-04-19 10:01:50 | INFO     | [Neo4j] Upserted 612 article nodes.
2026-04-19 10:01:51 | INFO     | [Pipeline] RUN COMPLETE — Run a1b2c3d4 | Fetched=847 | Cleaned=612 | Dupes=198 | Stored=612
✅ Run a1b2c3d4 | Fetched=847 | Cleaned=612 | Dupes=198 | Stored=612
```

### 4. Run on a schedule (every 30 minutes)

```bash
python ingestion_pipeline.py --schedule
```

Custom interval:
```bash
python ingestion_pipeline.py --schedule --interval 60
```

---

## Running Tests

```bash
# All tests
pytest

# Specific test file
pytest tests/test_preprocessing.py -v

# With coverage
pip install pytest-cov
pytest --cov=. --cov-report=html
```

Tests use mocks — no real MongoDB / FAISS / Neo4j needed.

---

## Data Model

Every article that exits the preprocessing stage is a `ProcessedArticle`:

```json
{
  "article_id":      "3f7a2b1c-...",
  "title":           "RBI cuts repo rate by 25bps",
  "body":            "The Reserve Bank of India...",
  "url":             "https://economictimes.com/...",
  "source_name":     "Economic Times",
  "source_type":     "rss",
  "domain":          "finance",
  "raw_source":      "https://economictimes.com/rssfeedstopstories.cms",
  "published_at":    "2026-04-19T05:30:00Z",
  "ingested_at":     "2026-04-19T10:00:45Z",
  "language":        "en",
  "dedup_hash":      "a1b2c3d4e5f60001",
  "entities":        [
    {"name": "RBI",          "type": "ORG", "salience": 1.0},
    {"name": "India",        "type": "GPE", "salience": 0.8},
    {"name": "Shaktikanta Das", "type": "PERSON", "salience": 0.6}
  ],
  "sentiment_score": -0.1,
  "sentiment_label": "neutral",
  "keywords":        ["reserve", "bank", "repo", "rate", "inflation"],
  "topic_tags":      ["Finance", "Interest Rates"],
  "risk_score":      null,
  "summary_short":   null,
  "embedding_id":    "612"
}
```

---

## Source Coverage

| Category | Count | Examples |
|----------|-------|---------|
| Finance RSS | 10 | Reuters Business, Bloomberg, CNBC, ET, Mint |
| Geopolitics RSS | 8 | BBC World, Al Jazeera, Foreign Policy, NDTV |
| Technology RSS | 8 | TechCrunch, The Verge, MIT Tech Review, Wired |
| Health RSS | 6 | WHO, NIH, CDC, STAT News |
| Supply Chain RSS | 4 | Supply Chain Dive, Logistics Management |
| Government RSS | 8 | RBI, IMF, World Bank, SEBI, US Fed, UN |
| Reddit | 12 | r/worldnews, r/economics, r/technology, r/investing |
| Scrapers | 3 | Business Standard, LiveMint, NDTV |
| News APIs | 3 | NewsAPI, GNews, NewsData.io |
| **Total sources** | **~62** | |

---

## Deduplication Strategy

Two-stage deduplication (as per MAPNAI spec Section 3):

1. **SimHash** (Charikar 2002): 64-bit fingerprint on title + first 500 chars. Hamming distance ≤ 3 → duplicate. Fast O(n) in-memory scan per run. DB seeding for cross-run deduplication.

2. **MinHash LSH** (datasketch): Jaccard similarity via LSH. Threshold ≥ 0.5 → duplicate. Catches paraphrase duplicates (same story, different wording) that SimHash misses.

---

## Storage Architecture

### MongoDB
- Collection: `processed_articles`
- Indexes: `article_id` (unique), `dedup_hash`, `domain`, `published_at`, `source_name`
- Full-text index on `title + body` (backup search)

### FAISS
- Index type: `IndexFlatIP` (cosine similarity via normalized inner product)
- Embedding: `all-MiniLM-L6-v2` (384 dimensions, fast CPU inference)
- Persisted to `./data/faiss_index` between runs

### Neo4j
- Nodes: `Article`, `Entity`, `Domain`, `Source`
- Edges: `BELONGS_TO`, `MENTIONS` (with salience), `MENTIONED_WITH` (co-occurrence), `PUBLISHED_BY`
- Constraints: `article_id` unique, `(entity.name, entity.type)` node key

---

## Adding New Sources

### Add an RSS feed
In `config/sources.py`:
```python
FINANCE_RSS.append(
    RSSSource("My New Feed", "https://example.com/rss.xml", "finance")
)
```

### Add a subreddit
```python
REDDIT_SOURCES.append(
    RedditSource("IndiaInvestments", "finance", post_limit=20)
)
```

No other code changes needed — the pipeline picks up changes automatically.

---

## Environment Variables Reference

| Variable | Default | Description |
|----------|---------|-------------|
| `NEWSAPI_KEY` | — | NewsAPI.org key |
| `GNEWS_API_KEY` | — | GNews.io key |
| `NEWSDATA_API_KEY` | — | NewsData.io key |
| `REDDIT_CLIENT_ID` | — | Reddit app client ID |
| `REDDIT_CLIENT_SECRET` | — | Reddit app secret |
| `MONGO_URI` | `mongodb://localhost:27017` | MongoDB connection |
| `MONGO_DB_NAME` | `mapnai` | Database name |
| `NEO4J_URI` | `bolt://localhost:7687` | Neo4j connection |
| `NEO4J_USER` | `neo4j` | Neo4j username |
| `NEO4J_PASSWORD` | `password` | Neo4j password |
| `FAISS_INDEX_PATH` | `./data/faiss_index` | FAISS index file |
| `EMBEDDING_MODEL` | `all-MiniLM-L6-v2` | Sentence transformer |
| `INGESTION_INTERVAL_MINUTES` | `30` | Schedule interval |
| `MAX_ARTICLES_PER_SOURCE` | `50` | Per-source cap |
| `MIN_ARTICLE_LENGTH` | `100` | Min body length (chars) |

---

## Papers Implemented

| Paper | What's implemented |
|-------|--------------------|
| AutoGen (Wu et al., 2023) | Agent communication pattern — each agent produces structured JSON consumed by next |
| Self-RAG (Asai et al., 2023) | Enriched fields (`entities`, `keywords`, `topic_tags`) feed the Self-RAG router in Layer 3 |
| GraphRAG (Edge et al., 2024) | Neo4j co-occurrence graph built during ingestion; consumed by GraphRAG in Layer 3 |
| NER Survey (Keraghel et al., 2024) | spaCy used for ingestion-time NER; GLiNER integration point marked in `enrichment_agent.py` |
| RAG Survey (Gupta et al., 2024) | FAISS + metadata store pattern matches survey recommendations |

---

*MAPNAI Ingestion Layer v1.0 — April 2026*
