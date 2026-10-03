"""
MAPNAI — config/personalization.py
Every knob of the personalization engine (PERSONALIZATION_PLAN.md §3).
Loaded from .env the same way as config/settings.py; each field can be overridden
with PERS_<NAME> (e.g. PERS_CAND_WINDOW_H=72). Lists/dicts take JSON values.
"""

import json
from functools import lru_cache
from pathlib import Path
from typing import Dict, List

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from config.settings import _ENV_FILE

_SOURCE_CRED_FILE = Path(__file__).resolve().parent / "source_credibility.json"


def _load_source_cred() -> Dict[str, float]:
    """config/source_credibility.json {"tiers": {"0.8": [source_name, ...], ...}} → {source_name: 0.8}."""
    try:
        tiers = json.loads(_SOURCE_CRED_FILE.read_text(encoding="utf-8"))["tiers"]
    except FileNotFoundError:
        return {}
    return {name: float(tier) for tier, names in tiers.items() for name in names}


class PersonalizationSettings(BaseSettings):
    # ── Toggles ──────────────────────────────────────────────
    enable_hop2: bool = True
    enable_mmr: bool = True
    enable_calibration: bool = True
    enable_explore: bool = True
    enable_alerts: bool = True
    enable_render: bool = True
    enable_proposals: bool = True
    scheduler_enabled: bool = True
    policy_version: str = "v2.0"
    tz: str = "Asia/Kolkata"

    # ── processed_articles field names (PERSONALIZATION_CONTEXT.md §2) ──
    articles_collection: str = "processed_articles"
    id_field: str = "article_id"
    title_field: str = "title"
    topic_field: str = "domain"
    topic_exclude: List[str] = ["other"]
    url_field: str = "url"
    source_field: str = "source_name"
    published_field: str = "published_at"
    entities_field: str = "entities"
    entity_name_key: str = "name"
    entity_salience_key: str = "salience"
    risk_field: str = "risk_score"
    a4_facts_field: str = ""

    # ── Mongo collections ────────────────────────────────────
    personas_collection: str = "personas"
    aliases_collection: str = "entity_aliases"
    feedback_collection: str = "feedback"
    impressions_collection: str = "impressions"
    clusters_collection: str = "clusters"
    digests_collection: str = "digests"
    thresholds_collection: str = "thresholds"
    proposals_collection: str = "proposals"
    alerts_collection: str = "alerts"
    render_cache_collection: str = "render_cache"
    job_runs_collection: str = "job_runs"
    job_lease_s: int = 3600

    # ── Neo4j labels / properties ────────────────────────────
    user_label: str = "User"
    entity_label: str = "Entity"
    exposure_rel: str = "EXPOSED_TO"
    entity_name_prop: str = "name"

    # ── Personalization FAISS index (separate from the pipeline's) ──
    pers_faiss_index_path: str = "./data/pers_faiss_index"
    pers_faiss_metadata_path: str = "./data/pers_faiss_metadata.pkl"

    # ── A. Profile ───────────────────────────────────────────
    roles: List[str] = ["owns", "depends_on", "operates_in", "regulated_by", "covers", "follows"]
    # "You {phrase} {entity}" — used by profile sentences and why lines
    role_phrases: Dict[str, str] = {
        "owns": "own",
        "depends_on": "depend on",
        "operates_in": "operate in",
        "regulated_by": "are regulated by",
        "covers": "cover",
        "follows": "follow",
    }
    weight_levels: Dict[str, int] = {"low": 1, "medium": 2, "high": 3}
    topics_universe: List[str] = [
        "sports", "entertainment_movies", "finance", "geopolitics",
        "technology", "health", "supply_chain",
    ]
    style_options: Dict[str, List[str]] = {
        "tone": ["plain", "analyst"],
        "length": ["short", "medium"],
        "jargon": ["low", "high"],
    }
    style_defaults: Dict[str, str] = {"tone": "plain", "length": "short", "jargon": "low"}
    history_keep: int = 200
    search_limit: int = 10
    prior_strength: float = 3.0          # α = 1 + 3w, β = 1 + 3(1 − w)
    alert_prefs_default: Dict = {
        "max_per_day": 3, "quiet_start": "22:00", "quiet_end": "07:00", "tz": "Asia/Kolkata",
    }
    onboarding_headlines: int = 10
    onboarding_max_items: int = 50

    # ── B. Spread ────────────────────────────────────────────
    rel_weights: Dict[str, float] = {
        "SUBSIDIARY_OF": 0.5, "SUPPLIES": 0.3, "CUSTOMER_OF": 0.3, "REGULATES": 0.4,
        "SECTOR_PEER": 0.2, "LOCATED_IN": 0.15, "CO_MENTION": 0.1, "UNKNOWN": 0.1,
    }
    rel_type_map: Dict[str, str] = {"MENTIONED_WITH": "CO_MENTION"}
    rel_labels: Dict[str, str] = {"CO_MENTION": "often mentioned with"}
    hop1_top: int = 20
    hop2_top: int = 10
    hop2_decay: float = 0.5
    pi_topk_max: int = 500

    # ── C. Clustering ────────────────────────────────────────
    cluster_window_h: int = 48
    cluster_nn: int = 20
    # calibrated by scripts/calibrate_clustering.py on tests/data/cluster_pairs.jsonl (63 pairs, 2026-09-29):
    # precision .923 / recall .522; no threshold in [.70, .82] reached the .95 precision target
    cos_join: float = 0.77
    cos_strong: float = 0.88             # no-evidence override
    cluster_time_h: int = 36
    fuzzy_entity_min: float = 88.0       # rapidfuzz ratio on normalized entity names
    title_jaccard_min: float = 0.25      # title-token Jaccard, stopwords removed
    chain_margin: float = 0.05           # mean similarity to the cluster's members ≥ cos_join − chain_margin

    # ── D. Materiality ───────────────────────────────────────
    w_risk: float = 0.5
    w_size: float = 0.2
    w_first: float = 0.15
    w_cred: float = 0.15
    size_log_base: float = 11.0
    risk_scale_max: float = 100.0
    source_cred: Dict[str, float] = Field(default_factory=lambda: _load_source_cred())
    source_cred_default: float = 0.5

    # ── E. Interest ──────────────────────────────────────────
    short_window_h: int = 72
    short_half_life_h: float = 24.0
    long_window_d: int = 60
    long_half_life_d: float = 21.0
    lf_short_w: float = 0.4
    lf_long_w: float = 0.6
    w_lf: float = 0.5
    w_topic: float = 0.3
    w_entity: float = 0.2
    beta_top_entities: int = 3
    beta_deltas: Dict[str, List[float]] = {
        "more": [1, 0], "less": [0, 1], "open": [0.5, 0], "dwell": [0.5, 0],
    }
    dwell_min_s: float = 15.0
    history_w: Dict[str, float] = {"open": 1, "save": 2, "more": 2, "dwell": 1, "onboarding": 1}

    # ── F. Candidates ────────────────────────────────────────
    cand_window_h: int = 48
    r2_window_h: int = 24
    r2_top: int = 20
    r3_per_item: int = 30
    r3_history_items: int = 10
    r4_per_topic: int = 30
    recency_half_life_h: float = 24.0
    rrf_k: int = 60
    fused_top: int = 200

    # ── G. Slate ─────────────────────────────────────────────
    slate_k: int = 10
    tau_init: float = 0.2
    must_know_max: int = 5
    mmr_lambda: float = 0.7
    need_bonus: float = 0.3
    per_topic_cap: int = 3
    explore_slots: int = 1
    propensity_sims: int = 200

    # ── H. Why lines ─────────────────────────────────────────
    why_also_max: int = 2                # "(also: X 0.22)" lists up to this many other exposure hits …
    why_also_min_share: float = 0.01     # … whose share of the best path's pi rounds to at least 0.01
    why_min_lf: float = 0.3              # "Similar to <read article>" only from this late-fusion similarity up
    why_min_need_lift: float = 0.01      # for_you: name the exposure only if need_bonus · need adds this much to rel

    # ── I. Feedback / τ / proposals ──────────────────────────
    feedback_types: List[str] = ["open", "more", "less", "dwell", "save", "unsave", "share", "needed", "not_needed",
                                 "missed"]
    read_feedback_types: List[str] = ["open", "more", "save", "dwell"]      # these mark an article as read
    # τ ← clip(τ − tau_step·(miss_rate − miss_target), tau_min, tau_max), miss_rate = missed / (missed + needed)
    # over the last tau_window_d days; `needed` counts only on an article served in tau_section
    tau_step: float = 0.05
    miss_target: float = 0.1
    tau_min: float = 0.05
    tau_max: float = 0.6
    tau_window_d: int = 7
    tau_section: str = "must_know"
    # engagement proposals: an entity in the top entities of ≥ proposal_min_articles distinct engaged articles
    # (read_feedback_types; dwell only from dwell_min_s) in proposal_window_d days, with θ_entity ≥ proposal_min_theta
    proposal_min_articles: int = 3
    proposal_min_theta: float = 0.7
    proposal_window_d: int = 7
    proposal_role: str = "follows"
    proposal_medium_theta: float = 0.85  # suggested weight: medium from this θ up, else low
    proposal_max_per_user: int = 3       # new proposals per user per run
    # A4-fact proposals (inactive while a4_facts_field is ""). Facts: [{type, subject, object}] (names).
    # type → [side that must be one of the user's exposures, role suggested for the entity on the other side]
    a4_fact_rules: Dict[str, List[str]] = {
        "acquisition": ["subject", "owns"],        # your company acquires X → you own X
        "supplier": ["object", "depends_on"],      # X supplies your company → you depend on X
        "sanction": ["object", "regulated_by"],    # X sanctions your company → you are regulated by X
    }

    # ── J. Alerts ────────────────────────────────────────────
    # fire when need ≥ alert_min_need ∧ m ≥ alert_min_m, for articles published in the last alert_lookback_h;
    # at most one alert per (user, cluster) and alert_prefs.max_per_day per local day, deferred past quiet hours
    alert_min_need: float = 0.5
    alert_min_m: float = 0.6
    alert_lookback_h: int = 48
    alert_major_m: float = 0.8           # the app labels an alert Major from this materiality up, else High

    # ── K. Render ────────────────────────────────────────────
    render_prompt_version: str = "r2"    # part of the cache key: bump it when the prompt or style rules change
    # r2: r1's analyst tone ("… and what it implies") and "3-5 sentences" made the model pad short sources with
    # conclusions the text doesn't state; the length is now a maximum and implications are ruled out
    # the shared Groq client's built-in llama-3.3-70b-versatile is no longer served (404 on 2026-09-29);
    # gpt-oss-120b kept numbers and names in a trial where gpt-oss-20b copied the text and qwen3 respelled numbers
    render_model: str = "openai/gpt-oss-120b"
    render_llm_extra: Dict = {"reasoning_effort": "low"}   # gpt-oss reasons first; its tokens count in max_tokens
    render_temperature: float = 0.2
    render_max_tokens: int = 800
    render_source_chars: int = 600

    # ── M. App views ─────────────────────────────────────────
    feed_page_max: int = 30
    related_max: int = 5                 # story page: related stories (cluster mates, then shared entities)
    story_search_scan: int = 200         # newest matching articles ranked per search
    story_search_limit: int = 30

    # ── L. Jobs (cron, in tz) ────────────────────────────────
    job_pi_topk: str = "0 1 * * *"
    job_cluster: str = "5 * * * *"
    job_alerts: str = "*/5 * * * *"
    job_tau: str = "30 2 * * *"
    job_proposals: str = "0 3 * * mon"
    job_digests: str = "30 5 * * *"

    model_config = SettingsConfigDict(
        env_prefix="PERS_",
        env_file=str(_ENV_FILE),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


@lru_cache()
def get_pers_settings() -> PersonalizationSettings:
    """Cached singleton personalization settings."""
    return PersonalizationSettings()


pers_settings = get_pers_settings()
