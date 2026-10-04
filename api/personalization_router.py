"""
MAPNAI — api/personalization_router.py
/v1 personalization endpoints. Business logic and validation live in personalization/service.py;
this module only shapes requests and maps errors to HTTP status codes.
"""

from datetime import datetime
from typing import Dict, List, Optional, Union

from fastapi import APIRouter, Depends, Query, Request, status
from pydantic import BaseModel, Field

from config.personalization import pers_settings
from personalization import jobs
from personalization.service import PersonalizationService

router = APIRouter(prefix="/v1", tags=["personalization"])

_service: Optional[PersonalizationService] = None


def get_service() -> PersonalizationService:
    """Shared service instance (lazy, so importing the app doesn't connect). Overridable in tests."""
    global _service
    if _service is None:
        _service = PersonalizationService()
    return _service


# ── Request models ───────────────────────────────────────────

class ExposureIn(BaseModel):
    key: str = Field(min_length=1, description="canonical entity key from /v1/entities/search")
    role: str
    weight: Union[int, str] = Field(description='"low"|"medium"|"high" or 1..3')


class StyleIn(BaseModel):
    tone: Optional[str] = None
    length: Optional[str] = None
    jargon: Optional[str] = None


class UserCreate(BaseModel):
    name: str = Field(min_length=1)
    topics: Dict[str, float] = {}
    style: Optional[StyleIn] = None
    exposures: List[ExposureIn] = []


class OnboardingIn(BaseModel):
    likes: List[str] = []
    dislikes: List[str] = []


class ExposuresPatch(BaseModel):
    upsert: List[ExposureIn] = []
    remove: List[str] = []


class TopicsPatch(BaseModel):
    topics: Dict[str, Optional[float]]


class FeedbackIn(BaseModel):
    user_id: str = Field(min_length=1)
    article_id: str = Field(min_length=1)
    type: str = Field(description="open|more|less|unreact|dwell|save|unsave|share|needed|not_needed|missed")
    value: Optional[float] = Field(default=None, description="dwell seconds")
    section: Optional[str] = Field(default=None, description="default: the section the article was last served in")


class ProposalAccept(BaseModel):
    role: Optional[str] = Field(default=None, description="override the suggested role")
    weight: Optional[Union[int, str]] = Field(default=None, description="override the suggested weight")


class AlertPrefsPatch(BaseModel):
    max_per_day: Optional[int] = None
    quiet_start: Optional[str] = None
    quiet_end: Optional[str] = None
    tz: Optional[str] = None


# ── A. Entities / users / onboarding ─────────────────────────

@router.get("/entities/search")
def search_entities(
    q: str = Query(min_length=1, max_length=100),
    svc: PersonalizationService = Depends(get_service),
):
    return svc.search_entities(q)


@router.post("/users", status_code=status.HTTP_201_CREATED)
def create_user(body: UserCreate, svc: PersonalizationService = Depends(get_service)):
    return svc.create_user(
        body.name,
        body.topics,
        body.style.model_dump(exclude_none=True) if body.style else None,
        [e.model_dump() for e in body.exposures],
    )


@router.get("/onboarding/headlines")
def onboarding_headlines(svc: PersonalizationService = Depends(get_service)):
    return svc.onboarding_headlines()


@router.post("/users/{user_id}/onboarding")
def onboarding(user_id: str, body: OnboardingIn, svc: PersonalizationService = Depends(get_service)):
    return svc.onboarding(user_id, body.likes, body.dislikes)


@router.get("/users/{user_id}/profile")
def get_profile(user_id: str, svc: PersonalizationService = Depends(get_service)):
    return svc.get_profile(user_id)


# ── A. Profile edits ─────────────────────────────────────────

@router.patch("/users/{user_id}/exposures")
def patch_exposures(user_id: str, body: ExposuresPatch, svc: PersonalizationService = Depends(get_service)):
    return svc.patch_exposures(user_id, [e.model_dump() for e in body.upsert], body.remove)


@router.patch("/users/{user_id}/topics")
def patch_topics(user_id: str, body: TopicsPatch, svc: PersonalizationService = Depends(get_service)):
    return svc.patch_topics(user_id, body.topics)


@router.patch("/users/{user_id}/style")
def patch_style(user_id: str, body: StyleIn, svc: PersonalizationService = Depends(get_service)):
    return svc.patch_style(user_id, body.model_dump(exclude_none=True))


@router.patch("/users/{user_id}/alert_prefs")
def patch_alert_prefs(user_id: str, body: AlertPrefsPatch, svc: PersonalizationService = Depends(get_service)):
    return svc.patch_alert_prefs(user_id, body.model_dump(exclude_none=True))


# ── G. Digest ────────────────────────────────────────────────

@router.get("/users/{user_id}/digest")
def get_digest(
    user_id: str,
    refresh: bool = Query(default=False, description="recompute instead of serving today's cached digest"),
    svc: PersonalizationService = Depends(get_service),
):
    return svc.get_digest(user_id, refresh)


# ── E. Feedback ──────────────────────────────────────────────

