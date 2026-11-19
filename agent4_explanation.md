# Agent 4 — Offline Risk Scorer: Merge Guide

Everything the team needs to merge the Agent 4 work on `feat/risk-labelling-kaggle` with the rest of MAPNAI.
For the full design and metrics, see [`AGENT4_RISK_ARCHITECTURE.md`](AGENT4_RISK_ARCHITECTURE.md).

---

## 1. Summary

Agent 4 (risk scoring) no longer needs an LLM. With **`RISK_BACKEND=model`, which is now the default**, it scores
every article with MAPNAI's own fine-tuned **DistilRoBERTa** event classifier plus formulas over Agent 1–3
outputs. There are no Groq calls, no Ollama, no API key and no daily limit. The old LLM scorer is still there:
`RISK_BACKEND=auto | groq | ollama` behaves exactly as before.

| | Before | After (`RISK_BACKEND=model`) |
|---|---|---|
| Scoring engine | Groq `llama-3.3-70b`, or local Ollama `qwen2.5:7b` | DistilRoBERTa (82M parameters) + formulas |
| Needs | `GROQ_API_KEY` and/or Ollama with a ~5 GB model | The `models/risk_event/` folder (~330 MB) |
| Cost and limits | Groq daily token cap, rate limits | None |
| Speed | 1–10 s per article (network or local LLM) | **~190 ms per article on CPU**; ~20 s one-time load |
| When it can't score | Article left pending (`risk_skipped`) | Never: falls back to TF-IDF, then keyword rules |
| Output fields / MongoDB | — | **Unchanged** contract |

**Accuracy** on 86 hand-labelled gold articles (event type, which drives severity):

| Model | Accuracy | Macro-F1 | High-severity recall |
|---|---|---|---|
| **DistilRoBERTa (main)** | **73.3%** | **0.677** | **92.7%** |
| TF-IDF + logistic regression (fallback) | 67.4% | 0.652 | 85.5% |
| Qwen2.5-7B LLM (reference) | 73.3% | 0.698 | 96.4% |

---

## 2. Branch status and merge check

| Branch | Relation to this work |
|---|---|
| `feat/risk-labelling-kaggle` | This work: one commit `6f8ca19` on top of `cleanup@24b3287` |
| `cleanup` | Has one newer commit, `c5baf38` (continuous stream worker, hotness, breaking alerts, Expo push) |
| `main` | Behind both: it doesn't yet have the `cleanup` work this branch is based on |

**Trial merge (done 2026-11-19):** `feat/risk-labelling-kaggle` merged into `origin/cleanup@c5baf38`:

- **No conflicts.** `.env.example`, `README.md` and `config/settings.py` auto-merged, because the changes are in
  different sections.
- **All 934 tests pass** on the merged result, including the new stream-worker tests.

### How to merge

```bash
git fetch origin
git checkout cleanup
git pull
git merge --no-ff origin/feat/risk-labelling-kaggle
python -m pytest -q          # expect all tests to pass
git push origin cleanup
```

When `cleanup` is later merged into `main`, the Agent 4 work goes with it.

---

## 3. Behaviour changes everyone should know

1. **The default backend changed from `auto` to `model`.** Anyone with `RISK_BACKEND=auto` in their own `.env`
   keeps the LLM scorer. Delete that line, or set it to `model`, to switch.
2. **An unknown `RISK_BACKEND` value now falls back to `model`,** not `auto`.
3. **Agent 4 never leaves an article pending in `model` mode.** `risk_skipped` only happens with the LLM backends.
   If every model file is missing, the keyword rules still score.
4. **New `risk_model` values:**
   - `distilroberta:event-v2`: main model
   - `tfidf:event`: fallback
   - `rules:v1`: last resort

   The older values (`groq:<model>`, `ollama:<model>`) still appear on articles scored before the switch. LLM
   scores and model scores aren't on exactly the same scale, so **filter on `risk_model`** when comparing them.
5. **New field `risk_event_type`** (for example `injury` or `integrity`). It is in the payload passed to Agent 5,
   but **not written to MongoDB**, because `update_article_risk` keeps its existing whitelist. Add it to
   `allowed_keys` in `storage/mongo_store.py` if the API or app should show it.
