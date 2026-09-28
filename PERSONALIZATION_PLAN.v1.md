# PERSONALIZATION_PLAN.md

Design for a minimal personalization engine on top of MAPNAI. It is based on `PERSONALIZATION_CONTEXT.md`
(snapshot 2026-09-29, branch `agent-satvik` @ 8a8b086) and the code in `config/`, `storage/`, `utils/` and `tests/`.
There is no implementation code yet.

## 0. Decisions where the spec conflicted with the codebase

| Conflict | Decision (confirmed with user) |
|---|---|
| "mounted in the existing app": no FastAPI app exists, only CLI entry points | New `api/app.py` (FastAPI) that mounts the `/v1` router, plus a `run_api.py` uvicorn entry in the style of `run_mapnai.py` |
| Neo4j Aura is empty (0 nodes), so exposures never match and there are no one-hop neighbours | Phase 1 adds `scripts/backfill_neo4j.py`. It replays `processed_articles` through the existing `Neo4jStore.upsert_articles` / `upsert_entities` and adds no new schema |
| FAISS is stale (0 of 687 ids are in Mongo), so latefusion is always 0 | Phase 2 adds `scripts/rebuild_faiss.py`. It re-embeds `processed_articles` into a fresh index through the existing `FAISSStore.add_articles` / `save`. The digest still reads vectors only from the index |

Smaller choices I made myself (each one can be changed in config or here):

- **Article topic = `domain`**, not `category`. `domain` is set on all 955 docs; `category` is null on 174. Config: `PERS_TOPIC_FIELD`.
- **Materiality scale = `risk_score` int 0–100**, so `materiality = risk_score / 100`. Null gives `0.5`. Null is true for all 955 docs today, so see Risks.
- **Candidate time field = `published_at`** (the ISO string, parsed in Python). `ingested_at` is naive and every doc has the same value (one run), so it can't tell articles apart by recency.
- **Matching article entities to exposures** uses the lower-cased `entities[].name` only and ignores `type`. The spaCy fallback mis-types entities ("Big Bang" is a Location), so matching on `(name, type)` would miss real hits.
- **Case-insensitive Neo4j match that hits several `(name, type)` nodes**: link `EXPOSED_TO` to *all* of them and report `matched: true, matched_nodes: N`. When nothing matches, create `(:Entity {name, type: <given or "Unknown">, created_by: "user_exposure"})`. A `type` is required because `Entity` has a node key on `(name, type)`.
- **"Already read"** = history article_ids ∪ distinct `article_id` of `open`/`more` events in `feedback`. History alone keeps only 30 items, so older reads would come back.
- **Edge weight for neighbours**: `MENTIONED_WITH.count` (the only weight in the graph). Other relationship types fall back to `1`. The neighbour query is restricted to `:Entity` endpoints, so `MENTIONS` (Article) and `EXPOSED_TO` (User) are skipped automatically.
- **Readable relation names for the why line**: `MENTIONED_WITH` becomes "often mentioned with". Other types are lower-cased with `_` replaced by a space. Config map `PERS_RELATION_LABELS`.
- **Topic cap of 3** applies to the interest section only, as the spec says. must_know items don't count toward it.
- **Why template per section**: must_know uses direct/one-hop, interest uses similar/topic, explore uses the explore line. For interest, the "Similar to" line is chosen when `0.6·latefusion ≥ 0.4·topic_weight` and a history item has cosine > 0; the "Matches your interest" line is used otherwise.

---

## 1. Files

### New

