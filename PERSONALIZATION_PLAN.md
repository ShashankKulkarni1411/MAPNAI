# PERSONALIZATION_PLAN.md (v2)

This is the design for the full personalization spec (sections A–L). It replaces the earlier, smaller plan, which is
kept as `PERSONALIZATION_PLAN.v1.md`. It contains no implementation code.

The plan is based on `PERSONALIZATION_CONTEXT.md`, the v1 code already in the working tree, and a live re-check done
on 2026-09-29.

## 0. Starting point

### 0.1 Live state has changed since PERSONALIZATION_CONTEXT.md

| Item | Context file said | Now |
|---|---|---|
| Neo4j | empty | Backfilled by `scripts/backfill_neo4j.py`. Nodes: `Article` 955, `Entity` 3144, `Source` 80, `Domain` 3, `User` 1. Relationships: `MENTIONS` 4556, `MENTIONED_WITH` 12467 (`count` min 1 / max 9 / avg 1.07), `BELONGS_TO` 955, `PUBLISHED_BY` 955, `EXPOSED_TO` 6 |
| `:Entity` props | — | `name`, `type`, `frequency`, `first_seen`, `last_seen` (518), `created_by` (1). There are **no id, alias or ticker properties** |
| Mongo | `processed_articles`, `ingestion_runs` | plus `personas` (1 demo doc, v1 shape: `{user_id, name, topics, history, created_at}`) |
| FAISS `data/faiss_index` | stale (687 rows, 0 in Mongo) | **unchanged, still stale** |
| A4 | 0 scored | **still 0 scored**, so `risk_score` is null everywhere |
| py -3.10 | no pymongo/neo4j | pymongo 4.18.2, neo4j 6.3.1, fastapi 0.115.0, uvicorn, pytest 8.4 installed. **apscheduler, groq and mongomock are missing.** openai 2.44 is present, which is enough for Groq through `utils.groq_client.init_groq_llm` |

### 0.2 v1 code already in the tree (uncommitted)

- `config/personalization.py`, `personalization/{scoring,service}.py`, `storage/{exposure_store,persona_store}.py`,
  `api/{app,personalization_router}.py`, `run_api.py` and `scripts/backfill_neo4j.py`.
- Additive methods: `FAISSStore.indexed_article_ids`, `MongoStore.get_articles_published_since`.
- `requirements.txt`: adds fastapi and uvicorn.

v2 **keeps** these conventions: `PERS_` env prefix, pydantic-settings, `_ident()` guarded Cypher labels, stores that
wrap the existing `MongoStore`/`Neo4jStore` lazy connections, a pure `scoring` module, and the service error →
HTTP status mapping.

v2 **changes** these parts of v1, which is safe because v1 was never committed:
- the config knobs;
- the persona shape (upgraded lazily, see §2.2);
- free-text exposures that create new `:Entity` nodes (replaced by picked canonical keys);
- `PUT /topics` (becomes `PATCH`).

### 0.3 Where the spec conflicts with the code, and the adaptations