@router.post("/feedback")
def feedback(body: FeedbackIn, svc: PersonalizationService = Depends(get_service)):
    return svc.record_feedback(body.user_id, body.article_id, body.type, body.value, body.section)


# ── I. Proposals ─────────────────────────────────────────────

@router.get("/users/{user_id}/proposals")
def list_proposals(
    user_id: str,
    status: Optional[str] = Query(default=None, description="pending|accepted|rejected; default all"),
    svc: PersonalizationService = Depends(get_service),
):
    return svc.list_proposals(user_id, status)


@router.post("/users/{user_id}/proposals/{proposal_id}/accept")
def accept_proposal(user_id: str, proposal_id: str, body: Optional[ProposalAccept] = None,
                    svc: PersonalizationService = Depends(get_service)):
    body = body or ProposalAccept()
    return svc.accept_proposal(user_id, proposal_id, body.role, body.weight)


@router.post("/users/{user_id}/proposals/{proposal_id}/reject")
def reject_proposal(user_id: str, proposal_id: str, svc: PersonalizationService = Depends(get_service)):
    return svc.reject_proposal(user_id, proposal_id)


# ── J. Alerts ────────────────────────────────────────────────

@router.get("/users/{user_id}/alerts")
def list_alerts(
    user_id: str,
    since: Optional[datetime] = Query(default=None, description="delivered after this time (ISO; naive = UTC)"),
    include_pending: bool = Query(default=False, description="also alerts still held by quiet hours"),
    limit: int = Query(default=50, ge=1, le=200),
    svc: PersonalizationService = Depends(get_service),
):
    return svc.alerts(user_id, since, include_pending, limit)


# ── M. App views ─────────────────────────────────────────────

class AskIn(BaseModel):
    query: str = Field(min_length=1, max_length=500)
    domain: Optional[str] = None
    context_article_id: Optional[str] = None


@router.get("/users/{user_id}/feed")
def feed(
    user_id: str,
    cursor: Optional[str] = Query(default=None, description="next_cursor of the previous page"),
    limit: int = Query(default=10, ge=1, le=pers_settings.feed_page_max),
    exclude: str = Query(default="", description="comma-separated article ids to leave out (e.g. today's brief)"),
    svc: PersonalizationService = Depends(get_service),
):
    return svc.feed(user_id, cursor, limit, [a for a in exclude.split(",") if a])


@router.get("/users/{user_id}/saved")
def saved(user_id: str, svc: PersonalizationService = Depends(get_service)):
    return svc.saved(user_id)


@router.get("/articles/top")
def top_articles(
    hours: int = Query(default=24, ge=1, le=24 * 7),
    limit: int = Query(default=8, ge=1, le=50),
    svc: PersonalizationService = Depends(get_service),
):
    return svc.top(hours, limit)


@router.get("/articles/{article_id}")
def story(article_id: str, user_id: Optional[str] = Query(default=None),
          svc: PersonalizationService = Depends(get_service)):
    return svc.story(article_id, user_id)


class CommentIn(BaseModel):
    user_id: str = Field(min_length=1)
    text: str = Field(min_length=1, max_length=pers_settings.comment_max_chars)


@router.get("/articles/{article_id}/comments")
def list_comments(article_id: str, limit: int = Query(default=50, ge=1, le=pers_settings.comments_page_max),
                  svc: PersonalizationService = Depends(get_service)):
    return svc.comments(article_id, limit)


@router.post("/articles/{article_id}/comments", status_code=status.HTTP_201_CREATED)
def add_comment(article_id: str, body: CommentIn, svc: PersonalizationService = Depends(get_service)):
    return svc.add_comment(article_id, body.user_id, body.text)


@router.get("/clusters/by-article/{article_id}")
def cluster_sources(article_id: str, svc: PersonalizationService = Depends(get_service)):
    return svc.cluster_sources(article_id)


@router.get("/search")
def search(
    q: str = Query(min_length=1, max_length=200),
    topic: Optional[str] = Query(default=None),
    svc: PersonalizationService = Depends(get_service),
):
    return svc.search(q, topic)


@router.post("/ask")
def ask(body: AskIn, svc: PersonalizationService = Depends(get_service)):
    return svc.ask(body.query, body.domain, body.context_article_id)


# ── K. Render ────────────────────────────────────────────────

@router.get("/articles/{article_id}/render")
def render_article(
    article_id: str,
    user_id: str = Query(min_length=1),
    refresh: bool = Query(default=False, description="rewrite again instead of serving the cached rewrite"),
    svc: PersonalizationService = Depends(get_service),
):
    return svc.render(article_id, user_id, refresh)


# ── Health ───────────────────────────────────────────────────

@router.get("/personalization/health")
def health(
    request: Request,
    hours: int = Query(default=pers_settings.cand_window_h, ge=1, le=24 * 365),
    svc: PersonalizationService = Depends(get_service),
):
    out = svc.health(hours)
    out["scheduler"] = jobs.scheduler_status(getattr(request.app.state, "scheduler", None))
    return out