| File | Purpose |
|---|---|
| `config/personalization.py` | `PersonalizationSettings(BaseSettings)`, `env_prefix="PERS_"`. Same `.env` handling as `config/settings.py` (`_ENV_FILE`, .env wins). Holds every knob in §2 |
| `personalization/__init__.py` | package marker |
| `personalization/scoring.py` | **Pure** module: no DB, no I/O, no clock (`now` is passed in), injectable RNG. Exposure map, materiality, need, latefusion, interest, candidate filter, slate assembly, why lines |
| `personalization/service.py` | `PersonalizationService`: loads data from the stores, calls `scoring`, writes logs. The only place that combines Mongo, Neo4j and FAISS |
| `storage/persona_store.py` | `PersonaStore`: `personas`, `impressions`, `feedback` collections. Wraps an existing `MongoStore` (reuses its lazy `db`) |
| `storage/exposure_store.py` | `ExposureStore`: `(:User)-[:EXPOSED_TO]->(:Entity)` read/write and neighbour fetch. Wraps an existing `Neo4jStore` (reuses its `driver`) |
| `api/__init__.py` | package marker |
| `api/app.py` | `create_app() -> FastAPI` and a module-level `app`. Mounts the router and builds one shared `PersonalizationService` |
| `api/personalization_router.py` | `APIRouter(prefix="/v1")`, pydantic request/response models, and a `get_service` dependency (overridable in tests) |
| `run_api.py` | `python run_api.py [--host] [--port]` → `uvicorn.run("api.app:app")` |
| `scripts/backfill_neo4j.py` | Mongo → `ProcessedArticle(**doc)` → `Neo4jStore.upsert_articles` + `upsert_entities`, in batches of `--batch 20` (see Risk R6) |
| `scripts/rebuild_faiss.py` | Mongo → `ProcessedArticle` → a new `FAISSStore(index_path=tmp)` → `add_articles` → `save`, then an atomic swap of the files. `--dry-run` |
| `scripts/seed_demo_personas.py` | Creates 2–3 demo users through `PersonalizationService` (not raw DB writes), using entities that really occur in the data (e.g. a sports club, a film studio) |
| `tests/test_personalization_scoring.py` | Unit tests for the pure module (no mocks needed) |
| `tests/test_persona_store.py` | Mocked Mongo/Neo4j tests, in the `tests/test_storage.py` style (`@patch("storage.mongo_store.MongoClient")`) |
| `tests/test_personalization_api.py` | `fastapi.testclient.TestClient` with `get_service` overridden by a fake |

### Modified

| File | Change |
|---|---|
| `storage/faiss_store.py` | Add `vectors_for(article_ids) -> Dict[str, np.ndarray]` (uses `reconstruct(row)`; the row comes from `metadata[i]["article_id"]`, last occurrence wins because of append-only duplicates) and `indexed_article_ids() -> Set[str]`. A lazy `_row_by_article_id` cache is rebuilt after `add_articles`. The embedding model is not loaded for reads |
| `storage/mongo_store.py` | Add `get_articles_published_since(cutoff: datetime, limit: int) -> List[Dict]` and `get_newest_articles(limit: int) -> List[Dict]` (sorted by `published_at` desc, projection without `body`). Existing `get_recent_articles` uses `ingested_at`, so it is left untouched |
| `requirements.txt` | Add `fastapi` and `uvicorn` pins (`httpx==0.27.0` is already there, which covers TestClient) |
| `README.md` | A short "Personalization API" section: env knobs, the two scripts, `run_api.py` |

The existing agents and pipelines are not changed.

---

## 2. Config (`config/personalization.py`)

All values can be overridden with `PERS_<NAME>`.

```
# field names on processed_articles (from context §2)
id_field="article_id"  title_field="title"  topic_field="domain"  url_field="url"
published_field="published_at"  entities_field="entities"  entity_name_key="name"
risk_field="risk_score"  risk_scale_max=100  materiality_default=0.5

# collections / labels
personas_collection="personas"  impressions_collection="impressions"  feedback_collection="feedback"
articles_collection="processed_articles"
user_label="User"  entity_label="Entity"  exposure_rel="EXPOSED_TO"  entity_name_prop="name"
edge_weight_props=["count","weight"]  default_edge_weight=1.0
relation_labels={"MENTIONED_WITH": "often mentioned with"}
new_entity_type="Unknown"

# exposure
roles=["owns","depends_on","operates_in","regulated_by","covers","follows"]
weight_levels={"low":1,"medium":2,"high":3}  weight_divisor=3
hop_factor=0.3  max_neighbours_per_seed=15

# interest
latefusion_weight=0.6  topic_weight=0.4  half_life_hours=72  history_max=30

# candidates
candidate_hours=48  candidate_fallback_limit=500

# digest
digest_size=10  must_know_max=4  must_know_min_need=0.2
interest_need_bonus=0.5  per_topic_cap=3  explore_count=1

# feedback
feedback_types=["open","more","less","needed","not_needed"]
open_history_w=1.0  more_history_w=2.0  topic_step=0.1
```

Exposed as `pers_settings = get_pers_settings()` (`lru_cache`), which mirrors `settings = get_settings()`.

---

## 3. Data model

