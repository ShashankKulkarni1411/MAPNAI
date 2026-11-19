"""
MAPNAI — config/settings.py
Central configuration loaded from .env via pydantic-settings.
All other modules import from here — no direct os.getenv() calls elsewhere.

Note: Reddit has been replaced by the Bluesky Firehose (WebSocket, zero-auth).
"""

from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache

# Resolve .env relative to project root (parent of config/), not the process cwd.
_ENV_FILE = Path(__file__).resolve().parent.parent / ".env"


class Settings(BaseSettings):
    # ── News APIs ────────────────────────────────────────────
    newsapi_key: str = ""
    gnews_api_key: str = ""
    newsdata_api_key: str = ""
    groq_api_key: str = Field(
        default="",
        validation_alias=AliasChoices("GROQ_API_KEY", "OPENAI_API_KEY"),
    )
    # ── Bluesky Firehose (zero-auth public WebSocket) ────────
    bluesky_firehose_url: str = "wss://bsky.network/xrpc/com.atproto.sync.subscribeRepos"
    bluesky_max_posts: int = 200

    # ── LLM / Groq Settings ──────────────────────────────────
    groq_model: str = "openai/gpt-oss-120b"
    # Agent 3: "auto" = Groq LLM when GROQ_API_KEY is set, else extractive TF-IDF;
    # "extractive" = always offline TF-IDF; "llm" = Groq only
    summarizer_backend: str = "auto"
    # Agent 4: "model" = offline event model + formulas, no LLM (agents/risk_model.py);
    # "auto" = Groq, falling back to the local Ollama model when Groq fails (e.g. 429 daily limit)
    # or GROQ_API_KEY is missing; "groq" = Groq only (failures leave the article pending);
    # "ollama" = local model only.
    risk_backend: str = "model"
    # Offline event models for RISK_BACKEND=model: DistilRoBERTa first, then TF-IDF, then keyword rules.
    risk_event_model_dir: str = "models/risk_event"
    risk_tfidf_model_path: str = "models/risk/event_model.joblib"
    # Ollama's OpenAI-compatible endpoint and the model Agent 4 uses locally.
    ollama_base_url: str = "http://localhost:11434/v1"
    risk_ollama_model: str = "mapnai-risk"
    risk_ollama_timeout_seconds: float = 300.0
    # After Groq fails in "auto" mode, Agent 4 goes straight to Ollama for this long instead of
    # spending a doomed Groq request on every article.
    risk_groq_cooldown_seconds: float = 900.0

    # ── Agent 1 NER ──────────────────────────────────────────
    # Type stored for the BERT model's CoNLL MISC label (nationalities, events, works). "Product" is the historical
    # mapping; "Misc" is correct but only consistent with stored data after scripts/migrate_ner_misc_types.py runs.
    ner_misc_label: str = "Product"

    # ── Agent 5 query graph (agents/query_graph.py) ──────────
    # Off, or no GROQ_API_KEY → Agent 5 runs its single-pass retrieve → generate path.
    query_graph_enabled: bool = True
    # Blank → GROQ_MODEL. The grader runs once per retrieval, so a smaller model keeps it cheap.
    query_graph_model: str = ""
    query_graph_grader_model: str = ""
    query_graph_max_rewrites: int = 2
    query_graph_max_regenerations: int = 1
    # Hard cap on Groq calls per question, single-pass fallback included (the graph keeps one in reserve for it).
    # Worst case with the defaults above: grade + 2×(rewrite + grade) + 2×(generate + check) = 9, +1 reserved.
    query_graph_max_llm_calls: int = 10
    # Fewer graded-relevant articles than this → rewrite the query (while rewrites remain). 1 = rewrite only when
    # nothing relevant survived; specific questions often have a single matching story.
    query_graph_min_relevant_docs: int = 1
    # No rewrite/regeneration starts after this many seconds (the app's /v1/ask timeout is 20 s).
    query_graph_deadline_seconds: float = 12.0
    query_graph_llm_timeout_seconds: float = 8.0
    # Ranking: relevance × (1 − w + w·source_cred); articles below min_credibility are dropped
    # unless that would drop every article.
    query_graph_credibility_weight: float = 0.3
    query_graph_min_credibility: float = 0.2
    # After a Neo4j failure, graph retrieval is skipped for this long (connecting can block ~10 s).
    query_graph_neo4j_cooldown_seconds: float = 300.0

    # ── MongoDB ──────────────────────────────────────────────
    mongo_uri: str = "mongodb://localhost:27017"
    mongo_db_name: str = "mapnai"

    # ── Neo4j ────────────────────────────────────────────────
    neo4j_uri: str = "bolt://localhost:7687"
    # Aura's credentials file names it NEO4J_USERNAME (newer instances use the instance id, not "neo4j")
    neo4j_user: str = Field(default="neo4j", validation_alias=AliasChoices("NEO4J_USER", "NEO4J_USERNAME"))
    neo4j_password: str = "password"

    # ── FAISS ────────────────────────────────────────────────
    faiss_index_path: str = "./data/faiss_index"
    faiss_metadata_path: str = "./data/faiss_metadata.pkl"

    # ── Embedding ────────────────────────────────────────────
    embedding_model: str = "all-MiniLM-L6-v2"

    # ── Ingestion ────────────────────────────────────────────
    ingestion_interval_minutes: int = 30
    max_articles_per_source: int = 50
    min_article_length: int = 100
    request_timeout_seconds: int = 15
    # A publish time further than this ahead of the ingestion time is a wrong date (bad feed / timezone): it is
    # dropped and the article falls back to its ingestion time (date_source "ingested")
    max_future_skew_minutes: int = 60
    # Article images: when the feed/API gave no usable hero image, read og:image / JSON-LD from the article page
    media_page_lookup: bool = True
    media_lookup_workers: int = 8
    media_lookup_timeout_seconds: int = 8
    media_lookup_max: int = 400   # page fetches per run
    # Still no image after the page lookup: free Wikipedia image of the story's main entity (utils/image_fallback.py)
    media_fallback: bool = True
    # Wikimedia throttles anonymous clients hard unless the User-Agent names the project and a contact
    wikimedia_user_agent: str = "MAPNAI/1.0 (https://github.com/ShashankKulkarni1411/MAPNAI) news-images"
    # Duplicate fingerprints older than this are not loaded: an old story doesn't come back as a duplicate, and the
    # lookup stays small however large the archive grows
    dedup_seed_days: int = 7
    # Raw Bluesky firehose posts as articles (random public posts: mostly noise). Off; the stream worker can use
    # Bluesky as a social signal instead (stream_social_enabled)
    bluesky_ingest_articles: bool = False

    # ── Continuous stream (stream_worker.py; continousexplanation.md §5) ──
    stream_tick_seconds: float = 15.0          # how often the worker looks for due sources
    stream_flush_seconds: float = 120.0        # micro-batch: flush new items at least this often …
    stream_flush_max: int = 200                # … or as soon as this many are waiting
    stream_poll_workers: int = 8               # feeds downloaded in parallel
    stream_initial_interval_s: float = 900.0   # a new source's first polling interval
    stream_min_interval_top_s: float = 120.0   # top-stories feeds may be polled this often …
    stream_min_interval_s: float = 300.0       # … section feeds this often …
    stream_max_interval_s: float = 1200.0      # … and nobody less often than this (20 min: scripts/stream_benchmark.py
                                               # polling — fewer requests than fixed 15-min polling, same p90 delay)
    stream_seen_keep: int = 500                # item keys remembered per source (feeds carry ≤ 50 items)
    stream_api_interval_minutes: float = 60.0  # news APIs (NewsAPI / GNews free tiers: ~100 requests a day)
    stream_scraper_interval_minutes: float = 30.0
    stream_faiss_save_seconds: float = 600.0   # the FAISS index is written to disk at most this often
    stream_reseed_hours: float = 24.0          # rebuild the in-memory duplicate index from Mongo this often
    # Agents 1-2 (local models) run on every flush; Agents 3-4 (LLM) on at most this many articles per flush,
    # hottest stories first (0 = leave them to `python pipeline.py --schedule`)
    stream_run_agents: bool = True
    stream_llm_per_flush: int = 20
    # Bluesky Jetstream social signal for trending stories (agents/social_signal.py)
    stream_social_enabled: bool = False
    stream_social_url: str = "wss://jetstream2.us-east.bsky.network/subscribe?wantedCollections=app.bsky.feed.post"
    stream_social_bucket_minutes: int = 10
    stream_social_refresh_seconds: float = 300.0   # reload the watched stories this often
    # Agent 4: reuse the risk score of an article in the same event cluster instead of another LLM call
    risk_share_in_cluster: bool = True

    # ── Language ─────────────────────────────────────────────
    primary_language: str = "en"

    # ── Logging ──────────────────────────────────────────────
    log_level: str = "INFO"
    log_file: str = "./logs/ingestion.log"

    # ── App accounts (api/auth_router.py) ────────────────────
    # Signs access/refresh tokens. Unset → a random key per API process (every token dies on restart).
    auth_secret: str = ""
    auth_access_ttl_min: int = 60
    auth_refresh_ttl_days: int = 30
    auth_code_ttl_min: int = 10
    auth_code_max_attempts: int = 5
    # Email codes go out over SMTP; with no SMTP_HOST they are written to the API log instead (development).
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = ""

    model_config = SettingsConfigDict(
        env_file=str(_ENV_FILE),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls,
        init_settings,
        env_settings,
        dotenv_settings,
        file_secret_settings,
    ):
        # .env wins over OS-level env vars (e.g. stale OPENAI_API_KEY on Windows).
        return (init_settings, dotenv_settings, env_settings, file_secret_settings)


@lru_cache()
def get_settings() -> Settings:
    """Cached singleton settings instance."""
    return Settings()


settings = get_settings()