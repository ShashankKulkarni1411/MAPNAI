"""
MAPNAI — tests/test_auth.py
App accounts (utils/auth.py, api/auth_router.py) on mongomock with a fixed clock and a captured mailbox:
register → email code → verify, sign-in (wrong password, unverified), token expiry / tampering / refresh,
linking the engine user, password reset revoking old tokens, code expiry and attempt limits, and the API.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import re
from datetime import timedelta
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from api.app import create_app
from api.auth_router import get_auth
from storage.account_store import AccountStore
from tests.test_pers_phase2 import NOW, FakeMongo
from utils.auth import (AuthService, EmailTaken, InvalidRequest, Unauthorized, Unverified, check_password,
                        hash_password)

CFG = SimpleNamespace(auth_secret="test-secret", auth_access_ttl_min=60, auth_refresh_ttl_days=30,
                      auth_code_ttl_min=10, auth_code_max_attempts=5)
PW = "correct horse"


class Clock:
    def __init__(self):
        self.now = NOW

    def __call__(self):
        return self.now


@pytest.fixture
def auth():
    mail = []
    clock = Clock()
    svc = AuthService(store=AccountStore(FakeMongo()), cfg=CFG, clock=clock,
                      send_email=lambda to, subject, body: mail.append((to, body)))
    svc.mail, svc.tick = mail, clock
    return svc


def last_code(svc):
    return re.search(r"\b(\d{6})\b", svc.mail[-1][1]).group(1)


def signed_up(svc, email="ana@example.com"):
    svc.register(email, PW, 1990)
    return svc.verify(email, last_code(svc))


class TestPasswords:
    def test_hash_roundtrip_and_salt(self):
        h = hash_password(PW)
        assert check_password(PW, h) and not check_password("wrong", h) and hash_password(PW) != h
        assert not check_password(PW, "garbage")


class TestSignUp:
    def test_register_verify_gives_tokens(self, auth):
        assert auth.register(" Ana@Example.com ", PW, 1990) == {"ok": True}
        assert auth.mail[-1][0] == "ana@example.com"
        out = auth.verify("ana@example.com", last_code(auth))
        assert out["user_id"] is None and auth.account_for(out["access_token"])["email"] == "ana@example.com"

    @pytest.mark.parametrize("email,pw,year", [("nope", PW, 1990), ("a@b.co", "short", 1990),
                                               ("a@b.co", "password1", 1990), ("a@b.co", PW, NOW.year - 10)])
    def test_rejects(self, auth, email, pw, year):
        with pytest.raises(InvalidRequest):
            auth.register(email, pw, year)

    def test_verified_email_is_taken_but_unverified_can_retry(self, auth):
        auth.register("ana@example.com", PW, 1990)
        auth.register("ana@example.com", "another pass", 1991)           # not verified yet: starts over
        auth.verify("ana@example.com", last_code(auth))
        with pytest.raises(EmailTaken):
            auth.register("ana@example.com", PW, 1990)

    def test_wrong_code_counts_and_locks(self, auth):
        auth.register("ana@example.com", PW, 1990)
        good = last_code(auth)
        bad = "000000" if good != "000000" else "111111"
        for _ in range(CFG.auth_code_max_attempts):
            with pytest.raises(InvalidRequest, match="didn't work"):
                auth.verify("ana@example.com", bad)
        with pytest.raises(InvalidRequest, match="Too many"):
            auth.verify("ana@example.com", good)
        auth.resend("ana@example.com")                                    # a new code resets the tries
        assert auth.verify("ana@example.com", last_code(auth))["access_token"]

    def test_code_expires_and_is_single_use(self, auth):
        auth.register("ana@example.com", PW, 1990)
        code = last_code(auth)
        auth.tick.now = NOW + timedelta(minutes=11)
        with pytest.raises(InvalidRequest, match="expired"):
            auth.verify("ana@example.com", code)
        auth.resend("ana@example.com")
        code = last_code(auth)
        auth.verify("ana@example.com", code)
        with pytest.raises(InvalidRequest):
            auth.verify("ana@example.com", code)

    def test_resend_and_reset_request_reveal_nothing(self, auth):
        assert auth.resend("ghost@example.com") == {"ok": True}
        assert auth.request_reset("ghost@example.com") == {"ok": True}
        assert auth.mail == []


class TestSignIn:
    def test_login(self, auth):
        signed_up(auth)
        assert auth.login("ANA@example.com", PW)["access_token"]
        with pytest.raises(Unauthorized):
            auth.login("ana@example.com", "wrong password")
        with pytest.raises(Unauthorized):
            auth.login("ghost@example.com", PW)

    def test_unverified_login_sends_a_fresh_code(self, auth):
        auth.register("ana@example.com", PW, 1990)
        with pytest.raises(Unverified):
            auth.login("ana@example.com", PW)
        assert len(auth.mail) == 2 and auth.verify("ana@example.com", last_code(auth))

    def test_tokens_expire_and_refresh(self, auth):
        tokens = signed_up(auth)
        with pytest.raises(Unauthorized):
            auth.account_for(tokens["refresh_token"])                      # wrong type
        auth.tick.now = NOW + timedelta(minutes=61)
        with pytest.raises(Unauthorized):
            auth.account_for(tokens["access_token"])
        fresh = auth.refresh(tokens["refresh_token"])
        assert auth.account_for(fresh["access_token"])["email"] == "ana@example.com"

    def test_tampered_token(self, auth):
        token = signed_up(auth)["access_token"]
        body, sig = token.split(".")
        for bad in [f"{body}x.{sig}", f"{body}.{sig[:-2]}AA", "nonsense", ""]:
            with pytest.raises(Unauthorized):
                auth.account_for(bad)

    def test_link_returns_the_user_on_later_sign_in(self, auth):
        tokens = signed_up(auth)
        auth.link(auth.account_for(tokens["access_token"]), "user-1")
        assert auth.login("ana@example.com", PW)["user_id"] == "user-1"


class TestReset:
    def test_reset_changes_password_and_revokes_tokens(self, auth):
        old = signed_up(auth)
        auth.request_reset("ana@example.com")
        auth.confirm_reset("ana@example.com", last_code(auth), "brand new pass")
        with pytest.raises(Unauthorized):
            auth.account_for(old["access_token"])
        with pytest.raises(Unauthorized):
            auth.login("ana@example.com", PW)
        assert auth.login("ana@example.com", "brand new pass")["access_token"]

    def test_reset_code_is_not_a_verify_code(self, auth):
        signed_up(auth)
        auth.request_reset("ana@example.com")
        with pytest.raises(InvalidRequest):
            auth.verify("ana@example.com", last_code(auth))


class TestApi:
    @pytest.fixture
    def client(self, auth):
        app = create_app()
        app.dependency_overrides[get_auth] = lambda: auth
        return TestClient(app)

    def test_flow(self, client, auth):
        r = client.post("/v1/auth/register", json={"email": "ana@example.com", "password": PW, "birth_year": 1990})
        assert r.status_code == 201
        assert client.post("/v1/auth/register", json={"email": "x", "password": PW,
                                                      "birth_year": 1990}).status_code == 422
        assert client.post("/v1/auth/login", json={"email": "ana@example.com", "password": PW}).status_code == 403
        r = client.post("/v1/auth/verify", json={"email": "ana@example.com", "code": last_code(auth)})
        tokens = r.json()
        assert r.status_code == 200 and tokens["user_id"] is None
        assert client.post("/v1/auth/register", json={"email": "ana@example.com", "password": PW,
                                                      "birth_year": 1990}).status_code == 409
        assert client.post("/v1/auth/login", json={"email": "ana@example.com", "password": "nope nope"}
                           ).status_code == 401

        assert client.post("/v1/auth/link", json={"user_id": "u1"}).status_code == 401
        r = client.post("/v1/auth/link", json={"user_id": "u1"},
                        headers={"Authorization": f"Bearer {tokens['access_token']}"})
        assert r.status_code == 200
        login = client.post("/v1/auth/login", json={"email": "ana@example.com", "password": PW}).json()
        assert login["user_id"] == "u1"
        assert client.post("/v1/auth/refresh", json={"refresh_token": login["refresh_token"]}).status_code == 200

        assert client.post("/v1/auth/reset/request", json={"email": "ana@example.com"}).json() == {"ok": True}
        r = client.post("/v1/auth/reset/confirm", json={"email": "ana@example.com", "code": last_code(auth),
                                                        "password": "brand new pass"})
        assert r.status_code == 200
        assert client.post("/v1/auth/refresh", json={"refresh_token": login["refresh_token"]}).status_code == 401