**Neo4j**
```
(:User {user_id, name, created_at})
  -[:EXPOSED_TO {role, weight, updated_at}]->
(:Entity {name, type, ...existing props})        // existing node, or new with created_by:"user_exposure"
CONSTRAINT user_id IF NOT EXISTS FOR (u:User) REQUIRE u.user_id IS UNIQUE
```
`updated_at` is an epoch-ms `timestamp()`, which matches `first_seen`/`last_seen` in `neo4j_store.py`.

**Mongo `personas`**
```
{user_id: str(uuid4), name, topics: {topic: float 0–1},
 history: [{article_id, title, t: datetime(UTC), w: float}],   // $push $each $slice -30
 created_at: datetime(UTC)}
index: user_id unique
```

**Mongo `impressions`**: one doc per digest item.
```
{digest_id, user_id, article_id, rank, section, topic, need, interest, why,
 propensity (explore only, else null), hours, ts: datetime(UTC)}
index: (user_id, ts desc), digest_id
```

**Mongo `feedback`**: one doc per event.
```
{user_id, article_id, type, topic (resolved from the article), ts: datetime(UTC)}
index: (user_id, ts desc), (user_id, type)
```
New collections store real BSON Dates, even though `processed_articles` uses strings (context §2, open question 8).

---

## 4. Function signatures

### `personalization/scoring.py` (pure)

```python
Seed      = TypedDict("Seed", {"name": str, "role": str, "weight": str})
Neighbour = TypedDict("Neighbour", {"name": str, "relation": str, "edge_weight": float})
Path      = TypedDict("Path", {"seed": str, "role": str, "via": Optional[str], "relation": Optional[str]})
HistItem  = TypedDict("HistItem", {"article_id": str, "title": str, "t": datetime, "w": float})

def seed_weight(level: str, cfg) -> float
def build_exposure_map(seeds: List[Seed],
                       neighbours: Dict[str, List[Neighbour]],    # key = lower(seed name)
                       cfg) -> Dict[str, Tuple[float, Path]]       # key = lower(entity name)
    # seeds get score w with via=None; each neighbour gets w*hop*(ew/max_ew_for_seed);
    # keep max per entity; truncate neighbours to cfg.max_neighbours_per_seed by ew desc

def materiality(article: Dict, cfg) -> float                       # risk/scale_max, clamp 0–1, None → 0.5
def article_exposure(article: Dict, exposure: Dict, cfg) -> Tuple[float, Optional[Path], Optional[str]]
    # max over lower(entities[].name); returns (score, path, matched entity)
def need(article: Dict, exposure: Dict, cfg) -> Tuple[float, Optional[Path]]

def decay(t: datetime, now: datetime, half_life_h: float) -> float  # 0.5 ** (age_h / half_life)
def latefusion(article_vec: Optional[np.ndarray],
               history: List[HistItem],
               hist_vecs: Dict[str, np.ndarray],
               now: datetime, cfg) -> Tuple[float, Optional[HistItem]]
    # Σ d_i·w_i·cos(a,h_i) / Σ d_i·w_i over history items that have vectors; no vectors → (0, None)
    # also returns the item with the highest cosine, used for the "Similar to" line
def interest(article: Dict, article_vec, history, hist_vecs, topics: Dict[str, float],
             now: datetime, cfg) -> Tuple[float, Dict]                # Dict = components for why

def parse_ts(value: Any) -> Optional[datetime]                     # ISO str / naive str / datetime → aware UTC
def filter_candidates(articles: List[Dict], read_ids: Set[str],
                      now: datetime, hours: int, cfg) -> List[Dict]

def why_line(section: str, path: Optional[Path], interest_parts: Dict, topic: str, cfg) -> str

ScoredItem = TypedDict(..., article, need, need_path, interest, interest_parts, topic)
def score_candidates(candidates, exposure, vectors, history, topics, now, cfg) -> List[ScoredItem]
def assemble_digest(scored: List[ScoredItem], rng: random.Random, cfg) -> List[Dict]
    # returns [{rank, section, article_id, title, topic, url, why, need, interest, propensity}]

def normalize_topics(topics: Dict[str, float]) -> Dict[str, float]  # divide by max; all ≤0 → {}
def apply_topic_delta(topics: Dict[str, float], topic: str, delta: float) -> Dict[str, float]  # clamp 0–1
def profile_sentences(exposures: List[Dict], topics: Dict[str, float]) -> List[str]
    # "You own X (high)." / "You depend on Y (medium)." (role → verb map in cfg)
```

