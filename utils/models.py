"""
MAPNAI — utils/models.py
Pydantic data models for every object that moves through the ingestion pipeline.
These are the canonical schemas — all agents produce and consume these types.
"""

from __future__ import annotations
from pydantic import BaseModel, Field, field_validator
from typing import Optional, List, Dict, Any
from datetime import datetime, timezone
from enum import Enum
import uuid


class Domain(str, Enum):
    FINANCE       = "finance"
    GEOPOLITICS   = "geopolitics"
    TECHNOLOGY    = "technology"
    HEALTH        = "health"
    SUPPLY_CHAIN  = "supply_chain"
    SPORTS        = "sports"
    ENTERTAINMENT_MOVIES = "entertainment_movies"
    GENERAL       = "general"
    OTHER         = "other"          # Agent 2 classifier's catch-all domain


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


# ── Article images (utils/image_extractor.py) ────────────────
class ArticleImage(BaseModel):
    """One image referenced at its original URL. width/height only when the source states them."""
    url:     str
    width:   Optional[int] = None
    height:  Optional[int] = None
    alt:     Optional[str] = None
    source:  str = ""                  # og:image | json-ld | twitter:image | media:content | enclosure | api | wikipedia | …
    credit:     Optional[str] = None   # author · licence, for images not from the article's own publisher
    credit_url: Optional[str] = None


class ArticleMedia(BaseModel):
    primary_image:     Optional[ArticleImage] = None
    additional_images: List[ArticleImage]     = Field(default_factory=list)


# ── Raw article (pre-preprocessing) ─────────────────────────
class RawArticle(BaseModel):
    """Produced by source fetchers. Not yet cleaned or deduplicated."""
    article_id:    str           = Field(default_factory=lambda: str(uuid.uuid4()))
    title:         str
    body:          str
    url:           str           = ""
    source_name:   str
    source_type:   SourceType
    author:        Optional[str] = None
    domain:        Domain        = Domain.GENERAL
    published_at:  Optional[datetime] = None
    language:      str           = "unknown"
    raw_metadata:  Dict[str, Any] = Field(default_factory=dict)
    images:        List[Dict[str, Any]] = Field(default_factory=list)   # candidates, ranked in preprocessing


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
    author:         Optional[str] = None

    # ── Timestamps (ISO 8601 UTC) ─────────────────────────────
    published_at:   Optional[datetime] = None
    ingested_at:    datetime           = Field(default_factory=lambda: datetime.now(timezone.utc))
    # where the article's time comes from: "published" (the source's own field), "page_meta" (read from the
    # article page) or "ingested" (none found, ingested_at stands in); None → derived from published_at
    date_source:    Optional[str]      = None

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

    # ── Images (hero + extras, original URLs; None = none found) ─
    media:           Optional[ArticleMedia] = None

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
        # BSON dates for exact range queries (recaps): the article's time, with ingested_at standing in when the
        # source gave none, and the ingestion time. The ISO strings above stay for existing readers.
        d["date_source"]  = self.date_source or ("published" if self.published_at else "ingested")
        d["published_ts"] = self.published_at or self.ingested_at
        d["ingested_ts"]  = self.ingested_at
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

# ── Insights (GET /v1/users/{user_id}/insights) ──────────────
# Every claim carries `sources`: the article ids that support it. Scenarios are analysis, labelled by likelihood
# only (never a percentage).

class InsightClaim(BaseModel):
    text: str
    sources: List[str] = Field(default_factory=list)


class InsightWatchNext(InsightClaim):
    when: Optional[str] = None


class InsightAction(InsightClaim):
    origin: str = "analysis"             # "analysis" (the insight's LLM) | "risk_agent" (Agent 4's recommendation)


class InsightScenario(BaseModel):
    title: str
    explanation: str
    likelihood: str                      # "likely" | "possible" | "unlikely"
    watch_for: List[str] = Field(default_factory=list)
    sources: List[str] = Field(default_factory=list)


class InsightSource(BaseModel):
    article_id: str
    source_name: Optional[str] = None
    title: str = ""
    url: Optional[str] = None
    published_at: Optional[Any] = None


class InsightEntity(BaseModel):
    key: str
    name: str
    followed: bool = False


class InsightForYou(BaseModel):
    kind: str                            # "direct" | "connected"
    text: str                            # "You follow Jasprit Bumrah"
    entities: List[str] = Field(default_factory=list)


class InsightAnalysis(BaseModel):
    status: str                          # "ok" | "partial" (no scenarios) | "fallback" (no LLM analysis)
    reason: Optional[str] = None
    model: Optional[str] = None
    generated_at: Optional[datetime] = None
    version: int = 1
    dropped: int = 0                     # claims the fact check removed


class InsightWatch(BaseModel):
    watching: bool = False
    since: Optional[datetime] = None
    new_sources: int = 0
    changed: bool = False                # the analysis was made again since the reader started watching


class Insight(BaseModel):
    story_id: str
    lead_article_id: str
    rank: int
    topic: Optional[str] = None
    title: str
    image_url: Optional[str] = None
    first_seen: Optional[datetime] = None
    last_updated: Optional[datetime] = None
    span_days: int = 1
    source_count: int
    article_count: int
    what_happened: InsightClaim
    why_it_matters: List[InsightClaim] = Field(default_factory=list)
    for_you: Optional[InsightForYou] = None
    scenarios: List[InsightScenario] = Field(default_factory=list)
    watch_next: List[InsightWatchNext] = Field(default_factory=list)
    actions: List[InsightAction] = Field(default_factory=list)
    entities: List[InsightEntity] = Field(default_factory=list)
    sources: List[InsightSource] = Field(default_factory=list)
    analysis: InsightAnalysis
    watch: InsightWatch = Field(default_factory=InsightWatch)
    disclaimer: str


class FollowChange(BaseModel):
    key: str
    name: str
    role: Optional[str] = None
    weight: Optional[Any] = None
    this_week: int = 0
    last_week: int = 0
    top_story: Optional[Dict[str, Any]] = None
    insight_story_id: Optional[str] = None


class InsightsResponse(BaseModel):
    user_id: str
    generated_at: datetime
    window_h: int
    personalized: bool
    persona_version: Optional[int] = None
    insights: List[Insight] = Field(default_factory=list)
    follows: List[FollowChange] = Field(default_factory=list)
