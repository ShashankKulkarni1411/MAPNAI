"""
MAPNAI — personalization/models.py
Response models for the personalization API (api/personalization_router.py).
"""

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


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
