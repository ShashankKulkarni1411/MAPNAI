"""
MAPNAI — api/auth_router.py
/v1/auth endpoints for the mobile app's accounts. Logic lives in utils/auth.py.
"""

from typing import Dict, Optional

from fastapi import APIRouter, Depends, Header, status
from pydantic import BaseModel, Field

from utils.auth import AuthService, Unauthorized

router = APIRouter(prefix="/v1/auth", tags=["auth"])

_service: Optional[AuthService] = None


def get_auth() -> AuthService:
    """Shared service instance (lazy, so importing the app doesn't connect). Overridable in tests."""
    global _service
    if _service is None:
        _service = AuthService()
    return _service


def current_account(authorization: str = Header(default=""), auth: AuthService = Depends(get_auth)) -> Dict:
    """The account of the request's `Authorization: Bearer <access_token>`."""
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise Unauthorized("Sign in again.")
    return auth.account_for(token)


class RegisterIn(BaseModel):
    email: str
    password: str
    birth_year: int


class EmailIn(BaseModel):
    email: str


class VerifyIn(BaseModel):
    email: str
    code: str = Field(min_length=1, max_length=12)


class LoginIn(BaseModel):
    email: str
    password: str


class RefreshIn(BaseModel):
    refresh_token: str


class LinkIn(BaseModel):
    user_id: str = Field(min_length=1)


class ResetConfirmIn(BaseModel):
    email: str
    code: str = Field(min_length=1, max_length=12)
    password: str


@router.post("/register", status_code=status.HTTP_201_CREATED)
def register(body: RegisterIn, auth: AuthService = Depends(get_auth)):
    return auth.register(body.email, body.password, body.birth_year)


@router.post("/verify")
def verify(body: VerifyIn, auth: AuthService = Depends(get_auth)):
    return auth.verify(body.email, body.code)


@router.post("/resend")
def resend(body: EmailIn, auth: AuthService = Depends(get_auth)):
    return auth.resend(body.email)


@router.post("/login")
def login(body: LoginIn, auth: AuthService = Depends(get_auth)):
    return auth.login(body.email, body.password)


@router.post("/refresh")
def refresh(body: RefreshIn, auth: AuthService = Depends(get_auth)):
    return auth.refresh(body.refresh_token)


@router.post("/link")
def link(body: LinkIn, account: Dict = Depends(current_account), auth: AuthService = Depends(get_auth)):
    return auth.link(account, body.user_id)


@router.post("/reset/request")
def reset_request(body: EmailIn, auth: AuthService = Depends(get_auth)):
    return auth.request_reset(body.email)


@router.post("/reset/confirm")
def reset_confirm(body: ResetConfirmIn, auth: AuthService = Depends(get_auth)):
    return auth.confirm_reset(body.email, body.code, body.password)
