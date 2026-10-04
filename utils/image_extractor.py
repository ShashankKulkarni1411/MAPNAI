"""
MAPNAI — utils/image_extractor.py
Article image extraction. Every fetcher turns what its source exposes into image candidates
({url, width, height, alt, source}); build_media() ranks them into the article's media
({primary_image, additional_images}). Images are referenced at their original URL, never downloaded.

Candidate sources, most to least trusted as the article's hero image:
  og:image / JSON-LD NewsArticle.image / twitter:image   (article page <head>, set by the publisher)
  media:content / enclosure / the API's image field     (feed or API metadata)
  <img> inside the article body or the feed's HTML
  media:thumbnail                                         (feed thumbnails, often ~240 px)
Logos, avatars, icons, tracking pixels, SVGs and images known to be tiny are dropped.
"""

import json
import re
from typing import Dict, Iterable, List, Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup

# rank of each candidate source (lower = more trusted as the hero image)
PRIORITY = {
    "og:image": 0, "json-ld": 1, "twitter:image": 2,
    "media:content": 3, "enclosure": 3, "api": 3, "bluesky": 3,
    "article:img": 4, "feed:img": 5, "media:thumbnail": 6,
}

MIN_WIDTH, MIN_HEIGHT = 300, 150          # smaller known sizes are thumbnails / icons
GOOD_WIDTH = 600                          # a primary narrower than this sends ingestion to the article page
MAX_ADDITIONAL = 4

# whole URL tokens only, so "silicon", "authority" or a Google Pixel photo are kept
_JUNK = re.compile(
    r"(?<![a-z0-9])(logos?|favicons?|sprites?|avatars?|gravatar|icons?|emoji|badges?|spacer|blank|1x1|"
    r"tracking|beacon|placeholder|authors?|byline|headshots?|ads?|default[-_]?(image|img|og|thumb)|"
    r"share[-_]?(button|icon)|pixel\.(gif|png))(?![a-z0-9])|doubleclick\.net|feedburner\.com/~", re.I)


def candidate(url: Optional[str], source: str, base: str = "", width=None, height=None,
              alt: Optional[str] = None) -> Optional[Dict]:
    """One image candidate, or None when the URL is unusable or looks like a logo / icon / pixel."""
    url = (url or "").strip()
    if not url or url.startswith("data:"):
        return None
    if url.startswith("//"):
        url = "https:" + url
    url = urljoin(base, url) if base else url
    if not url.startswith(("http://", "https://")):
        return None
    url = _unbranded(url)
    path = url.split("?")[0].lower()
    if path.endswith((".svg", ".ico")) or _JUNK.search(url):
        return None
    w, h = _int(width), _int(height)
    if (w and w < MIN_WIDTH) or (h and h < MIN_HEIGHT):
        return None
    return {"url": url, "width": w, "height": h, "alt": (alt or "").strip()[:300] or None, "source": source}


def _unbranded(url: str) -> str:
    """BBC's og:image has the BBC logo burned in; its CDN serves the same picture without it at /ace/standard/."""
    if "ichef.bbci.co.uk/ace/branded_" in url:
        return re.sub(r"/ace/branded_[a-z]+/", "/ace/standard/", url, count=1)
    return url


def _int(v) -> Optional[int]:
    try:
        n = int(float(str(v).strip().rstrip("px")))
        return n if n > 0 else None
    except (TypeError, ValueError):
        return None


def _largest_srcset(srcset: str) -> Optional[str]:
    """The widest entry of a srcset ("a.jpg 320w, b.jpg 1024w")."""
    best, best_w = None, -1
    for part in (srcset or "").split(","):
        bits = part.strip().split()
        if not bits:
            continue
        w = _int(bits[1][:-1]) if len(bits) > 1 and bits[1].endswith("w") else 0
        if (w or 0) > best_w:
            best, best_w = bits[0], w or 0
    return best


def _img_tags(soup, source: str, base: str, limit: int) -> List[Dict]:
    out = []
    for img in soup.find_all("img"):
        url = (_largest_srcset(img.get("srcset") or img.get("data-srcset") or "")
               or img.get("data-src") or img.get("data-original") or img.get("src"))
        c = candidate(url, source, base, img.get("width"), img.get("height"), img.get("alt"))
        if c:
            out.append(c)
            if len(out) >= limit:
                break
    return out


# ── Feed entries (feedparser) ────────────────────────────────

