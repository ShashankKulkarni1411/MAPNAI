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