### `storage/exposure_store.py`

```python
class ExposureStore:
    def __init__(self, neo4j: Optional[Neo4jStore] = None)
    def ensure_constraints(self) -> None
    def upsert_user(self, user_id: str, name: str) -> None
    def add_exposure(self, user_id: str, entity: str, role: str, weight: str,
                     entity_type: Optional[str] = None) -> Dict   # {entity, matched, matched_nodes, created}
    def remove_exposure(self, user_id: str, entity: str) -> int   # edges deleted (case-insensitive name)
    def get_exposures(self, user_id: str) -> List[Dict]           # [{name, type, role, weight, updated_at}]
    def get_seed_neighbours(self, user_id: str, k: int) -> Tuple[List[Seed], Dict[str, List[Neighbour]]]
    def is_available(self) -> Dict                                # {ok, users, entities}
```
Neighbour Cypher (a single round-trip):
```
MATCH (u:User {user_id:$uid})-[x:EXPOSED_TO]->(s:Entity)
CALL { WITH s
  MATCH (s)-[r]-(n:Entity) WHERE n <> s
  WITH n, type(r) AS rel, coalesce(r.count, r.weight, 1.0) AS ew
  ORDER BY ew DESC LIMIT $k
  RETURN collect({name:n.name, relation:rel, edge_weight:ew}) AS nbrs }
RETURN s.name AS seed, x.role AS role, x.weight AS weight, nbrs
```
Match for `add_exposure`: `MATCH (e:Entity) WHERE toLower(e.name) = toLower($name)`.

### `storage/persona_store.py`

```python
class PersonaStore:
    def __init__(self, mongo: Optional[MongoStore] = None)
    def ensure_indexes(self) -> None
    def create_persona(self, user_id: str, name: str, topics: Dict[str, float]) -> Dict
    def get_persona(self, user_id: str) -> Optional[Dict]
    def set_topics(self, user_id: str, topics: Dict[str, float]) -> bool
    def append_history(self, user_id: str, item: HistItem, keep: int) -> bool
    def get_read_ids(self, user_id: str) -> Set[str]              # history ∪ feedback open/more
    def log_impressions(self, docs: List[Dict]) -> int
    def log_feedback(self, doc: Dict) -> None
```

### `storage/faiss_store.py` (additions)

```python
def vectors_for(self, article_ids: Iterable[str]) -> Dict[str, np.ndarray]
def indexed_article_ids(self) -> Set[str]
```

### `storage/mongo_store.py` (additions)

```python
def get_articles_published_since(self, cutoff: datetime, limit: int = 5000) -> List[Dict]
    # string prefilter: published_at >= cutoff.date().isoformat() (uses the index); exact filter in scoring.parse_ts
def get_newest_articles(self, limit: int = 500) -> List[Dict]
def get_articles_by_ids(self, ids: List[str]) -> List[Dict]      # for feedback topic + history titles
```

### `personalization/service.py`

```python
class UserNotFound(Exception)
class PersonalizationService:
    def __init__(self, mongo: MongoStore = None, neo4j: Neo4jStore = None,
                 faiss: FAISSStore = None, cfg=None, rng: random.Random = None,
                 clock: Callable[[], datetime] = None)
    def create_user(self, name: str, exposures: List[Dict], topics: Dict[str, float]) -> Dict
        # → {user_id, exposures: [add_exposure results]}
    def add_exposure(self, user_id: str, exp: Dict) -> Dict
    def remove_exposure(self, user_id: str, entity: str) -> Dict
    def set_topics(self, user_id: str, topics: Dict[str, float]) -> Dict
    def get_profile(self, user_id: str) -> Dict       # {sentences, exposures, topics, recent_reads}
    def get_digest(self, user_id: str, hours: int) -> Dict   # {digest_id, generated_at, items, stats}
    def record_feedback(self, user_id: str, article_id: str, type: str) -> Dict
    def health(self) -> Dict                          # {mongo, neo4j, faiss:{ok,ntotal,recent_indexed}, recent_articles}
```
`get_digest` flow: persona → read_ids → Mongo candidates (48h, else newest 500) → `filter_candidates` → Neo4j seeds and neighbours → `build_exposure_map` → `faiss.vectors_for(candidates ∪ history)` → `score_candidates` → `assemble_digest(rng)` → `log_impressions` → return. `stats` reports the candidate count, how many candidates have vectors, how many history items have vectors, and whether the fallback was used. That makes stale data visible.