| # | Spec | Code / data reality | Smallest adaptation |
|---|---|---|---|
| C1 | `EXPOSED_TO` → "existing entity node"; search returns a "canonical key" | `:Entity` has a node key on `(name, type)`, has no ids, and the fallback NER splits one entity across types ("Manchester City" is stored as a Location) | **Canonical key = `name_lower`** (trim, collapse whitespace, lower-case). This is an additive property on `:Entity` with an index. `EXPOSED_TO` links to **every** type variant of the key, as v1 did. New nodes from ingestion get `name_lower` from the hourly job. Until then, queries use `coalesce(e.name_lower, toLower(e.name))` |
| C2 | `entity_aliases` "seeded from any ticker/alias properties" | none exist | The collection starts empty. `scripts/seed_entity_aliases.py` loads an optional hand-written `config/entity_aliases_seed.json` (e.g. `"u.s" → "us"`, `"man city" → "manchester city"`) |
| C3 | Relation weights for SUBSIDIARY_OF, SUPPLIES, … | The only Entity–Entity relationship is `MENTIONED_WITH {count}`. `MENTIONS`, `BELONGS_TO` and `PUBLISHED_BY` touch Article/Domain/Source nodes, and `EXPOSED_TO` touches User nodes | `rel_type_map = {"MENTIONED_WITH": "CO_MENTION"}`, so every hop uses 0.1. The spread query is restricted to `(:Entity)-[r]-(:Entity)` with `type(r) <> EXPOSED_TO`. Typed relations work automatically if they are ever added. **Consequence:** hop scores are ≤ 0.1 (hop 2 ≤ 0.005), so hop items can't reach τ = 0.2 and only affect interest ranking and explanations (Risk R1) |
| C4 | Edge strength | `MENTIONED_WITH` was MERGEd without a direction, and `count` is mostly 1 | Match it undirected. Strength = Σ `count` across the type variants of the neighbour key. Ties are broken by neighbour `frequency` |
| C5 | Clustering and interest use "FAISS neighbours" | `data/faiss_index` is stale and git-tracked. Only ingestion appends to it, and only when FAISS is installed on the machine running ingestion | Use a **separate personalization index**, `data/pers_faiss_index` + `data/pers_faiss_metadata.pkl`. It is the same `FAISSStore` class with different paths, synced hourly from Mongo (articles not yet in it). The pipeline's index is never written. Add `data/pers_faiss_*` to `.gitignore` |
| C6 | "skip clustering if the project already has one" | Only `dedup_hash` exists, and it drops duplicates at ingest instead of grouping them | Build clustering (§C) |
| C7 | R1: "index on the entities field" | `entities[].name` is case-sensitive and its variants differ in case/type | Add a derived field `entity_keys: [name_lower…]` on each article, written hourly, with a multikey index. Leave `entities` untouched |
| C8 | Materiality uses A4 risk; proposals use "A4 facts (acquisition/supplier/sanction)" | A4 writes no facts. Its only structure is `risk_reasoning` sub-scores. `risk_score` is null on all docs | `risk_norm = risk_score/100`, null → 0.5 + `unscored`. The fact-based proposal rule sits behind `PERS_A4_FACTS_FIELD` (default empty = inactive), with no keyword heuristics. It activates if A4 ever writes e.g. `event_facts` |
| C9 | Alert "hook right after A4 scores" | That would change `pipeline.py`, which the spec forbids | Poll every 5 min only, using `risk_processed_at` and the clustering job's `materiality.computed_at` as the watermark |
| C10 | "Use the existing scheduler if there is one" | Only `schedule` in blocking CLI loops; nothing runs in-process | APScheduler `BackgroundScheduler` started in the FastAPI lifespan (`PERS_SCHEDULER_ENABLED`, default true). `apscheduler==3.10.4` is already pinned but must be installed. There is also a CLI `python -m personalization.jobs <job>` for manual runs and tests |
| C11 | `locality_mix` / locality calibration "if a locality field exists" | none exists | Omit it from the persona and skip locality calibration. The config key is reserved |
| C12 | Topic | `domain` is set on every doc. `category` is null on 174. `other` is 41% of docs | **topic = `domain`** (`PERS_TOPIC_FIELD`). Candidates **don't** filter on `in_scope`: A2 only knows sports/movies, so a story about a user's company may be labelled `other`. Onboarding headlines and topic lists skip `topic_exclude=["other"]` |
| C13 | Rendering "if an LLM/Agent 6 exists" | There is no Agent 6. Groq is reachable through `utils.groq_client.init_groq_llm` (openai client). `summary_*` is null on 570 docs | `personalization/render.py` uses `init_groq_llm`. The source text is `summary_long` → `summary_short` → `body[:600]`. With no client or `ENABLE_RENDER=false`, it returns the source text |
| C14 | `beta` keys `"topic:x" \| "entity:y"` | Entity keys can contain `.` or `$` (e.g. `u.s`), which breaks Mongo `$inc` paths | Encode keys when storing them (`.`→`%2E`, `$`→`%24`, `%`→`%25`) and decode on read. The API shows raw keys |
| C15 | Onboarding "likes go into history (long window)" | History items only carry `t` | History items get `win: "long"` (onboarding) or `"both"`. `LF_short` ignores `"long"` items |
| C16 | Provenance ∈ declared / proposed / confirmed | Proposals must not change anything silently | No edge is written at proposal time. User-added edges get `declared`. An accepted proposal writes the edge with `confirmed` and `proposal_id`. `proposed` is the proposal doc's `origin`. It is also allowed on an edge only if a later flag wants shadow edges (off) |
| C17 | Feedback `save`, `needed`, `not_needed`, `missed` | E defines Beta deltas only for more / less / open / dwell | `save` → history (w = 2) with no Beta change. `needed`/`not_needed`/`missed` are logged only, for τ and metrics. Config `beta_deltas`, `history_w` |
| C18 | Dates | `published_at` is an ISO string with offsets, `ingested_at` is naive | Keep v1's approach: a coarse string prefilter in Mongo, then exact `scoring.parse_ts`. All new collections use BSON Dates |

---

## 1. Files

### New

| File | Purpose |
|---|---|
| `personalization/spread.py` | pure: exposure spread → pi_topk |
| `personalization/materiality.py` | pure: m and its components |
| `personalization/clustering.py` | pure: cluster assignment given neighbours and metadata |
| `personalization/interest.py` | pure: decay, late fusion, Beta/θ, interest |
| `personalization/candidates.py` | pure: RRF, read filter, cluster collapse |
| `personalization/slate.py` | pure: need, must_know, MMR, calibration, Thompson explore + propensity |
| `personalization/explain.py` | pure: why templates, profile sentences |
| `personalization/factcheck.py` | pure: extract numbers/dates/entity names, verify the rewrite |
| `personalization/keys.py` | pure: `entity_key()`, `encode_key()/decode_key()`, `beta_key()` |
| `personalization/render.py` | Groq rewrite, cache, fact-check fallback |
| `personalization/jobs.py` | job functions + `build_scheduler()` + CLI `python -m personalization.jobs <name>` |
| `personalization/metrics.py` | Mongo aggregations for `/admin/metrics` |
| `storage/pers_vector_store.py` | `PersVectorStore(FAISSStore)`: separate paths, `vectors_for`, `search_vector`, `sync_from_mongo` |
| `storage/pers_article_store.py` | Read and **additive** writes on `processed_articles` (`cluster_*`, `entity_keys`, `materiality`) + `clusters` |
| `storage/pers_log_store.py` | `feedback`, `impressions`, `thresholds`, `proposals`, `alerts`, `digests`, `render_cache`, `job_runs`, `entity_aliases` |
| `api/admin_router.py` | `/v1/admin/metrics`, `/v1/admin/jobs/{name}/run` |
| `scripts/rebuild_pers_faiss.py` | one-off full build of the personalization index |
| `scripts/seed_entity_aliases.py` | + `config/entity_aliases_seed.json` |
| `scripts/seed_demo_personas.py` | 3 demo users (see Phase 8), created via the service |
| `scripts/smoke_personalization.py` | end-to-end run against the live DBs with TestClient |
| `tests/test_pers_*.py` | one per pure module + store (mocked) + API (fake service) |

### Modified (all v1 files, all uncommitted)

