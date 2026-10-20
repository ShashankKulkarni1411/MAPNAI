"""
MAPNAI — tests/test_media.py
Article images: candidate filtering, feed / page / JSON-LD extraction, ranking into `media`,
the page-lookup agent (network mocked) and media through preprocessing.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from unittest.mock import MagicMock, patch

import feedparser

from agents.media_agent import MediaAgent
from agents.preprocessing_agent import PreprocessingAgent
from utils.image_extractor import build_media, candidate, from_feed_entry, from_html, needs_page_lookup
from utils.models import ArticleMedia, ProcessedArticle, RawArticle, SourceType, Domain

BODY = "Karigowda began cultivating baby bottle gourd on his farm after learning about its overseas demand. " * 3

PAGE = """<html><head>
<meta property="og:image" content="/img/hero.jpg"><meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630"><meta property="og:image:alt" content="A farmer">
<meta name="twitter:image" content="https://cdn.example.com/img/hero.jpg?tw=1">
<script type="application/ld+json">{"@type": "NewsArticle", "image": [{"@type": "ImageObject",
 "url": "https://cdn.example.com/img/gourd.jpg", "width": 1600, "height": 900}]}</script>
</head><body><header><img src="/static/site-logo.png"></header>
<article><img src="https://cdn.example.com/img/field.jpg" width="800" height="450" alt="Field">
<img src="https://cdn.example.com/img/author-headshot.jpg"><img src="https://t.example.com/1x1.gif"></article>
</body></html>"""

RSS = """<?xml version="1.0"?><rss version="2.0" xmlns:media="http://search.yahoo.com/mrss/"><channel><title>t</title>
<item><title>Gourd exports</title><link>https://news.example.com/a</link>
<media:thumbnail url="https://cdn.example.com/240/thumb.jpg" width="240" height="135"/>
<media:content url="https://cdn.example.com/full.jpg" medium="image" width="1024" height="576"/>
<enclosure url="https://cdn.example.com/enc.jpg" type="image/jpeg" length="1"/>
<description><![CDATA[<p><img src="https://cdn.example.com/inline.jpg"></p>text]]></description></item>
</channel></rss>"""


class TestCandidate:
    def test_drops_logos_icons_pixels_svg_and_small(self):
        for url in ["https://x.com/logo.png", "https://x.com/i/icons/a.png", "https://x.com/1x1.gif",
                    "https://x.com/a.svg", "data:image/png;base64,AA", "https://x.com/u/avatar_9.jpg", "ftp://x/a.jpg"]:
            assert candidate(url, "og:image") is None, url
        assert candidate("https://x.com/a.jpg", "og:image", width=120) is None

    def test_keeps_words_that_only_contain_junk_tokens(self):
        for url in ["https://x.com/silicon-valley.jpg", "https://x.com/authority-meeting.jpg",
                    "https://x.com/uploads/2026/pixel-10-review.jpg"]:
            assert candidate(url, "og:image") is not None, url

    def test_resolves_relative_and_protocol_relative(self):
        assert candidate("/a/b.jpg", "og:image", "https://site.com/news/1")["url"] == "https://site.com/a/b.jpg"
        assert candidate("//cdn.site.com/b.jpg", "og:image")["url"] == "https://cdn.site.com/b.jpg"

    def test_bbc_branded_image_is_swapped_for_the_plain_one(self):
        c = candidate("https://ichef.bbci.co.uk/ace/branded_news/1200/cpsprodpb/1/live/x.jpg", "og:image")
        assert c["url"] == "https://ichef.bbci.co.uk/ace/standard/1200/cpsprodpb/1/live/x.jpg"


class TestExtraction:
    def test_page_og_jsonld_twitter_and_article_images(self):
        got = from_html(PAGE, "https://news.example.com/story")
        assert [(c["source"], c["url"]) for c in got] == [
            ("og:image", "https://news.example.com/img/hero.jpg"),
            ("json-ld", "https://cdn.example.com/img/gourd.jpg"),
            ("twitter:image", "https://cdn.example.com/img/hero.jpg?tw=1"),
            ("article:img", "https://cdn.example.com/img/field.jpg"),
        ]
        assert got[0]["width"] == 1200 and got[0]["alt"] == "A farmer"

    def test_feed_entry(self):
        entry = feedparser.parse(RSS).entries[0]
        got = {c["source"]: c["url"] for c in from_feed_entry(entry)}
        assert got == {"media:content": "https://cdn.example.com/full.jpg", "enclosure": "https://cdn.example.com/enc.jpg",
                       "feed:img": "https://cdn.example.com/inline.jpg"}          # the 240 px thumbnail is dropped

    def test_ranking_prefers_publisher_hero_and_dedupes(self):
        media = build_media([candidate("https://c.com/thumb.jpg", "media:thumbnail"),
                             candidate("https://c.com/hero.jpg?w=1", "media:content", width=1024),
                             candidate("https://c.com/hero.jpg?w=2", "og:image"),
                             None])
        assert media["primary_image"]["url"] == "https://c.com/hero.jpg?w=2"
        assert [i["url"] for i in media["additional_images"]] == ["https://c.com/thumb.jpg"]
        assert build_media([None]) is None

    def test_needs_page_lookup(self):
        assert needs_page_lookup(None)
        assert needs_page_lookup(build_media([candidate("https://c.com/a.jpg", "feed:img")]))
        assert needs_page_lookup(build_media([candidate("https://c.com/a.jpg", "media:content", width=460)]))
        assert not needs_page_lookup(build_media([candidate("https://c.com/a.jpg", "media:content", width=1024)]))
        assert not needs_page_lookup(build_media([candidate("https://c.com/a.jpg", "og:image")]))


def _article(url, media=None, source_type=SourceType.RSS):
    return ProcessedArticle(title="Gourd", body=BODY, url=url, source_name="S", source_type=source_type,
                            domain=Domain.GENERAL, media=ArticleMedia(**media) if media else None)


class TestMediaAgent:
    @patch("agents.media_agent.requests.get")
    def test_looks_up_only_articles_without_a_good_image(self, mock_get):
        resp = MagicMock(status_code=200, headers={"Content-Type": "text/html"}, encoding="utf-8",
                         url="https://news.example.com/story")
        resp.iter_content.return_value = [PAGE.encode()]
        mock_get.return_value.__enter__.return_value = resp
        good = _article("https://n.com/good", build_media([candidate("https://c.com/og.jpg", "og:image")]))
        bare = _article("https://n.com/bare")
        post = _article("https://bsky.app/x", source_type=SourceType.BLUESKY)
        out = MediaAgent(workers=2, timeout=1, max_lookups=10).enrich_batch([good, bare, post])
        assert mock_get.call_count == 1 and mock_get.call_args[0][0] == "https://n.com/bare"
        assert out[1].media.primary_image.url == "https://news.example.com/img/hero.jpg"
        assert out[0].media.primary_image.url == "https://c.com/og.jpg" and out[2].media is None

    @patch("agents.media_agent.requests.get", side_effect=Exception("boom"))
    def test_a_failed_lookup_keeps_the_article(self, _):
        out = MediaAgent(workers=1, timeout=1, max_lookups=10).enrich_batch([_article("https://n.com/a")])
        assert len(out) == 1 and out[0].media is None


class TestPreprocessingMedia:
    def test_raw_images_become_media_and_reach_mongo(self):
        raw = RawArticle(title="Bengaluru farmer turns baby bottle gourd into export crop", body=BODY,
                         url="https://n.com/a", source_name="S", source_type=SourceType.NEWS_API, author="A. Writer",
                         images=[candidate("https://c.com/hero.jpg", "api")])
        art, status = PreprocessingAgent().process(raw)
        assert status == "ok" and art.author == "A. Writer"
        doc = art.to_mongo_dict()
        assert doc["media"]["primary_image"]["url"] == "https://c.com/hero.jpg"
        assert doc["media"]["additional_images"] == []

    def test_no_image_is_fine(self):
        raw = RawArticle(title="Bengaluru farmer turns baby bottle gourd into export crop", body=BODY,
                         source_name="S", source_type=SourceType.RSS)
        art, status = PreprocessingAgent().process(raw)
        assert status == "ok" and art.to_mongo_dict()["media"] is None


# ── Fallback images (Wikipedia, network mocked) ──────────────

def _wiki_page(title, extract, image="Pic.jpg", **extra):
    return {"title": title, "extract": extract, "pageimage": image,
            "thumbnail": {"source": f"https://upload.wikimedia.org/{image}", "width": 1200, "height": 800}, **extra}


def _wiki_answer(pages, redirects=()):
    def answer(url, params, **_):
        resp = MagicMock(status_code=200, headers={})
        if params.get("prop") == "imageinfo":
            resp.json.return_value = {"query": {"pages": [
                {"title": t, "imageinfo": [{"extmetadata": {"Artist": {"value": "<a>Jane Doe</a>"},
                                                            "LicenseShortName": {"value": "CC BY-SA 4.0"}}}]}
                for t in params["titles"].split("|")]}}
        else:
            asked = params["titles"].split("|")
            resp.json.return_value = {"query": {"redirects": [{"from": a, "to": b} for a, b in redirects],
                                                "pages": [p for p in pages if p["title"] in asked or
                                                          p["title"] in dict(redirects).values()]}}
        return resp
    return answer


NVIDIA = _wiki_page("Nvidia", "Nvidia Corporation is an American multinational technology company that designs "
                              "graphics processing units and chips for artificial intelligence.", "Nvidia_HQ.jpg")
SURREY = _wiki_page("Surrey", "Surrey is a ceremonial county in South East England. Cricket is popular.", "Downs.jpg")
TREASURY = _wiki_page("Treasury", "A treasury is either a government department or a place for valuables.")
PAUL = _wiki_page("Paul", "Paul may refer to:", pageprops={"disambiguation": ""})
HUANG = _wiki_page("Jensen Huang", "Jen-Hsun Huang (born February 17, 1963) is the co-founder and chief executive "
                                   "of Nvidia, the chips company.", "Huang.jpg")


class TestImageFallback:
    def setup_method(self):
        from utils import image_fallback
        self.fb = image_fallback

    def _run(self, pages, title, text, entities, redirects=()):
        cache = {}
        with patch("utils.image_fallback.requests.get", side_effect=_wiki_answer(pages, redirects)):
            self.fb.resolve({e["name"] for e in self.fb.pick_entities(title, entities)}, cache)
        return self.fb.fallback_image(title, text, entities, cache), cache

    def test_headline_entity_gets_its_free_image_with_credit(self):
        img, _ = self._run([NVIDIA], "Nvidia boosts buyback as AI chips demand soars",
                           "The chips designer said demand for artificial intelligence hardware keeps rising.",
                           [{"name": "Nvidia", "type": "Organization", "salience": 1.0}])
        assert img["url"].endswith("Nvidia_HQ.jpg") and img["source"] == "wikipedia"
        assert img["credit"] == "Jane Doe · CC BY-SA 4.0 · Wikimedia Commons"
        assert img["credit_url"] == "https://commons.wikimedia.org/wiki/File:Nvidia_HQ.jpg"

    def test_surname_in_headline_and_redirect(self):
        img, _ = self._run([HUANG], "Huang says Nvidia chips are sold out", "The chief executive spoke on Monday.",
                           [{"name": "Jensen Huang", "type": "Person", "salience": 1.0}])
        assert img["alt"] == "Jensen Huang"

    def test_entity_not_in_headline_is_ignored(self):
        img, cache = self._run([NVIDIA], "Thailand eyes short-term debt", "Chips and artificial intelligence...",
                               [{"name": "Nvidia", "type": "Organization", "salience": 1.0}])
        assert img is None and cache == {}

    def test_places_generic_and_disambiguation_pages_are_rejected(self):
        img, cache = self._run([SURREY, TREASURY, PAUL], "Surrey beat Paul's side as Treasury watches",
                               "Cricket county championship match report.",
                               [{"name": "Surrey", "type": "Organization"}, {"name": "Treasury", "type": "Organization"},
                                {"name": "Paul", "type": "Person"}])
        assert img is None
        assert cache["treasury"] is None and cache["paul"] is None and cache["surrey"] is not None   # place → _fits

    def test_unrelated_page_is_rejected(self):
        # "Nvidia" resolves fine, but the story shares nothing with the page beyond the name
        img, _ = self._run([NVIDIA], "Nvidia the racehorse wins at Ascot", "The filly won by two lengths.",
                           [{"name": "Nvidia", "type": "Organization"}])
        assert img is None

    def test_person_entity_must_resolve_to_a_biography(self):
        img, _ = self._run([NVIDIA], "Nvidia praised for AI chips", "artificial intelligence chips company",
                           [{"name": "Nvidia", "type": "Person"}])
        assert img is None

    def test_wikipedia_down_is_not_cached(self):
        cache = {}
        import requests
        with patch("utils.image_fallback.requests.get", side_effect=requests.ConnectionError("down")):
            self.fb.resolve({"Nvidia"}, cache)
        assert cache == {}

    def test_media_agent_fills_only_articles_without_image(self):
        good = _article("https://n.com/good", build_media([candidate("https://c.com/og.jpg", "og:image")]))
        bare = _article("https://n.com/bare")
        bare.title = "Nvidia boosts buyback as AI chips demand soars"
        bare.body = "The chips designer said demand for artificial intelligence hardware keeps rising. " * 3
        bare.entities = good.entities = [{"name": "Nvidia", "type": "Organization", "salience": 1.0}]
        with patch("utils.image_fallback.requests.get", side_effect=_wiki_answer([NVIDIA])) as g:
            out = MediaAgent().fill_missing([good, bare])
        assert out[0].media.primary_image.url == "https://c.com/og.jpg"
        assert out[1].media.primary_image.source == "wikipedia" and out[1].media.primary_image.credit
        assert g.call_count == 2    # one batched page lookup + one batched credit lookup