### `api/personalization_router.py`

```python
router = APIRouter(prefix="/v1", tags=["personalization"])
def get_service() -> PersonalizationService

class ExposureIn(BaseModel): entity: str; role: Literal[...]; weight: Literal["low","medium","high"]; type: Optional[str] = None
class UserCreate(BaseModel): name: str; exposures: List[ExposureIn] = []; topics: Dict[str, float] = {}
class TopicsIn(BaseModel):   topics: Dict[str, float]
class FeedbackIn(BaseModel): user_id: str; article_id: str; type: Literal["open","more","less","needed","not_needed"]
class DigestItem(BaseModel): rank: int; section: Literal["must_know","interest","explore"]; article_id: str
                             title: str; topic: Optional[str]; url: str; why: str; need: float; interest: float

POST   /v1/users                              → 201 {user_id, exposures}
POST   /v1/users/{user_id}/exposures          → {entity, matched, matched_nodes, created}
DELETE /v1/users/{user_id}/exposures/{entity} → {removed: int}
PUT    /v1/users/{user_id}/topics             → {topics}
GET    /v1/users/{user_id}/profile            → {sentences, exposures, topics, recent_reads}
GET    /v1/users/{user_id}/digest?hours=48    → {digest_id, items: [DigestItem], stats}
POST   /v1/feedback                           → {ok, type}
GET    /v1/personalization/health             → {mongo, neo4j, faiss, recent_articles}
```
`UserNotFound` → 404. Unknown article in feedback → 404. Store unavailable → 503 (in health it becomes `{ok:false}` rather than an error).

---

## 5. Build order

### Phase 1: exposures + profile
1. `config/personalization.py`
2. `storage/exposure_store.py`, `storage/persona_store.py` (create/get/topics only)
3. `scoring.normalize_topics`, `profile_sentences`, `seed_weight`
4. `service.create_user / add_exposure / remove_exposure / set_topics / get_profile`
5. `api/app.py`, `api/personalization_router.py` (users, exposures, topics, profile, health skeleton), `run_api.py`, requirements
6. `scripts/backfill_neo4j.py`, then run it against Aura and check `get_graph_stats()`

**Done when:** creating a user with an exposure to an entity from the data returns `matched: true`, and the profile shows "You own X (high)."

### Phase 2: scoring + digest
1. `scoring.py` in full (exposure map, materiality, need, decay, latefusion, interest, parse_ts, candidates, assemble, why)
2. `FAISSStore.vectors_for / indexed_article_ids`, `MongoStore.get_articles_published_since / get_newest_articles / get_articles_by_ids`
3. `scripts/rebuild_faiss.py`, then run it and confirm `ntotal ≈ 955` and `recent_indexed > 0` in health
4. `service.get_digest` and `GET /digest` (no impression logging yet)
5. Fill in the health endpoint (recent count, FAISS overlap)

**Done when:** a demo user with a high exposure gets a must_know item with a direct why line, and interest items appear once there is history.

### Phase 3: feedback + logging
1. `PersonaStore.append_history / get_read_ids / log_impressions / log_feedback` + indexes
2. `scoring.apply_topic_delta`
3. `service.record_feedback`, `POST /v1/feedback`. Impression logging goes into `get_digest` (with explore `propensity = 1/len(pool)`)
4. Read-exclusion in candidates

**Done when:** an `open` removes the article from the next digest and adds a "Similar to" line, `more`/`less` change the topic weights, and every event and digest item has a log row.

### Phase 4: tests + demo seed
1. `tests/test_personalization_scoring.py`: seed weights 1/3, 2/3, 1; neighbour scaling and max-merge; a cap of 15; null risk gives 0.5 and 100 gives 1.0; need = mat × max; decay at 72h = 0.5; latefusion is per-item and not the mean vector (a test where the mean-vector result would differ); topic normalization; must_know threshold and cap 4; topic cap 3; explore topic not in slate and propensity; each why template; a stable result under a seeded RNG; `parse_ts` for tz and naive strings
2. `tests/test_persona_store.py`: `$slice -30`, clamp, read_ids union (mocked)
3. `tests/test_personalization_api.py`: every endpoint against a fake service, status codes, validation (bad role/weight/type gives 422)
4. `scripts/seed_demo_personas.py` + README section