def from_feed_entry(entry) -> List[Dict]:
    """Image candidates from one feedparser entry: media:content, enclosures, media:thumbnail, <img> in its HTML."""
    out: List[Dict] = []
    for m in entry.get("media_content") or []:
        medium, mtype = (m.get("medium") or ""), (m.get("type") or "")
        if medium == "image" or mtype.startswith("image") or (not medium and not mtype):
            out.append(candidate(m.get("url"), "media:content", width=m.get("width"), height=m.get("height")))
    for link in entry.get("links") or []:
        if link.get("rel") == "enclosure" and (link.get("type") or "").startswith("image"):
            out.append(candidate(link.get("href"), "enclosure"))
    for t in entry.get("media_thumbnail") or []:
        out.append(candidate(t.get("url"), "media:thumbnail", width=t.get("width"), height=t.get("height")))
    html = " ".join([(entry.get("content") or [{}])[0].get("value", ""), entry.get("summary") or ""])
    if "<img" in html:
        out += _img_tags(BeautifulSoup(html, "lxml"), "feed:img", entry.get("link") or "", 3)
    return [c for c in out if c]


# ── Article pages ────────────────────────────────────────────

def _meta(soup, *names: str) -> Optional[str]:
    for n in names:
        tag = soup.find("meta", attrs={"property": n}) or soup.find("meta", attrs={"name": n})
        if tag and tag.get("content"):
            return tag["content"]
    return None


def _jsonld_images(soup, base: str) -> List[Dict]:
    """NewsArticle / Article / ReportageNewsArticle `image` (a URL, a list, or ImageObject{url,width,height})."""
    out: List[Dict] = []
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
        except (ValueError, TypeError):
            continue
        nodes = data if isinstance(data, list) else data.get("@graph", [data]) if isinstance(data, dict) else []
        for node in nodes:
            if not isinstance(node, dict):
                continue
            kind = node.get("@type")
            kinds = kind if isinstance(kind, list) else [kind]
            if not any(isinstance(k, str) and "Article" in k for k in kinds):
                continue
            imgs = node.get("image")
            for img in imgs if isinstance(imgs, list) else [imgs]:
                if isinstance(img, str):
                    out.append(candidate(img, "json-ld", base))
                elif isinstance(img, dict):
                    out.append(candidate(img.get("url") or img.get("contentUrl"), "json-ld", base,
                                         img.get("width"), img.get("height"), img.get("caption")))
    return [c for c in out if c]


def from_html(html, base_url: str) -> List[Dict]:
    """Image candidates from an article page (HTML string or BeautifulSoup)."""
    soup = html if isinstance(html, BeautifulSoup) else BeautifulSoup(html or "", "lxml")
    out: List[Dict] = []
    og = _meta(soup, "og:image:secure_url", "og:image", "og:image:url")
    if og:
        out.append(candidate(og, "og:image", base_url, _meta(soup, "og:image:width"),
                             _meta(soup, "og:image:height"), _meta(soup, "og:image:alt")))
    out += _jsonld_images(soup, base_url)
    tw = _meta(soup, "twitter:image", "twitter:image:src")
    if tw:
        out.append(candidate(tw, "twitter:image", base_url, alt=_meta(soup, "twitter:image:alt")))
    body = soup.find("article") or soup.find("main")
    if body:
        out += _img_tags(body, "article:img", base_url, 6)
    return [c for c in out if c]


# ── Ranking ──────────────────────────────────────────────────

def _dedupe_key(url: str) -> str:
    return url.split("?")[0].split("#")[0].lower()


def build_media(candidates: Iterable[Optional[Dict]]) -> Optional[Dict]:
    """
    Candidates → {primary_image, additional_images} or None. Ranked by source trust, then known area;
    the same image (URL without query) is kept once, at its best-ranked occurrence.
    """
    seen, ranked = set(), []
    for c in sorted((c for c in candidates if c),
                    key=lambda c: (PRIORITY.get(c["source"], 9), -((c.get("width") or 0) * (c.get("height") or 0)))):
        k = _dedupe_key(c["url"])
        if k not in seen:
            seen.add(k)
            ranked.append(c)
    if not ranked:
        return None
    return {"primary_image": ranked[0], "additional_images": ranked[1:1 + MAX_ADDITIONAL]}


def needs_page_lookup(media: Optional[Dict]) -> bool:
    """True when the article page may hold a better hero image than the feed gave (none, a thumbnail, or small)."""
    p = (media or {}).get("primary_image")
    if not p:
        return True
    if PRIORITY.get(p["source"], 9) >= PRIORITY["article:img"]:
        return True
    return bool(p.get("width") and p["width"] < GOOD_WIDTH)


def merge(media: Optional[Dict], more: List[Dict]) -> Optional[Dict]:
    """Re-rank an article's media with extra candidates (e.g. from its page)."""
    if not more:
        return media
    have = [] if not media else [media.get("primary_image"), *(media.get("additional_images") or [])]
    return build_media(have + more)
