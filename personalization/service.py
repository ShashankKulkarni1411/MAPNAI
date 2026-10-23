"""
MAPNAI — personalization/service.py
Orchestrates the personalization engine: reads/writes Mongo (personas, aliases, feedback, articles)
and Neo4j (exposures), and calls the pure modules (keys, interest, explain, scoring).
This is the only module that talks to more than one store.

Phase 1 (PERSONALIZATION_PLAN.md §6): profile, entity search, aliases, onboarding, PATCH endpoints, health.
Phase 2: event clustering + materiality (cluster_articles), exposure spread (compute_pi), headline rule.
Phase 3: interest + candidates (R1–R4, RRF, collapse), feedback → Beta + history.
Phase 4: digest = need + slate (must_know / more_you_need / MMR / calibration / explore), why lines,
         per-day cache keyed on persona_version, impressions on every serve.
Phase 5: feedback (section from the last impression), adaptive τ (update_tau), exposure proposals
         (run_proposals, list / accept / reject).
Phase 6: alerts (run_alerts: inverted pi index, thresholds, one per cluster, per-day cap, quiet hours; alerts).
Phase 7: render (style rewrite through the shared Groq client, cached per style, fact-checked, + persona brief).
Phase 8: metrics (admin), delete_user (demo seeding / smoke cleanup); the jobs run on APScheduler (jobs.py).
Recaps (recap.py): the daily (yesterday) and weekly (Monday-Sunday 22:00) recaps, the same for every reader of a time
         zone, frozen per version in `recaps`, with per-reader marks added on serve.
Insights (insights.py): developing stories with an LLM analysis (what happened, why it matters, scenarios, what to
         watch), cached per story in `insights_cache` until the story gains articles; "why it matters to you", the
         reader's watches and their follows' week are added on serve.
App views (mobile/): feed, Big today, story page, cluster sources, saved, story search, Ask (Agent 5), comments; the
         digest, alerts and proposals also carry the fields the app shows (additive), including each article's
         ingested images (`media`) and its engagement counts.
"""

import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Callable, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import numpy as np

from config.personalization import pers_settings
from personalization import candidates, clustering, explain, interest, materiality, scoring, slate, spread
from personalization import alerts as alert_rules
from personalization import feedback as feedback_rules
from personalization import insights as insight_rules
from personalization import metrics as pers_metrics
from personalization import recap as recap_rules
from personalization import render as render_rules
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


class ProposalNotFound(PersonalizationError):
    status_code = 404


class InvalidInput(PersonalizationError):
    status_code = 422


class Conflict(PersonalizationError):
    status_code = 409


class StoreUnavailable(PersonalizationError):
    status_code = 503


class RecapNotReady(PersonalizationError):
    status_code = 404


class InsightNotFound(PersonalizationError):
    status_code = 404


def _shared_llm() -> Tuple[Optional[object], Optional[str]]:
    """The Groq client Agents 2–4 use (OpenAI-compatible); (None, None) without a key or the openai package."""
    from utils.groq_client import init_groq_llm
    return init_groq_llm("[Render]", "Rendering")


