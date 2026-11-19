# CONTINUOUS_STREAM_PLAN.md

Implementation plan for the continuous news stream and hit-news detection. The design and its rationale are in
`continousexplanation.md`; this file is the build order, the file-level changes and the test plan.

Baseline before any change: `research/experiments/run_suite_isolated.sh` → **821 passed** (2026-11-19).

## Decisions taken (defaults; each is a setting)

| Question | Decision | Setting |
|---|---|---|
| Domains whose hits are shown / pushed | In-scope domains only (sports, entertainment_movies); `H` is computed for every cluster | `PERS_HOT_DOMAINS` |
| Global breaking push | Opt-in per user, off by default, max 2/day | `alert_prefs.breaking_global`, `PERS_BREAKING_GLOBAL_MAX_PER_DAY` |
| Where the stream runs | Separate worker process (`stream_worker.py`, docker-compose service `stream`) | — |
| Google News | Prominence signal only, never stored as articles | `RSSSource.store_items=False` |
| Raw Bluesky posts as articles | Off | `BLUESKY_INGEST_ARTICLES` |
| Jetstream social signal | Built, off by default | `STREAM_SOCIAL_ENABLED` |
| Reuters feeds (`feeds.reuters.com` does not resolve) | Marked inactive | `RSSSource.active=False` |

## Compatibility rules

- `python ingestion_pipeline.py [--schedule]`, `python pipeline.py`, `python run_mapnai.py` keep working with the
  same output; the batch path reuses the same phase functions as the stream.
- `fetch_rss_source(source, max)` keeps its signature (tested); the stream uses the new `poll_rss_source`.
- `ArticleDeduplicator.is_duplicate/register/load_existing_hashes` keep their signatures; additions are optional
  parameters and new methods.
- Personalization writes stay additive and field-scoped (`hot`, `sightings` are new fields).
- Existing tests must keep passing; the two schedule assertions in `tests/test_pers_phase8.py` are updated for
  the new crons (alerts `2-59/5`, a new `hotness` job).

## Phase 1 — Sources and polling

| File | Change |
|---|---|
| `config/sources.py` | `RSSSource.role` (`section`/`top_stories`), `store_items`; `TOP_STORIES_RSS` (ToI top stories, BBC News front page — stored; Google News IN top / Sports / Entertainment — prominence only); Reuters entries `active=False`; `STREAM_RSS_SOURCES` |
| `config/settings.py` | `stream_*` knobs, `dedup_seed_days`, `bluesky_ingest_articles`, `risk_share_in_cluster`, social knobs |
| `stream/__init__.py`, `stream/polling.py` (pure) | `item_key(entry)`, `next_interval(prev, outcome, new_count, role, cfg)`, `bounds(role, cfg)`, `due(states, now)`, `remember_seen(seen, keys, cap)` |
| `storage/source_state_store.py` | `source_state` collection: `ensure(sources)`, `get_all()`, `due(now)`, `record_poll(name, result, now)`, `health()`; `prominence` collection: `add_prominence(rows)`, `prominence_since(t)` (TTL index 3 days); `stream_status` heartbeat |
| `agents/rss_fetcher.py` | `poll_rss_source(source, state, max) → PollResult{status, articles, prominence, etag, last_modified, seen_keys, error}`: conditional GET, 304, seen filter; prominence rows for `top_stories` feeds; items of `store_items=False` feeds become prominence only |

## Phase 2 — Shared ingestion + coverage-preserving dedup

