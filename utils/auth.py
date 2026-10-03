"""
MAPNAI — utils/auth.py
App accounts: email + password sign-up with a 6-digit email code, sign-in, token refresh, password reset, and
linking an account to its engine user. Standard library only:
  - passwords: scrypt (n=2^14, r=8, p=1) with a 16-byte salt per password
  - tokens: HMAC-SHA256-signed JSON {sub, uid, typ, tv, exp}; tv (token_version) bumps on a password reset,
    which revokes every older token
  - codes: 6 digits, stored as an HMAC, valid auth_code_ttl_min, at most auth_code_max_attempts tries
"""

import base64
import hashlib
import hmac
import json
import re
import secrets
import smtplib
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from typing import Callable, Dict, Optional

from config.settings import settings as app_settings
from storage.account_store import AccountStore
from utils.logger import logger

_EMAIL = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]{2,}$")
# the app's list (mobile/src/state/authDraft.ts), so both sides reject the same passwords
_COMMON = {"password", "password1", "12345678", "123456789", "qwerty123", "iloveyou", "11111111", "abc12345",
           "football", "cricket123"}
MIN_AGE = 18


class AuthError(Exception):
    status_code = 400


class InvalidRequest(AuthError):
    status_code = 422


class Unauthorized(AuthError):
    status_code = 401


class Unverified(AuthError):
    status_code = 403


class EmailTaken(AuthError):
    status_code = 409


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=2 ** 14, r=8, p=1)
    return f"scrypt${salt.hex()}${digest.hex()}"


def check_password(password: str, stored: str) -> bool:
    try:
        _, salt, digest = stored.split("$")
    except (AttributeError, ValueError):
        return False
    candidate = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=2 ** 14, r=8, p=1)
    return hmac.compare_digest(candidate.hex(), digest)


def password_problem(password: str) -> Optional[str]:
    if len(password) < 8:
        return "Use at least 8 characters."
    if password.lower() in _COMMON:
        return "That password is too common. Try another."
    return None


def smtp_sender(cfg) -> Callable[[str, str, str], None]:
    """Send over SMTP when SMTP_HOST is set; otherwise log the message (development)."""
    def send(to: str, subject: str, body: str) -> None:
        if not cfg.smtp_host:
            logger.warning(f"[Auth] SMTP not configured — email to {to}: {subject}: {body}")
            return
        msg = EmailMessage()
        msg["From"], msg["To"], msg["Subject"] = cfg.smtp_from or cfg.smtp_user, to, subject
        msg.set_content(body)
        with smtplib.SMTP(cfg.smtp_host, cfg.smtp_port, timeout=15) as smtp:
            smtp.starttls()
            if cfg.smtp_user:
                smtp.login(cfg.smtp_user, cfg.smtp_password)
            smtp.send_message(msg)
    return send


