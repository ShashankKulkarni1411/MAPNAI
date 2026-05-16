"""
MAPNAI — config/settings.py
Central configuration loaded from .env via pydantic-settings.
All other modules import from here — no direct os.getenv() calls elsewhere.
"""

from pydantic_settings import BaseSettings
from pydantic import Field
from functools import lru_cache


class Settings(BaseSettings):
    # ── News APIs ────────────────────────────────────────────
    newsapi_key: str = Field(default="", env="NEWSAPI_KEY")
    gnews_api_key: str = Field(default="", env="GNEWS_API_KEY")
    newsdata_api_key: str = Field(default="", env="NEWSDATA_API_KEY")

    # ── LLMs ─────────────────────────────────────────────────
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
    neo4j_user: str = Field(default="neo4j", env="NEO4J_USER")
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

    # ── Language ─────────────────────────────────────────────
    primary_language: str = Field(default="en", env="PRIMARY_LANGUAGE")

    # ── Logging ──────────────────────────────────────────────
    log_level: str = Field(default="INFO", env="LOG_LEVEL")
    log_file: str = Field(default="./logs/ingestion.log", env="LOG_FILE")

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False


@lru_cache()
def get_settings() -> Settings:
    """Cached singleton settings instance."""
    return Settings()


settings = get_settings()
