"""research2 shared code: paths, MIND loading, the news-value prompt and its parser.

The block between BEGIN SHARED and END SHARED is copied verbatim into the Kaggle
notebook by n02_build_notebook.py, so the notebook and the local scripts use the
same prompt and parser. The notebook checks the prompt hash at run time.
Pure standard library: runs under any Python >= 3.9.
"""
from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Tuple

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parent
MIND_DIR = REPO / "research" / "experiments" / "data" / "external" / "mind"
DATA = ROOT / "data"            # MIND-derived text: git-ignored, never published
RESULTS = ROOT / "results"      # counts and statistics only: safe to commit
ANNOT = ROOT / "annotation"     # workbooks contain MIND text: git-ignored
SEED = 13
ABSTRACT_MAX_CHARS = 600

csv.field_size_limit(10_000_000)

# --- BEGIN SHARED ---
import json as _json
import re as _re
import hashlib as _hashlib

VALUES = ["conflict", "magnitude", "prominence", "surprise", "utility", "entertainment", "importance"]

SYSTEM_PROMPT = (
    "You are a careful news content analyst. "
    "You answer with a single JSON object and nothing else."
)

USER_TEMPLATE = """Rate this news item on seven news values, each from 1 (not present) to 5 (very strong).

conflict: conflict, negativity or bad news (disputes, violence, crime, disasters, deaths, losses, scandals, failures).
magnitude: scale of impact (how many people are affected, or how large the event, sum or consequence is).
prominence: involvement of famous people, celebrities, powerful organisations, governments or nations.
surprise: how unexpected, unusual or out of the ordinary the content is.
utility: practical use to the reader (information they could act on: health, money, safety, weather, travel, shopping, how-to).
entertainment: entertainment or human interest (showbiz, sport as spectacle, humour, animals, quirky or emotional personal stories).
importance: public importance (how much a well-informed citizen ought to know this, however entertaining or dull it is).

Rules: judge only from the text below; do not guess how many readers it will get. Ordinary sports wins and losses are not conflict (1 or 2) unless there is violence, scandal or serious injury. Use the whole 1-5 range.

Headline: {title}
Abstract: {abstract}

Answer with JSON only, in this form:
{{"conflict": <1-5>, "magnitude": <1-5>, "prominence": <1-5>, "surprise": <1-5>, "utility": <1-5>, "entertainment": <1-5>, "importance": <1-5>}}"""


def build_messages(title, abstract):
    """Chat messages for one article. Empty abstract -> '(none)'."""
    abstract = (abstract or "").strip() or "(none)"
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": USER_TEMPLATE.format(title=(title or "").strip(), abstract=abstract)},
    ]


def prompt_sha256():
    """Hash of everything that defines the prompt (system text, template, value order)."""
    blob = _json.dumps([SYSTEM_PROMPT, USER_TEMPLATE, VALUES], ensure_ascii=False)
    return _hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _valid(d):
    out = {}
    for k in VALUES:
        v = d.get(k)
        if isinstance(v, bool):
            return None
        if isinstance(v, str) and v.strip().isdigit():
            v = int(v.strip())
        if isinstance(v, float) and v.is_integer():
            v = int(v)
        if not isinstance(v, int) or not 1 <= v <= 5:
            return None
        out[k] = v
    return out


def parse_scores(text):
    """Return {value: int 1..5} for all seven values, or None.

    Tries the first {...} object as JSON, then a per-key regex fallback.
    Extra keys are ignored; a missing or out-of-range key makes the item fail.
    """
    if not text:
        return None
    m = _re.search(r"\{.*?\}", text, _re.DOTALL)
    if m:
        try:
            d = _json.loads(m.group(0))
            if isinstance(d, dict):
                got = _valid(d)
                if got is not None:
                    return got
        except ValueError:
            pass
    d = {}
    for k in VALUES:
        km = _re.search(r'"?' + k + r'"?\s*[:=]\s*"?(\d)"?', text)
        if not km:
            return None
        d[k] = int(km.group(1))
    return _valid(d)
# --- END SHARED ---


def truncate(text: str, max_chars: int = ABSTRACT_MAX_CHARS) -> str:
    """Cut at a word boundary and add an ellipsis. Humans and the LLM see the same text."""
    text = " ".join((text or "").split())
    if len(text) <= max_chars:
        return text
    cut = text[:max_chars].rsplit(" ", 1)[0]
    return cut + " …"


def load_news() -> Dict[str, Dict[str, str]]:
    """news_id -> {category, subcategory, title, abstract}, first occurrence across train then dev."""
    news: Dict[str, Dict[str, str]] = {}
    for split in ("train", "dev"):
        with open(MIND_DIR / split / "news.tsv", encoding="utf-8", newline="") as f:
            for row in csv.reader(f, delimiter="\t", quoting=csv.QUOTE_NONE):
                if row[0] in news:
                    continue
                news[row[0]] = {"category": row[1], "subcategory": row[2], "title": row[3], "abstract": row[4]}
    return news


def iter_impressions(split: str) -> Iterator[Tuple[str, str, str, List[str], List[Tuple[str, int]]]]:
    """(impression_id, user_id, time, history, [(news_id, clicked)]) for one MIND split."""
    with open(MIND_DIR / split / "behaviors.tsv", encoding="utf-8") as f:
        for line in f:
            p = line.rstrip("\n").split("\t")
            hist = p[3].split() if p[3] else []
            cands = []
            for c in p[4].split():
                nid, lab = c.rsplit("-", 1)
                cands.append((nid, int(lab)))
            yield p[0], p[1], p[2], hist, cands


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def read_jsonl(path: Path) -> List[dict]:
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, ensure_ascii=False)
        f.write("\n")


def load_scores(path: Path) -> Dict[str, Optional[Dict[str, int]]]:
    """news_id -> scores (None if unparsed) from a notebook output file; last ok record wins."""
    out: Dict[str, Optional[Dict[str, int]]] = {}
    for rec in read_jsonl(path):
        if rec.get("ok"):
            out[rec["id"]] = rec["scores"]
        else:
            out.setdefault(rec["id"], None)
    return out