class AuthService:
    def __init__(self, store: AccountStore = None, cfg=None, clock: Callable[[], datetime] = None,
                 send_email: Callable[[str, str, str], None] = None, code_factory: Callable[[], str] = None):
        self.cfg = cfg or app_settings
        self.store = store or AccountStore()
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.send_email = send_email or smtp_sender(self.cfg)
        self.new_code = code_factory or (lambda: f"{secrets.randbelow(10 ** 6):06d}")
        self.secret = (self.cfg.auth_secret or "").encode()
        if not self.secret:
            self.secret = secrets.token_bytes(32)
            logger.warning("[Auth] AUTH_SECRET is not set: using a random key, so tokens end when the API restarts")

    # ── Helpers ──────────────────────────────────────────────

    @staticmethod
    def _email(email: str) -> str:
        email = (email or "").strip().lower()
        if not _EMAIL.match(email):
            raise InvalidRequest("Enter a valid email address.")
        return email

    def _sign(self, payload: Dict) -> str:
        body = _b64(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode())
        return f"{body}.{_b64(hmac.new(self.secret, body.encode(), hashlib.sha256).digest())}"

    def _code_hash(self, email: str, purpose: str, code: str) -> str:
        return hmac.new(self.secret, f"{email}|{purpose}|{code}".encode(), hashlib.sha256).hexdigest()

    def _send_code(self, email: str, purpose: str) -> None:
        code = self.new_code()
        expires = self.clock() + timedelta(minutes=self.cfg.auth_code_ttl_min)
        self.store.put_code(email, purpose, self._code_hash(email, purpose, code), expires)
        what = "verify your email" if purpose == "verify" else "reset your password"
        self.send_email(email, f"Your MAPNAI code: {code}",
                        f"Use {code} to {what}. It expires in {self.cfg.auth_code_ttl_min} minutes.")

    def _use_code(self, email: str, purpose: str, code: str) -> None:
        row = self.store.get_code(email, purpose)
        expires = row and row["expires_at"]
        if expires is not None and expires.tzinfo is None:          # Mongo hands back naive UTC
            expires = expires.replace(tzinfo=timezone.utc)
        if not row or expires <= self.clock():
            raise InvalidRequest("That code has expired. Send a new code.")
        if row["attempts"] >= self.cfg.auth_code_max_attempts:
            raise InvalidRequest("Too many tries. Send a new code.")
        if not hmac.compare_digest(row["code_hash"], self._code_hash(email, purpose, (code or "").strip())):
            self.store.count_attempt(email, purpose)
            raise InvalidRequest("That code didn't work.")
        self.store.drop_code(email, purpose)

    def tokens(self, account: Dict) -> Dict:
        now = int(self.clock().timestamp())
        base = {"sub": account["email"], "tv": account.get("token_version", 0)}
        return {
            "access_token": self._sign({**base, "typ": "access", "exp": now + 60 * self.cfg.auth_access_ttl_min}),
            "refresh_token": self._sign({**base, "typ": "refresh",
                                         "exp": now + 86400 * self.cfg.auth_refresh_ttl_days}),
            "user_id": account.get("user_id"),
        }

    def account_for(self, token: str, typ: str = "access") -> Dict:
        """The account a valid, unexpired, unrevoked token of type `typ` belongs to; else Unauthorized."""
        try:
            body, sig = (token or "").split(".")
            good = _b64(hmac.new(self.secret, body.encode(), hashlib.sha256).digest())
            payload = json.loads(_unb64(body)) if hmac.compare_digest(sig, good) else None
        except (ValueError, json.JSONDecodeError):
            payload = None
        if not payload or payload.get("typ") != typ or payload.get("exp", 0) <= self.clock().timestamp():
            raise Unauthorized("Sign in again.")
        account = self.store.get(payload["sub"])
        if not account or account.get("token_version", 0) != payload.get("tv"):
            raise Unauthorized("Sign in again.")
        return account

    # ── Flows ────────────────────────────────────────────────

    def register(self, email: str, password: str, birth_year: int) -> Dict:
        """New or still-unverified account: (re)set the password and email a verification code."""
        email = self._email(email)
        problem = password_problem(password or "")
        if problem:
            raise InvalidRequest(problem)
        if birth_year > self.clock().year - MIN_AGE or birth_year < 1900:
            raise InvalidRequest(f"MAPNAI is for people aged {MIN_AGE} and over.")
        existing = self.store.get(email)
        if existing and existing.get("verified"):
            raise EmailTaken("An account with this email exists.")
        fields = {"email": email, "password_hash": hash_password(password), "birth_year": birth_year,
                  "verified": False}
        if not existing:
            fields.update({"user_id": None, "token_version": 0, "created_at": self.clock()})
        self.store.upsert(email, fields)
        self._send_code(email, "verify")
        return {"ok": True}

    def verify(self, email: str, code: str) -> Dict:
        email = self._email(email)
        if not self.store.get(email):
            raise InvalidRequest("That code didn't work.")
        self._use_code(email, "verify", code)
        self.store.upsert(email, {"verified": True, "verified_at": self.clock()})
        return self.tokens(self.store.get(email))

    def resend(self, email: str) -> Dict:
        """A new verification code for an unverified account. Always ok, so it can't probe for accounts."""
        email = self._email(email)
        account = self.store.get(email)
        if account and not account.get("verified"):
            self._send_code(email, "verify")
        return {"ok": True}

    def login(self, email: str, password: str) -> Dict:
        email = self._email(email)
        account = self.store.get(email)
        if not account or not check_password(password or "", account.get("password_hash", "")):
            raise Unauthorized("Email or password is incorrect.")
        if not account.get("verified"):
            self._send_code(email, "verify")
            raise Unverified("unverified")
        return self.tokens(account)

    def refresh(self, refresh_token: str) -> Dict:
        return self.tokens(self.account_for(refresh_token, "refresh"))

    def link(self, account: Dict, user_id: str) -> Dict:
        """Attach the engine user created in onboarding, so a later sign-in on any device returns it."""
        self.store.upsert(account["email"], {"user_id": user_id})
        return {"ok": True, "user_id": user_id}

    def request_reset(self, email: str) -> Dict:
        """Email a reset code to a verified account. Always ok, so it can't probe for accounts."""
        email = self._email(email)
        account = self.store.get(email)
        if account and account.get("verified"):
            self._send_code(email, "reset")
        return {"ok": True}

    def confirm_reset(self, email: str, code: str, password: str) -> Dict:
        """Set the new password and revoke every token issued before."""
        email = self._email(email)
        problem = password_problem(password or "")
        if problem:
            raise InvalidRequest(problem)
        if not self.store.get(email):
            raise InvalidRequest("That code didn't work.")
        self._use_code(email, "reset", code)
        self.store.bump_token_version(email, {"password_hash": hash_password(password)})
        return {"ok": True}