class PersonalizationService:
    def __init__(
        self,
        mongo: MongoStore = None,
        exposures: ExposureStore = None,
        vectors=None,
        cfg=None,
        clock: Callable[[], datetime] = None,
        llm_factory: Callable[[], Tuple[Optional[object], Optional[str]]] = None,
        query_agent_factory: Callable[[], object] = None,
    ):
        self.cfg = cfg or pers_settings
        self.mongo = mongo or MongoStore()
        self.personas = PersonaStore(self.mongo, self.cfg)
        self.logs = PersLogStore(self.mongo, self.cfg)
        self.articles = PersArticleStore(self.mongo, self.cfg)
        self.exposures = exposures or ExposureStore(cfg=self.cfg)
        self._vectors = vectors
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self._llm_factory = llm_factory or _shared_llm
        self._renderer: Optional[render_rules.Renderer] = None
        self._recap_llm: Optional[Tuple[Optional[object], Optional[str]]] = None
        self._query_agent_factory = query_agent_factory or self._default_query_agent
        self._query_agent = None

    def _default_query_agent(self):
        """Agent 5 over this service's Mongo (loads the embedding model and the pipeline's FAISS index)."""
        from agents.agent5_query import QueryAgent
        return QueryAgent(mongo_store=self.mongo)

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

    def _beta_base(self, user_id: str, persona: Dict) -> Dict[str, List[float]]:
        """Where a key without a Beta starts: declared topic weight, exposure weight, else [1, 1] (inc_beta)."""
        return {**self._topic_priors(persona.get("topics") or {}),
                **self._entity_priors(self.exposures.get_exposures(user_id))}

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
        self._refresh_pi(user_id)
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
        Round-robin over topics (minus topic_exclude); within a topic, highest materiality first (then newest),
        one headline per cluster and distinct titles. Articles the clustering job hasn't reached sort last.
        """
        c = self.cfg
        epoch = datetime.min.replace(tzinfo=timezone.utc)
        topics = [t for t in self.articles.topics() if t not in c.topic_exclude]
        per_topic = []
        for topic in topics:
            docs = self.articles.ranked_by_topic(topic, limit=c.onboarding_headlines * 3)
            docs.sort(key=lambda d: ((d.get("materiality") or {}).get("m", -1.0),
                                     scoring.parse_ts(d.get(c.published_field)) or epoch), reverse=True)
            per_topic.append(docs)

        out, titles, clusters = [], set(), set()
        while len(out) < c.onboarding_headlines and any(per_topic):
            for docs in per_topic:
                while docs:
                    doc = docs.pop(0)
                    title = (doc.get(c.title_field) or "").strip()
                    cluster = doc.get("cluster_id") or doc[c.id_field]
                    if title and title.lower() not in titles and cluster not in clusters:
                        titles.add(title.lower())
                        clusters.add(cluster)
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
        self.personas.inc_beta(user_id, deltas, self._beta_base(user_id, persona))
        self.personas.push_history(user_id, history)
        self.logs.log_feedback(feedback)
        version = self.personas.patch(user_id, {"onboarded_at": now})
        self._after_edit(user_id)

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
            "pending_proposals": len(self.logs.list_proposals(user_id, "pending")),
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
        self._refresh_pi(user_id)
        self._after_edit(user_id)
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
        self._after_edit(user_id)
        persona = self.personas.get(user_id)
        return {"user_id": user_id, "topics": persona.get("topics") or {}, "persona_version": version}

    def patch_style(self, user_id: str, style: Dict[str, Optional[str]]) -> Dict:
        self._require_persona(user_id)
        style = self._style_in(style)
        if not style:
            raise InvalidInput("nothing to update: style is empty")
        version = self.personas.patch(user_id, {f"style.{k}": v for k, v in style.items()})
        self._after_edit(user_id)
        return {"user_id": user_id, "style": self.personas.get(user_id)["style"], "persona_version": version}

    def patch_alert_prefs(self, user_id: str, prefs: Dict) -> Dict:
        self._require_persona(user_id)
        prefs = self._alert_prefs_in(prefs)
        if not prefs:
            raise InvalidInput("nothing to update: alert_prefs is empty")
        version = self.personas.patch(user_id, {f"alert_prefs.{k}": v for k, v in prefs.items()})
        self._after_edit(user_id)
        return {"user_id": user_id, "alert_prefs": self.personas.get(user_id)["alert_prefs"],
                "persona_version": version}

    # ── B. Exposure spread ───────────────────────────────────

    def compute_pi(self, user_id: str) -> List[Dict]:
        """
        Seeds → hop 1 → (hop 2 from the retained hop-1 keys) → pi_topk, stored on the persona. Keys are canonical
        through entity_aliases, so an alias of a seed ("man city") is the seed itself, not a co-mentioned neighbour.
        """
        c = self.cfg
        self._require_persona(user_id)
        aliases = self.logs.alias_map()
        seeds = spread.canonicalize_seeds(self.exposures.get_seeds(user_id), aliases)

        def neighbours(keys: List[str], top: int) -> Dict[str, List[Dict]]:
            if not keys:
                return {}
            return spread.canonicalize_nbrs(
                self.exposures.neighbours(spread.with_alias_sources(keys, aliases), top), aliases)

        hop1 = neighbours([s["key"] for s in seeds], c.hop1_top)
        hop2 = None
        if c.enable_hop2:
            hop2 = neighbours(spread.hop1_keys(spread.spread(seeds, hop1, None, c)), c.hop2_top)
        pi = spread.spread(seeds, hop1, hop2, c)
        self.personas.set_pi_topk(user_id, pi)
        return pi

    def _refresh_pi(self, user_id: str) -> None:
        """After an exposure edit. A Neo4j failure leaves the old pi_topk; the nightly job retries."""
        try:
            self.compute_pi(user_id)
        except Exception as e:
            logger.warning(f"[Personalization] pi_topk refresh failed for {user_id}: {type(e).__name__}: {e}")

    # ── E. Feedback → Beta + history ─────────────────────────

    def record_feedback(self, user_id: str, article_id: str, fb_type: str, value: Optional[float] = None,
                        section: Optional[str] = None) -> Dict:
        """
        more/less/open/dwell(≥ dwell_min_s) → Beta deltas on the article's topic and top entities;
        open/save/more/dwell → a history item (weight history_w[type]); needed/not_needed/missed are logged only
        (the τ job reads them). Every event is logged in `feedback`, with the section the article was last served
        in when the client doesn't send one. The cached digest is kept: feedback shows from the next digest
        (or ?refresh=true), so today's slate doesn't reshuffle on every click.
        """
        c = self.cfg
        if fb_type not in c.feedback_types:
            raise InvalidInput(f"type must be one of {c.feedback_types}")
        if fb_type == "dwell" and (value is None or float(value) < 0):
            raise InvalidInput("dwell needs value = seconds ≥ 0")
        persona = self._require_persona(user_id)
        docs = self.articles.by_ids([article_id])
        if not docs:
            raise ArticleNotFound(f"article {article_id} not found")
        doc, now = docs[0], self.clock()
        topic = doc.get(c.topic_field)
        ents = candidates.doc_entity_keys(doc, c)[: c.beta_top_entities]
        served = self.logs.last_impression(user_id, article_id)
        if section is None and served:
            section = served.get("section")

        deltas = interest.beta_updates(fb_type, value, topic, ents, c)
        if deltas:
            self.personas.inc_beta(user_id, deltas, self._beta_base(user_id, persona))
        history_added = False
        if fb_type in c.history_w and not (fb_type == "dwell" and float(value) < c.dwell_min_s):
            self.personas.push_history(user_id, [{"article_id": article_id, "title": doc.get(c.title_field),
                                                  "t": now, "w": c.history_w[fb_type], "win": "both",
                                                  "src": fb_type}])
            history_added = True
        self.logs.log_feedback([{"user_id": user_id, "article_id": article_id, "type": fb_type, "value": value,
                                 "section": section, "topic": topic, "entity_keys": ents, "t": now}])
        beta = self.personas.get(user_id)["beta"]
        out = {"user_id": user_id, "article_id": article_id, "type": fb_type, "section": section,
               "served": {k: served.get(k) for k in ("section", "slot", "digest_id")} if served else None,
               "beta_deltas": deltas, "beta": {k: beta[k] for k in deltas},
               "theta": {k: round(interest.theta(beta[k]), 6) for k in deltas}, "history_added": history_added}
        if fb_type == "needed":
            # the τ job counts `needed` only for an article served in tau_section within its window
            since = now - timedelta(days=c.tau_window_d)
            out["counts_for_tau"] = bool(self.logs.served_pairs({(user_id, article_id)}, c.tau_section, since))
        elif fb_type == "missed":
            out["counts_for_tau"] = True
        return out

    # ── I. Adaptive τ ────────────────────────────────────────

    def update_tau(self, now: Optional[datetime] = None) -> Dict:
        """
        The daily τ job body: needed / missed feedback of the last tau_window_d days (all users) → miss_rate →
        one step of τ, clipped to [tau_min, tau_max]. A row is written even when there is no evidence (τ kept).
        """
        c = self.cfg
        now = now or self.clock()
        since = now - timedelta(days=c.tau_window_d)
        rows = self.logs.feedback_window(since, ["needed", "not_needed", "missed"])
        needed = {(r["user_id"], r["article_id"]) for r in rows if r["type"] == "needed"}
        counts = feedback_rules.tau_counts(rows, self.logs.served_pairs(needed, c.tau_section, since))
        step = feedback_rules.tau_update(self.logs.current_tau(), counts["missed"], counts["needed"], c)
        row = {"t": now, **step, **counts, "window_days": c.tau_window_d}
        self.logs.push_tau(row)
        logger.info(f"[Personalization] τ {step['prev_tau']} → {step['tau']} (miss_rate {step['miss_rate']}, "
                    f"missed {counts['missed']}, needed {counts['needed']})")
        return row

    # ── I. Exposure proposals ────────────────────────────────

    def run_proposals(self, user_ids: Optional[List[str]] = None, now: Optional[datetime] = None) -> Dict:
        """
        The weekly proposals job body. Engagement rule per user; the A4-fact rule only when a4_facts_field is set.
        Nothing is written to the graph here: a proposal becomes an exposure only when the user accepts it.
        """
        c = self.cfg
        now = now or self.clock()
        stats: Dict = {"users": 0, "created": 0, "by_reason": {"engagement": 0, "a4_fact": 0},
                       "unresolved": 0, "duplicates": 0, "failed": {}}
        fact_docs = None
        if c.a4_facts_field:
            projection = {"_id": 0, c.id_field: 1, c.published_field: 1, c.a4_facts_field: 1}
            fact_docs = [{"article_id": d[c.id_field], "facts": d[c.a4_facts_field]}
                         for d in self.articles.window(c.proposal_window_d * 24, now, projection)
                         if d.get(c.a4_facts_field)]
            stats["a4_fact_rule"] = f"active ({c.a4_facts_field}: {len(fact_docs)} articles with facts)"
        else:
            stats["a4_fact_rule"] = "inactive (a4_facts_field unset)"
        logger.info(f"[Proposals] A4-fact rule {stats['a4_fact_rule']}")
        if not c.enable_proposals:
            return {**stats, "skipped": "enable_proposals is false"}

        since = now - timedelta(days=c.proposal_window_d)
        aliases = self.logs.alias_map()
        for user_id in user_ids or self.personas.all_ids():
            try:
                res = self._propose_for(user_id, since, now, aliases, fact_docs)
            except Exception as e:
                stats["failed"][user_id] = f"{type(e).__name__}: {e}"
                logger.error(f"[Proposals] failed for {user_id}: {e}")
                continue
            stats["users"] += 1
            for key in ("created", "unresolved", "duplicates"):
                stats[key] += res[key]
            for reason, n in res["by_reason"].items():
                stats["by_reason"][reason] += n
        return stats

    def _propose_for(self, user_id: str, since: datetime, now: datetime, aliases: Dict[str, str],
                     fact_docs: Optional[List[Dict]]) -> Dict:
        c = self.cfg
        persona = self._require_persona(user_id)
        exposure_keys = {aliases.get(e["key"], e["key"]) for e in self.exposures.get_exposures(user_id)}
        blocked = self.logs.proposal_keys(user_id)
        rows = self.logs.feedback_window(since, c.read_feedback_types, user_id)
        props = feedback_rules.engagement_proposals(rows, persona.get("beta") or {}, exposure_keys, blocked, c,
                                                    aliases)
        if fact_docs:
            props += feedback_rules.fact_proposals(fact_docs, exposure_keys,
                                                   blocked | {p["entity_key"] for p in props}, c, aliases)

        out = {"created": 0, "unresolved": 0, "duplicates": 0, "by_reason": {}}
        for p in props[: c.proposal_max_per_user]:
            nodes = self.exposures.resolve_key(p["entity_key"])
            if not nodes:                   # not in the graph: accepting it could never create an edge
                out["unresolved"] += 1
                continue
            name = nodes[0]["name"]         # resolve_key orders variants by frequency
            doc = {
                "proposal_id": str(uuid.uuid4()), "user_id": user_id, "kind": "exposure",
                "entity_key": p["entity_key"], "name": name,
                "suggested_role": p["suggested_role"], "suggested_weight": p["suggested_weight"],
                "suggested_weight_label": {v: k for k, v in c.weight_levels.items()}[p["suggested_weight"]],
                "origin": "proposed", "reason": p["reason"], "evidence": p["evidence"],
                "why": explain.why_proposal(p, c, {p["entity_key"]: name}),
                "signal": {k: p[k] for k in ("articles", "theta", "fact_type", "via") if k in p},
                "status": "pending", "created_at": now, "decided_at": None,
            }
            if self.logs.add_proposal(doc):
                out["created"] += 1
                out["by_reason"][p["reason"]] = out["by_reason"].get(p["reason"], 0) + 1
            else:
                out["duplicates"] += 1
        return out

    def list_proposals(self, user_id: str, status: Optional[str] = None) -> List[Dict]:
        self._require_persona(user_id)
        if status is not None and status not in ("pending", "accepted", "rejected"):
            raise InvalidInput("status must be pending, accepted or rejected")
        props = [self._proposal_out(p) for p in self.logs.list_proposals(user_id, status)]
        c = self.cfg
        titles = {d[c.id_field]: d.get(c.title_field) for d in self.articles.by_ids(
            list({a for p in props for a in p.get("evidence") or []}), {"_id": 0, c.id_field: 1, c.title_field: 1})}
        for p in props:   # for the app: the evidence articles with their titles
            p["evidence_articles"] = [{"article_id": a, "title": titles[a]} for a in p.get("evidence") or []
                                      if a in titles]
        return props

    @staticmethod
    def _proposal_out(prop: Dict) -> Dict:
        # pymongo returns naive datetimes; stored values are UTC
        return {**prop, **{k: scoring.parse_ts(prop.get(k)) for k in ("created_at", "decided_at")}}

    def _pending_proposal(self, user_id: str, proposal_id: str) -> Dict:
        prop = self.logs.get_proposal(user_id, proposal_id)
        if prop is None:
            raise ProposalNotFound(f"proposal {proposal_id} not found for user {user_id}")
        if prop["status"] != "pending":
            raise Conflict(f"proposal {proposal_id} is already {prop['status']}")
        return prop

    def accept_proposal(self, user_id: str, proposal_id: str, role: Optional[str] = None, weight=None) -> Dict:
        """
        Write the exposure (provenance "confirmed", proposal_id on the edge) with the suggested role/weight or the
        user's override, then the same follow-up as an exposure edit: Beta prior, version bump, pi_topk, digest.
        """
        c = self.cfg
        persona = self._require_persona(user_id)
        prop = self._pending_proposal(user_id, proposal_id)
        exp = self._exposure_in({"key": prop["entity_key"], "role": role or prop["suggested_role"],
                                 "weight": weight if weight is not None else prop["suggested_weight"]})
        self._resolve(exp["key"])
        if any(e["key"] == exp["key"] for e in self.exposures.get_exposures(user_id)):
            raise Conflict(f"{exp['key']!r} is already one of your exposures; reject the proposal instead")

        now = self.clock()
        decided = self.logs.decide_proposal(user_id, proposal_id, "accepted", now,
                                            {"accepted_role": exp["role"], "accepted_weight": exp["weight"]})
        if decided is None:
            raise Conflict(f"proposal {proposal_id} was decided concurrently")
        try:
            self.exposures.upsert_user(user_id, persona["name"])
            linked = self.exposures.set_exposure(user_id, exp["key"], exp["role"], exp["weight"], "confirmed",
                                                 proposal_id=proposal_id)
        except Exception as e:
            self.logs.decide_proposal(user_id, proposal_id, "pending", None,
                                      {"accepted_role": None, "accepted_weight": None}, from_status="accepted")
            raise StoreUnavailable(f"Neo4j write failed: {type(e).__name__}") from e
        if not linked:
            self.logs.decide_proposal(user_id, proposal_id, "pending", None,
                                      {"accepted_role": None, "accepted_weight": None}, from_status="accepted")
            raise EntityNotFound(f"entity key {exp['key']!r} is no longer in the graph")

        self.personas.init_beta(user_id, self._entity_priors([exp]))
        version = self.personas.patch(user_id, {})
        self._refresh_pi(user_id)
        self._after_edit(user_id)
        exposures = self.exposures.get_exposures(user_id)
        persona = self.personas.get(user_id)
        return {
            "user_id": user_id, "proposal": self._proposal_out(decided), "exposure": linked,
            "persona_version": version,
            "sentences": explain.profile_sentences(exposures, persona.get("topics") or {},
                                                   persona.get("style") or {}, c),
        }

    def reject_proposal(self, user_id: str, proposal_id: str) -> Dict:
        """Mark it rejected (it won't be proposed again). The persona, graph and digest are untouched."""
        persona = self._require_persona(user_id)
        self._pending_proposal(user_id, proposal_id)
        decided = self.logs.decide_proposal(user_id, proposal_id, "rejected", self.clock())
        if decided is None:
            raise Conflict(f"proposal {proposal_id} was decided concurrently")
        return {"user_id": user_id, "proposal": self._proposal_out(decided),
                "persona_version": persona.get("persona_version")}

    # ── E/F. Candidates + interest ───────────────────────────

    def _candidate_projection(self) -> Dict:
        c = self.cfg
        fields = [c.id_field, c.title_field, c.topic_field, c.source_field, c.published_field, c.entities_field,
                  c.url_field, "entity_keys", "cluster_id", "cluster_size", "materiality"]
        return {"_id": 0, **{f: 1 for f in fields}}

    def candidates(self, user_id: str, now: Optional[datetime] = None) -> Dict:
        """
        R1–R4 → RRF (R1/R2 bypass the cut) → drop read → interest per candidate → cluster collapse.
        A debug view of the digest's candidate stage: items plus per-retriever stats.
        """
        pool = self._candidate_pool(user_id, now or self.clock())
        items = candidates.collapse_clusters(pool["scored"])
        return {"user_id": user_id, "items": items, "stats": {**pool["stats"], "after_collapse": len(items)},
                "retrieved": {n: sorted(s) for n, s in pool["sets"].items()}}

    def _candidate_pool(self, user_id: str, now: datetime) -> Dict:
        """The candidate stage up to interest scoring (before cluster collapse), plus what the slate needs."""
        c = self.cfg
        persona = self._require_persona(user_id)
        pi = persona.get("pi_topk") or []
        if not pi:
            try:
                pi = self.compute_pi(user_id)
            except Exception as e:  # Neo4j down: no exposure hits this time, the digest still works
                logger.warning(f"[Personalization] compute_pi failed for {user_id}: {type(e).__name__}: {e}")
        history = persona.get("history") or []

        docs = self.articles.window(c.cand_window_h, now, self._candidate_projection())
        by_id = {d[c.id_field]: d for d in docs}
        aliases = self.logs.alias_map()

        r1 = candidates.r1_exposure(docs, pi, c, aliases)
        r2 = candidates.r2_material(docs, now, c)
        vectors = self.vector_store()
        recent = [h["article_id"] for h in history[-c.r3_history_items:] if h.get("article_id")]
        recent = list(dict.fromkeys(reversed(recent)))
        hist_vecs = vectors.vectors_for({h.get("article_id") for h in history if h.get("article_id")})
        r3_hits = {a: vectors.search_vector(hist_vecs[a], c.r3_per_item * 3) for a in recent if a in hist_vecs}
        r3 = candidates.r3_similar(r3_hits, set(by_id), c)
        topics = [t for t, w in (persona.get("topics") or {}).items() if w and w > 0]
        r4 = [candidates.r4_topic(docs, t, now, c) for t in topics]

        fused, sources = candidates.merge_candidates(r1, r2, r3, r4, c)
        read = self.logs.read_ids(user_id, history)
        kept = candidates.drop_read(fused, read)

        cand_vecs = vectors.vectors_for(a for a, _ in kept)
        scored = []
        for article_id, rrf_score in kept:
            d = by_id[article_id]
            keys = candidates.doc_entity_keys(d, c)
            score, parts = interest.interest({"topic": d.get(c.topic_field), "entity_keys": keys},
                                             cand_vecs.get(article_id), persona, hist_vecs, now, c)
            scored.append({
                "article_id": article_id, "title": d.get(c.title_field), "source_name": d.get(c.source_field),
                "url": d.get(c.url_field), "topic": d.get(c.topic_field), "cluster_id": d.get("cluster_id"),
                "published_at": d.get(c.published_field), "m": (d.get("materiality") or {}).get("m"),
                "materiality": d.get("materiality"),
                "entity_keys": keys, "sources": sorted(sources.get(article_id, ())), "rrf": round(rrf_score, 6),
                "score": score, "interest_parts": parts,
            })

        sets = {"R1": set(r1), "R2": set(r2), "R3": {a for lst in r3 for a in lst},
                "R4": {a for lst in r4 for a in lst}}
        names = sorted(sets)
        stats = {
            "window_articles": len(docs),
            "retrievers": {n: len(s) for n, s in sets.items()},
            "r3_history_items": len(r3_hits), "r4_topics": topics,
            "overlap": {f"{a}&{b}": len(sets[a] & sets[b]) for i, a in enumerate(names) for b in names[i + 1:]},
            "union": len(set().union(*sets.values())),
            "fused_kept": len(fused), "read_dropped": len(fused) - len(kept),
            "scored": len(scored),
            "vector_coverage": round(len(cand_vecs) / len(kept), 4) if kept else None,
            "history_vectors": f"{len(hist_vecs)}/{len({h.get('article_id') for h in history})}",
        }
        return {"persona": persona, "pi": pi, "docs": by_id, "aliases": aliases, "scored": scored,
                "vectors": {**hist_vecs, **cand_vecs}, "sets": sets, "stats": stats}

    # ── G/H. Digest: slate + explanations + cache + impressions ──

    def _local_date(self, persona: Dict, now: datetime) -> str:
        """The digest's day in the user's time zone (alert_prefs.tz, else cfg.tz)."""
        zone = alert_rules.zone((persona.get("alert_prefs") or {}).get("tz"), self.cfg.tz)
        return now.astimezone(zone).date().isoformat()

    def _display_names(self, user_id: str, docs: Dict[str, Dict], pi_entries: List[Dict]) -> Dict[str, str]:
        """
        Entity key → display name: the user's exposures, then the most salient spelling in the window, then the
        graph's most-mentioned spelling for the path keys (seeds, intermediates) the window doesn't contain.
        """
        c = self.cfg
        names: Dict[str, str] = {}
        for d in docs.values():
            for ent in sorted(d.get(c.entities_field) or [], key=lambda e: -(e.get(c.entity_salience_key) or 0.0)):
                raw = (ent.get(c.entity_name_key) or "").strip()
                if raw:
                    names.setdefault(entity_key(raw), raw)
        path_keys = {k for e in pi_entries for k in (e["entity"], e["path"]["seed"], *e["path"]["via"])}
        try:
            names.update({e["key"]: e["name"] for e in self.exposures.get_exposures(user_id) if e.get("name")})
            missing = sorted(k for k in path_keys if k not in names)
            names.update(self.exposures.display_names(missing))
        except Exception as e:
            logger.warning(f"[Personalization] entity names unavailable: {type(e).__name__}: {e}")
        return names

    @staticmethod
    def _similarity(vectors: Dict[str, "object"], keys: Dict[str, set]) -> Callable[[str, str], float]:
        """MMR similarity: cosine of the pers-index vectors, else Jaccard of the entity keys."""
        def sim(a: str, b: str) -> float:
            if a in vectors and b in vectors:
                return max(0.0, interest._cos(vectors[a], vectors[b]))
            ka, kb = keys.get(a) or set(), keys.get(b) or set()
            return len(ka & kb) / len(ka | kb) if ka and kb else 0.0
        return sim

    def _why(self, item: Dict, names: Dict[str, str], tau: float) -> Tuple[str, Dict]:
        """The why line of one slate item and its structured parts (the numbers the text is built from)."""
        c = self.cfg
        hits, section = item.get("need_hits") or [], item["section"]
        entry = hits[0] if hits else None
        parts: Dict = {"kind": "interest", "need": item["need"], "m": item["m"], "tau": tau}
        if section == slate.EXPLORE:
            parts["kind"] = "explore"
            return explain.why_explore(item.get("topic")), parts
        must = section in (slate.MUST_KNOW, slate.MORE_YOU_NEED)
        # outside must_know an exposure is named only when it moves the ranking noticeably
        if entry and (must or c.need_bonus * item["need"] >= c.why_min_need_lift):
            parts.update({
                "kind": "direct" if not entry["path"]["relations"] else "hop",
                "entity": entry["entity"], "pi": float(entry["score"]), "path": entry["path"],
                "share": explain.need_share(entry["score"], entry["score"]),
                "also": explain.also_hits(hits, c),
            })
        else:
            entry = None
        if must:
            return (f"{explain.why_exposure(entry, c, names)} "
                    f"{explain.why_need(item['need'], item['m'], hits, c, names)}"), parts
        text = explain.why_interest(item["interest_parts"], item.get("topic"), c, names, item.get("m"),
                                    skip_entity=entry["entity"] if entry else None)
        return (f"{explain.why_exposure(entry, c, names)} {text}" if entry else text), parts

    @staticmethod
    def _m_parts(mat: Optional[Dict]) -> Optional[Dict]:
        return {k: mat.get(k) for k in ("risk_norm", "size_score", "first_report", "source_cred", "unscored")}             if mat else None

    def _digest_item(self, item: Dict, names: Dict[str, str], tau: float) -> Dict:
        why, why_parts = self._why(item, names, tau)
        return {
            "slot": item["slot"], "section": item["section"],
            "article_id": item["article_id"], "title": item.get("title"), "source_name": item.get("source_name"),
            "url": item.get("url"), "topic": item.get("topic"), "published_at": item.get("published_at"),
            "cluster_id": item.get("cluster_id"), "cluster_members": item.get("cluster_members"),
            "m": item.get("m"), "m_parts": self._m_parts(item.get("materiality")),
            "need": item["need"], "interest": item["score"], "interest_parts": item["interest_parts"],
            "rel": item["rel"], "propensity": item["propensity"], "sources": item.get("sources"),
            "why": why, "why_parts": why_parts, "another_angle": item.get("another_angle"),
        }

    def compute_digest(self, user_id: str, now: Optional[datetime] = None) -> Dict:
        """
        Candidates → need (m × max pi, entities canonicalized through aliases) and rel per article → cluster collapse
        (members at or above τ first, then rel) → slate (must_know / for_you / explore) → why lines.
        Pure computation plus reads: nothing is cached or logged here.
        """
        c = self.cfg
        now = now or self.clock()
        pool = self._candidate_pool(user_id, now)
        persona, tau = pool["persona"], self.logs.current_tau()
        pi = {e["entity"]: e for e in pool["pi"]}
        for item in pool["scored"]:
            keys = candidates.resolve_keys(item["entity_keys"], pool["aliases"])
            item["need"], _ = slate.need(keys, item["m"], pi)
            item["need_hits"] = slate.pi_hits(keys, pi)[:3]
            item["rel"] = slate.relevance(item["score"], item["need"], c)
            item["rank"] = item["rel"] + (1.0 if item["need"] >= tau else 0.0)
        collapsed = candidates.collapse_clusters(pool["scored"], score_key="rank")

        date = self._local_date(persona, now)
        sim = self._similarity(pool["vectors"], {i["article_id"]: set(i["entity_keys"]) for i in collapsed})
        rng = np.random.default_rng(slate.rng_seed(user_id, date))
        result = slate.build_slate(collapsed, tau, persona, sim, rng, c)

        names = self._display_names(user_id, pool["docs"], [h for i in result["items"] + result["more_you_need"]
                                                             for h in i["need_hits"]])
        items = [self._digest_item(i, names, tau) for i in result["items"]]
        more = [self._digest_item(i, names, tau) for i in result["more_you_need"]]
        served = items + more
        stats = {
            **pool["stats"], "after_collapse": len(collapsed), **result["stats"],
            "unscored_share": round(sum(1 for i in collapsed if (i.get("materiality") or {}).get("unscored"))
                                    / len(collapsed), 4) if collapsed else None,
            "m_missing": sum(1 for i in collapsed if i.get("m") is None),
            "need_positive": sum(1 for i in collapsed if i["need"] > 0),
            "hop_need_items": sum(1 for i in served if i["why_parts"].get("kind") == "hop"),
            "max_hop_need": max((i["need"] for i in collapsed
                                 if i["need_hits"] and i["need_hits"][0]["path"]["relations"]), default=0.0),
        }
        return {
            "user_id": user_id, "date": date, "items": items, "more_you_need": more, "tau": tau,
            "policy_version": c.policy_version, "persona_version": persona.get("persona_version"),
            "generated_at": now, "stats": stats,
        }

    def get_digest(self, user_id: str, refresh: bool = False) -> Dict:
        """
        Today's digest (user's local date) from the `digests` cache when its persona_version, policy_version and τ
        still match, else computed and cached. Every serve logs one impression per item with a fresh digest_id.
        """
        c = self.cfg
        persona = self._require_persona(user_id)
        now = self.clock()
        date = self._local_date(persona, now)
        cached = None if refresh else self.logs.get_digest(user_id, date)
        if (cached and cached.get("persona_version") == persona.get("persona_version")
                and cached.get("policy_version") == c.policy_version
                and cached.get("tau") == self.logs.current_tau()):
            digest, from_cache = cached, True
            digest["generated_at"] = scoring.parse_ts(digest.get("generated_at"))
        else:
            digest, from_cache = self.compute_digest(user_id, now), False
            self.logs.put_digest(dict(digest))
        digest_id = str(uuid.uuid4())
        self._log_impressions(digest, digest_id, now)
        app = self._app_items(user_id, digest["items"] + digest["more_you_need"])
        n = len(digest["items"])
        return {**digest, "items": app[:n], "more_you_need": app[n:], "digest_id": digest_id, "cached": from_cache,
                "served_at": now}

    def _log_impressions(self, digest: Dict, digest_id: str, now: datetime) -> int:
        rows = [{
            "impression_id": str(uuid.uuid4()), "digest_id": digest_id, "user_id": digest["user_id"],
            "article_id": i["article_id"], "cluster_id": i.get("cluster_id"), "slot": i["slot"],
            "section": i["section"], "need": i["need"], "m": i["m"], "m_parts": i.get("m_parts"),
            "interest": i["interest"], "interest_parts": i["interest_parts"], "tau": digest["tau"],
            "propensity": i["propensity"], "policy_version": digest["policy_version"],
            "persona_version": digest["persona_version"], "t": now,
        } for i in digest["items"] + digest["more_you_need"]]
        return self.logs.log_impressions(rows)

    def _after_edit(self, user_id: str) -> None:
        """A profile edit: the cached digest no longer reflects the persona."""
        self.logs.invalidate_digest(user_id)

    # ── J. Alerts ────────────────────────────────────────────

    def _score_alert(self, user_id: str, doc: Dict, keys: List[str], pi: Dict[str, Dict]) -> Dict:
        """One (user, article) pair: need = m × max pi. Only ever called for users the inverted index returns."""
        c = self.cfg
        m = (doc.get("materiality") or {}).get("m")
        need, _ = slate.need(keys, m, pi)
        return {"user_id": user_id, "article_id": doc[c.id_field],
                "cluster_id": doc.get("cluster_id") or doc[c.id_field],   # an unclustered article is its own cluster
                "need": need, "m": m, "hits": slate.pi_hits(keys, pi)[:3]}

    def _alert_doc(self, item: Dict, doc: Dict, row: Dict, names: Dict[str, str], now: datetime,
                   deliver: datetime, deferred: bool) -> Dict:
        c = self.cfg
        entry = item["hits"][0]
        why = (f"{explain.why_exposure(entry, c, names)} "
               f"{explain.why_need(item['need'], item['m'], item['hits'], c, names)}")
        return {
            "alert_id": str(uuid.uuid4()), "user_id": item["user_id"], "article_id": item["article_id"],
            "cluster_id": item["cluster_id"], "title": doc.get(c.title_field), "url": doc.get(c.url_field),
            "source_name": doc.get(c.source_field), "topic": doc.get(c.topic_field),
            "published_at": doc.get(c.published_field),
            "need": item["need"], "m": item["m"], "m_parts": self._m_parts(doc.get("materiality")),
            "entity": entry["entity"], "path": entry["path"], "explanation": why,
            "created_at": now, "deliver_after": deliver, "deferred": deferred,
            "policy_version": c.policy_version, "persona_version": row.get("persona_version"),
        }

    def run_alerts(self, now: Optional[datetime] = None, rescan: bool = False) -> Dict:
        """
        The */5 alerts job body (plan §5 Alerts): window articles (alert_lookback_h) whose current materiality
        hasn't been evaluated → entity keys (aliases resolved) → users from the inverted pi index → need →
        need ≥ alert_min_need ∧ m ≥ alert_min_m → one per (user, cluster) → per-day cap → quiet-hours deferral.

        Every evaluated article is marked, so it is looked at again only when its materiality changes (cluster
        growth, A4 rescore). This replaces the plan's "computed_at > last run" watermark, which misses articles
        whose materiality is written after an alerts run that started during the clustering job.
        `rescan` evaluates the whole window again (e.g. after lowering a threshold); duplicates are impossible.
        """
        c = self.cfg
        now = now or self.clock()
        if not c.enable_alerts:
            return {"skipped": "enable_alerts=false"}
        docs = self.articles.alert_scan_pending(c.alert_lookback_h, now, rescan=rescan)
        rows = {r["user_id"]: r for r in self.personas.pi_rows()}
        index = alert_rules.build_index(rows.values(), c.alert_min_need)
        aliases = self.logs.alias_map()
        ms = [m for d in docs if (m := (d.get("materiality") or {}).get("m")) is not None]
        stats: Dict = {
            "rescan": rescan, "min_need": c.alert_min_need, "min_m": c.alert_min_m,
            "articles_scanned": len(docs), "articles_material": 0, "max_m": max(ms, default=None),
            "users": len(rows), "users_indexed": len(set().union(*index.values())) if index else 0,
            "index_keys": len(index), "pairs_scored": 0, "eligible": 0,
        }

        pi_maps: Dict[str, Dict[str, Dict]] = {}
        by_user: Dict[str, List[Dict]] = {}
        for d in docs:
            m = (d.get("materiality") or {}).get("m")
            if m is None or m < c.alert_min_m:
                continue
            stats["articles_material"] += 1
            keys = candidates.resolve_keys(candidates.doc_entity_keys(d, c), aliases)
            for user_id in sorted(alert_rules.users_for(keys, index)):
                if user_id not in pi_maps:
                    pi_maps[user_id] = {e["entity"]: e for e in rows[user_id]["pi_topk"]}
                item = self._score_alert(user_id, d, keys, pi_maps[user_id])
                stats["pairs_scored"] += 1
                if alert_rules.eligible(item["need"], item["m"], c):
                    by_user.setdefault(user_id, []).append(item)
        stats["eligible"] = sum(len(v) for v in by_user.values())

        docs_by_id = {d[c.id_field]: d for d in docs}
        dropped = {"already_alerted": 0, "same_cluster": 0, "capped": 0, "race": 0}
        created, deferred = [], 0
        for user_id, items in sorted(by_user.items()):
            row = rows[user_id]
            prefs = alert_rules.prefs(row.get("alert_prefs"), c)
            deliver, is_deferred = alert_rules.deliver_after(now, prefs, c.tz)
            day = alert_rules.day_bounds(deliver, alert_rules.zone(prefs.get("tz"), c.tz))
            remaining = int(prefs["max_per_day"]) - self.logs.count_alerts(user_id, *day)
            alerted = self.logs.alerted_clusters(user_id, sorted({i["cluster_id"] for i in items}))
            chosen, drop = alert_rules.select(items, alerted, remaining)
            for k, v in drop.items():
                dropped[k] += v
            if not chosen:
                continue
            names = self._display_names(user_id, {i["article_id"]: docs_by_id[i["article_id"]] for i in chosen},
                                        [h for i in chosen for h in i["hits"]])
            for item in chosen:
                alert = self._alert_doc(item, docs_by_id[item["article_id"]], row, names, now, deliver, is_deferred)
                if self.logs.add_alert(alert):
                    created.append({k: alert[k] for k in ("alert_id", "user_id", "article_id", "cluster_id",
                                                          "need", "deliver_after")})
                    deferred += is_deferred
                else:  # a concurrent run alerted the same cluster first
                    dropped["race"] += 1

        # marked only after the alerts are written: a crash mid-run re-evaluates, and the unique index dedups
        self.articles.mark_alert_scanned(
            {d[c.id_field]: d["materiality"].get("computed_at") for d in docs if d.get("materiality")}, now)
        stats.update({"created": len(created), "deferred": deferred, "dropped": dropped, "alerts": created})
        return stats

    def alerts(self, user_id: str, since: Optional[datetime] = None, include_pending: bool = False,
               limit: int = 50) -> List[Dict]:
        """
        The user's alerts by delivery time, newest first: those delivered after `since` (by deliver_after, so a
        client polling with its last poll time also gets alerts released from quiet hours since). Alerts still
        held by quiet hours are left out unless include_pending.
        """
        self._require_persona(user_id)
        now = self.clock()
        rows = self.logs.alerts_for(user_id, scoring.parse_ts(since), None if include_pending else now, limit)
        c = self.cfg
        docs = {d[c.id_field]: d for d in self.articles.by_ids(
            [r["article_id"] for r in rows], {"_id": 0, c.id_field: 1, "cluster_size": 1, c.entities_field: 1})}
        sizes = {a: d.get("cluster_size") or 1 for a, d in docs.items()}
        names = self._display_names(user_id, docs, [{"entity": r["entity"], "path": r["path"]} for r in rows]) \
            if rows else {}
        for r in rows:
            for f in ("created_at", "deliver_after"):
                r[f] = scoring.parse_ts(r[f])                  # Mongo hands back naive UTC
            r["delivered"] = r["deliver_after"] <= now
            # for the app: the exposure that fired it, Major vs High, and how many outlets carry the story
            r["entity_name"] = names.get(r["path"]["seed"], r["path"]["seed"])
            r["tier"] = "major" if (r.get("m") or 0.0) >= c.alert_major_m else "high"
            r["cluster_size"] = sizes.get(r["article_id"], 1)
        return rows

    # ── K. Render ────────────────────────────────────────────

    @property
    def renderer(self) -> render_rules.Renderer:
        if self._renderer is None:
            self._renderer = render_rules.Renderer(self.logs, self.cfg, self._llm_factory, self.clock)
        return self._renderer

    def _render_brief(self, user_id: str, persona: Dict, doc: Dict, style: Dict[str, str]) -> Dict:
        """
        The personal part of a render: style, the reader's top 3 exposure hits in the article and the why line —
        the one served in today's digest when the article was in it, else built from the exposure hits.
        """
        c = self.cfg
        article_id = doc[c.id_field]
        keys = candidates.resolve_keys(candidates.doc_entity_keys(doc, c), self.logs.alias_map())
        pi = {e["entity"]: e for e in persona.get("pi_topk") or []}
        hits = slate.pi_hits(keys, pi)[:3]
        m = (doc.get("materiality") or {}).get("m")
        names = self._display_names(user_id, {article_id: doc}, hits)

        why, why_source = None, None
        digest = self.logs.get_digest(user_id, self._local_date(persona, self.clock()))
        served = next((i for i in (digest or {}).get("items", []) + (digest or {}).get("more_you_need", [])
                       if i["article_id"] == article_id), None)
        if served and served.get("why"):
            why, why_source = served["why"], "digest"
        elif hits:
            need, _ = slate.need(keys, m, pi)
            why = f"{explain.why_exposure(hits[0], c, names)} {explain.why_need(need, m, hits, c, names)}"
            why_source = "exposure"
        return {
            "style": style,
            "exposures": [{"entity": h["entity"], "name": names.get(h["entity"], h["entity"]), "pi": h["score"],
                           "why": explain.why_exposure(h, c, names)} for h in hits],
            "why": why, "why_source": why_source,
        }

    def render(self, article_id: str, user_id: str, refresh: bool = False) -> Dict:
        """
        The article rewritten in the reader's style ({tone, length, jargon}) plus their persona brief:
        {text, why, brief, cached, fallback, reason, missing, added, ...}. The rewrite is shared by every reader
        with the same style; `fallback` means the source text is served (fact check failed, no LLM, render off).
        """
        c = self.cfg
        persona = self._require_persona(user_id)
        fields = [c.id_field, c.title_field, c.topic_field, c.url_field, c.source_field, c.published_field,
                  c.entities_field, "entity_keys", "cluster_id", "materiality", "summary_short", "summary_long", "body"]
        docs = self.articles.by_ids([article_id], {"_id": 0, **{f: 1 for f in fields}})
        if not docs:
            raise ArticleNotFound(f"article {article_id} not found")
        doc = docs[0]
        style = {**c.style_defaults, **(persona.get("style") or {})}
        source, source_field = render_rules.source_text(doc, style["length"], c)
        names = [e.get(c.entity_name_key) for e in doc.get(c.entities_field) or [] if e.get(c.entity_name_key)]
        out = self.renderer.render(article_id, source, source_field, names, style, refresh)
        brief = self._render_brief(user_id, persona, doc, style)
        return {
            "article_id": article_id, "user_id": user_id, "title": doc.get(c.title_field),
            "url": doc.get(c.url_field), "source_name": doc.get(c.source_field), "style": style,
            "text": out["text"], "why": brief["why"], "brief": brief,
            "cached": out["cached"], "fallback": out["fallback"], "reason": out["reason"],
            "missing": out["missing"], "added": out["added"], "model": out["model"], "llm_call": out["llm_call"],
            "source_field": source_field, "prompt_version": c.render_prompt_version,
        }

    # ── M. App views (the mobile app's StoryItem / StoryDetail shapes, mobile/src/api/types.ts) ──

    def _story_projection(self, *more: str) -> Dict:
        c = self.cfg
        fields = [c.id_field, c.title_field, c.topic_field, c.url_field, c.source_field, c.published_field,
                  c.entities_field, "entity_keys", "cluster_id", "cluster_size", "first_report", "materiality",
                  "summary_short", "summary_long", "topic_tags", "risk_level", "urgency_flag", "media", "author", *more]
        return {"_id": 0, **{f: 1 for f in fields}}

    def _story_item(self, doc: Dict, **extra) -> Dict:
        """One article as the app's StoryItem (top 3 entities by salience; first_report = this article opened it)."""
        c = self.cfg
        entities, seen = [], set()
        for ent in sorted(doc.get(c.entities_field) or [], key=lambda e: -(e.get(c.entity_salience_key) or 0.0)):
            raw = (ent.get(c.entity_name_key) or "").strip()
            key = entity_key(raw)
            if key and key not in seen and len(entities) < 3:
                seen.add(key)
                entities.append({"key": key, "name": raw})
        body = doc.get("body") or ""
        return {
            "article_id": doc[c.id_field], "url": doc.get(c.url_field) or "", "title": doc.get(c.title_field) or "",
            "summary_short": doc.get("summary_short"), "summary_long": doc.get("summary_long"),
            "body_snippet": body[:280] or None, "media": doc.get("media"), "author": doc.get("author"),
            "source_name": doc.get(c.source_field), "published_at": doc.get(c.published_field),
            "topic": doc.get(c.topic_field), "topic_tags": doc.get("topic_tags") or [], "entities": entities,
            "cluster_id": doc.get("cluster_id"), "cluster_size": doc.get("cluster_size") or 1,
            "first_report": doc.get("first_report") == doc[c.id_field], "risk_level": doc.get("risk_level"),
            "unscored": bool((doc.get("materiality") or {}).get("unscored")),
            "urgency_flag": bool(doc.get("urgency_flag")),
            **extra,
        }

    def _app_parts(self, why_parts: Dict, topic: Optional[str], names: Dict[str, str]) -> Dict:
        """why_parts (entity keys, paths) → the app's explanation_parts (display names)."""
        c = self.cfg
        kind, path = why_parts.get("kind"), why_parts.get("path")
        if kind == "explore":
            return {"kind": "explore", "topic": explain.topic_label(topic)}
        if kind in ("direct", "hop") and path:
            out = {"kind": "direct" if kind == "direct" else "connected",
                   "seed_name": names.get(path["seed"], path["seed"]), "role": path["role"],
                   "also": [names.get(a["entity"], a["entity"]) for a in why_parts.get("also") or []]}
            if kind == "hop":
                out["via_name"] = names.get(why_parts["entity"], why_parts["entity"])
                out["relation"] = explain._rel_label(path["relations"][-1], c)
            return out
        return {"kind": "topic", "topic": explain.topic_label(topic)}

    def _app_items(self, user_id: str, items: List[Dict]) -> List[Dict]:
        """Slate items ({article_id, why, why_parts, another_angle, …}) + their articles → StoryItems."""
        c = self.cfg
        angles = [i["another_angle"]["article_id"] for i in items if (i.get("another_angle") or {}).get("article_id")]
        docs = {d[c.id_field]: d for d in self.articles.by_ids([i["article_id"] for i in items] + angles,
                                                                 self._story_projection())}
        entries = []
        for i in items:
            wp = i.get("why_parts") or {}
            if wp.get("path"):
                entries.append({"entity": wp["entity"], "path": wp["path"]})
                entries += [{"entity": a["entity"], "path": {"seed": a["entity"], "via": []}}
                            for a in wp.get("also") or []]
        names = self._display_names(user_id, docs, entries) if entries else {}
        counts = self._engagement([i["article_id"] for i in items], user_id)
        out = []
        for i in items:
            doc = docs.get(i["article_id"])
            angle = i.get("another_angle")
            if angle and angle.get("article_id") in docs:
                angle = {**angle, "url": docs[angle["article_id"]].get(c.url_field)}
            out.append({**(self._story_item(doc) if doc else {}), **i, "another_angle": angle,
                        "explanation": i.get("why"),
                        "explanation_parts": self._app_parts(i.get("why_parts") or {}, i.get("topic"), names),
                        **counts.get(i["article_id"], {})})
        return out

    def _engagement(self, article_ids: List[str], viewer: Optional[str]) -> Dict[str, Dict]:
        """{article_id: {"engagement": counts without the viewer, "viewer": their reaction / saved}}; {} on a store error."""
        try:
            rows = self.logs.engagement(article_ids, viewer)
        except Exception as e:
            logger.warning(f"[Personalization] engagement counts unavailable: {type(e).__name__}: {e}")
            return {}
        return {a: {"engagement": {k: v for k, v in r.items() if k != "viewer"},
                    **({"viewer": r["viewer"]} if viewer else {})} for a, r in rows.items()}

    def feed(self, user_id: str, cursor: Optional[str] = None, limit: int = 10,
             exclude: Optional[List[str]] = None) -> Dict:
        """
        Endless pages after the brief: unread window candidates (minus `exclude`, e.g. today's brief), one per
        cluster, ranked by rel = interest + need_bonus·need. The cursor is an offset into that ranking, which is
        recomputed per page, so a page can shift slightly when new articles arrive in between.
        """
        c, now = self.cfg, self.clock()
        if cursor and not cursor.isdigit():
            raise InvalidInput("cursor must be the next_cursor of the previous page")
        offset = int(cursor or 0)
        pool = self._candidate_pool(user_id, now)
        pi = {e["entity"]: e for e in pool["pi"]}
        skip = set(exclude or [])
        scored = [i for i in pool["scored"] if i["article_id"] not in skip]
        for item in scored:
            keys = candidates.resolve_keys(item["entity_keys"], pool["aliases"])
            item["need"], _ = slate.need(keys, item["m"], pi)
            item["need_hits"] = slate.pi_hits(keys, pi)[:3]
            item["rel"] = slate.relevance(item["score"], item["need"], c)
        ranked = candidates.collapse_clusters(scored, score_key="rel")
        page = ranked[offset: offset + limit]
        names = self._display_names(user_id, pool["docs"], [h for i in page for h in i["need_hits"]])
        tau = self.logs.current_tau()
        items = []
        for slot, item in enumerate(page, start=offset):
            item.update(section="feed", slot=slot)
            why, parts = self._why(item, names, tau)
            items.append({"article_id": item["article_id"], "section": "feed", "slot": slot, "topic": item["topic"],
                          "why": why, "why_parts": parts, "another_angle": item.get("another_angle")})
        exhausted = offset + limit >= len(ranked)
        return {"items": self._app_items(user_id, items), "next_cursor": None if exhausted else str(offset + limit),
                "exhausted": exhausted, "window_h": c.cand_window_h}

    def top(self, hours: float = 24, limit: int = 8, after_recap: bool = False, tz: Optional[str] = None) -> List[Dict]:
        """
        Big today: the last `hours` of articles by materiality, one per cluster. after_recap: instead, everything
        since the end of the newest daily recap in `tz` (today so far once it is ready, else since yesterday's
        start), so Big today and the recap never repeat each other.
        """
        c, now = self.cfg, self.clock()
        if after_recap:
            _, z = self._recap_zone(tz)
            start = recap_rules.daily_period(recap_rules.latest_daily(now, z, c), z, c)["end"]
            hours = max(0.0, (now - start).total_seconds() / 3600)
        docs = self.articles.window(hours, now, self._story_projection())
        docs.sort(key=lambda d: (-((d.get("materiality") or {}).get("m") or 0.0), d[c.id_field]))
        best: Dict[str, Dict] = {}
        for d in docs:
            best.setdefault(d.get("cluster_id") or d[c.id_field], d)
        out = []
        picked = list(best.values())[:limit]
        counts = self._engagement([d[c.id_field] for d in picked], None)
        for d in picked:
            n = d.get("cluster_size") or 1
            out.append(self._story_item(
                d, section="big_today", explanation_parts={"kind": "big_today"},
                explanation=f"Covered by {n} sources" if n > 1 else "One of the most significant stories today",
                **counts.get(d[c.id_field], {})))
        return out

    # ── N. Recaps (personalization/recap.py) ─────────────────

    def _recap_zone(self, tz: Optional[str], user_id: Optional[str] = None) -> Tuple[str, ZoneInfo]:
        """(name, zone): the request's time zone (the device's), else the reader's alert_prefs.tz, else cfg.tz."""
        if tz:
            try:
                return tz, ZoneInfo(tz)
            except (ZoneInfoNotFoundError, ValueError):
                raise InvalidInput(f"unknown time zone {tz!r}")
        if user_id:
            pref = ((self.personas.get(user_id) or {}).get("alert_prefs") or {}).get("tz")
            if pref:
                zone = alert_rules.zone(pref, self.cfg.tz)
                return zone.key, zone
        return self.cfg.tz, ZoneInfo(self.cfg.tz)

    def _recap_period(self, kind: str, key: Optional[str], z: ZoneInfo, now: datetime) -> Dict:
        """The asked-for period (default: the newest ready one). A period that isn't over and ready → RecapNotReady."""
        c = self.cfg
        if kind not in ("daily", "weekly"):
            raise InvalidInput(f"kind must be daily or weekly, got {kind!r}")
        latest = recap_rules.latest_daily(now, z, c) if kind == "daily" else recap_rules.latest_weekly(now, z, c)
        try:
            start = (recap_rules.parse_day(key) if kind == "daily" else recap_rules.parse_week(key)) if key else latest
        except ValueError as e:
            raise InvalidInput(str(e))
        build = recap_rules.daily_period if kind == "daily" else recap_rules.weekly_period
        period = build(start, z, c)
        if start > latest:
            raise RecapNotReady(f"the {kind} recap for {period['key']} is ready at {period['ready_at'].isoformat()}")
        return {**period, "latest": start == latest,
                "next_at": build(start + timedelta(days=1 if kind == "daily" else 7), z, c)["ready_at"]}

    def _recap_projection(self) -> Dict:
        return self._story_projection("published_ts", "ingested_ts", "ingested_at", "date_source",
                                      self.cfg.risk_field, "risk_processed_at")

    def _recap_client(self) -> Tuple[Optional[object], Optional[str]]:
        if self._recap_llm is None:
            client, model = self._llm_factory()
            self._recap_llm = (client, self.cfg.render_model or model) if client else (None, None)
        return self._recap_llm

    def _recap_overview(self, kind: str, title: str, items: List[Dict]) -> Dict:
        """{text, reason, model, added}: text None when off, without an LLM, on an error or a failed check."""
        c = self.cfg
        if not c.recap_overview or not items:
            return {"text": None, "reason": "disabled" if items else "no_items", "model": None, "added": []}
        client, model = self._recap_client()
        if client is None:
            return {"text": None, "reason": "no_llm_client", "model": None, "added": []}
        source = recap_rules.overview_source(items, c)
        try:
            response = client.chat.completions.create(
                model=model, messages=recap_rules.overview_messages(kind, title, source),
                response_format={"type": "json_object"}, temperature=c.render_temperature,
                max_tokens=c.recap_overview_max_tokens, extra_body=c.render_llm_extra)
            text = recap_rules.parse_overview(response.choices[0].message.content)
        except Exception as e:
            logger.error(f"[Recap] overview failed ({model}): {type(e).__name__}: {e}")
            return {"text": None, "reason": f"llm_error: {type(e).__name__}", "model": model, "added": []}
        ok, added = recap_rules.overview_check(source, text)
        if not ok:
            logger.warning(f"[Recap] overview dropped: {'unparseable' if text is None else 'added'} {added}")
            return {"text": None, "reason": "unparseable_response" if text is None else "fact_check",
                    "model": model, "added": added}
        return {"text": text, "reason": None, "model": model, "added": []}

    def _recap_items(self, kind: str, picks: List[Dict], times: Dict[str, Tuple[datetime, str]]) -> List[Dict]:
        """Selected stories → StoryItems of their lead article, frozen into the recap (summary filled when missing)."""
        from agents.extractive_summarizer import extractive_summarize
        c = self.cfg
        full = {d[c.id_field]: d for d in self.articles.by_ids([p["lead"][c.id_field] for p in picks],
                                                                 self._story_projection("body"))}
        out = []
        for p in picks:
            article_id = p["lead"][c.id_field]
            doc = full.get(article_id, p["lead"])
            item = self._story_item(doc)
            filled = False
            if not (item["summary_short"] or item["summary_long"]) and (doc.get("body") or "").strip():
                s = extractive_summarize(doc.get(c.title_field) or "", doc["body"], doc.get(c.entities_field) or [],
                                         doc.get(c.topic_field) or "")
                item.update(summary_short=s["summary_short"], summary_long=s["summary_long"])
                filled = True
            item.update({
                "section": "recap", "rank": p["rank"], "group": p["group"], "story_id": p["story_id"],
                "member_ids": p["member_ids"][: c.recap_member_ids_max], "cluster_size": p["size"],
                "m": p["m"], "m_fallback": p["m_fallback"], "score": p["score"], "span_days": p.get("span_days"),
                "happened_at": p["first_t"], "date_source": times[article_id][1], "summary_fallback": filled,
                "explanation": recap_rules.story_explanation(p, kind), "explanation_parts": {"kind": "recap"},
            })
            out.append(item)
        return out

    def compute_recap(self, kind: str, period: Dict, z: ZoneInfo, tz: str, now: datetime,
                      excluded: Optional[List[str]] = None, pinned: Optional[List[str]] = None) -> Dict:
        """
        One recap for (kind, period, tz), not stored. Weekly also takes in the late arrivals: articles from up to
        recap_undated_lookback_h before the week whose ingestion came after last week's recap was built, and that
        it didn't show.
        """
        c = self.cfg
        lookback = timedelta(hours=c.recap_undated_lookback_h)
        proj = self._recap_projection()
        docs = {d[c.id_field]: d for d in self.articles.by_time(period["start"] - lookback, period["end"], proj)}

        late: Dict[str, Dict] = {}
        served: set = set()
        built = None
        if kind == "weekly":
            prev = self.logs.get_recap("weekly", recap_rules.week_key(period["days"][0] - timedelta(days=7)), tz)
            built = scoring.parse_ts((prev or {}).get("generated_at"))
            if built:
                served = {a for i in prev["items"] for a in i.get("member_ids") or [i["article_id"]]}
                for d in self.articles.ingested_between(built, now, proj):
                    ts = scoring.parse_ts(d.get("ingested_ts") or d.get("ingested_at"))
                    if ts and ts >= built:
                        late[d[c.id_field]] = d
                        docs.setdefault(d[c.id_field], d)

        times = recap_rules.effective_times(list(docs.values()), c)
        carry = {a for a in late if a in times and a not in served
                 and period["start"] - lookback <= times[a][0] < period["start"]}
        inside = recap_rules.in_window(times, period, carry)
        period_docs = [d for a, d in docs.items() if a in inside]
        stories = recap_rules.drop_excluded(recap_rules.build_stories(period_docs, times, c), excluded or [])
        if kind == "daily":
            picks = recap_rules.select_daily(stories, c, pinned or [])
        else:
            picks = recap_rules.select_weekly(stories, z, period, c, pinned or [])
        items = self._recap_items(kind, picks, times)
        return {
            "kind": kind, "period": period["key"], "tz": tz, "title": period["title"],
            "start": period["start"], "end": period["end"], "ready_at": period["ready_at"],
            "days": [d.isoformat() for d in period["days"]], "generated_at": now,
            "policy_version": c.policy_version, "domains": list(c.recap_domains),
            "items": items, "sections": recap_rules.sections(kind, items, period),
            "coverage": {**recap_rules.coverage(period_docs, times, stories, c), "carried_over": len(carry)},
            "overview": self._recap_overview(kind, period["title"], items),
            "excluded": list(excluded or []), "pinned": list(pinned or []),
        }

    def _recap_outdated(self, doc: Dict, period: Dict) -> bool:
        """
        A recap is frozen, except one built on too few articles (coverage.limited): it is built again once
        articles of its period have been ingested since (ingestion is run by hand, so it can lag a day).
        """
        if not (doc.get("coverage") or {}).get("limited"):
            return False
        built = scoring.parse_ts(doc.get("generated_at"))
        proj = {"_id": 0, self.cfg.id_field: 1, "published_ts": 1, self.cfg.published_field: 1,
                "ingested_ts": 1, "ingested_at": 1}
        for d in self.articles.ingested_between(built, self.clock() + timedelta(days=1), proj):
            ingested = scoring.parse_ts(d.get("ingested_ts") or d.get("ingested_at"))
            ts = recap_rules._raw_time(d)
            if ingested and ingested > built and ts and period["start"] <= ts < period["end"]:
                return True
        return False

    def _build_recap(self, kind: str, period: Dict, z: ZoneInfo, tz: str, prev: Optional[Dict] = None,
                     excluded: Optional[List[str]] = None, pinned: Optional[List[str]] = None) -> Dict:
        """Compute and store a new version, keeping the previous version's exclusions and pins unless given."""
        excluded = excluded if excluded is not None else (prev or {}).get("excluded") or []
        pinned = pinned if pinned is not None else (prev or {}).get("pinned") or []
        doc = self.compute_recap(kind, period, z, tz, self.clock(), excluded, pinned)
        stored = self.logs.put_recap(doc)
        logger.info(f"[Recap] built {kind} {period['key']} ({tz}) v{stored['version']}: "
                    f"{len(stored['items'])} items from {stored['coverage']['articles']} articles")
        return stored

    def _recap_out(self, doc: Dict, period: Dict, user_id: Optional[str]) -> Dict:
        """The stored recap for the app: datetimes back to UTC-aware, engagement, and the reader's marks."""
        c = self.cfg
        items = [{**i, "happened_at": scoring.parse_ts(i.get("happened_at"))} for i in doc["items"]]
        counts = self._engagement([i["article_id"] for i in items], user_id)
        persona = self.personas.get(user_id) if user_id else None
        read, follows, topics = set(), {}, {}
        if persona:
            read = self.logs.read_ids(user_id, persona.get("history") or [])
            topics = persona.get("topics") or {}
            try:
                follows = {e["key"]: e for e in self.exposures.get_exposures(user_id)}
            except Exception as e:
                logger.warning(f"[Recap] exposures unavailable: {type(e).__name__}: {e}")
        for i in items:
            hit = next((e for e in i.get("entities") or [] if e["key"] in follows), None)
            i["marks"] = {"follows": hit["name"] if hit else None,
                          "in_your_topics": float(topics.get(i.get("topic")) or 0.0) >= 0.8,
                          "seen": bool(read & set(i.get("member_ids") or [i["article_id"]]))}
            if hit:
                role = follows[hit["key"]].get("role") or "follows"
                i["explanation"] = f"You {c.role_phrases.get(role, 'follow')} {hit['name']}"
                i["explanation_parts"] = {"kind": "direct", "seed_name": hit["name"], "role": role}
            elif i["marks"]["in_your_topics"]:
                i["explanation"] = f"In your topics · {i['explanation']}"
            i.update(counts.get(i["article_id"], {}))
        out = {k: v for k, v in doc.items() if k not in ("excluded", "pinned")}
        for k in ("start", "end", "ready_at", "generated_at"):
            out[k] = scoring.parse_ts(out.get(k))
        return {**out, "items": items, "latest": period["latest"], "next_at": period["next_at"],
                "served_at": self.clock()}

    def get_recap(self, kind: str, tz: Optional[str] = None, period: Optional[str] = None,
                  user_id: Optional[str] = None) -> Dict:
        """
        The daily / weekly recap of `period` (default: the newest ready one) in `tz`: the stored version, built on
        first request (or by the job) and frozen from then on.
        """
        tz_name, z = self._recap_zone(tz, user_id)
        p = self._recap_period(kind, period, z, self.clock())
        doc = self.logs.get_recap(kind, p["key"], tz_name)
        if doc is None or self._recap_outdated(doc, p):
            doc = self._build_recap(kind, p, z, tz_name, doc)
        return self._recap_out(doc, p, user_id)

    def rebuild_recap(self, kind: str, period: Optional[str] = None, tz: Optional[str] = None,
                      exclude: Optional[List[str]] = None, pin: Optional[List[str]] = None) -> Dict:
        """Editor's override: a new version now, with these exclusions / pins (None keeps the current lists)."""
        tz_name, z = self._recap_zone(tz)
        p = self._recap_period(kind, period, z, self.clock())
        doc = self._build_recap(kind, p, z, tz_name, self.logs.get_recap(kind, p["key"], tz_name), exclude, pin)
        return self._recap_out(doc, p, None)

    def run_recap(self, kind: str) -> Dict:
        """The recap jobs' body: build the newest period in cfg.tz unless it is stored and current."""
        tz_name, z = self._recap_zone(None)
        p = self._recap_period(kind, None, z, self.clock())
        doc = self.logs.get_recap(kind, p["key"], tz_name)
        built = doc is None or self._recap_outdated(doc, p)
        if built:
            doc = self._build_recap(kind, p, z, tz_name, doc)
        return {"period": p["key"], "tz": tz_name, "built": built, "version": doc["version"],
                "items": len(doc["items"]), "articles": doc["coverage"]["articles"],
                "limited": doc["coverage"]["limited"], "overview": bool((doc.get("overview") or {}).get("text"))}

    # ── O. Insights (personalization/insights.py) ────────────

    def _insight_fallback(self, pick: Dict, reason: str, model: Optional[str], dropped: int = 0) -> Dict:
        return {"content": {"what_happened": insight_rules.fallback_what(pick, self.cfg), "why_it_matters": [],
                            "scenarios": [], "watch_next": [], "actions": []},
                "analysis": {"status": "fallback", "reason": reason, "model": model, "dropped": dropped}}

    def _analyse_story(self, pick: Dict, articles: List[Dict]) -> Dict:
        """
        {content, analysis}: the LLM's analysis of one story, validated and fact-checked; asked once more when it
        fails, then served without scenarios (status "partial") or as the lead's own summary ("fallback").
        """
        c = self.cfg
        client, model = self._recap_client()
        if client is None:
            return self._insight_fallback(pick, "no_llm_client", None)
        retry, best, dropped, failure = None, None, 0, "unparseable_response"
        for _ in range(max(1, c.insights_attempts)):
            try:
                response = client.chat.completions.create(
                    model=model, messages=insight_rules.messages(pick["topic"], articles, c, retry),
                    response_format={"type": "json_object"}, temperature=c.render_temperature,
                    max_tokens=c.insights_max_tokens, extra_body=c.render_llm_extra)
                parsed = insight_rules.parse(response.choices[0].message.content, len(articles), c)
            except Exception as e:
                logger.error(f"[Insights] {pick['story_id']} failed ({model}): {type(e).__name__}: {e}")
                failure = f"llm_error: {type(e).__name__}"
                break
            checked, gone = insight_rules.fact_check(parsed, articles, c) if parsed else (None, [])
            dropped += len(gone) + len((parsed or {}).get("invalid") or [])
            ok, why = insight_rules.usable(checked, c)
            if checked and checked["what_happened"] and (
                    best is None or len(checked["scenarios"]) > len(best["scenarios"])):
                best = checked
            if ok:
                return {"content": insight_rules.cite_ids(checked, articles, c),
                        "analysis": {"status": "ok", "reason": None, "model": model, "dropped": dropped}}
            failure = "unparseable_response" if checked is None else "fact_check"
            retry = why
            logger.warning(f"[Insights] {pick['story_id']} rejected: {why} {[g['added'] for g in gone]}")
        if best is None:
            return self._insight_fallback(pick, failure, model, dropped)
        # "what happened" held up but the scenarios didn't: keep the facts, show no scenarios
        content = insight_rules.cite_ids({**best, "scenarios": []}, articles, c)
        return {"content": content, "analysis": {"status": "partial", "reason": failure, "model": model,
                                                 "dropped": dropped}}

    def _insight_fresh(self, cached: Optional[Dict], pick: Dict, now: datetime) -> bool:
        """
        The cached analysis serves while the story's articles are unchanged; one made without a complete LLM
        analysis is tried again after insights_retry_min.
        """
        if not cached or cached.get("members_hash") != insight_rules.members_hash(pick):
            return False
        if cached["analysis"]["status"] == "ok":
            return True
        made = scoring.parse_ts(cached["analysis"].get("generated_at"))
        return bool(made) and now - made < timedelta(minutes=self.cfg.insights_retry_min)

    def _insight_analyses(self, picks: List[Dict], articles: Dict[str, List[Dict]]) -> Dict[str, Dict]:
        """story_id → its cache doc; the stale and missing ones are analysed (in parallel) and stored."""
        c, now = self.cfg, self.clock()
        cached = self.logs.insights_get([p["story_id"] for p in picks], c.insights_prompt_version)
        todo = [p for p in picks if not self._insight_fresh(cached.get(p["story_id"]), p, now)]
        if len(todo) > 1 and c.insights_llm_workers > 1:
            from concurrent.futures import ThreadPoolExecutor
            with ThreadPoolExecutor(max_workers=min(c.insights_llm_workers, len(todo))) as pool:
                made = list(pool.map(lambda p: self._analyse_story(p, articles[p["story_id"]]), todo))
        else:
            made = [self._analyse_story(p, articles[p["story_id"]]) for p in todo]
        for p, result in zip(todo, made):
            # no actions from the analysis (or none at all without the LLM): Agent 4's recommendations stand in
            if not result["content"].get("actions"):
                result["content"]["actions"] = insight_rules.fallback_actions(articles[p["story_id"]], c)
            prev = cached.get(p["story_id"]) or {}
            doc = {"story_id": p["story_id"], "prompt_version": c.insights_prompt_version,
                   "members_hash": insight_rules.members_hash(p), "member_ids": p["member_ids"],
                   "article_ids": [d[c.id_field] for d in articles[p["story_id"]]],
                   "source_count": len(p["outlets"]), "version": int(prev.get("version") or 0) + 1,
                   "content": result["content"], "analysis": {**result["analysis"], "generated_at": now}}
            try:
                self.logs.insights_put(doc)
            except Exception as e:
                logger.warning(f"[Insights] cache write failed: {type(e).__name__}: {e}")
            cached[p["story_id"]] = doc
        return cached

    def _insight_out(self, pick: Dict, doc: Dict, articles: List[Dict], names: Dict[str, str],
                     follow_keys: set, watch: Optional[Dict]) -> Dict:
        """One Insight for the app: the shared analysis plus this reader's link to it and their watch."""
        c = self.cfg
        lead = pick["lead"]
        image = ((lead.get("media") or {}).get("primary_image") or {}).get("url")
        sources = [{"article_id": d[c.id_field], "source_name": d.get(c.source_field),
                    "title": d.get(c.title_field) or "", "url": d.get(c.url_field),
                    "published_at": d.get(c.published_field)} for d in articles[: c.insights_sources_shown]]
        entities = [{"key": k, "name": names.get(k, k.title()), "followed": k in follow_keys}
                    for k in pick["keys"][:6]]
        out_watch = {"watching": False, "since": None, "new_sources": 0, "changed": False}
        if watch:
            out_watch = {"watching": True, "since": scoring.parse_ts(watch.get("since")),
                         "new_sources": max(0, len(pick["outlets"]) - int(watch.get("sources_at") or 0)),
                         "changed": int(doc.get("version") or 1) > int(watch.get("version_at") or 0)}
        content = doc["content"]
        return {
            "story_id": pick["story_id"], "lead_article_id": lead[c.id_field], "rank": pick["rank"],
            "topic": pick["topic"], "title": lead.get(c.title_field) or "", "image_url": image,
            "first_seen": pick["first_t"], "last_updated": max(pick["times"]), "span_days": pick["span_days"],
            "source_count": len(pick["outlets"]), "article_count": len(pick["member_ids"]),
            "what_happened": content["what_happened"], "why_it_matters": content["why_it_matters"],
            "for_you": insight_rules.for_you(pick, names, c), "scenarios": content["scenarios"],
            "watch_next": content["watch_next"], "actions": content.get("actions") or [],
            "entities": entities, "sources": sources,
            "analysis": {**doc["analysis"], "generated_at": scoring.parse_ts(doc["analysis"].get("generated_at")),
                         "version": int(doc.get("version") or 1)},
            "watch": out_watch, "disclaimer": insight_rules.DISCLAIMER,
        }

    def get_insights(self, user_id: str) -> Dict:
        """
        The reader's developing stories with their analysis (shared, cached per story) and the per-reader parts:
        why it matters to them, their watches, and what changed this week for each thing they follow.
        """
        c, now = self.cfg, self.clock()
        persona = self._require_persona(user_id)
        _, z = self._recap_zone(None, user_id)
        try:
            follows = self.exposures.get_exposures(user_id)
        except Exception as e:
            logger.warning(f"[Insights] exposures unavailable: {type(e).__name__}: {e}")
            follows = []
        follow_keys = {f["key"] for f in follows}
        pi = {e["entity"]: e for e in persona.get("pi_topk") or []}
        aliases = self.logs.alias_map()

        # two weeks for the follows' "this week vs last week"; the stories come from the last insights_window_h
        proj = {**self._recap_projection(), "action_recommendation": 1, "action_rec": 1}
        docs = {d[c.id_field]: d for d in self.articles.by_time(now - timedelta(days=14), now + timedelta(hours=1), proj)}
        times = {a: v for a, v in recap_rules.effective_times(list(docs.values()), c).items() if v[0] <= now}
        keys_by_id = {a: candidates.resolve_keys(candidates.doc_entity_keys(d, c), aliases) for a, d in docs.items()}
        start = now - timedelta(hours=c.insights_window_h)
        window = [d for a, d in docs.items() if a in times and times[a][0] >= start]
        stories = recap_rules.build_stories(window, times, c)
        picks = insight_rules.select(stories, docs, keys_by_id, z, c, follow_keys, pi)
        articles = {p["story_id"]: insight_rules.source_articles(p, docs, times, c) for p in picks}
        cache = self._insight_analyses(picks, articles)

        member_docs = {a: docs[a] for p in picks for a in p["member_ids"] if a in docs}
        names = self._display_names(user_id, member_docs, [p["pi_hit"] for p in picks if p.get("pi_hit")])
        try:
            watches = self.logs.watches_for(user_id, [p["story_id"] for p in picks])
        except Exception as e:
            logger.warning(f"[Insights] watches unavailable: {type(e).__name__}: {e}")
            watches = {}
        items = [self._insight_out(p, cache[p["story_id"]], articles[p["story_id"]], names, follow_keys,
                                   watches.get(p["story_id"])) for p in picks]
        developing: Dict[str, str] = {}
        for p in picks:
            for k in p["keys"]:
                developing.setdefault(k, p["story_id"])
        return {
            "user_id": user_id, "generated_at": now, "window_h": c.insights_window_h,
            "personalized": any(i["for_you"] for i in items), "persona_version": persona.get("persona_version"),
            "insights": items,
            "follows": insight_rules.follow_changes(follows, list(docs.values()), keys_by_id, times, now, c,
                                                    developing),
        }

    def watch_insight(self, user_id: str, story_id: str) -> Dict:
        """Alert me if this changes: remember the story's outlets and analysis version as of now."""
        self._require_persona(user_id)
        doc = self.logs.insights_get([story_id], self.cfg.insights_prompt_version).get(story_id)
        if doc is None:
            raise InsightNotFound(f"no insight for story {story_id}")
        now = self.clock()
        self.logs.watch_put({"user_id": user_id, "story_id": story_id, "since": now,
                             "sources_at": int(doc.get("source_count") or 0),
                             "version_at": int(doc.get("version") or 1)})
        return {"story_id": story_id, "watching": True, "since": now}

    def unwatch_insight(self, user_id: str, story_id: str) -> Dict:
        self._require_persona(user_id)
        self.logs.watch_delete(user_id, story_id)
        return {"story_id": story_id, "watching": False, "since": None}

    @staticmethod
    def _risk(doc: Dict) -> Optional[Dict]:
        """Agent 4's risk fields; reasoning factors renamed to the app's labels."""
        if doc.get("risk_score") is None:
            return None
        r = doc.get("risk_reasoning") or {}
        out = {"score": doc["risk_score"], "level": doc.get("risk_level"),
               "action_recommendation": doc.get("action_recommendation") or doc.get("action_rec")}
        if r:
            out["reasoning"] = {"severity": r.get("event_severity"), "prominence": r.get("entity_salience"),
                                "urgency": r.get("temporal_urgency"), "base_weight": r.get("domain_criticality")}
        return out

    def story(self, article_id: str, user_id: Optional[str] = None) -> Dict:
        """
        One article in full: summaries, risk, related stories (its cluster, then articles sharing its top entities)
        and, with a user, why it matters to them (their best exposure hits in the article).
        """
        c = self.cfg
        docs = self.articles.by_ids([article_id], self._story_projection(
            "summary_long", "body", c.risk_field, "risk_reasoning", "action_recommendation", "action_rec"))
        if not docs:
            raise ArticleNotFound(f"article {article_id} not found")
        doc = docs[0]

        personal = None
        if user_id:
            persona = self._require_persona(user_id)
            keys = candidates.resolve_keys(candidates.doc_entity_keys(doc, c), self.logs.alias_map())
            pi = {e["entity"]: e for e in persona.get("pi_topk") or []}
            hits = slate.pi_hits(keys, pi)[:3]
            if hits:
                names = self._display_names(user_id, {article_id: doc}, hits)
                m = (doc.get("materiality") or {}).get("m")
                need, _ = slate.need(keys, m, pi)
                parts = self._app_parts({"kind": "hop" if hits[0]["path"]["relations"] else "direct",
                                         "entity": hits[0]["entity"], "path": hits[0]["path"],
                                         "also": explain.also_hits(hits, c)}, doc.get(c.topic_field), names)
                personal = {"explanation": f"{explain.why_exposure(hits[0], c, names)} "
                                           f"{explain.why_need(need, m, hits, c, names)}",
                            "also": parts.get("also", []), "parts": parts}

        related = [d for d in (self.articles.cluster_members(doc["cluster_id"], self._story_projection())
                               if doc.get("cluster_id") else []) if d[c.id_field] != article_id]
        keys = (doc.get("entity_keys") or self._top_entity_keys(doc))[:3]
        if len(related) < c.related_max and keys:
            seen = {article_id, *(d[c.id_field] for d in related)}
            related += [d for d in self.articles.with_entity_keys(keys, c.related_max * 2, self._story_projection())
                        if d[c.id_field] not in seen]
        return self._story_item(doc, summary_long=doc.get("summary_long"), risk=self._risk(doc), personal=personal,
                                related=[self._story_item(d) for d in related[: c.related_max]])

    def comments(self, article_id: str, limit: int = 50) -> List[Dict]:
        """An article's comments, newest first."""
        if not self.articles.by_ids([article_id], {"_id": 0, self.cfg.id_field: 1}):
            raise ArticleNotFound(f"article {article_id} not found")
        return [self._comment_out(d) for d in self.logs.comments_for(article_id, min(limit, self.cfg.comments_page_max))]

    def add_comment(self, article_id: str, user_id: str, text: str) -> Dict:
        """A reader's comment on an article, shown under their profile name."""
        c = self.cfg
        text = re.sub(r"\s+", " ", text or "").strip()
        if not text:
            raise InvalidInput("text is empty")
        if len(text) > c.comment_max_chars:
            raise InvalidInput(f"text is longer than {c.comment_max_chars} characters")
        persona = self._require_persona(user_id)
        if not self.articles.by_ids([article_id], {"_id": 0, c.id_field: 1}):
            raise ArticleNotFound(f"article {article_id} not found")
        doc = self.logs.add_comment({"comment_id": str(uuid.uuid4()), "article_id": article_id, "user_id": user_id,
                                     "author_name": persona.get("name") or "Reader", "text": text, "t": self.clock()})
        return self._comment_out(doc)

    @staticmethod
    def _comment_out(doc: Dict) -> Dict:
        t = doc["t"]
        if isinstance(t, datetime) and t.tzinfo is None:      # Mongo returns naive UTC
            t = t.replace(tzinfo=timezone.utc)
        return {"comment_id": doc["comment_id"], "article_id": doc["article_id"], "user_id": doc["user_id"],
                "author_name": doc.get("author_name"), "text": doc["text"], "created_at": t}

    def cluster_sources(self, article_id: str) -> List[Dict]:
        """Every outlet's version of the article's story (its cluster), oldest first."""
        c = self.cfg
        proj = self._story_projection()
        docs = self.articles.by_ids([article_id], proj)
        if not docs:
            raise ArticleNotFound(f"article {article_id} not found")
        members = self.articles.cluster_members(docs[0]["cluster_id"], proj) if docs[0].get("cluster_id") else docs
        epoch = datetime.min.replace(tzinfo=timezone.utc)
        members.sort(key=lambda d: (scoring.parse_ts(d.get(c.published_field)) or epoch, d[c.id_field]))
        return [{"article_id": d[c.id_field], "source_name": d.get(c.source_field), "title": d.get(c.title_field),
                 "published_at": d.get(c.published_field), "url": d.get(c.url_field),
                 "first_report": d.get("first_report") == d[c.id_field]} for d in members]

    def saved(self, user_id: str) -> List[Dict]:
        """Saved stories (latest save/unsave feedback per article), most recently saved first."""
        c = self.cfg
        self._require_persona(user_id)
        ids = self.logs.saved_ids(user_id)
        docs = {d[c.id_field]: d for d in self.articles.by_ids(ids, self._story_projection())}
        return [self._story_item(docs[a]) for a in ids if a in docs]

    def search(self, q: str, topic: Optional[str] = None) -> Dict:
        """Stories whose title, summary or entities match the query words: most words matched first, then newest."""
        c = self.cfg
        terms = sorted(clustering.title_tokens(q))
        if not terms:
            raise InvalidInput("q has no searchable words")
        docs = self.articles.search(terms, topic, c.story_search_scan, self._story_projection())
        items = []
        for d in docs:                                      # newest first; the sort below is stable
            hay = " ".join([d.get(c.title_field) or "", d.get("summary_short") or "",
                            *(e.get(c.entity_name_key) or "" for e in d.get(c.entities_field) or [])]).lower()
            matched = [t for t in terms if t in hay]
            if matched:
                items.append({**self._story_item(d), "matched_terms": matched})
        items.sort(key=lambda i: -len(i["matched_terms"]))
        return {"items": items[: c.story_search_limit], "next_cursor": None}

    def query_agent(self):
        if self._query_agent is None:
            self._query_agent = self._query_agent_factory()
        return self._query_agent

    def ask(self, query: str, domain: Optional[str] = None, context_article_id: Optional[str] = None) -> Dict:
        """Agent 5 (RAG over the stored articles); `context_article_id` scopes the question to that story."""
        c = self.cfg
        query = (query or "").strip()
        if not query:
            raise InvalidInput("query is empty")
        question = query
        if context_article_id:
            docs = self.articles.by_ids([context_article_id], {"_id": 0, c.title_field: 1})
            if docs and docs[0].get(c.title_field):
                question = f"{query} (about: {docs[0][c.title_field]})"
        try:
            res = self.query_agent().process(question, domain_filter=domain, top_k=5)
        except Exception as e:
            raise StoreUnavailable(f"Ask is unavailable: {type(e).__name__}") from e
        sources = res.get("sources") or []
        docs = {d[c.id_field]: d for d in self.articles.by_ids(
            [s["article_id"] for s in sources], {"_id": 0, c.id_field: 1, c.source_field: 1, c.published_field: 1})}
        return {
            "query": query,
            "answer": res.get("answer") if sources else None,     # no sources → no grounded answer
            "sources": [{**s, "source_name": docs.get(s["article_id"], {}).get(c.source_field),
                         "published_at": docs.get(s["article_id"], {}).get(c.published_field)} for s in sources],
            "confidence": res.get("confidence") or 0.0,
        }

    # ── C/D. Clustering + materiality ────────────────────────

    def vector_store(self):
        if self._vectors is None:
            from storage.pers_vector_store import PersVectorStore
            self._vectors = PersVectorStore(self.cfg)
        return self._vectors

    def _materiality(self, doc: Dict, size: int, is_first: bool, now: datetime) -> Dict:
        return {**materiality.materiality(doc, size, is_first, self.cfg),
                "risk_seen_at": doc.get("risk_processed_at"), "computed_at": now}

    def sync_vectors(self, now: Optional[datetime] = None) -> int:
        """Embed every article that isn't in the personalization index yet. Returns rows added."""
        c, vectors = self.cfg, self.vector_store()
        indexed = vectors.indexed_article_ids()
        missing = [a for a in self.articles.all_ids() if a not in indexed]
        if not missing:
            return 0
        added = vectors.sync_from_mongo(self.articles.docs_for_embedding(missing))
        now_indexed = vectors.indexed_article_ids()
        self.articles.mark_indexed([a for a in missing if a in now_indexed], now or self.clock())
        if added < len(missing):
            logger.warning(f"[Personalization] {len(missing) - added} articles could not be embedded")
        return added

    def cluster_articles(self, now: Optional[datetime] = None) -> Dict:
        """
        The hourly clustering job body (plan §5): name_lower sync → entity_keys → pers index sync →
        assign window articles without a cluster → rewrite size/first_report of changed clusters →
        materiality for their members and for articles A4 has (re)scored since. Returns stats.
        """
        c = self.cfg
        now = now or self.clock()
        stats: Dict = {"window_h": c.cluster_window_h}

        try:
            stats["name_lower_synced"] = self.exposures.sync_name_lower()
        except Exception as e:  # Neo4j is not needed for clustering itself
            logger.warning(f"[Personalization] sync_name_lower failed: {type(e).__name__}: {e}")
            stats["name_lower_synced"] = None

        window = self.articles.window(c.cluster_window_h, now)
        keys_updates = {}
        for doc in window + self.articles.missing_entity_keys():
            keys = self._top_entity_keys(doc)
            if doc.get("entity_keys") != keys:
                keys_updates[doc[c.id_field]] = keys
                doc["entity_keys"] = keys
        self.articles.set_entity_keys(keys_updates)
        stats["entity_keys_set"] = len(keys_updates)

        stats["vectors_added"] = self.sync_vectors(now)
        vectors = self.vector_store()

        meta = {
            d[c.id_field]: {"article_id": d[c.id_field], "published": d.get(c.published_field),
                            "title": d.get(c.title_field) or "", "entity_keys": d.get("entity_keys") or [],
                            "cluster_id": d.get("cluster_id")}
            for d in window
        }
        new = [m for m in meta.values() if not m["cluster_id"]]
        known = {a: m for a, m in meta.items() if m["cluster_id"]}
        window_vecs = vectors.vectors_for(meta)
        vecs = {m["article_id"]: window_vecs[m["article_id"]] for m in new if m["article_id"] in window_vecs}
        neighbours = {}
        for article_id, vec in vecs.items():
            hits = vectors.search_vector(vec, c.cluster_nn + 1)   # +1: the article itself comes back first
            neighbours[article_id] = [(b, s) for b, s in hits if b != article_id and b in meta][: c.cluster_nn]

        def sim(a: str, b: str) -> Optional[float]:
            if a not in window_vecs or b not in window_vecs:
                return None
            return float(window_vecs[a] @ window_vecs[b])

        ops = clustering.assign_clusters(new, neighbours, known, c, sim=sim)
        for op in ops:
            if op["merge_candidates"]:
                logger.info(f"[Personalization] cluster {op['cluster_id']} also matches "
                            f"{op['merge_candidates']} via {op['article_id']} (not merged)")
        stats.update({
            "window_articles": len(window),
            "new_articles": len(new),
            "without_vector": len(new) - len(vecs),
            "joined": sum(1 for op in ops if not op["created"]),
            "new_clusters": sum(1 for op in ops if op["created"]),
            "merge_candidates": sum(1 for op in ops if op["merge_candidates"]),
        })

        changed = {op["cluster_id"] for op in ops}
        existing = self.articles.get_clusters(list(changed))
        members: Dict[str, set] = {cid: set((existing.get(cid) or {}).get("members") or []) for cid in changed}
        for m in known.values():
            if m["cluster_id"] in changed:
                members[m["cluster_id"]].add(m["article_id"])
        for op in ops:
            members[op["cluster_id"]].add(op["article_id"])

        mat_updates = self._write_clusters(members, now)
        stats["clusters_changed"] = len(members)

        rescored = 0
        for doc in self.articles.rescore_candidates():
            a = doc[c.id_field]
            seen = (doc.get("materiality") or {})
            if a in mat_updates or (seen and seen.get("risk_seen_at") == doc.get("risk_processed_at")):
                continue
            mat_updates[a] = self._materiality(doc, doc.get("cluster_size") or 1, doc.get("first_report") == a, now)
            rescored += 1
        self.articles.set_materiality(mat_updates)
        stats["materiality_written"] = len(mat_updates)
        stats["rescored"] = rescored
        stats["unscored"] = sum(1 for m in mat_updates.values() if m["unscored"])
        return stats

    def _write_clusters(self, members: Dict[str, set], now: datetime) -> Dict[str, Dict]:
        """Upsert each cluster (summary + member fields). Returns the members' new materiality (not yet written)."""
        c = self.cfg
        docs = {d[c.id_field]: d for d in self.articles.by_ids([a for ids in members.values() for a in ids])}
        cluster_docs, mat_updates = [], {}
        for cid, ids in members.items():
            present = sorted(a for a in ids if a in docs)
            if not present:
                continue
            summary = clustering.cluster_summary([
                {"article_id": a, "published": docs[a].get(c.published_field),
                 "entity_keys": docs[a].get("entity_keys") or []} for a in present
            ])
            cluster_docs.append({**summary, "cluster_id": cid, "members": present,
                                 "first_published": scoring.parse_ts(summary["first_published"])})
            for a in present:
                mat_updates[a] = self._materiality(docs[a], summary["size"], a == summary["first_report"], now)
        self.articles.apply_clusters(cluster_docs, now)
        return mat_updates

    def recluster_window(self, now: Optional[datetime] = None) -> Dict:
        """
        One-off: forget the clustering of every article in the window and cluster it again from scratch
        (after a rule or threshold change; the hourly job only assigns new articles). Clusters that also have
        members outside the window keep those members, with size/first_report/materiality recomputed.
        """
        c = self.cfg
        now = now or self.clock()
        window_ids = {d[c.id_field] for d in self.articles.window(
            c.cluster_window_h, now, {"_id": 0, c.id_field: 1, c.published_field: 1})}
        affected = self.articles.clusters_with_members(list(window_ids))
        remainder = {cid: set(cl["members"]) - window_ids for cid, cl in affected.items()}
        self.articles.reset_clusters(list(window_ids), list(affected))
        kept = {cid: ids for cid, ids in remainder.items() if ids}
        self.articles.set_materiality(self._write_clusters(kept, now))
        stats = self.cluster_articles(now)
        stats["reset"] = {"articles": len(window_ids), "clusters_dropped": len(affected),
                          "clusters_kept_outside_window": len(kept)}
        return stats

    # ── L. Metrics / maintenance ─────────────────────────────

    def metrics(self, days: int = 7) -> Dict:
        """GET /admin/metrics: see personalization/metrics.py for the blocks."""
        if days < 1:
            raise InvalidInput("days must be ≥ 1")
        c, now = self.cfg, self.clock()
        window = self.articles.window(c.cand_window_h, now, projection={
            "_id": 0, c.id_field: 1, c.published_field: 1, "cluster_id": 1, "materiality": 1})
        return pers_metrics.collect(self.mongo.db, c, now, days, window, self.logs.current_tau(),
                                    self.personas.count())

    def delete_user(self, user_id: str) -> Dict:
        """Remove a user everywhere: persona, Neo4j user + exposures, and every per-user log row."""
        self._require_persona(user_id)
        purged = self.logs.purge_user(user_id)
        self.exposures.delete_user(user_id)
        self.personas.delete(user_id)
        logger.info(f"[Personalization] Deleted user {user_id}: {purged}")
        return {"user_id": user_id, "deleted": True, "purged": purged}

    # ── Health ───────────────────────────────────────────────

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
            out["jobs"] = {
                job: {"started_at": r["started_at"], "ok": r["ok"], "error": r.get("error")}
                for job, r in self.logs.last_runs().items()
            }
        except Exception as e:
            logger.error(f"[Personalization] Mongo health failed: {e}")
            out["mongo"] = {"ok": False, "error": type(e).__name__}
        out["recent_articles"] = len(recent_ids)

        out["neo4j"] = self.exposures.is_available()

        try:
            store = self.vector_store()
            indexed = store.indexed_article_ids()
            recent_indexed = sum(1 for a in recent_ids if a in indexed)
            out["faiss"] = {                      # the personalization index (plan C5)
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
