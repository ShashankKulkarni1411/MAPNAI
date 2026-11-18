"""
MAPNAI — tests/fakes.py
Shared in-memory fakes and fixture data for the personalization, recap, insights and auth tests.
"""

import math
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import mongomock
import numpy as np

from config.personalization import PersonalizationSettings
from personalization.keys import entity_key

CFG = PersonalizationSettings(_env_file=None)
NOW = datetime(2026, 9, 29, 12, 0, tzinfo=timezone.utc)
IST = ZoneInfo("Asia/Kolkata")

# ── Clock and LLM ───────────────────────────────────────

class Clock:
    def __init__(self, now):
        self.now = now

    def __call__(self):
        return self.now

class FakeLLM:
    """An OpenAI-SDK-shaped client: client.chat.completions.create(...) → choices[0].message.content."""

    def __init__(self, reply):
        self.reply, self.calls = reply, []
        self.chat = SimpleNamespace(completions=self)

    def create(self, **kwargs):
        self.calls.append(kwargs)
        content = self.reply(kwargs["messages"]) if callable(self.reply) else self.reply
        if isinstance(content, Exception):
            raise content
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])

# ── Stores ──────────────────────────────────────────────

class FakeMongo:
    def __init__(self):
        self.db = mongomock.MongoClient().db

def unit(dim, base_cos, k):
    """A unit vector with cosine base_cos to e0 and its remainder on axis k (so two such vectors on different
    axes have cosine base_cos_1 · base_cos_2)."""
    v = np.zeros(dim, dtype=np.float32)
    v[0] = base_cos
    v[k] = math.sqrt(max(0.0, 1 - base_cos ** 2))
    return v

class FakeVectors:
    """The PersVectorStore contract over a dict of preset vectors."""

    def __init__(self, preset):
        self.preset, self.rows = preset, {}

    def indexed_article_ids(self):
        return set(self.rows)

    def sync_from_mongo(self, docs):
        added = [d["article_id"] for d in docs if d["article_id"] in self.preset and d["article_id"] not in self.rows]
        for a in added:
            self.rows[a] = self.preset[a]
        return len(added)

    def vectors_for(self, ids):
        return {a: self.rows[a] for a in ids if a in self.rows}

    def search_vector(self, vec, k):
        hits = sorted(((a, float(np.dot(vec, v))) for a, v in self.rows.items()), key=lambda h: -h[1])
        return hits[:k]

    @property
    def total_vectors(self):
        return len(self.rows)

class FakeExposures:
    def __init__(self, seeds, graph):
        self.seeds, self.graph = seeds, graph

    def sync_name_lower(self):
        return 0

    def get_seeds(self, user_id):
        return self.seeds

    def get_exposures(self, user_id):
        return [{"key": s["key"], "role": s["role"], "weight": s["weight"]} for s in self.seeds]

    def neighbours(self, keys, top):
        return {k: self.graph[k][:top] for k in keys if k in self.graph}

class NamedExposures(FakeExposures):
    def get_exposures(self, user_id):
        return [{**e, "name": e["key"].title()} for e in super().get_exposures(user_id)]

    def display_names(self, keys):
        return {k: k.upper() for k in keys}

class FakeExposureStore:
    """(name, type, frequency) nodes; edges keyed by (user, name, type) — mirrors ExposureStore's contract."""

    def __init__(self, cfg):
        self.cfg = cfg
        self.nodes = [
            ("Manchester City", "Location", 16), ("Manchester city", "Location", 1),
            ("Man City", "Location", 13), ("England", "Location", 31), ("U.S", "Location", 21),
            ("WHO", "Organization", 16),
        ]
        self.edges = {}
        self.users = {}

    def _variants(self, key):
        return [n for n in self.nodes if entity_key(n[0]) == key]

    def upsert_user(self, user_id, name):
        self.users[user_id] = name

    def delete_user(self, user_id):
        self.users.pop(user_id, None)
        self.edges = {k: v for k, v in self.edges.items() if k[0] != user_id}

    def resolve_key(self, key):
        return [{"name": n, "type": t, "frequency": f} for n, t, f in self._variants(key)]

    def search_entities(self, q, alias_keys, limit):
        keys = {entity_key(n) for n, _, _ in self.nodes if q in entity_key(n) or entity_key(n) in alias_keys}
        return [{"key": k, "name": self.resolve_key(k)[0]["name"], "types": [], "mention_count": 0}
                for k in sorted(keys)][:limit]

    def set_exposure(self, user_id, key, role, weight, provenance, proposal_id=None):
        label = {v: k for k, v in self.cfg.weight_levels.items()}[weight]
        for n, t, _ in self._variants(key):
            self.edges[(user_id, n, t)] = {"key": key, "role": role, "weight": weight, "weight_label": label,
                                           "provenance": provenance}
        v = self.resolve_key(key)
        return {"key": key, "name": v[0]["name"], "role": role, "weight": weight, "weight_label": label,
                "provenance": provenance, "nodes": len(v)} if v else {}

    def remove_exposure(self, user_id, key):
        gone = [k for k, e in self.edges.items() if k[0] == user_id and e["key"] == key]
        for k in gone:
            del self.edges[k]
        return len(gone)

    def get_exposures(self, user_id):
        out = {}
        for (u, _, _), e in self.edges.items():
            if u == user_id:
                out[e["key"]] = {**e, "name": self.resolve_key(e["key"])[0]["name"]}
        return sorted(out.values(), key=lambda e: (-e["weight"], e["key"]))

    def get_seeds(self, user_id):
        return [{"key": e["key"], "role": e["role"], "weight": e["weight"]} for e in self.get_exposures(user_id)]

    def neighbours(self, keys, top):
        return {}

    def is_available(self):
        return {"ok": True}

