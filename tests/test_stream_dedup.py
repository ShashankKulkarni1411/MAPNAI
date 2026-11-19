"""
MAPNAI — tests/test_stream_dedup.py
The banded SimHash index (exact for Hamming distance ≤ threshold), duplicate lookup with the matched article and its
source, sightings (a duplicate from another outlet is recorded on the original), and their storage.
"""

import random
from datetime import datetime, timedelta, timezone

import mongomock
import pytest

from agents.preprocessing_agent import PreprocessingAgent
from storage.mongo_store import MongoStore
from utils.deduplicator import ArticleDeduplicator, SimHashIndex, simhash_distance
from utils.models import Domain, RawArticle, SourceType

BODY = ("The Federal Reserve raised interest rates by 25 basis points on Wednesday, citing persistent inflation. "
        "The move was widely expected by markets and analysts, who now look to the next meeting.")


def flip(value: str, bits) -> str:
    v = int(value, 16)
    for b in bits:
        v ^= 1 << b
    return f"{v:016x}"


class TestSimHashIndex:
    def test_exact_within_the_threshold_against_a_linear_scan(self):
        rng = random.Random(7)
        index = SimHashIndex(3)
        stored = [f"{rng.getrandbits(64):016x}" for _ in range(400)]
        for h in stored:
            index.add(h)
        queries = [flip(rng.choice(stored), rng.sample(range(64), rng.randint(0, 5))) for _ in range(300)]
        for q in queries:
            linear = min(((simhash_distance(q, h), h) for h in stored), key=lambda x: (x[0], int(x[1], 16)))
            found = index.find(q)
            if linear[0] <= 3:
                assert found is not None and simhash_distance(q, found) == linear[0]
            else:
                assert found is None

    def test_bad_values_are_ignored(self):
        index = SimHashIndex(3)
        assert index.add("not-hex") is False and index.find("zz") is None and len(index) == 0
        assert index.add("00000000000000ff") is True and index.add("00000000000000ff") is False
        assert index.find(flip("00000000000000ff", [40, 41, 42])) == "00000000000000ff"
        assert index.find(flip("00000000000000ff", [40, 41, 42, 43])) is None


class TestFindDuplicate:
    def test_returns_the_original_and_its_source(self):
        d = ArticleDeduplicator(simhash_threshold=3)
        h = d.compute_hash("Fed raises rates", BODY)
        d.load_existing_hashes([{"dedup_hash": h, "article_id": "a1", "source_name": "Reuters"}, "", None])
        hit = d.find_duplicate("b1", "Fed raises rates", BODY)
        assert hit == {"article_id": "a1", "source": "Reuters", "method": "simhash"}
        assert d.source_of("a1") == "Reuters" and len(d) == 1
        assert d.is_duplicate("b2", "Fed raises rates", BODY)

    def test_plain_hash_strings_have_no_owner(self):
        d = ArticleDeduplicator()
        d.load_existing_hashes([d.compute_hash("Fed raises rates", BODY)])
        assert d.find_duplicate("b1", "Fed raises rates", BODY) == {"article_id": None, "source": None,
                                                                    "method": "simhash"}


def raw(source, title="Fed raises rates by 25bps", published=None):
    return RawArticle(title=title, body=BODY, url=f"https://{source.lower()}.example/fed", source_name=source,
                      source_type=SourceType.RSS, domain=Domain("finance"), published_at=published, language="en")


class TestSightings:
    def test_a_duplicate_from_another_outlet_is_a_sighting(self):
        agent = PreprocessingAgent()
        first, status = agent.process(raw("Reuters"))
        assert status == "ok"
        published = datetime.now(timezone.utc) - timedelta(minutes=20)
        second, status = agent.process(raw("BBC", published=published))
        assert second is None and "dup" in status
        again, _ = agent.process(raw("BBC"))                       # the same outlet again: still one sighting
        same, _ = agent.process(raw("Reuters"))                     # the original's own outlet: not a sighting
        assert again is None and same is None
        sightings = agent.pop_sightings()
        assert list(sightings) == [first.article_id]
        [row] = sightings[first.article_id]
        assert row["source"] == "BBC" and abs((row["at"] - published).total_seconds()) < 1
        assert agent.pop_sightings() == {}

    def test_a_future_publish_time_is_clamped_to_now(self):
        agent = PreprocessingAgent()
        first, _ = agent.process(raw("Reuters"))
        agent.process(raw("BBC", published=datetime.now(timezone.utc) + timedelta(hours=3)))
        [row] = agent.pop_sightings()[first.article_id]
        assert row["at"] <= datetime.now(timezone.utc)


@pytest.fixture
def store():
    s = MongoStore(uri="mongodb://unused", db_name="test")
    s._client = mongomock.MongoClient()
    s._db = s._client["test"]
    return s


class TestStoredSightings:
    def test_each_outlet_is_recorded_once(self, store):
        store.db.processed_articles.insert_one({"article_id": "a1", "source_name": "Reuters"})
        t = datetime(2026, 9, 29, 10, 0, tzinfo=timezone.utc)
        assert store.record_sightings({"a1": [{"source": "BBC", "at": t}, {"source": "Hindu", "at": t}]}) == 2
        assert store.record_sightings({"a1": [{"source": "BBC", "at": t}], "missing": [{"source": "X"}]}) == 0
        doc = store.db.processed_articles.find_one({"article_id": "a1"})
        assert [s["source"] for s in doc["sightings"]] == ["BBC", "Hindu"] and doc.get("last_sighting_at")

    def test_recent_hash_docs(self, store):
        now = datetime.now(timezone.utc)
        store.db.processed_articles.insert_many([
            {"article_id": "new", "source_name": "A", "dedup_hash": "00ff", "ingested_ts": now - timedelta(days=1)},
            {"article_id": "old", "source_name": "B", "dedup_hash": "11ff", "ingested_ts": now - timedelta(days=9)},
            {"article_id": "legacy", "source_name": "C", "dedup_hash": "22ff",
             "ingested_at": (now - timedelta(days=2)).isoformat()},
            {"article_id": "nohash", "source_name": "D", "dedup_hash": "", "ingested_ts": now},
        ])
        ids = sorted(d["article_id"] for d in store.get_recent_hash_docs(7))
        assert ids == ["legacy", "new"]

    def test_cluster_risk_takes_a_model_score_not_a_shared_one(self, store):
        store.db.processed_articles.insert_many([
            {"article_id": "a1", "cluster_id": "c", "risk_processed": True, "risk_score": 70,
             "risk_processed_at": "2026-09-29T10:00:00+00:00", "risk_level": "high"},
            {"article_id": "a2", "cluster_id": "c", "risk_processed": True, "risk_score": 40,
             "risk_processed_at": "2026-09-29T11:00:00+00:00", "risk_shared_from": "a1"},
            {"article_id": "a3", "cluster_id": "c"},
        ])
        hit = store.find_cluster_risk("c", "a3")
        assert hit["article_id"] == "a1" and hit["risk_score"] == 70
        assert store.find_cluster_risk("c", "a1") is None and store.find_cluster_risk(None, "a3") is None