**Done when:** `pytest tests/test_personalization_*.py` passes offline (no DBs, no model download).

---

## 6. Risks (from the context file)

| # | Risk | Effect | Mitigation in this plan |
|---|---|---|---|
| R1 | **`risk_score` is null on all 955 docs** (A4 never ran) | materiality = 0.5 for everything, so need = 0.5 × exposure. must_know (need ≥ 0.2) requires exposure ≥ 0.4, which means **only direct medium/high seeds qualify**: low = 0.33·0.5 = 0.17 and one-hop ≤ 0.3·0.5 = 0.15. Once A4 runs, one-hop can reach must_know only if the seed is high, the edge is the seed's strongest and risk ≥ 67 | Documented behaviour. Threshold is configurable. Health/`stats` report how many candidates have a risk score |
| R2 | **Neo4j empty** | No matches or neighbours until the backfill runs | `backfill_neo4j.py` (Phase 1). `add_exposure` reports `matched:false` so the gap is visible |
| R3 | **FAISS stale / not updated by the last ingestion run** | latefusion is 0 and interest reduces to topic weight | `rebuild_faiss.py` (Phase 2). `stats` shows vector coverage. Ingestion keeps appending, so new articles are covered only if ingestion runs on this machine with FAISS installed (open question 2) |
| R4 | **FAISS is append-only with possible duplicate ids, and `embedding_id` is always null** | Wrong vector if an article is re-embedded | Map through `metadata[i]["article_id"]` only, last row wins. `embedding_id` is ignored |
| R5 | **Entity quality (spaCy fallback)**: mis-types, fragments like "Synopsis Upcoming", no ids or aliases | Missed or false matches ("Man Utd" ≠ "Manchester United"); `(name,type)` duplicates | Name-only, case-insensitive matching; link to all type variants. No alias handling (out of scope), noted in the profile response |
| R6 | **`_build_cooccurrence` silently caps at 5000 pairs per call**, and `article_ids` grows without bound on each edge | A large backfill batch drops most co-occurrence edges, so neighbours are incomplete | Backfill in small batches (default 20 articles) and log the pair count per batch. Don't change `neo4j_store.py` |
| R7 | **Case-insensitive match is a full scan** (`toLower(e.name)` can't use the node-key index) | Slow `add_exposure` on a large graph (fine at a few thousand entities) | Accept for now. Later option: a `name_lower` property + index written by the backfill |
| R8 | **`published_at` is an ISO string with mixed offsets, `ingested_at` is naive** | String range queries can be off near the cutoff | Coarse string prefilter by date in Mongo, then an exact `parse_ts` filter in Python |
| R9 | **The data is 1 run, 955 docs, dominated by other/sports/entertainment_movies** | The 48h window may be small. Explore needs a topic that isn't in the slate, and with 3 dominant topics the pool is often empty | Fallback to the newest 500. If the explore pool is empty, the slot is filled by the next interest item and `stats.explore_skipped=true` is logged. The digest can come back shorter than 10 |
| R10 | **`domain` is overwritten by A2 while legacy domains remain**, and `entities[].domain` disagrees with the article | User topic keys may not match article topics | Use article `domain` only. The API accepts any topic key and the profile lists the known domain values |
| R11 | **No interpreter has the full requirements** (3.13 lacks pymongo/neo4j/faiss and numpy segfaults; 3.10 lacks pymongo/neo4j) | The API can't start locally | Phase 1 step 0: pick one interpreter (3.10 has faiss + sentence-transformers) and `pip install pymongo neo4j fastapi uvicorn`. The scoring tests need only numpy |
| R12 | **FAISS files are tracked in git** | Rebuilding produces large binary diffs | The rebuild script writes to the configured path. Whether to untrack `data/faiss_*` is your call (open question 2); this plan doesn't commit the rebuilt index |
| R13 | **Cosine can be negative** | latefusion can go below 0 and push interest down | Keep raw values, as the spec says. Flag it if it's a problem in the demo |
| R14 | **History keeps only 30 items** | Read-exclusion would miss older reads | read_ids also include `feedback` open/more events |

## 7. Out of scope

Alerts, LLM calls, calibration, bandits, learned rankers, entity alias resolution, auth on the API, and changes to Agents 1–5 or the ingestion pipeline.