| File | Change |
|---|---|
| `config/personalization.py` | Replace the knobs with §3 (keep field-name knobs and `env_prefix`) |
| `personalization/scoring.py` | Split into the pure modules above. Keep `parse_ts` and `normalize_topics` (the latter as `topic_shares`) |
| `personalization/service.py` | Grows into `PersonalizationService` (§4.4). Keep the error classes |
| `storage/exposure_store.py` | Link by canonical key (no `create_new`), provenance/valid_from, `set_exposure`, `spread_neighbours`, `search_entities`, `sync_name_lower` |
| `storage/persona_store.py` | v2 schema, lazy upgrade, Beta `$inc`, history `$slice -200`, pi_topk, `persona_version` |
| `api/app.py` | Lifespan: start/stop the scheduler. Mount `admin_router` |
| `api/personalization_router.py` | All endpoints in §4.5 |
| `storage/faiss_store.py` | **Revert** v1's `indexed_article_ids` (it moves to `PersVectorStore`), so this file ends up unchanged |
| `.gitignore` | `data/pers_faiss_*` |
| `requirements.txt` | already has fastapi/uvicorn. Add `mongomock` to the 3.10 environment for tests (it's already listed) |
| `README.md` | "Personalization" section |

**Not touched:** everything under `agents/`, `ingestion_pipeline.py`, `pipeline.py`, `run_mapnai.py`, `utils/`, `config/settings.py`, `neo4j_store.py`, and `data/faiss_*`.

---

## 2. Data model (additive only)

### 2.1 Neo4j

```
(:Entity) + name_lower: str                     // additive; set by sync_name_lower (hourly)
INDEX entity_name_lower IF NOT EXISTS FOR (e:Entity) ON (e.name_lower)
(:User {user_id, name, created_at})             // v1, unchanged
(:User)-[:EXPOSED_TO {role, weight:int 1..3, weight_label, provenance, valid_from, updated_at, proposal_id?}]->(:Entity)
CONSTRAINT user_id (v1)
```
The 6 existing v1 edges (`weight` stored as a string label) are migrated by `sync_name_lower`: `weight_label` =
old value, `weight` = int, `provenance="declared"`, `valid_from=updated_at`.

### 2.2 Mongo: new collections

**`personas`** (v2). v1 docs are upgraded lazily on read by adding the missing fields.
```
{user_id, name,
 topics: {domain: 0–1},                          // declared; share_t = topics[t]/Σ topics
 style: {tone: "plain"|"analyst", length: "short"|"medium", jargon: "low"|"high"},
 beta: {enc("topic:sports"): [α, β], enc("entity:manchester city"): [α, β]},
 history: [{article_id, title, t: Date, w, win: "both"|"long", src}],   // $slice -200
 pi_topk: [{entity, score, path: {seed, role, via: [..], relations: [..]}}],  // ≤ 500
 alert_prefs: {max_per_day: 3, quiet_start: "22:00", quiet_end: "07:00", tz: "Asia/Kolkata"},
 persona_version: int, updated_at: Date, created_at: Date}
idx: user_id unique
```

**Other collections**

| Collection | Doc shape | Indexes |
|---|---|---|
| `entity_aliases` | `{alias (lower), entity_key, source: "seed"\|"manual"}` | alias unique, entity_key |
| `clusters` | `{cluster_id, members: [article_id], first_report: article_id, first_published: Date, entity_keys: [..], size, updated_at}` | cluster_id unique, updated_at |
| `feedback` | `{user_id, article_id, type, value?, section?, topic, entity_keys: [≤3], t: Date}` | (user_id, t desc), (type, t) |
| `impressions` | `{impression_id, digest_id, user_id, article_id, cluster_id, slot, section, need, m, m_parts, interest, interest_parts, tau, propensity, policy_version, persona_version, t: Date}` | (user_id, t desc), (section, t), article_id |
| `thresholds` | `{t: Date, tau, prev_tau, miss_rate, missed, needed, window_days}` | t desc. Current τ = latest, else `tau_init` |
| `proposals` | `{proposal_id, user_id, kind: "exposure", entity_key, suggested_role, suggested_weight, origin: "proposed", reason: "engagement"\|"a4_fact", evidence: [article_id], status: "pending"\|"accepted"\|"rejected", created_at, decided_at}` | (user_id, status), unique (user_id, entity_key, status=pending) via partial index |
| `alerts` | `{alert_id, user_id, article_id, cluster_id, need, m, explanation, path, created_at, deliver_after}` | (user_id, deliver_after), unique (user_id, cluster_id) |
| `digests` | `{user_id, date: "YYYY-MM-DD" (user tz), items, more_you_need, policy_version, persona_version, generated_at}` | unique (user_id, date) |
| `render_cache` | `{article_id, tone, length, jargon, prompt_version, text, fallback: bool, missing: [..], model, created_at}` | unique (article_id, tone, length, jargon, prompt_version) |
| `job_runs` | `{job, started_at, finished_at, ok, stats, error, lease_until}` | (job, started_at desc). The lease prevents double runs (multi-worker) |

### 2.3 Additive fields on `processed_articles` (written only by personalization jobs)

```
entity_keys: [str]                    // multikey index
cluster_id: str, cluster_size: int, first_report: article_id (earliest in cluster)
materiality: {m, risk_norm, size_score, first_report: 0|1, source_cred, unscored: bool,
              risk_seen_at: <risk_processed_at or null>, computed_at: Date}
pers_indexed_at: Date                 // present once the article is in the pers FAISS index
indexes: entity_keys, cluster_id, materiality.m, (published_at desc, materiality.m desc)
```
Pipeline safety: `MongoStore.upsert_articles` does a `$set` of the model's own fields only, and the NER, classification,
summary and risk updaters use allow-listed `$set`s. None of them touch these keys.

---

## 3. Config (`config/personalization.py`, all `PERS_*`)

```
# toggles
enable_hop2=True enable_mmr=True enable_calibration=True enable_explore=True
enable_alerts=True enable_render=True enable_proposals=True scheduler_enabled=True
policy_version="v2.0" tz="Asia/Kolkata"

# field names (v1, kept) + topic_field="domain" topic_exclude=["other"] a4_facts_field=""
# pers index
pers_faiss_index_path="./data/pers_faiss_index" pers_faiss_metadata_path="./data/pers_faiss_metadata.pkl"

# A. profile
roles=[owns,depends_on,operates_in,regulated_by,covers,follows] weight_levels={low:1,medium:2,high:3}
topics_universe=[sports,entertainment_movies,finance,geopolitics,technology,health,supply_chain]
style_defaults={tone:plain,length:short,jargon:low} history_keep=200 search_limit=10
prior_strength=3.0                       # α=1+3w, β=1+3(1−w)
alert_prefs_default={max_per_day:3,quiet_start:"22:00",quiet_end:"07:00",tz:"Asia/Kolkata"}

# B. spread
rel_weights={SUBSIDIARY_OF:.5,SUPPLIES:.3,CUSTOMER_OF:.3,REGULATES:.4,SECTOR_PEER:.2,LOCATED_IN:.15,CO_MENTION:.1,UNKNOWN:.1}
rel_type_map={MENTIONED_WITH:CO_MENTION} rel_labels={CO_MENTION:"often mentioned with"}
hop1_top=20 hop2_top=10 hop2_decay=0.5 pi_topk_max=500

# C. clustering
cluster_window_h=48 cluster_nn=20 cos_join=0.80 cos_strong=0.88 cluster_time_h=36 min_shared_entities=1

# D. materiality
w_risk=.5 w_size=.2 w_first=.15 w_cred=.15 size_log_base=11 risk_scale_max=100 risk_missing=.5
source_cred={} source_cred_default=.5

# E. interest
short_window_h=72 short_half_life_h=24 long_window_d=60 long_half_life_d=21
lf_short_w=.4 lf_long_w=.6 w_lf=.5 w_topic=.3 w_entity=.2 beta_top_entities=3
beta_deltas={more:[1,0],less:[0,1],open:[.5,0],dwell:[.5,0]} dwell_min_s=15
history_w={open:1,save:2,more:2,dwell:1,onboarding:1}

# F. candidates
cand_window_h=48 r2_window_h=24 r2_top=20 r3_per_item=30 r3_history_items=10 r4_per_topic=30
recency_half_life_h=24 rrf_k=60 fused_top=200

# G. slate
slate_k=10 tau_init=.2 must_know_max=5 mmr_lambda=.7 need_bonus=.3 per_topic_cap=3
explore_slots=1 propensity_sims=200

# I. feedback / τ / proposals
tau_step=.05 miss_target=.1 tau_min=.05 tau_max=.6 tau_window_d=7
proposal_min_articles=3 proposal_min_theta=.7 proposal_window_d=7

# J. alerts
alert_min_need=.5 alert_min_m=.6 alert_lookback_h=48

# K. render
render_prompt_version="r1" render_max_tokens=400 render_source_chars=600

# L. jobs (cron in tz)
job_pi_topk="0 1 * * *" job_cluster="5 * * * *" job_alerts="*/5 * * * *"
job_tau="30 2 * * *" job_proposals="0 3 * * mon" job_digests="30 5 * * *"
```

---

## 4. Function signatures

### 4.1 Pure modules (no DB, no clock, RNG injected)

```python
# keys.py
def entity_key(name: str) -> str
def encode_key(k: str) -> str; def decode_key(k: str) -> str
def beta_key(kind: Literal["topic","entity"], value: str) -> str

# spread.py
Seed = TypedDict(key, role, weight:int)
Nbr  = TypedDict(key, rel_type, strength:float)
PiEntry = TypedDict(entity, score, path)
def seed_score(weight: int, cfg) -> float                         # weight/3
def rel_weight(rel_type: str, cfg) -> float                       # via rel_type_map → rel_weights, else UNKNOWN
def hop(frontier: Dict[str, PiEntry], nbrs: Dict[str, List[Nbr]], top: int, factor: float, cfg) -> Dict[str, PiEntry]
    # per source: take top-`top` by strength; score = src × rel_w × strength/max_strength(src) × factor
def spread(seeds: List[Seed], hop1: Dict[str, List[Nbr]], hop2: Optional[Dict[str, List[Nbr]]], cfg) -> List[PiEntry]
    # seeds ∪ hop1 ∪ hop2, max per entity keeps best path; sorted desc; cut pi_topk_max

# materiality.py
def size_score(n: int, cfg) -> float                              # min(1, ln(1+n)/ln(11))
def materiality(article: Dict, cluster_size: int, is_first: bool, cfg) -> Dict   # {m, risk_norm, size_score, first_report, source_cred, unscored}

# clustering.py
def assign_clusters(new: List[ArtMeta], neighbours: Dict[str, List[Tuple[str, float]]],
                    known: Dict[str, ArtMeta], cfg) -> List[ClusterOp]
    # ArtMeta = {article_id, published: datetime, entity_keys, cluster_id?}
    # join iff (cos≥.80 ∧ |Δt|≤36h ∧ shared≥1) ∨ cos≥.88; best-cos existing cluster wins;
    # else new cluster; merges of two existing clusters are NOT done (logged) — keeps ids stable
def cluster_summary(members: List[ArtMeta]) -> Dict               # size, first_report (earliest published, tie → article_id)

# interest.py
def decay(age_h: float, half_life_h: float) -> float
def late_fusion(vec, history, hist_vecs, now, window_h, half_life_h, include_long_only: bool) -> Tuple[float, Optional[HistItem]]
def theta(ab: Sequence[float]) -> float                           # α/(α+β)
def prior(w: float, cfg) -> List[float]                           # [1+3w, 1+3(1−w)]
def topic_theta(beta, topic, declared, cfg) -> float
def max_entity_theta(beta, entity_keys) -> float                  # missing → prior [1,1] = .5
def interest(article, vec, persona, hist_vecs, now, cfg) -> Tuple[float, Dict]    # parts: lf_short, lf_long, θ_topic, θ_entity, closest
def beta_updates(fb_type: str, value: Optional[float], topic: str, top_entities: List[str], cfg) -> Dict[str, List[float]]

# candidates.py
def rrf(lists: List[List[str]], k: int) -> List[Tuple[str, float]]
def merge_candidates(r1, r2, r3_lists, r4_lists, cfg) -> Dict[str, Set[str]]   # article_id → {"R1","R2","R3","R4"}
def drop_read(cands, read_ids) -> ...
def collapse_clusters(scored: List[Dict]) -> List[Dict]           # best per cluster_id; others → another_angle (different source_name first)

# slate.py
def need(entity_keys: List[str], m: float, pi: Dict[str, PiEntry]) -> Tuple[float, Optional[PiEntry]]
def pick_must_know(items, tau, cfg) -> Tuple[List, List]          # (≤5 by need desc, overflow → more_you_need)
def mmr(items, sim: Callable[[str,str], float], k: int, cfg, caps: Dict[str,int]) -> List
def calibration_caps(declared: Dict[str,float], k: int, cfg) -> Dict[str, int]    # round(share·k)+1; undeclared → 1
def thompson_explore(pool, slate_topics, beta, declared, rng, cfg) -> Tuple[Optional[Dict], float]  # (item, propensity from 200 sims)
def build_slate(items, pi, tau, persona, sim, rng, cfg) -> Dict   # {items:[...], more_you_need:[...]}

# explain.py
def why_direct(path, cfg) -> str; def why_hop(path, cfg) -> str; def why_interest(parts, topic) -> str
def why_explore(topic) -> str; def need_share(path_score, need) -> float
def profile_sentences(exposures, topics, style, cfg) -> List[str]

# factcheck.py
def extract_facts(text: str, entity_names: List[str]) -> Set[str]   # numbers, dates, entity names present in source
def verify(source: str, rewrite: str, entity_names: List[str]) -> Tuple[bool, List[str]]
```

### 4.2 Stores

```python
class ExposureStore:                      # storage/exposure_store.py (v1, extended)
    def search_entities(self, q: str, alias_keys: List[str], limit: int) -> List[Dict]   # {key, name, types, mention_count}
    def resolve_key(self, key: str) -> List[Dict]                                        # variant nodes; [] → 404
    def set_exposure(self, user_id, key, role, weight: int, provenance, proposal_id=None) -> Dict
    def remove_exposure(self, user_id, key) -> int
    def get_exposures(self, user_id) -> List[Dict]                                       # grouped per key
    def get_seeds(self, user_id) -> List[Seed]
    def neighbours(self, keys: List[str], top: int) -> Dict[str, List[Nbr]]              # one UNWIND query per hop
    def sync_name_lower(self) -> int                                                     # + v1 edge migration
    def ensure_schema(self) -> None

class PersonaStore:                       # storage/persona_store.py (v1, extended)
    def get(self, user_id) -> Optional[Dict]              # decodes beta keys, upgrades v1 lazily
    def create(self, user_id, name, topics, style) -> Dict
    def patch(self, user_id, fields: Dict) -> int         # $set + $inc persona_version, updated_at; returns new version
    def inc_beta(self, user_id, deltas: Dict[str, List[float]]) -> None   # initializes from prior via $setOnInsert-style read-modify-write
    def push_history(self, user_id, items: List[HistItem]) -> None       # $push $each $slice -200
    def set_pi_topk(self, user_id, pi: List[PiEntry]) -> None
    def all_ids(self) -> List[str]; def pi_index(self) -> Dict[str, List[Tuple[str, float, Dict]]]   # entity → [(user, pi, path)]

class PersArticleStore:                   # storage/pers_article_store.py
    def window(self, hours: int, now, projection=None) -> List[Dict]
    def by_ids(self, ids) -> List[Dict]
    def by_entity_keys(self, keys: List[str], hours: int, now) -> List[Dict]      # R1
    def top_by_m(self, hours: int, now, limit: int) -> List[Dict]                 # R2
    def by_topic(self, topic: str, hours: int, now, limit: int) -> List[Dict]     # R4 raw, ranked in pure code
    def unclustered(self, hours: int, now) -> List[Dict]
    def set_entity_keys(self, docs) -> int
    def apply_cluster_ops(self, ops) -> int                                       # articles + clusters collection
    def set_materiality(self, updates: Dict[str, Dict]) -> int
    def rescore_needed(self) -> List[Dict]            # risk_processed_at > materiality.risk_seen_at, or no materiality
    def ensure_indexes(self) -> None

class PersVectorStore(FAISSStore):        # storage/pers_vector_store.py
    def __init__(self, cfg=None)                       # pers paths
    def indexed_article_ids(self) -> Set[str]
    def vectors_for(self, ids) -> Dict[str, np.ndarray]    # reconstruct(row), last row wins
    def search_vector(self, vec, k) -> List[Tuple[str, float]]
    def cosine(self, a_id, b_id) -> Optional[float]
    def sync_from_mongo(self, docs: List[Dict]) -> int      # ProcessedArticle(**doc) → add_articles → save (atomic tmp+rename)

class PersLogStore:                       # storage/pers_log_store.py
    log_feedback, log_impressions, read_ids(user_id) (history ∪ feedback open/more/save/dwell),
    current_tau, push_tau, feedback_window, impressions_window,
    add_proposal, list_proposals, decide_proposal,
    add_alert, alerts_since, alerts_today(user_id, tz), alerted_clusters(user_id),
    get_digest, put_digest, invalidate_digest(user_id),
    render_get, render_put,
    job_start (lease), job_finish, last_runs,
    alias_lookup(q) -> List[str], alias_upsert(...)
```

### 4.3 Jobs (`personalization/jobs.py`)

```python
def job_pi_topk(svc, user_ids=None) -> Dict          # nightly 01:00 + on edit (single user)
def job_cluster(svc) -> Dict                         # hourly: sync_name_lower → entity_keys → pers FAISS sync → cluster → materiality (new + rescore)
def job_alerts(svc) -> Dict                          # */5
def job_tau(svc) -> Dict                             # daily 02:30
def job_proposals(svc) -> Dict                       # weekly Mon 03:00
def job_digests(svc) -> Dict                         # daily 05:30
def build_scheduler(svc, cfg) -> BackgroundScheduler # CronTrigger(tz=cfg.tz); each job wrapped in job_runs lease
if __name__ == "__main__": argparse name → run once, print JSON
```

### 4.4 Service (`personalization/service.py`)

```python
class PersonalizationService:
    # A
    def search_entities(self, q) -> List[Dict]
    def create_user(self, name, topics, style, exposures: List[ExposureIn]) -> Dict
    def onboarding_headlines(self) -> List[Dict]
    def onboarding(self, user_id, likes, dislikes) -> Dict
    def get_profile(self, user_id) -> Dict
    def patch_exposures(self, user_id, upserts, removes) -> Dict
    def patch_topics(self, user_id, topics) -> Dict
    def patch_style(self, user_id, style) -> Dict
    def patch_alert_prefs(self, user_id, prefs) -> Dict
    def _after_edit(self, user_id) -> None           # bump version, recompute pi_topk, invalidate digest
    # B–G
    def compute_pi(self, user_id) -> List[PiEntry]
    def compute_digest(self, user_id, now=None) -> Dict
    def get_digest(self, user_id, refresh=False) -> Dict   # cache → compute; logs impressions on every serve
    # I
    def record_feedback(self, user_id, article_id, type, value=None) -> Dict
    def list_proposals / accept_proposal / reject_proposal
    # J / K / L
    def alerts(self, user_id, since) -> List[Dict]
    def render(self, article_id, user_id) -> Dict
    def metrics(self, days) -> Dict
    def health(self) -> Dict                         # mongo, neo4j, faiss (pipeline + pers, staleness), job last runs
```
`compute_digest` flow:
1. Load the persona (with pi_topk; if it's missing, run `compute_pi`) and the current τ.
2. Build R1 from `by_entity_keys(pi keys)`, R2 from `top_by_m`, R3 from `search_vector` × the last 10 history items
   (48h filter), and R4 from `by_topic` ranked by recency × m.
3. Merge with RRF, drop read articles, and hydrate the docs.
4. Compute `vectors_for(candidates ∪ history)`, then need and interest per item.
5. Run `collapse_clusters`, then `build_slate`, then add explanations.
6. Return `{items, more_you_need, policy_version, stats}`, where `stats` = candidate counts per retriever, vector
   coverage, unscored share, and whether explore was skipped.

### 4.5 API (`/v1`)

| Method | Path | Body / query | Returns |
|---|---|---|---|
| GET | `/entities/search?q=` | — | top 10 `{key, name, types, mention_count}` |
| POST | `/users` | `{name, topics?, style?, exposures?: [{key, role, weight}]}` | 201 |
| GET | `/onboarding/headlines` | — | 10 `{article_id, title, topic, source, url, cluster_id, m}` |
| POST | `/users/{id}/onboarding` | `{likes: [], dislikes: []}` | — |
| GET | `/users/{id}/profile` | — | `{sentences, exposures, topics, style, alert_prefs, beta, pi_topk[:20], persona_version}` |
| PATCH | `/users/{id}/exposures` | `{upsert: [{key, role, weight}], remove: [key]}` | unknown key → 404 |
| PATCH | `/users/{id}/topics` | — | — |
| PATCH | `/users/{id}/style` | — | — |
| PATCH | `/users/{id}/alert_prefs` | — | — |
| GET | `/users/{id}/digest?refresh=` | — | — |
| POST | `/feedback` | `{user_id, article_id, type, value?}` | — |
| GET | `/users/{id}/proposals` | — | — |
| POST | `/users/{id}/proposals/{pid}/accept` | — | — |
| POST | `/users/{id}/proposals/{pid}/reject` | — | — |
| GET | `/users/{id}/alerts?since=` | — | — |
| GET | `/articles/{aid}/render?user_id=` | — | `{text, why, brief, cached, fallback, missing}` |
| GET | `/admin/metrics?days=7` | — | — |
| POST | `/admin/jobs/{name}/run` | — | — |
| GET | `/personalization/health` | — | — |

v1 endpoints removed: `POST /users/{id}/exposures`, `DELETE /users/{id}/exposures/{entity}` and `PUT /topics`, all
replaced by the PATCH endpoints.

---

## 5. Algorithms: the binding details

**Spread**
- Seeds are the user's `EXPOSED_TO` edges grouped by `name_lower`, using the max weight.
- The neighbour query uses one UNWIND over keys:
  `MATCH (s:Entity) WHERE s.name_lower IN $keys MATCH (s)-[r]-(n:Entity) WHERE type(r) <> 'EXPOSED_TO' AND n.name_lower <> s.name_lower`
  → group by `(s.name_lower, n.name_lower, type(r))`, `strength = sum(coalesce(r.count, r.weight, 1))`.
- Hop 2 expands only the retained hop-1 keys.
- Seeds themselves always score `weight/3` and are never lowered by a hop.

**Clustering**
- Candidates are articles in the last 48h with no `cluster_id`, sorted by `published_at` ascending, so earlier
  articles seed clusters.
- For each one, take `search_vector(k=20)` hits restricted to the 48h window (the pers index covers every article,
  so the window filter is applied after the search).
- It joins the cluster of its best qualifying neighbour, or starts a new one. `cluster_size` and `first_report` are
  rewritten on every member whenever a cluster grows.
- `materiality` is recomputed for all members of a changed cluster.

**Interest**
- An empty short window gives `LF = LF_long`, and an empty long window gives `LF = 0`.
- History vectors come from the pers index. History items without a vector are skipped and counted in `stats`.

**Need path share**: `share = path.score / max pi over the article's entities` (always 1 for the displayed max path).
When several of the article's entities hit pi, the text lists up to 2 more, e.g.
"(also: X 0.22)".

**Explore**
- Pool = candidates whose topic ∉ the slate topics, excluding must_know and items already in the slate.
- One draw θ_t ~ Beta(persona beta or prior) per pool topic. Pick the top-draw topic, then the highest-m article in
  that topic.
- Propensity = the share of 200 re-draws (same RNG stream, seeded per `(user, date)` for reproducibility) that pick
  the same article.
- An empty pool means the slot goes to MMR and `stats.explore_skipped = true`.

**Adaptive τ**
- `needed` counts only feedback where (user, article) has an impression with `section = must_know` in the window.
  `missed` counts all `missed` feedback.
- With a denominator of 0, τ stays the same (a row is still logged).

**Alerts**
- Scan articles with `materiality.computed_at > last successful run` and `published ≤ 48h`.
- Look each article's `entity_keys` up in `pi_index` (rebuilt each run from `personas.pi_topk`, which is 500 × users
  in memory, fine).
- Fire when `need ≥ .5 ∧ m ≥ .6`, with no existing alert for (user, cluster) and `alerts_today < max_per_day`.
- `deliver_after = now`, or the end of the quiet window in the user's tz.

**Render**
- The brief is style + top 3 `pi_topk` entries that hit the article + the why line.
- The **LLM prompt uses only the style triple**, not the brief, so the cache key is `(article, tone, length, jargon)`
  as the spec requires. The personal why line and exposures are attached deterministically outside the rewrite.
- Fact-check extracts numbers (`\d[\d,.]*%?`), dates (month names, ISO, `\d{1,2} (Jan…)`) and the article's entity
  names that occur verbatim in the source. Anything missing from the rewrite → fallback to the source and
  `fallback=true`. The failure is cached too, so the call isn't retried.

**Digest cache**
- Keyed by `(user_id, local date)`. It is valid only if `persona_version` matches; `_after_edit` also deletes it.
- Precompute doesn't log impressions; every GET serve logs them with a fresh `digest_id`.

---

## 6. Build phases

Each phase ends with a runnable check. Run everything with `py -3.10`. The test baseline outside `tests/test_pers_*`
stays at 12 failed / 46 passed.

### Phase 0: environment
- `py -3.10 -m pip install apscheduler==3.10.4 mongomock`
- **Verify:** `py -3.10 -c "import apscheduler, mongomock"`; the existing API still starts.

### Phase 1: profile, entity search, onboarding (without the cluster-dependent headline rule)
- `keys.py`, `explain.profile_sentences`, config v2, `ExposureStore` (search / resolve / set / sync_name_lower +
  v1 migration), `PersonaStore` v2 + lazy upgrade, `PersLogStore` (aliases, feedback).
- Endpoints: search, users, profile, PATCH × 4, onboarding POST, plus headlines (temporary rule: one per topic by
  recency).
- `scripts/seed_entity_aliases.py`.
- **Verify:**
  - `pytest tests/test_pers_keys.py tests/test_pers_profile.py`.
  - Live: `GET /v1/entities/search?q=manch` returns "manchester city" with `types` ⊇ {Location} and a mention count.
  - `POST /users` with key `manchester city`/owns/high, then the profile says "You own Manchester City (high)."
    and `persona_version` = 1.
  - A PATCH bumps the version.
  - Onboarding likes change `beta["topic:sports"]` α by +1.

### Phase 2: clustering, materiality, exposure spread
- `PersVectorStore`, `scripts/rebuild_pers_faiss.py`, `PersArticleStore` (entity_keys, cluster ops,
  materiality), `clustering.py`, `materiality.py`, `spread.py`, `job_cluster`, `job_pi_topk`,
  `compute_pi` wired into `_after_edit`.
- Headlines switch to the real rule (topic → max m → distinct cluster).
- **Verify:**
  - Unit tests: join rules at .79/.80/.88 × 35h/37h × shared 0/1; size_score(10) = 1; null risk gives m with
    `unscored`; seed 1/3/2/3/1; hop1 normalization; hop2 × .5; max-merge keeps best path; top-20/10 cuts.
  - Live: `rebuild_pers_faiss` → ntotal = 955, then `python -m personalization.jobs cluster` → every article in
    the 48h window has `cluster_id` and `materiality`, and `job_runs` has a row.
  - The demo user's `pi_topk[0]` is the seed with score 1.0 and neighbours ≤ 0.1.

### Phase 3: interest + candidates
- `interest.py`, `candidates.py`, `PersArticleStore` R1–R4 queries, `PersLogStore.read_ids`, feedback → Beta +
  history.
- **Verify:**
  - Unit tests:
    - decay(24, 24) = .5;
    - the late-fusion ≠ mean-vector case;
    - short-empty → long-only;
    - onboarding `win: long` excluded from short;
    - θ priors (w = 1 → [4, 1]);
    - RRF order;
    - R1/R2 bypass;
    - collapse keeps the best and sets another_angle from a different source.
  - Live: the service's debug method `candidates(user)` returns a non-empty R1 for the demo user, and its stats
    show vector coverage.

### Phase 4: slate + explanations + digest cache
- `slate.py`, `explain.py`, `compute_digest`, `get_digest`, `job_digests`, and impressions logging.
- **Verify:**
  - Unit tests: must_know ≤ 5 with overflow kept in `more_you_need`; MMR with λ = 1 equals greedy; topic cap 3;
    calibration caps; explore topic ∉ slate; propensity ∈ (0, 1] and reproducible under a seed; must_know never
    explore; every template string.
  - Live: `GET /users/{demo}/digest` returns 10 items with sections and why lines, a second GET is served from
    `digests`, a PATCH invalidates it, and `impressions` rows = items served.

### Phase 5: feedback + adaptive τ + proposals
- `record_feedback` (all 8 types), `job_tau`, `job_proposals`, and the proposal endpoints.
- **Verify:**
  - Unit tests: τ math: miss_rate .1 → unchanged, 1.0 → −.045, clip at .05/.6, denominator 0 → unchanged.
  - Live, with seeded fake feedback in a scratch user: `jobs tau` writes a `thresholds` row; `jobs proposals`
    creates one pending proposal, accept → the edge has `provenance=confirmed` and the profile changes, reject →
    nothing changes.
  - The A4-fact rule logs "inactive (a4_facts_field unset)".

### Phase 6: alerts
- `job_alerts` and `GET /alerts`.
- **Verify:**
  - Unit tests: quiet-hours deferral across midnight in Asia/Kolkata, 3/day cap, 1 per cluster.
  - Live: with real data (no A4), m < .6 normally gives **0 alerts**, and this is expected (see R2). A test mode
    with `PERS_ALERT_MIN_M=0.3` produces alerts for the demo user.

### Phase 7: rendering
- `factcheck.py`, `render.py`, and the render endpoint.
- **Verify:**
  - Unit tests: extraction of numbers, dates and entities; a missing number means fallback.
  - Live: two renders with the same style hit `render_cache` (one Groq call); a different user with the same style
    reuses the cache; `ENABLE_RENDER=false` or an empty key returns the source text.

### Phase 8: jobs + metrics + demo personas + smoke tests
- `build_scheduler` in the lifespan, `/admin/metrics`, and health with job last runs.
- `scripts/seed_demo_personas.py`, with entities checked against the live graph:
  1. "Football fan": owns/high `manchester city`, follows/medium `england`, topics sports 1.0.
  2. "Film buff": covers/high a top `entertainment_movies` Person/Org chosen by frequency at seed time;
     topics entertainment_movies 1.0, sports 0.2.
  3. "India desk": operates_in/high `india`, regulated_by/medium `who`; topics health, geopolitics.
- `scripts/smoke_personalization.py`: health → search → create → onboarding → digest → feedback × types → τ job
  → proposals job → alerts job → render → metrics. It asserts status codes and shapes and prints a summary.
- **Verify:**
  - `py -3.10 run_api.py` logs the 6 scheduled jobs.
  - `py -3.10 scripts/smoke_personalization.py` exits with 0.
  - `pytest tests/test_pers_*.py` passes offline (mongomock + fake Neo4j + an in-memory FAISS with 8 dims).

---

## 7. Risks (given the context file + today's re-check)

| # | Risk | Effect | Mitigation |
|---|---|---|---|
| R1 | Co-mention is the only relation and is weighted 0.1 | Hop scores ≤ 0.1, and need = m × pi ≤ ~0.05, so **hop items never reach must_know or alerts**. Only direct seeds do | Documented. `rel_weights.CO_MENTION` is overridable. `stats` reports the hop contribution |
| R2 | `risk_score` is null on all docs (A4 never run) | Every article is `unscored`. m ranges ≈ .33 (size 1, not first) to .53 (size 1, first) and reaches ≥ .6 only for clusters of 5+ with first_report. Alerts almost never fire, and must_know needs medium/high seeds | Nothing in personalization fixes this; the fix is to run A4 (`python pipeline.py --agents 4` with a Groq key). `job_cluster` rescores articles automatically when `risk_processed_at` appears. Metrics show the unscored share |
| R3 | The data is one ingestion run (955 docs, newest `published_at` 2026-09-28) | The 48h windows **empty out after about 2026-09-30**, which leaves no candidates, clusters or alerts | Health flags `recent_articles=0`. Keep ingestion running (`ingestion_pipeline.py --schedule`). For demos, `PERS_CAND_WINDOW_H` / `PERS_CLUSTER_WINDOW_H` can be widened |
| R4 | Pipeline FAISS is stale, and ingestion elsewhere may never update it | — | Separate pers index synced from Mongo (C5). It costs one extra MiniLM embedding per article (≈ ms on CPU). The first build loads sentence-transformers (~90 MB download if not cached) |
| R5 | Entity quality (spaCy fallback): mis-types, fragments ("Synopsis Upcoming"), variants ("US" / "U.S") | Missed or false exposure hits. Search shows junk | Name-level keys across types, aliases seed, search ranked by mention count. There's no fuzzy matching (out of scope). Fixing A1 BERT is the real fix (context open question 5) |
| R6 | Hub entities (US, India, AI-as-Location) have many co-mentions | Spread from a hub seed floods pi_topk with weak entities | Top-20 / top-10 cuts, normalized by the seed's max strength. `pi_topk_max=500` |
| R7 | `MENTIONED_WITH.article_ids` grows without bound, and backfill isn't idempotent | Re-running the backfill doubles counts | Personalization only reads counts (ratios within a seed, so doubling doesn't change scores). Don't rerun the backfill without `--force` |
| R8 | Concurrent writers | Ingestion and the personalization jobs both write `processed_articles` (different fields). Pers FAISS is written only by `job_cluster` | Field-scoped `$set`s. `job_runs` lease against double runs. Atomic tmp+rename for the index files. Run uvicorn with **1 worker** (or `PERS_SCHEDULER_ENABLED=false` on the extra ones) |
| R9 | `domain` is dominated by `other`, and the A2 taxonomy is only sports/movies | Topic prefs for finance/tech/etc. match only legacy or preprocess-labelled docs. Explore pools are small | `topics_universe` is configurable. The explore fallback is logged. `other` is excluded from onboarding topics but not from candidates |
| R10 | `summary_*` is null on 570 docs | Render falls back to a body snippet, and fact-checking against a raw body is stricter (more fallbacks) | Accept it and track `fallback` in metrics |
| R11 | `published_at` strings with mixed offsets, plus some very old dates (2016) | Window edge errors | Coarse Mongo prefilter + exact `parse_ts`. Articles older than the window never get clustered (by design) |
| R12 | Beta keys with `.`/`$` | Broken updates | `encode_key` (C14), with a unit test on `"u.s"` |
| R13 | No auth on the API | Anyone on the host can read or edit profiles | Bind to 127.0.0.1 (the v1 default). Auth is out of scope |
| R14 | Environment: 3.13 segfaults on numpy, and 3.10 lacks apscheduler/mongomock/groq | — | Phase 0. Render uses openai → Groq, so there's no need for the `groq` SDK |
| R15 | v1 persona doc + 6 v1 edges (weight as string, no provenance) | Mixed shapes | Lazy persona upgrade + one-time edge migration in `sync_name_lower`, both covered by tests |

## 8. Out of scope

Conformal guarantees, trained rankers, ReFinED, MiniCheck, offline benchmarks, alert delivery channels, API auth,
fuzzy entity resolution, and any change to Agents 1–5, `pipeline.py` or `ingestion_pipeline.py`.
