"""
MAPNAI — config/personalization.py
Every knob of the personalization engine (PERSONALIZATION_PLAN.md §3).
Loaded from .env the same way as config/settings.py; each field can be overridden
with PERS_<NAME> (e.g. PERS_CAND_WINDOW_H=72). Lists/dicts take JSON values.
"""

from functools import lru_cache
from typing import Dict, List

from pydantic_settings import BaseSettings, SettingsConfigDict

from config.settings import _ENV_FILE


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
    cos_join: float = 0.80
    cos_strong: float = 0.88
    cluster_time_h: int = 36
    min_shared_entities: int = 1

    # ── D. Materiality ───────────────────────────────────────
    w_risk: float = 0.5
    w_size: float = 0.2
    w_first: float = 0.15
    w_cred: float = 0.15
    size_log_base: float = 11.0
    risk_scale_max: float = 100.0
    risk_missing: float = 0.5
    source_cred: Dict[str, float] = {}
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

    # ── I. Feedback / τ / proposals ──────────────────────────
    feedback_types: List[str] = ["open", "more", "less", "dwell", "save", "needed", "not_needed", "missed"]
    tau_step: float = 0.05
    miss_target: float = 0.1
    tau_min: float = 0.05
    tau_max: float = 0.6
    tau_window_d: int = 7
    proposal_min_articles: int = 3
    proposal_min_theta: float = 0.7
    proposal_window_d: int = 7

    # ── J. Alerts ────────────────────────────────────────────
    alert_min_need: float = 0.5
    alert_min_m: float = 0.6
    alert_lookback_h: int = 48

    # ── K. Render ────────────────────────────────────────────
    render_prompt_version: str = "r1"
    render_max_tokens: int = 400
    render_source_chars: int = 600

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