6. **`GROQ_API_KEY` is no longer needed for Agent 4.** It's still used by Agent 3 (LLM summaries) and Agent 5.

---

## 4. How this interacts with the newer `cleanup` work (`c5baf38`)

| Teammate feature | Interaction | Action needed |
|---|---|---|
| **Risk sharing in clusters** (`_shared_risk` in `pipeline.py`, `RISK_SHARE_IN_CLUSTER`, `find_cluster_risk`) | Compatible: it copies a cluster-mate's score, including `risk_model`. It was built to save LLM calls, and Agent 4 is now cheap, so sharing is optional. A shared score also carries the sibling's entity salience and urgency. | None. Consider `RISK_SHARE_IN_CLUSTER=false` so every article gets its own score. |
| **Stream worker** (`stream_worker.py`, `STREAM_LLM_PER_FLUSH`) | Agents 3–4 run on at most `STREAM_LLM_PER_FLUSH` articles per flush, treated as LLM work. Agent 4 is no longer LLM work, but Agent 3 still can be. | None for correctness. Follow-up: run Agent 4 on every flushed article and keep the limit only for Agent 3. |
| **Agent pool in `pipeline.py`** (agents reused across runs) | Good fit: the DistilRoBERTa model loads once (~20 s) and is reused. | None. |
| **`scripts/backfill_a4.py`** | Still works: it calls `RiskScoringAgent.score()`. Its rate limiter and daily cap were designed for Groq and are unnecessary in model mode, but harmless. | Optional: raise `--rpm` and `--daily-cap` for fast backfills. |

---

## 5. What changed (files)

**New**

| File | Purpose |
|---|---|
| `agents/risk_model.py` | Offline scorer: three event tiers, factor formulas, confidence, recommendation templates |
| `config/risk_taxonomy.py` | Single source of truth: 8 event types, their severities, keyword rules, doping-label fix |
| `tests/test_agent4_model.py` | 9 offline tests: tier fallback, formulas, output contract, no-LLM guarantee |
| `scripts/risk/train_event_model.py` | Trains the TF-IDF fallback on CPU (< 1 min) |
| `scripts/risk/train_event_distilroberta.ipynb` | Trains DistilRoBERTa on a Kaggle or Colab GPU (~20 min), with gold evaluation |
| `scripts/risk/label_kaggle.ipynb`, `label_colab.ipynb` | One-time LLM labelling of training data (offline, never at runtime) |
| `scripts/risk/build_topup.py` | Mines extra rare-event articles (doping, bans, cancellations, legal) for labelling |
| `data/risk/risk_labeled.jsonl` | 5,347 v2 training labels (Qwen2.5-7B, prompt v2) |
| `data/risk/candidates_extra.jsonl` | 1,077 top-up candidate articles |
| `data/risk/gold_*.csv`, `gold_ids.txt` | Gold set (97 ids) and the LLM's answers for it |
| `data/risk/ANNOTATION_GUIDE.md` | How the gold set is hand-labelled |
| `data/risk/v1/` | First-round (v1) labels, kept for reference |
| `AGENT4_RISK_ARCHITECTURE.md` | Design, formulas, metrics, status |
| `agent4_explanation.md` | This file |

**Modified**

| File | Change |
|---|---|
| `agents/agent4_risk_scorer.py` | `RISK_BACKENDS` gains `model`. In model mode it creates `OfflineRiskScorer` and no LLM clients, and `score()` delegates to it. LLM paths are unchanged. |
| `config/settings.py` | `risk_backend` default is `model`; new `risk_event_model_dir`, `risk_tfidf_model_path` |
| `run_mapnai.py` | `--check` reports both Agent 4 models in model mode (Ollama is checked only for `auto`/`ollama`) |
| `.env.example`, `README.md` | Document `RISK_BACKEND=model` and model setup |
| `tests/test_agent4_backends.py` | The unknown-backend test now expects `model` |

**Not touched:** `storage/mongo_store.py`, `pipeline.py`, `agents/pipeline_bridge.py`, the API, the mobile app,
and Agents 1–3 and 5.

---

## 6. Setting up the models (not in git)