| File | Change |
|---|---|
| `utils/deduplicator.py` | Banded SimHash index (4×16 bits) with exact Hamming check; `find_duplicate(...) → Optional[str]` (matched article id); `register(hash, article_id=None, source=None)`; `load_existing_hashes` accepts strings or `{dedup_hash, article_id, source_name}` docs; `source_of(id)` |
| `agents/preprocessing_agent.py` | Uses `find_duplicate`; a cross-outlet duplicate adds `{source, at}` to `self.sightings[original_id]`; `existing_docs` seeding |
| `storage/mongo_store.py` | `get_recent_hash_docs(days)`; `record_sightings({id: [{source, at}]})` (push only if the source is new); pending queues sorted `hot.score` desc first; `find_cluster_risk(cluster_id, exclude)` |
| `ingestion_pipeline.py` | `ingest_batch(raw, dedup_agent=None, save_faiss=True) → stats`; `_store_phase(save_faiss)`; sightings written after the store; seeding from the last `dedup_seed_days`; Bluesky only when `bluesky_ingest_articles`; `run_ingestion_pipeline` becomes fetch + `ingest_batch` (same stats) |

## Phase 3 — Agents in the worker

| File | Change |
|---|---|
| `pipeline.py` | `AgentPool` (resident NER / classifier / summarizer / risk scorer / FAISS / Mongo; `close()`); `run_agent_pipeline(..., pool=None, article_ids=None)` — with a pool nothing is reloaded or closed; risk sharing in the Agent 4 step (`risk_shared` stat) |
| `storage/mongo_store.py` | `update_article_risk` allows `risk_shared_from`; `get_articles_by_ids` |

## Phase 4 — Stream worker

| File | Change |
|---|---|
| `stream_worker.py` | `StreamWorker`: tick loop, due sources polled in a thread pool, buffer, flush (`ingest_batch` → Agents 1–2 on the flushed ids → Agents 3–4 up to `stream_llm_per_flush`, hottest first), API fetchers / scrapers on fixed intervals, FAISS save throttle, dedup re-seed every 24 h, heartbeat, graceful shutdown; CLI `--once`, `--no-agents`, `--llm-per-flush`, `--max-ticks` |
| `docker-compose.yml` | `stream` service (`python stream_worker.py`, restart unless-stopped) |

## Phase 5 — Hotness

| File | Change |
|---|---|
| `config/personalization.py` | `hot_*` knobs, `job_hotness`, `job_cluster="*/5 * * * *"`, `job_alerts="2-59/5 * * * *"`, `rescore_window_d`, `top_hot_weight`, breaking alert + push knobs, `alert_prefs_default` + `breaking_for_you`, `breaking_global` |
| `personalization/hotness.py` (pure) | `strip_publisher`, `outlets(members, sightings)`, `prominent(members, signals, cfg)`, `components(...)`, `hotness(cluster, now, cfg) → {score, tier, components, …}`, `tier(...)`, `history_due(prev, new, cfg)` |
| `storage/pers_article_store.py` | `count_unclustered(hours, now)`; `rescore_candidates(since)` bounded; `hot_window(hours, now)` projection incl. sightings / urgency / risk; `set_hot(cluster_docs, article_hot)`; `hot_clusters(tiers, since)`; `append_hot_history(rows)`; `social_counts(cluster_ids, since)` |
| `personalization/service.py` | `cluster_articles` skip guard; `compute_hotness(now)`; `top()` ranks by `(1−w)·m + w·H`; `breaking(hours, limit, tz, include_trending)`; `_story_item` adds `hot` |
| `personalization/jobs.py` | `hotness` job (scheduled) |

## Phase 6 — Personal hits + push

| File | Change |
|---|---|
| `personalization/alerts.py` | `breaking_candidates(...)`, `global_allowed(...)` pure helpers |
| `personalization/service.py` | `run_alerts`: exposure pass (unchanged) + breaking pass (`breaking_for_you`, `breaking_global`), `kind` on every alert, then `push_due(now)`; `alerts()` handles alerts without an exposure path; `_alert_prefs_in` accepts the two booleans; push token methods |
| `personalization/push.py` | `build_message(alert)`, `ExpoPushClient.send(messages)` / `receipts(ids)` (requests, batches of 100, injectable session), ticket / receipt interpretation |
| `storage/pers_log_store.py` | `push_tokens` collection (`register_token`, `deactivate_token`, `tokens_for(users)`), `alerts_to_push(now, max_age)`, `set_push(alert_id, push)`, `push_receipts_due(before)` |
| `api/personalization_router.py` | `GET /v1/articles/breaking`, `POST /v1/users/{id}/push_tokens`, `DELETE /v1/users/{id}/push_tokens/{token}`; `AlertPrefsPatch` + 2 booleans |
| `api/admin_router.py` | `GET /v1/admin/sources` |

