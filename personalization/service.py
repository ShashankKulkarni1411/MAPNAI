"""
MAPNAI — personalization/service.py
Orchestrates the personalization engine: reads/writes Mongo (personas, aliases, feedback, articles)
and Neo4j (exposures), and calls the pure modules (keys, interest, explain, scoring).
This is the only module that talks to more than one store.

Phase 1 (PERSONALIZATION_PLAN.md §6): profile, entity search, aliases, onboarding, PATCH endpoints, health.
"""

import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Callable, Dict, List, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from config.personalization import pers_settings
from personalization import explain, interest, scoring
from personalization.keys import beta_key, entity_key
from storage.exposure_store import ExposureStore
from storage.mongo_store import MongoStore
from storage.pers_article_store import PersArticleStore
from storage.pers_log_store import PersLogStore
from storage.persona_store import PersonaStore
from utils.logger import logger

_HHMM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


class PersonalizationError(Exception):
    status_code = 500


class UserNotFound(PersonalizationError):
    status_code = 404


class EntityNotFound(PersonalizationError):
    status_code = 404


class ArticleNotFound(PersonalizationError):
    status_code = 404


class InvalidInput(PersonalizationError):
    status_code = 422


class StoreUnavailable(PersonalizationError):
    status_code = 503


class PersonalizationService:
    def __init__(
        self,
        mongo: MongoStore = None,
        exposures: ExposureStore = None,
        faiss=None,
        cfg=None,
        clock: Callable[[], datetime] = None,
    ):
        self.cfg = cfg or pers_settings
        self.mongo = mongo or MongoStore()
        self.personas = PersonaStore(self.mongo, self.cfg)
        self.logs = PersLogStore(self.mongo, self.cfg)
        self.articles = PersArticleStore(self.mongo, self.cfg)
        self.exposures = exposures or ExposureStore(cfg=self.cfg)
        self._faiss = faiss
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    # ── Validation helpers ───────────────────────────────────

    def _require_persona(self, user_id: str) -> Dict:
        persona = self.personas.get(user_id)
        if persona is None:
            raise UserNotFound(f"user {user_id} not found")
        return persona

    def _weight(self, weight) -> int:
        """"low"/"medium"/"high" or 1..3 → int."""
        levels = self.cfg.weight_levels
        if isinstance(weight, str) and weight in levels:
            return levels[weight]
        if isinstance(weight, int) and not isinstance(weight, bool) and weight in levels.values():
            return weight
        raise InvalidInput(f"weight must be one of {list(levels)} or {sorted(levels.values())}")

    def _exposure_in(self, exp: Dict) -> Dict:
        key = entity_key(exp.get("key", ""))
        if not key:
            raise InvalidInput("exposure key is empty")
        if exp.get("role") not in self.cfg.roles:
            raise InvalidInput(f"role must be one of {self.cfg.roles}")
        return {"key": key, "role": exp["role"], "weight": self._weight(exp.get("weight"))}

    def _resolve(self, key: str) -> List[Dict]:
        nodes = self.exposures.resolve_key(key)
        if not nodes:
            raise EntityNotFound(f"entity key {key!r} not found; use /v1/entities/search")
        return nodes

    def _topics_in(self, topics: Dict, allow_null: bool) -> Dict[str, Optional[float]]:
        out: Dict[str, Optional[float]] = {}
        for raw, value in (topics or {}).items():
            topic = str(raw).strip().lower()
            if topic not in self.cfg.topics_universe:
                raise InvalidInput(f"topic {raw!r} must be one of {self.cfg.topics_universe}")
            if value is None:
                if not allow_null:
                    raise InvalidInput(f"topic {raw!r} needs a weight in [0, 1]")
                out[topic] = None
                continue
            value = float(value)
            if not 0.0 <= value <= 1.0:
                raise InvalidInput(f"topic {raw!r} weight must be in [0, 1]")
            out[topic] = value
        return out

    def _style_in(self, style: Dict) -> Dict[str, str]:
        out = {}
        for field, value in (style or {}).items():
            if value is None:
                continue
            options = self.cfg.style_options.get(field)
            if options is None:
                raise InvalidInput(f"style field {field!r} must be one of {list(self.cfg.style_options)}")
            if value not in options:
                raise InvalidInput(f"style.{field} must be one of {options}")
            out[field] = value
        return out

    def _alert_prefs_in(self, prefs: Dict) -> Dict:
        out = {}
        for field, value in (prefs or {}).items():
            if value is None:
                continue
            if field == "max_per_day":
                if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 50:
                    raise InvalidInput("alert_prefs.max_per_day must be an integer in [0, 50]")
            elif field in ("quiet_start", "quiet_end"):
                if not isinstance(value, str) or not _HHMM.match(value):
                    raise InvalidInput(f"alert_prefs.{field} must be HH:MM")
            elif field == "tz":
                try:
                    ZoneInfo(str(value))
                except (ZoneInfoNotFoundError, ValueError):
                    raise InvalidInput(f"alert_prefs.tz {value!r} is not a known time zone")
            else:
                raise InvalidInput(f"alert_prefs field {field!r} must be one of {list(self.cfg.alert_prefs_default)}")
            out[field] = value
        return out

    def _topic_priors(self, topics: Dict[str, Optional[float]]) -> Dict[str, List[float]]:
        return {beta_key("topic", t): interest.prior(w, self.cfg) for t, w in topics.items() if w is not None}

    def _entity_priors(self, exposures: List[Dict]) -> Dict[str, List[float]]:
        top = max(self.cfg.weight_levels.values())
        return {beta_key("entity", e["key"]): interest.prior(e["weight"] / top, self.cfg) for e in exposures}

    # ── A. Entity search ─────────────────────────────────────

    def search_entities(self, q: str) -> List[Dict]:
        key = entity_key(q)
        if not key:
            raise InvalidInput("q is empty")
        alias_keys = self.logs.alias_lookup(key)
        return self.exposures.search_entities(key, alias_keys, self.cfg.search_limit)

    # ── A. Users ─────────────────────────────────────────────

    def create_user(
        self,
        name: str,
        topics: Dict[str, float],
        style: Optional[Dict[str, str]],
        exposures: List[Dict],
    ) -> Dict:
        name = (name or "").strip()
        if not name:
            raise InvalidInput("name is empty")
        topics = self._topics_in(topics, allow_null=False)
        style = {**self.cfg.style_defaults, **self._style_in(style or {})}
        # one exposure per key (last wins); every key must already exist in the graph
        exps = list({e["key"]: e for e in (self._exposure_in(x) for x in exposures)}.values())
        for exp in exps:
            self._resolve(exp["key"])

        user_id = str(uuid.uuid4())
        beta = {**self._topic_priors(topics), **self._entity_priors(exps)}
        self.personas.create(user_id, name, topics, style, beta)
        try:
            self.exposures.upsert_user(user_id, name)
            linked = [
                self.exposures.set_exposure(user_id, e["key"], e["role"], e["weight"], "declared") for e in exps
            ]
        except Exception as e:
            # Keep Mongo and Neo4j consistent: undo both halves of a failed create.
            logger.error(f"[Personalization] create_user failed, rolling back {user_id}: {e}")
            self.personas.delete(user_id)
            try:
                self.exposures.delete_user(user_id)
            except Exception:
                pass
            raise StoreUnavailable(f"Neo4j write failed: {type(e).__name__}") from e

        logger.info(f"[Personalization] Created user {user_id} with {len(linked)} exposures")
        return {
            "user_id": user_id,
            "name": name,
            "topics": topics,
            "style": style,
            "exposures": linked,
            "beta": beta,
            "persona_version": 1,
        }

    # ── A. Onboarding ────────────────────────────────────────

    def _top_entity_keys(self, article: Dict) -> List[str]:
        """The article's entity keys by salience (desc), deduplicated."""
        c = self.cfg
        ents = sorted(
            article.get(c.entities_field) or [],
            key=lambda e: -(e.get(c.entity_salience_key) or 0.0),
        )
        keys: List[str] = []
        for ent in ents:
            key = entity_key(ent.get(c.entity_name_key, ""))
            if key and key not in keys:
                keys.append(key)
        return keys

    def onboarding_headlines(self) -> List[Dict]:
        """
        Temporary Phase 1 rule: round-robin over topics (minus topic_exclude), newest first, distinct titles.
        Phase 2 switches to topic → max materiality → distinct cluster.
        """
        c = self.cfg
        topics = [t for t in self.articles.topics() if t not in c.topic_exclude]
        per_topic = []
        for topic in topics:
            docs = self.articles.recent_by_topic(topic, limit=c.onboarding_headlines * 3)
            epoch = datetime.min.replace(tzinfo=timezone.utc)
            docs.sort(key=lambda d: scoring.parse_ts(d.get(c.published_field)) or epoch, reverse=True)
            per_topic.append(docs)

        out, titles = [], set()
        while len(out) < c.onboarding_headlines and any(per_topic):
            for docs in per_topic:
                while docs:
                    doc = docs.pop(0)
                    title = (doc.get(c.title_field) or "").strip()
                    if title and title.lower() not in titles:
                        titles.add(title.lower())
                        out.append({
                            "article_id": doc[c.id_field],
                            "title": title,
                            "topic": doc.get(c.topic_field),
                            "source": doc.get(c.source_field),
                            "url": doc.get(c.url_field),
                            "published_at": doc.get(c.published_field),
                            "cluster_id": doc.get("cluster_id"),
                            "m": (doc.get("materiality") or {}).get("m"),
                        })
                        break
                if len(out) >= c.onboarding_headlines:
                    break
        return out

    def onboarding(self, user_id: str, likes: List[str], dislikes: List[str]) -> Dict:
        """
        Likes: Beta "more" on the article's topic and top entities, plus a long-window history item.
        Dislikes: Beta "less". Both are logged in `feedback` with section="onboarding".
        """
        c = self.cfg
        persona = self._require_persona(user_id)
        likes, dislikes = list(dict.fromkeys(likes or [])), list(dict.fromkeys(dislikes or []))
        if not likes and not dislikes:
            raise InvalidInput("likes and dislikes are both empty")
        if set(likes) & set(dislikes):
            raise InvalidInput("an article can't be both liked and disliked")
        if len(likes) + len(dislikes) > c.onboarding_max_items:
            raise InvalidInput(f"at most {c.onboarding_max_items} onboarding items")

        docs = {d[c.id_field]: d for d in self.articles.by_ids(likes + dislikes)}
        unknown = [a for a in likes + dislikes if a not in docs]
        if unknown:
            raise ArticleNotFound(f"articles not found: {unknown}")

        now = self.clock()
        parts, history, feedback = [], [], []
        for article_id, fb_type in [(a, "more") for a in likes] + [(a, "less") for a in dislikes]:
            doc = docs[article_id]
            topic = doc.get(c.topic_field)
            ents = self._top_entity_keys(doc)[: c.beta_top_entities]
            parts.append(interest.beta_updates(fb_type, None, topic, ents, c))
            feedback.append({
                "user_id": user_id, "article_id": article_id, "type": fb_type, "section": "onboarding",
                "topic": topic, "entity_keys": ents, "t": now,
            })
            if fb_type == "more":
                history.append({
                    "article_id": article_id, "title": doc.get(c.title_field), "t": now,
                    "w": c.history_w["onboarding"], "win": "long", "src": "onboarding",
                })
        deltas = interest.merge_deltas(parts)

        # keys without a Beta start from their prior: declared topic weight, exposure weight, else [1, 1]
        top = max(c.weight_levels.values())
        base = {
            **self._topic_priors(persona.get("topics") or {}),
            **{beta_key("entity", e["key"]): interest.prior(e["weight"] / top, c)
               for e in self.exposures.get_exposures(user_id)},
        }
        self.personas.inc_beta(user_id, deltas, base)
        self.personas.push_history(user_id, history)
        self.logs.log_feedback(feedback)
        version = self.personas.patch(user_id, {"onboarded_at": now})

        beta = self.personas.get(user_id)["beta"]
        return {
            "user_id": user_id,
            "likes": len(likes),
            "dislikes": len(dislikes),
            "history_added": len(history),
            "beta_deltas": deltas,
            "beta": {k: beta[k] for k in deltas},
            "persona_version": version,
        }

    # ── A. Profile ───────────────────────────────────────────

    def get_profile(self, user_id: str) -> Dict:
        persona = self._require_persona(user_id)
        exposures = self.exposures.get_exposures(user_id)
        topics = persona.get("topics") or {}
        style = persona.get("style") or {}
        history = persona.get("history") or []
        return {
            "user_id": user_id,
            "name": persona["name"],
            "sentences": explain.profile_sentences(exposures, topics, style, self.cfg),
            "exposures": exposures,
            "topics": topics,
            "topic_shares": scoring.topic_shares(topics),
            "style": style,
            "alert_prefs": persona.get("alert_prefs"),
            "beta": persona.get("beta") or {},
            "pi_topk": (persona.get("pi_topk") or [])[:20],
            "recent_reads": [{**h, "t": scoring.parse_ts(h.get("t"))} for h in reversed(history[-10:])],
            "persona_version": persona.get("persona_version"),
            # pymongo returns naive datetimes; stored values are UTC
            "created_at": scoring.parse_ts(persona.get("created_at")),
            "updated_at": scoring.parse_ts(persona.get("updated_at")),
        }

    # ── A. PATCH endpoints ───────────────────────────────────

    def patch_exposures(self, user_id: str, upserts: List[Dict], removes: List[str]) -> Dict:
        persona = self._require_persona(user_id)
        exps = list({e["key"]: e for e in (self._exposure_in(x) for x in upserts or [])}.values())
        remove_keys = list(dict.fromkeys(entity_key(k) for k in removes or [] if entity_key(k)))
        if not exps and not remove_keys:
            raise InvalidInput("nothing to update: upsert and remove are both empty")
        both = {e["key"] for e in exps} & set(remove_keys)
        if both:
            raise InvalidInput(f"keys both upserted and removed: {sorted(both)}")
        for exp in exps:  # removes need no lookup: unlinking a stale or unknown key is harmless
            self._resolve(exp["key"])

        self.exposures.upsert_user(user_id, persona["name"])
        removed = {key: self.exposures.remove_exposure(user_id, key) for key in remove_keys}
        upserted = [self.exposures.set_exposure(user_id, e["key"], e["role"], e["weight"], "declared") for e in exps]
        self.personas.init_beta(user_id, self._entity_priors(exps))
        version = self.personas.patch(user_id, {})
        return {
            "user_id": user_id,
            "upserted": upserted,
            "removed": removed,
            "exposures": self.exposures.get_exposures(user_id),
            "persona_version": version,
        }

    def patch_topics(self, user_id: str, topics: Dict[str, Optional[float]]) -> Dict:
        """Merge: a weight sets the topic, null removes it. New topics get a Beta prior if they have none."""
        self._require_persona(user_id)
        topics = self._topics_in(topics, allow_null=True)
        if not topics:
            raise InvalidInput("nothing to update: topics is empty")
        set_fields = {f"topics.{t}": w for t, w in topics.items() if w is not None}
        unset_fields = [f"topics.{t}" for t, w in topics.items() if w is None]
        self.personas.init_beta(user_id, self._topic_priors(topics))
        version = self.personas.patch(user_id, set_fields, unset_fields)
        persona = self.personas.get(user_id)
        return {"user_id": user_id, "topics": persona.get("topics") or {}, "persona_version": version}

    def patch_style(self, user_id: str, style: Dict[str, Optional[str]]) -> Dict:
        self._require_persona(user_id)
        style = self._style_in(style)
        if not style:
            raise InvalidInput("nothing to update: style is empty")
        version = self.personas.patch(user_id, {f"style.{k}": v for k, v in style.items()})
        return {"user_id": user_id, "style": self.personas.get(user_id)["style"], "persona_version": version}

    def patch_alert_prefs(self, user_id: str, prefs: Dict) -> Dict:
        self._require_persona(user_id)
        prefs = self._alert_prefs_in(prefs)
        if not prefs:
            raise InvalidInput("nothing to update: alert_prefs is empty")
        version = self.personas.patch(user_id, {f"alert_prefs.{k}": v for k, v in prefs.items()})
        return {"user_id": user_id, "alert_prefs": self.personas.get(user_id)["alert_prefs"],
                "persona_version": version}

    # ── Health ───────────────────────────────────────────────

    def _faiss_store(self):
        if self._faiss is None:
            from storage.faiss_store import FAISSStore
            self._faiss = FAISSStore()
        return self._faiss

    def health(self, hours: Optional[int] = None) -> Dict:
        hours = hours or self.cfg.cand_window_h
        now = self.clock()
        cutoff = now - timedelta(hours=hours)
        out: Dict = {"hours": hours, "policy_version": self.cfg.policy_version}

        recent_ids: List[str] = []
        try:
            self.mongo.db.command("ping")
            docs = self.mongo.get_articles_published_since(
                cutoff, limit=100_000,
                projection={"_id": 0, self.cfg.id_field: 1, self.cfg.published_field: 1},
            )
            recent_ids = [
                d[self.cfg.id_field] for d in docs
                if (ts := scoring.parse_ts(d.get(self.cfg.published_field))) and ts >= cutoff
            ]
            out["mongo"] = {"ok": True, "personas": self.personas.count(), "entity_aliases": self.logs.alias_count()}
        except Exception as e:
            logger.error(f"[Personalization] Mongo health failed: {e}")
            out["mongo"] = {"ok": False, "error": type(e).__name__}
        out["recent_articles"] = len(recent_ids)

        out["neo4j"] = self.exposures.is_available()

        try:
            store = self._faiss_store()
            indexed = store.indexed_article_ids()
            recent_indexed = sum(1 for a in recent_ids if a in indexed)
            out["faiss"] = {
                "ok": store.total_vectors > 0,
                "ntotal": store.total_vectors,
                "recent_indexed": recent_indexed,
                # loaded, but none of the recent articles have vectors → interest can't use them
                "stale": bool(recent_ids) and recent_indexed == 0,
            }
        except Exception as e:
            logger.error(f"[Personalization] FAISS health failed: {e}")
            out["faiss"] = {"ok": False, "error": type(e).__name__}

        out["ok"] = all(out[k].get("ok") for k in ("mongo", "neo4j", "faiss"))
        return out