# ── Digest fixture data (the dsvc fixture in conftest.py) 

PI = {
    "acme": {"entity": "acme", "score": 1.0, "path": {"seed": "acme", "role": "owns", "via": [], "relations": []}},
    "zeta": {"entity": "zeta", "score": 0.1,
             "path": {"seed": "acme", "role": "owns", "via": [], "relations": ["MENTIONED_WITH"]}},
    "beta co": {"entity": "beta co", "score": 0.005,
                "path": {"seed": "acme", "role": "owns", "via": ["zeta"],
                         "relations": ["MENTIONED_WITH", "MENTIONED_WITH"]}},
}

def adoc(article_id, topic, m, keys, cluster=None, hours_ago=2, source="BBC"):
    return {"article_id": article_id, "title": f"title {article_id}", "domain": topic, "source_name": source,
            "url": f"u/{article_id}", "published_at": (NOW - timedelta(hours=hours_ago)).isoformat(),
            "materiality": {"m": m, "risk_norm": None, "size_score": 0.29, "first_report": 0, "source_cred": 0.5,
                            "unscored": True},
            "cluster_id": cluster or f"c-{article_id}", "entity_keys": list(keys),
            "entities": [{"name": k.title(), "type": "Organization", "salience": 1.0} for k in keys]}

ARTICLES = [
    # 7 above τ (need = m × 1.0): 5 must_know + 2 more_you_need
    adoc("mk-s1", "sports", 0.90, ["acme", "zeta"]), adoc("mk-s2", "sports", 0.85, ["acme"]),
    adoc("mk-f1", "finance", 0.80, ["acme"]), adoc("mk-s3", "sports", 0.75, ["acme"]),
    adoc("mk-f2", "finance", 0.70, ["acme"]), adoc("ov-s4", "sports", 0.65, ["acme"]),
    adoc("ov-f3", "finance", 0.60, ["acme"]),
    adoc("mk-s1-b", "sports", 0.50, ["acme"], cluster="c-mk-s1", source="Reuters"),   # same story, other source
    adoc("hop", "sports", 0.50, ["zeta"]),                                           # need .05 < τ
    adoc("sp1", "sports", 0.30, ["team"]), adoc("sp2", "sports", 0.30, ["team"]),
    adoc("h1", "health", 0.30, ["who"]), adoc("o1", "other", 0.30, ["x"]), adoc("t1", "technology", 0.30, ["y"]),
    adoc("g1", "geopolitics", 0.30, ["z"]), adoc("e1", "entertainment_movies", 0.30, ["w"]),
    adoc("sc1", "supply_chain", 0.40, ["v"]), adoc("sc2", "supply_chain", 0.20, ["v"]),
]

# ── Recap docs ──────────────────────────────────────────

def ist(d, h=12, mi=0):
    """A local Asia/Kolkata time on 2026-10-<d> → UTC."""
    return datetime(2026, 10, d, h, mi, tzinfo=IST).astimezone(timezone.utc)

def recap_doc(article_id, topic="sports", m=0.5, t=None, cluster=None, title=None, keys=(), size=1, source="published",
        summary="A summary.", body="", ingested=None):
    """A processed_articles doc as stored (published_ts / ingested_ts BSON dates)."""
    t = t or ist(21, 12)
    ingested = ingested or t + timedelta(minutes=30)
    published = None if source == "ingested" else t
    return {
        "article_id": article_id, "title": title or f"title {article_id}", "domain": topic, "source_name": "BBC",
        "url": f"https://x/{article_id}", "published_at": published.isoformat() if published else None,
        "published_ts": published or ingested, "ingested_ts": ingested, "ingested_at": ingested.isoformat(),
        "date_source": source, "cluster_id": cluster, "cluster_size": size,
        "entities": [{"name": k.title(), "salience": 0.9} for k in keys], "entity_keys": list(keys),
        "materiality": None if m is None else {"m": m, "unscored": True}, "summary_short": summary,
        "summary_long": None, "body": body, "media": {"primary_image": {"url": f"https://img/{article_id}.jpg"},
                                                      "additional_images": []},
    }
