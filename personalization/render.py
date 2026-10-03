"""
MAPNAI — personalization/render.py
Style rewrite of one article (PERSONALIZATION_PLAN.md §5 "Render", C13). There is no Agent 6: the LLM is Groq
through the shared utils.groq_client.init_groq_llm client (the one Agents 2–4 use), with the model from
render_model because the client's built-in model is no longer served.

The LLM sees only the source text and the style triple {tone, length, jargon}, never the reader, so one rewrite per
(article, tone, length, jargon, render_prompt_version) serves everyone with that style; the personal brief (why line,
exposures) is attached outside the rewrite by the service.

Source text: the summary sized for the target length (short → summary_short, medium → summary_long, each falling back
to the other), else the body cut to render_source_chars at a sentence end.
Every rewrite is fact-checked (personalization/factcheck.py); a failure serves the source text (`fallback`) and is
cached like a success, so the same rewrite isn't paid for again. Transport errors and a missing client are not cached.
"""

import hashlib
import json
import re
from datetime import datetime
from typing import Callable, Dict, List, Optional, Tuple

from personalization import factcheck
from utils.logger import logger

STYLE_RULES = {
    "tone": {
        "plain": "Plain, everyday language, as if explaining to a smart friend who hasn't followed the story.",
        "analyst": "A crisp analyst briefing: lead with the development. Neutral, no hype.",
    },
    "length": {
        "short": "1-2 sentences, at most 50 words.",
        "medium": "up to 5 sentences, at most 120 words.",
    },
    "jargon": {
        "low": "Avoid jargon; if a technical term must stay, explain it in a few words.",
        "high": "Domain terminology is fine; don't explain standard terms.",
    },
}

SYSTEM_PROMPT = """You rewrite a news text for one reader's preferred style.

STYLE
- Tone: {tone}
- Length: {length}
- Jargon: {jargon}

RULES
1. Keep every number, amount, percentage, date and name exactly as written. Write numbers as digits.
2. Add nothing that is not in the text: no new facts, numbers, names, background, implications, conclusions,
   opinions or speculation. Every sentence you write must be supported by the text.
3. The length is a maximum. Never make the rewrite longer than the text; a short text stays short.
4. Return only a JSON object: {{"text": "<the rewrite>"}}"""


def style_key(style: Dict[str, str]) -> Tuple[str, str, str]:
    return style["tone"], style["length"], style["jargon"]


def cache_key(article_id: str, style: Dict[str, str], cfg) -> Dict:
    tone, length, jargon = style_key(style)
    return {"article_id": article_id, "tone": tone, "length": length, "jargon": jargon,
            "prompt_version": cfg.render_prompt_version}


def _cut(body: str, limit: int) -> str:
    """The body up to `limit` characters, ending at the last sentence end inside it when there is one."""
    body = re.sub(r"\s+", " ", body or "").strip()
    if len(body) <= limit:
        return body
    head = body[:limit]
    end = max(head.rfind(". "), head.rfind("! "), head.rfind("? "))
    return head[:end + 1] if end > 0 else head.rstrip()


def source_text(doc: Dict, length: str, cfg) -> Tuple[str, Optional[str]]:
    """(the text to rewrite, the field it came from | None when the article has no text)."""
    order = ["summary_short", "summary_long"] if length == "short" else ["summary_long", "summary_short"]
    for field in order:
        text = (doc.get(field) or "").strip()
        if text:
            return text, field
    body = _cut(doc.get("body") or "", cfg.render_source_chars)
    return (body, "body") if body else ("", None)


def source_hash(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]


def build_messages(source: str, style: Dict[str, str]) -> List[Dict[str, str]]:
    rules = {k: STYLE_RULES[k][style[k]] for k in ("tone", "length", "jargon")}
    return [{"role": "system", "content": SYSTEM_PROMPT.format(**rules)},
            {"role": "user", "content": source}]


def parse_response(content: Optional[str]) -> Optional[str]:
    """{"text": "..."} → the text; None when the model returned anything else."""
    try:
        text = json.loads(content or "").get("text")
    except (ValueError, AttributeError):
        return None
    return text.strip() if isinstance(text, str) and text.strip() else None


class Renderer:
    """Cache → LLM → fact-check → cache. `llm_calls` counts the completions requested by this instance."""

    def __init__(self, logs, cfg, llm_factory: Callable[[], Tuple[Optional[object], Optional[str]]],
                 clock: Callable[[], datetime]):
        self.logs, self.cfg, self.clock = logs, cfg, clock
        self._llm_factory = llm_factory
        self._llm: Optional[Tuple[Optional[object], Optional[str]]] = None
        self.llm_calls = 0

    def _client(self) -> Tuple[Optional[object], Optional[str]]:
        if self._llm is None:
            client, model = self._llm_factory()
            self._llm = (client, self.cfg.render_model or model) if client else (None, None)
        return self._llm

    @staticmethod
    def _source_only(source: str, reason: str, **extra) -> Dict:
        return {"text": source, "cached": False, "fallback": True, "reason": reason, "missing": [], "added": [],
                "model": None, "llm_call": False, **extra}

    def render(self, article_id: str, source: str, source_field: Optional[str], entity_names: List[str],
               style: Dict[str, str], refresh: bool = False) -> Dict:
        c = self.cfg
        if not source:
            return self._source_only("", "no_source_text")
        if not c.enable_render:
            return self._source_only(source, "render_disabled")

        key, digest = cache_key(article_id, style, c), source_hash(source)
        hit = None if refresh else self.logs.render_get(key)
        if hit and hit.get("source_hash") == digest:      # a new summary for the article invalidates the entry
            return {**{k: hit.get(k) for k in ("text", "fallback", "reason", "missing", "added", "model")},
                    "cached": True, "llm_call": False}

        client, model = self._client()
        if client is None:
            return self._source_only(source, "no_llm_client")
        self.llm_calls += 1
        try:
            response = client.chat.completions.create(
                model=model, messages=build_messages(source, style), response_format={"type": "json_object"},
                temperature=c.render_temperature, max_tokens=c.render_max_tokens, extra_body=c.render_llm_extra)
            rewrite = parse_response(response.choices[0].message.content)
        except Exception as e:                            # not cached: the next request tries again
            logger.error(f"[Render] {model} failed for {article_id}: {type(e).__name__}: {e}")
            return self._source_only(source, f"llm_error: {type(e).__name__}", model=model, llm_call=True)

        if rewrite is None:
            ok, missing, added, reason = False, [], [], "unparseable_response"
        else:
            ok, missing, added = factcheck.verify(source, rewrite, entity_names)
            reason = None if ok else "fact_check"
        if not ok:
            logger.warning(f"[Render] {article_id} {style_key(style)} falls back to the source: {reason} "
                           f"missing={missing} added={added}")
        doc = {**key, "source_hash": digest, "source_field": source_field, "text": rewrite if ok else source,
               "rewrite": rewrite, "fallback": not ok, "reason": reason, "missing": missing, "added": added,
               "model": model, "created_at": self.clock()}
        self.logs.render_put(doc)
        return {**{k: doc[k] for k in ("text", "fallback", "reason", "missing", "added", "model")},
                "cached": False, "llm_call": True}
