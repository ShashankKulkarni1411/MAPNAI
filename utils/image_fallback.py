"""
MAPNAI — utils/image_fallback.py
Fallback hero image for articles whose feed and page gave none: the free-licensed lead image of the
Wikipedia article about the story's main named entity (person, organisation, product, event).

Relevance comes from the entity itself — it was extracted from this article — plus checks that the
Wikipedia page really is about that named thing and about this story's subject:
  - the entity is a person / organisation / product / event, never a place (a country flag or map would
    be the same generic picture on every story from that country)
  - only entities named in the headline (full name or surname): the story's subject, not a passing mention
  - the page exists, is not a disambiguation page and is not a generic concept ("A treasury is …")
  - a Person entity resolves to a biography, an Organization entity never to a place
  - the page intro shares content words with the headline/summary beyond the page's own name: one when the
    page title is the entity's full name ("Kawhi Leonard"), two when it was reached by a redirect or is a
    longer name ("US Treasury" → "United States Department of the Treasury")
  - Wikipedia's own `pilicense=free` filter: only freely licensed images, with author + licence kept
resolve() looks names up in batches (20 per call) and fills a cache of hits and misses, so a name is
resolved once; fallback_image() then only reads the cache.
"""

import re
import time
from typing import Dict, Iterable, List, Optional

import requests

from config.settings import settings
from utils.logger import logger

API = "https://en.wikipedia.org/w/api.php"
TYPES = {"Person", "Organization", "Product/Technology", "Event"}
MAX_TRIES = 3
THUMB_WIDTH = 1200
BATCH = 20                                  # extracts' limit per call with exintro

_GENERIC = re.compile(r"^(an?\s)|may refer to|most often refers|is either|is the common name", re.I)
_PERSON = re.compile(r"\bborn\b|\(\s*(c\.\s*)?\d{3,4}\s*[–-]|\b(1[89]|20)\d\d\s*[–-]\s*(1[89]|20)\d\d\b")
_PLACE = re.compile(r"^[^.]{0,120}\b(is|was) an? [^.]{0,40}\b(county|city|town|village|country|state|province|"
                    r"region|district|island|capital|municipality|river|mountain)\b", re.I)
_WORD = re.compile(r"[a-z][a-z0-9\-]{3,}")
_STOP = {
    "this", "that", "with", "from", "have", "been", "were", "will", "would", "about", "after", "their",
    "there", "which", "while", "where", "when", "what", "into", "over", "more", "most", "also", "than",
    "they", "them", "said", "says", "known", "born", "including", "other", "such", "since", "first",
    "american", "british", "based", "company", "people", "year", "years", "time", "world", "new",
}


def _norm(name: str) -> str:
    name = re.sub(r"[’']s\b", "", name or "")
    name = re.sub(r"^the\s+", "", name.strip(), flags=re.I)
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s.&-]", " ", name)).strip()


def _words(text: str) -> set:
    return {w for w in _WORD.findall((text or "").lower()) if w not in _STOP}


def _in_headline(name: str, title_words: set) -> bool:
    toks = name.lower().split()
    return bool(toks) and (all(t in title_words for t in toks) or (len(toks) > 1 and len(toks[-1]) >= 4
                                                                   and toks[-1] in title_words))


def pick_entities(title: str, entities: List[Dict]) -> List[Dict]:
    """[{name, type}] worth looking up: named in the headline, by salience."""
    title_words = set(re.findall(r"[\w.&-]+", _norm(title).lower()))
    seen, out = set(), []
    ranked = sorted((e for e in entities or [] if e.get("type") in TYPES), key=lambda e: -(e.get("salience") or 0))
    for e in ranked:
        name = _norm(e.get("name", ""))
        if len(name) < 3 or name.lower() in seen or not _in_headline(name, title_words):
            continue
        seen.add(name.lower())
        out.append({"name": name, "type": e["type"]})
    return out[:MAX_TRIES]


def _get(params: Dict) -> Optional[Dict]:
    """One API call (one retry after a 429); None on failure, so those names stay uncached and are retried."""
    for attempt in range(2):
        try:
            r = requests.get(API, params={"action": "query", "format": "json", "formatversion": 2, **params},
                             headers={"User-Agent": settings.wikimedia_user_agent},
                             timeout=settings.media_lookup_timeout_seconds)
            if r.status_code == 429 and attempt == 0:
                time.sleep(min(int(r.headers.get("Retry-After") or 5), 30))
                continue
            return r.json() if r.status_code == 200 else None
        except (requests.RequestException, ValueError) as e:
            logger.debug(f"[ImageFallback] wikipedia call failed: {type(e).__name__}")
            return None
    return None


