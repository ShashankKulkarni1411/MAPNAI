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
    newsapi_key: str = Field(default="", env="NEWSAPI_KEY")
    gnews_api_key: str = Field(default="", env="GNEWS_API_KEY")
    newsdata_api_key: str = Field(default="", env="NEWSDATA_API_KEY")
    groq_api_key: str = Field(
        default="",
        validation_alias=AliasChoices("GROQ_API_KEY", "OPENAI_API_KEY"),
    )
    # ── Bluesky Firehose (zero-auth public WebSocket) ────────
    bluesky_firehose_url: str = Field(
        default="wss://bsky.network/xrpc/com.atproto.sync.subscribeRepos",
        env="BLUESKY_FIREHOSE_URL",
    )
    bluesky_max_posts: int = Field(default=200, env="BLUESKY_MAX_POSTS")

    # ── LLM / Groq Settings ──────────────────────────────────
    groq_model: str = Field(default="llama-3.3-70b-versatile", env="GROQ_MODEL")
    # Agent 3: "auto" = Groq LLM when GROQ_API_KEY is set, else extractive TF-IDF;
    # "extractive" = always offline TF-IDF; "llm" = Groq only
    summarizer_backend: str = Field(default="auto", env="SUMMARIZER_BACKEND")
    openai_api_key: str = Field(default="", env="OPENAI_API_KEY")

    # ── Reddit ───────────────────────────────────────────────
    reddit_client_id: str = Field(default="", env="REDDIT_CLIENT_ID")
    reddit_client_secret: str = Field(default="", env="REDDIT_CLIENT_SECRET")
    reddit_user_agent: str = Field(default="MAPNAI/1.0", env="REDDIT_USER_AGENT")

    # ── MongoDB ──────────────────────────────────────────────
    mongo_uri: str = Field(default="mongodb://localhost:27017", env="MONGO_URI")
    mongo_db_name: str = Field(default="mapnai", env="MONGO_DB_NAME")

    # ── Neo4j ────────────────────────────────────────────────
    neo4j_uri: str = Field(default="bolt://localhost:7687", env="NEO4J_URI")
    # Aura's credentials file names it NEO4J_USERNAME (newer instances use the instance id, not "neo4j")
    neo4j_user: str = Field(default="neo4j", validation_alias=AliasChoices("NEO4J_USER", "NEO4J_USERNAME"))
    neo4j_password: str = Field(default="password", env="NEO4J_PASSWORD")

    # ── FAISS ────────────────────────────────────────────────
    faiss_index_path: str = Field(default="./data/faiss_index", env="FAISS_INDEX_PATH")
    faiss_metadata_path: str = Field(default="./data/faiss_metadata.pkl", env="FAISS_METADATA_PATH")

    # ── Embedding ────────────────────────────────────────────
    embedding_model: str = Field(default="all-MiniLM-L6-v2", env="EMBEDDING_MODEL")

    # ── Ingestion ────────────────────────────────────────────
    ingestion_interval_minutes: int = Field(default=30, env="INGESTION_INTERVAL_MINUTES")
    max_articles_per_source: int = Field(default=50, env="MAX_ARTICLES_PER_SOURCE")
    min_article_length: int = Field(default=100, env="MIN_ARTICLE_LENGTH")
    request_timeout_seconds: int = Field(default=15, env="REQUEST_TIMEOUT_SECONDS")
    max_retries: int = Field(default=3, env="MAX_RETRIES")
    # Article images: when the feed/API gave no usable hero image, read og:image / JSON-LD from the article page
    media_page_lookup: bool = Field(default=True, env="MEDIA_PAGE_LOOKUP")
    media_lookup_workers: int = Field(default=8, env="MEDIA_LOOKUP_WORKERS")
    media_lookup_timeout_seconds: int = Field(default=8, env="MEDIA_LOOKUP_TIMEOUT_SECONDS")
    media_lookup_max: int = Field(default=400, env="MEDIA_LOOKUP_MAX")   # page fetches per run

    # ── Language ─────────────────────────────────────────────
    primary_language: str = Field(default="en", env="PRIMARY_LANGUAGE")

    # ── Logging ──────────────────────────────────────────────
    log_level: str = Field(default="INFO", env="LOG_LEVEL")
    log_file: str = Field(default="./logs/ingestion.log", env="LOG_FILE")

    # ── App accounts (api/auth_router.py) ────────────────────
    # Signs access/refresh tokens. Unset → a random key per API process (every token dies on restart).
    auth_secret: str = Field(default="", env="AUTH_SECRET")
    auth_access_ttl_min: int = Field(default=60, env="AUTH_ACCESS_TTL_MIN")
    auth_refresh_ttl_days: int = Field(default=30, env="AUTH_REFRESH_TTL_DAYS")
    auth_code_ttl_min: int = Field(default=10, env="AUTH_CODE_TTL_MIN")
    auth_code_max_attempts: int = Field(default=5, env="AUTH_CODE_MAX_ATTEMPTS")
    # Email codes go out over SMTP; with no SMTP_HOST they are written to the API log instead (development).
    smtp_host: str = Field(default="", env="SMTP_HOST")
    smtp_port: int = Field(default=587, env="SMTP_PORT")
    smtp_user: str = Field(default="", env="SMTP_USER")
    smtp_password: str = Field(default="", env="SMTP_PASSWORD")
    smtp_from: str = Field(default="", env="SMTP_FROM")

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