## Phase 7 — Social signal (optional, default off)

| File | Change |
|---|---|
| `agents/social_signal.py` | `WatchList` (terms per trending/breaking cluster), `match_post(text, links, watch)`, `Buckets` (10-min counts, flush to `social_signals`), `JetstreamCollector` thread (websocket-client) |
| `stream_worker.py` | starts / stops the collector when `stream_social_enabled` |

## Phase 8 — Mobile

| File | Change |
|---|---|
| `mobile/src/api/types.ts` | `HotInfo`, `StoryItem.hot`, `Alert.kind`, `AlertPrefs` booleans |
| `mobile/src/api/endpoints.ts`, `mockServer.ts`, `fixtures.ts` | `breaking()`, `registerPushToken()`, `unregisterPushToken()` |
| `mobile/src/api/hooks.ts` | `useBreaking()` (refetch every 5 min) |
| `mobile/src/lib/push.ts` | permission, Android channel, Expo push token, registration with the API, tap → story |
| `mobile/src/app/_layout.tsx` or `(tabs)/_layout.tsx` | register once signed in; notification tap listener |
| `mobile/src/app/(tabs)/index.tsx` | Breaking strip |
| `mobile/src/app/(tabs)/flash.tsx` | breaking stories first after the brief |
| `mobile/src/app/settings/notifications.tsx` | two toggles |

## Phase 9 — Tooling, docs

- `scripts/replay_hotness.py` — replay stored articles in 15-min steps; per-day tier counts and first-breaking times.
- `scripts/stream_benchmark.py` — dedup lookup timing (linear vs banded) for the report.
- README: "Continuous stream" section; `.env.example`: new knobs.
- `continousexplanation.md` re-checked against the final code.

## Test plan

| Test file | Covers |
|---|---|
| `tests/test_stream_polling.py` | interval rules and bounds, equilibrium behaviour, seen-key cap, due selection, item keys |
| `tests/test_stream_fetch.py` | `poll_rss_source`: 304, conditional headers sent, seen filter, prominence-only feed, top-stories prominence rows, errors; `SourceStateStore` on mongomock |
| `tests/test_stream_dedup.py` | banded index equals the linear scan on random fingerprints; matched id; sightings (cross-outlet only); seeding from docs; Mongo `record_sightings` idempotence |
| `tests/test_stream_worker.py` | one tick with fake fetchers / ingest / agents: flush timing, buffer cap, FAISS save throttle, heartbeat, agent budget |
| `tests/test_hotness.py` | components, renormalization, decay, tiers (incl. the worked examples of the explanation), prominence title match, history rule; service `compute_hotness` on mongomock; cluster skip guard; `top()` blend; `breaking()` |
| `tests/test_breaking_alerts.py` | `breaking_for_you`, `breaking_global` opt-in and cap, one per cluster across kinds, quiet hours, prefs validation, `alerts()` output for breaking kinds |
| `tests/test_push.py` | message building, batching by 100, ticket errors deactivate tokens, receipts, stale alerts skipped, `push_due` marks alerts, token endpoints |
| `tests/test_pipeline.py` (extended) | `AgentPool` reuse, risk sharing, hot-first queue order |
| `tests/test_social_signal.py` | watch list terms, post matching, bucket flush |

Done = the isolated suite passes (821 + new), `npx tsc --noEmit` passes in `mobile/`, and a one-tick dry run of
the worker against fakes produces articles, sightings and a heartbeat.
