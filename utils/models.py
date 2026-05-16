"""
MAPNAI — utils/models.py
Pydantic data models for every object that moves through the ingestion pipeline.
These are the canonical schemas — all agents produce and consume these types.
"""

from __future__ import annotations
from pydantic import BaseModel, Field, field_validator
from typing import Optional, List, Dict, Any
from datetime import datetime
from enum import Enum
import uuid


class Domain(str, Enum):
    FINANCE       = "finance"
    GEOPOLITICS   = "geopolitics"
    TECHNOLOGY    = "technology"
    HEALTH        = "health"
    SUPPLY_CHAIN  = "supply_chain"
    GENERAL       = "general"


class SourceType(str, Enum):
    RSS         = "rss"
    NEWS_API    = "news_api"
    GNEWS       = "gnews"
    NEWSDATA    = "newsdata"
    BLUESKY     = "bluesky"
    SCRAPER     = "scraper"
    GOVERNMENT  = "government"


class SentimentLabel(str, Enum):
    POSITIVE = "positive"
    NEGATIVE = "negative"
    NEUTRAL  = "neutral"


# ── Raw article (pre-preprocessing) ─────────────────────────
class RawArticle(BaseModel):
    """Produced by source fetchers. Not yet cleaned or deduplicated."""
    article_id:    str           = Field(default_factory=lambda: str(uuid.uuid4()))
    title:         str
    body:          str
    url:           str           = ""
    source_name:   str
    source_type:   SourceType
    domain:        Domain        = Domain.GENERAL
    published_at:  Optional[datetime] = None
    language:      str           = "unknown"
    raw_metadata:  Dict[str, Any] = Field(default_factory=dict)


# ── Processed article (post-preprocessing) ───────────────────
class ProcessedArticle(BaseModel):
    """
    Produced by the Preprocessing Agent.
    Ready to be stored in MongoDB / FAISS / Neo4j.
    Mirrors the DB schema in Section 6 of MAPNAI spec.
    """
    # ── Identity ─────────────────────────────────────────────
    article_id:     str      = Field(default_factory=lambda: str(uuid.uuid4()))
    title:          str
    body:           str
    url:            str      = ""

    # ── Source metadata ───────────────────────────────────────
    source_name:    str
    source_type:    SourceType
    domain:         Domain
    raw_source:     str      = ""     # original feed URL or API name

    # ── Timestamps (ISO 8601 UTC) ─────────────────────────────
    published_at:   Optional[datetime] = None
    ingested_at:    datetime           = Field(default_factory=datetime.utcnow)

    # ── Language ──────────────────────────────────────────────
    language:       str      = "en"

    # ── Deduplication ─────────────────────────────────────────
    dedup_hash:     str      = ""     # SimHash hex string

    # ── Enrichment (filled by Agent 1 / pipeline.py after ingestion) ─
    entities:       List[Dict[str, Any]] = Field(default_factory=list)
    # e.g. [{"name": "RBI", "type": "Organization", "domain": "finance", "salience": 0.9, "mention_count": 3}]
    ner_processed:  bool = False

    sentiment_score:  float  = 0.0    # -1.0 to +1.0
    sentiment_label:  SentimentLabel = SentimentLabel.NEUTRAL
    keywords:        List[str]       = Field(default_factory=list)
    topic_tags:      List[str]       = Field(default_factory=list)

    # ── Risk assessment (filled by Risk Agent — later layer) ──
    risk_score:      Optional[int]   = None    # 0–100
    risk_confidence: Optional[float] = None    # 0.0–1.0
    urgency_flag:    bool            = False
    action_rec:      Optional[str]   = None

    # ── Summaries (filled by Summarization Agent — later) ─────
    summary_short:   Optional[str]   = None
    summary_long:    Optional[str]   = None

    # ── Vector store reference ────────────────────────────────
    embedding_id:    Optional[str]   = None

    @field_validator("body")
    @classmethod
    def body_must_have_content(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Article body cannot be empty")
        return v

    def to_mongo_dict(self) -> dict:
        """Serialize for MongoDB insertion."""
        d = self.model_dump()
        d["published_at"] = self.published_at.isoformat() if self.published_at else None
        d["ingested_at"]  = self.ingested_at.isoformat()
        d["domain"]       = self.domain.value
        d["source_type"]  = self.source_type.value
        d["sentiment_label"] = self.sentiment_label.value
        return d

    def to_neo4j_dict(self) -> dict:
        """Minimal dict for Neo4j article node."""
        return {
            "article_id":   self.article_id,
            "title":        self.title,
            "domain":       self.domain.value,
            "source_name":  self.source_name,
            "published_at": self.published_at.isoformat() if self.published_at else "",
            "ingested_at":  self.ingested_at.isoformat(),
            "url":          self.url,
        }


# ── Ingestion run stats ──────────────────────────────────────
class IngestionRunStats(BaseModel):
    run_id:           str      = Field(default_factory=lambda: str(uuid.uuid4()))
    started_at:       datetime = Field(default_factory=datetime.utcnow)
    completed_at:     Optional[datetime] = None
    total_fetched:    int      = 0
    total_cleaned:    int      = 0
    total_duplicates: int      = 0
    total_stored:     int      = 0
    errors:           List[str] = Field(default_factory=list)
    source_breakdown: Dict[str, int] = Field(default_factory=dict)
    # e.g. {"[RSS] Reuters Business": 12, "[NewsAPI]": 45}

    def log_summary(self) -> str:
        return (
            f"Run {self.run_id[:8]} | "
            f"Fetched={self.total_fetched} | "
            f"Cleaned={self.total_cleaned} | "
            f"Dupes={self.total_duplicates} | "
            f"Stored={self.total_stored} | "
            f"Errors={len(self.errors)}"
        )
