"""
MAPNAI — api/personalization_router.py
/v1 personalization endpoints. Business logic and validation live in personalization/service.py;
this module only shapes requests and maps errors to HTTP status codes.
"""

from typing import Dict, List, Optional, Union

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, Field

from config.personalization import pers_settings
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


# ── Health ───────────────────────────────────────────────────

@router.get("/personalization/health")
def health(
    hours: int = Query(default=pers_settings.cand_window_h, ge=1, le=24 * 365),
    svc: PersonalizationService = Depends(get_service),
):
    return svc.health(hours)
