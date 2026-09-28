"""
MAPNAI — personalization/keys.py
Canonical keys (pure).
  entity_key   — the canonical entity key is `name_lower` (plan C1): trim, collapse whitespace, lower-case.
                 One key covers every (name, type) variant of an entity in Neo4j.
  encode_key   — Beta keys become Mongo field names, which can't contain "." or "$" (plan C14).
  beta_key     — "topic:<topic>" | "entity:<entity_key>".
"""

import re
from typing import Literal

_WS = re.compile(r"\s+")


def entity_key(name: str) -> str:
    return _WS.sub(" ", str(name or "")).strip().lower()


def encode_key(k: str) -> str:
    """Reversible: "%" first, so an encoded key never decodes to something else."""
    return k.replace("%", "%25").replace(".", "%2E").replace("$", "%24")


def decode_key(k: str) -> str:
    return k.replace("%2E", ".").replace("%24", "$").replace("%25", "%")


def beta_key(kind: Literal["topic", "entity"], value: str) -> str:
    if kind not in ("topic", "entity"):
        raise ValueError(f"beta key kind must be topic or entity, got {kind!r}")
    value = entity_key(value) if kind == "entity" else str(value).strip().lower()
    return f"{kind}:{value}"