def _credits(files: List[str]) -> Dict[str, str]:
    """File name → "author · licence · Wikimedia Commons"."""
    out = {}
    for i in range(0, len(files), 50):
        data = _get({"titles": "|".join(f"File:{f}" for f in files[i:i + 50]), "prop": "imageinfo",
                     "iiprop": "extmetadata", "iiextmetadatafilter": "Artist|LicenseShortName"})
        for page in ((data or {}).get("query") or {}).get("pages", []):
            meta = ((page.get("imageinfo") or [{}])[0]).get("extmetadata") or {}
            artist = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", (meta.get("Artist") or {}).get("value", ""))).strip()[:120]
            lic = (meta.get("LicenseShortName") or {}).get("value", "").strip()
            out[page["title"].split(":", 1)[-1].replace(" ", "_")] = " · ".join(
                x for x in (artist, lic, "Wikimedia Commons") if x)
    return out


def _hit(page: Dict) -> Optional[Dict]:
    thumb, extract = page.get("thumbnail") or {}, (page.get("extract") or "").strip()
    if (page.get("missing") or "disambiguation" in (page.get("pageprops") or {})
            or not thumb.get("source") or not page.get("pageimage") or not extract or _GENERIC.search(extract[:80])):
        return None
    file_name = page["pageimage"]
    return {"page": page["title"], "extract": extract[:1000],
            "image": {"url": thumb["source"], "width": thumb.get("width"), "height": thumb.get("height"),
                      "alt": page["title"], "source": "wikipedia", "credit": "Wikimedia Commons",
                      "credit_url": f"https://commons.wikimedia.org/wiki/File:{file_name}"},
            "file": file_name}


def resolve(names: Iterable[str], cache: Dict) -> None:
    """Look up every name not yet in `cache` (key: lower-case name → hit dict or None)."""
    todo = sorted({n for n in names if n.lower() not in cache})
    for i in range(0, len(todo), BATCH):
        chunk = todo[i:i + BATCH]
        data = _get({"titles": "|".join(chunk), "redirects": 1, "prop": "pageimages|pageprops|extracts",
                     "piprop": "thumbnail|name", "pithumbsize": THUMB_WIDTH, "pilicense": "free", "pilimit": BATCH,
                     "ppprop": "disambiguation", "exintro": 1, "explaintext": 1, "exsentences": 3, "exlimit": BATCH})
        if not data or "query" not in data:
            continue
        q = data["query"]
        hops = {x["from"]: x["to"] for x in (q.get("normalized") or []) + (q.get("redirects") or [])}
        pages = {p["title"]: p for p in q.get("pages", [])}
        hits = {}
        for name in chunk:
            title = name
            for _ in range(3):
                title = hops.get(title, title)
            hits[name] = _hit(pages[title]) if title in pages else None
        credit = _credits(sorted({h["file"] for h in hits.values() if h}))
        for name, h in hits.items():
            if h and credit.get(h["file"]):
                h["image"]["credit"] = credit[h["file"]]
            cache[name.lower()] = h


def _fits(entity_type: str, extract: str) -> bool:
    if entity_type == "Person":
        return bool(_PERSON.search(extract[:300]))
    return not _PLACE.search(extract)


def fallback_image(title: str, text: str, entities: List[Dict], cache: Dict) -> Optional[Dict]:
    """A relevant free image for an article (title + summary/body `text`) from a resolve()d cache, or None."""
    article_words = _words(f"{title} {text}")
    for ent in pick_entities(title, entities):
        hit = cache.get(ent["name"].lower())
        if not hit or not _fits(ent["type"], hit["extract"]):
            continue
        exact = re.sub(r"\s*\(.*\)$", "", hit["page"]).lower() == ent["name"].lower()
        shared = (article_words & _words(hit["extract"])) - _words(hit["page"]) - _words(ent["name"])
        if len(shared) >= (1 if exact else 2):
            return dict(hit["image"])
    return None