`models/` is gitignored, and the DistilRoBERTa weights (~330 MB) are over GitHub's 100 MB limit.

| Model | How to get it | If missing |
|---|---|---|
| DistilRoBERTa (`models/risk_event/`) | Unzip `mapnai_risk_event_model.zip` (ask the Agent 4 owner) into `models/`, so that `models/risk_event/config.json` exists. Or retrain with `scripts/risk/train_event_distilroberta.ipynb`. | Agent 4 uses TF-IDF |
| TF-IDF (`models/risk/event_model.joblib`) | `python -m scripts.risk.train_event_model`, which builds it from the committed labels | Agent 4 uses keyword rules |

Check:

```bash
python run_mapnai.py --check
# [OK  ] Agent 4 DistilRoBERTa event model
# [OK  ] Agent 4 TF-IDF fallback model
# Agent 4 risk backend: model
```

> Follow-up worth doing: host `risk_event/` on Hugging Face (like Agent 2's `satvik4577/mapnai-classifier`) so it
> downloads automatically.

---

## 7. How a score is computed (short version)

```
risk_score = event_severity + entity_salience + temporal_urgency + domain_criticality      (each 0–25)
```

| Factor | Source |
|---|---|
| `event_severity` | Event type from DistilRoBERTa → fixed severity: routine 2, controversy 8, injury 12, legal 16, ban_suspension 17, cancellation 18, integrity 21, death_tragedy 25. A keyword match for a more severe type wins if the model gives it ≥ 20% probability. |
| `entity_salience` | Agent 1: top entity's salience and mention count |
| `temporal_urgency` | Agent 2's `urgency_flag`, negative sentiment, article age (`published_at`), urgent words |
| `domain_criticality` | Domain base (sports 12, entertainment 8, other 5), plus up to 8 when the model says something went wrong |

- **Level:** MONITOR (0–39), ALERT (40–69), ESCALATE (70–100). Same bands as before.
- **Confidence:** the model's top-class probability after temperature scaling. Calibration error is 0.029.
- **Recommendation:** a template by level and event type. For example: *"Escalate now: a cancellation or
  postponement involving City FC ("called off"); verify with official sources and brief stakeholders."*

**Example outputs:**

| Article | Score | Level | Event type |
|---|---|---|---|
| Match called off after stadium roof collapse | 71 | ESCALATE | cancellation |
| Sprinter tests positive for banned steroid | 84 | ESCALATE | integrity |
| Actor's remarks spark backlash online | 50 | ALERT | controversy |
| Film crosses 100 crore at the box office | 18 | MONITOR | routine |
| "Movie *killed it* at the box office" | 18 | MONITOR | routine (not a death) |

---

## 8. Verification checklist after merging

- [ ] `python -m pytest -q` passes. 934 tests passed on the trial merge.
- [ ] `python run_mapnai.py --check` shows both Agent 4 models as OK and `Agent 4 risk backend: model`
- [ ] One pipeline run: articles get `risk_model = distilroberta:event-v2` in MongoDB
- [ ] Stream worker run: the flush log shows Agent 4 scores, with no Groq calls attributed to Agent 4
- [ ] Spot-check 10–20 recent articles: do the levels match human judgement?

---

## 9. Rolling back

Set `RISK_BACKEND=auto` in `.env`. Agent 4 returns to Groq with Ollama as fallback, with no code changes.
Already-written model scores stay in MongoDB, marked by `risk_model`.

---

## 10. Known limitations and open items

1. **The factor weights are starting values,** not yet tuned on real pipeline articles.
2. **`controversy` is the weakest event type,** because it depends on tone. The model sometimes confuses it with
   `routine` or `legal`.
3. **The labels come from Qwen2.5-7B.** Its doping mistakes are corrected by a keyword rule at training time
   (259 rows relabelled to `integrity`).
4. **`risk_event_type` isn't stored in MongoDB** (see section 3, point 5).
5. **The model file has to be shared by hand** until it's on Hugging Face.
6. **The hand-labelled gold CSV is on the Kaggle dataset.** `data/risk/gold_to_label.csv` in git is still blank and
   should be replaced with the labelled copy.
