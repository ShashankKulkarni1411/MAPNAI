"""
MAPNAI — storage/account_store.py
App sign-in accounts (`accounts`) and one-time email codes (`auth_codes`) in Mongo.
An account links to an engine user (personas.user_id) once onboarding creates one.
"""

from datetime import datetime
from typing import Dict, Optional

from pymongo import ASCENDING

from storage.mongo_store import MongoStore

ACCOUNTS = "accounts"
CODES = "auth_codes"


class AccountStore:
    def __init__(self, mongo: Optional[MongoStore] = None):
        self.mongo = mongo or MongoStore()
        self._indexes_ok = False

    def _col(self, name: str):
        if not self._indexes_ok:
            self._indexes_ok = True
            db = self.mongo.db
            db[ACCOUNTS].create_index([("email", ASCENDING)], unique=True)
            db[CODES].create_index([("email", ASCENDING), ("purpose", ASCENDING)], unique=True)
        return self.mongo.db[name]

    # ── Accounts ─────────────────────────────────────────────

    def get(self, email: str) -> Optional[Dict]:
        return self._col(ACCOUNTS).find_one({"email": email}, {"_id": 0})

    def upsert(self, email: str, fields: Dict) -> None:
        self._col(ACCOUNTS).update_one({"email": email}, {"$set": fields}, upsert=True)

    def bump_token_version(self, email: str, fields: Dict) -> None:
        """Set fields and invalidate every token issued so far (password change)."""
        self._col(ACCOUNTS).update_one({"email": email}, {"$set": fields, "$inc": {"token_version": 1}})

    # ── One-time codes ───────────────────────────────────────

    def put_code(self, email: str, purpose: str, code_hash: str, expires_at: datetime) -> None:
        """A new code replaces the previous one for (email, purpose) and resets its attempts."""
        self._col(CODES).replace_one(
            {"email": email, "purpose": purpose},
            {"email": email, "purpose": purpose, "code_hash": code_hash, "expires_at": expires_at, "attempts": 0},
            upsert=True)

    def get_code(self, email: str, purpose: str) -> Optional[Dict]:
        return self._col(CODES).find_one({"email": email, "purpose": purpose}, {"_id": 0})

    def count_attempt(self, email: str, purpose: str) -> None:
        self._col(CODES).update_one({"email": email, "purpose": purpose}, {"$inc": {"attempts": 1}})

    def drop_code(self, email: str, purpose: str) -> None:
        self._col(CODES).delete_one({"email": email, "purpose": purpose})
