"""
MAPNAI — utils/text_cleaner.py
All text normalization, cleaning, language detection, and
timestamp normalization utilities live here.
"""

import re
import html
import chardet
from datetime import datetime, timezone
from typing import Optional
from bs4 import BeautifulSoup
from dateutil import parser as dateutil_parser
import ftfy
from langdetect import detect, LangDetectException

from utils.logger import logger


# ── HTML & Markup Removal ────────────────────────────────────

def strip_html(text: str) -> str:
    """Remove all HTML tags and decode HTML entities."""
    if not text:
        return ""
    # BeautifulSoup for proper tag removal
    soup = BeautifulSoup(text, "lxml")
    clean = soup.get_text(separator=" ", strip=True)
    # Decode remaining HTML entities
    clean = html.unescape(clean)
    return clean


def remove_urls(text: str) -> str:
    """Remove all URLs (http, https, www)."""
    url_pattern = re.compile(
        r"http[s]?://(?:[a-zA-Z]|[0-9]|[$\-_@.&+]|[!*\\(\\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+"
        r"|www\.[^\s]+"
    )
    return url_pattern.sub(" ", text)


def remove_special_chars(text: str) -> str:
    """Remove non-printable and exotic unicode characters, keep punctuation."""
    # Remove zero-width spaces, BOM, etc.
    text = re.sub(r"[\u200b\u200c\u200d\ufeff\u00ad]", "", text)
    # Collapse repeated punctuation
    text = re.sub(r"[!]{3,}", "!", text)
    text = re.sub(r"[?]{3,}", "?", text)
    text = re.sub(r"[.]{4,}", "...", text)
    return text


def normalize_whitespace(text: str) -> str:
    """Collapse multiple spaces/newlines into single space."""
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def fix_encoding(text: str) -> str:
    """
    Attempt to fix mojibake and bad encoding using ftfy.
    Handles Latin-1 misread as UTF-8, etc.
    """
    if not text:
        return ""
    try:
        return ftfy.fix_text(text)
    except Exception:
        return text


def clean_text(text: str) -> str:
    """
    Full cleaning pipeline for raw article body / title.
    Order matters: fix encoding → strip HTML → remove URLs
                   → remove special chars → normalize whitespace.
    """
    if not text:
        return ""
    text = fix_encoding(text)
    text = strip_html(text)
    text = remove_urls(text)
    text = remove_special_chars(text)
    text = normalize_whitespace(text)
    return text


# ── Language Detection ───────────────────────────────────────

def detect_language(text: str) -> str:
    """
    Detect language code from text (e.g. 'en', 'hi', 'fr').
    Returns 'unknown' if detection fails or text too short.
    """
    if not text or len(text.strip()) < 20:
        return "unknown"
    try:
        lang = detect(text)
        return lang
    except LangDetectException:
        return "unknown"
    except Exception as e:
        logger.warning(f"Language detection error: {e}")
        return "unknown"


def is_english(text: str) -> bool:
    """Quick boolean check — does this text appear to be English?"""
    return detect_language(text) == "en"


# ── Timestamp Normalization ──────────────────────────────────

def normalize_timestamp(raw_ts: Optional[str | datetime]) -> Optional[datetime]:
    """
    Convert any timestamp format to UTC-aware datetime object.
    Accepts:
      - ISO 8601 strings       → "2024-03-15T10:30:00+05:30"
      - RFC 2822 strings       → "Thu, 15 Mar 2024 10:30:00 +0530" (RSS)
      - Unix epoch integers    → 1710495000
      - Datetime objects       → already parsed
    Returns None if parsing fails.
    """
    if raw_ts is None:
        return None

    if isinstance(raw_ts, datetime):
        # Already a datetime — ensure UTC
        if raw_ts.tzinfo is None:
            return raw_ts.replace(tzinfo=timezone.utc)
        return raw_ts.astimezone(timezone.utc)

    if isinstance(raw_ts, (int, float)):
        # Unix epoch
        try:
            return datetime.fromtimestamp(raw_ts, tz=timezone.utc)
        except Exception:
            return None

    if isinstance(raw_ts, str):
        raw_ts = raw_ts.strip()
        if not raw_ts:
            return None
        try:
            dt = dateutil_parser.parse(raw_ts)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except Exception as e:
            logger.debug(f"Timestamp parse failed for '{raw_ts}': {e}")
            return None

    return None


def to_iso8601(dt: Optional[datetime]) -> Optional[str]:
    """Format datetime to ISO 8601 UTC string: 2026-04-19T14:30:00Z"""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ── Domain Classification ────────────────────────────────────

def classify_domain(text: str, title: str = "") -> str:
    """
    Keyword-based fallback domain classifier.
    Used when source-level domain is 'general' or missing.
    Returns the domain key with the highest keyword hit count.
    """
    from config.sources import DOMAIN_KEYWORDS

    combined = (title + " " + text).lower()
    scores: dict[str, int] = {}
    for domain, keywords in DOMAIN_KEYWORDS.items():
        score = sum(1 for kw in keywords if kw in combined)
        scores[domain] = score

    best = max(scores, key=scores.get)
    if scores[best] == 0:
        return "general"
    return best


# ── Quality Gates ─────────────────────────────────────────────

def passes_quality_gates(
    title: str,
    body: str,
    language: str,
    min_length: int = 100,
    require_english: bool = True,
) -> tuple[bool, str]:
    """
    Returns (passes: bool, reason: str).
    reason is empty string on pass, explanation on fail.
    """
    if not title or not title.strip():
        return False, "Empty title"
    if not body or not body.strip():
        return False, "Empty body"
    if len(body.strip()) < min_length:
        return False, f"Body too short ({len(body.strip())} < {min_length} chars)"
    if require_english and language not in ("en", "unknown"):
        # 'unknown' allowed — we can't reject what we can't detect
        if not is_english(body[:500]):
            return False, f"Non-English content (detected: {language})"
    return True, ""
