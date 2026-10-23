# SOTA TARGETS (Phase 1)

**Date:** 2026-10-23 · **Branch:** `research/sota-push` (tag `pre-phase1`) · No code was changed in this phase.
Every number below was read from the primary source named in its row, on 2026-10-23. Where two primary sources disagree, both values are given. Machine-readable leaderboard snapshot: `research/experiments/results/p1_aggrefact_leaderboard_2026-10-23.json` (42 models, parsed from the site's own data file at commit `5c43d7b5`, averages recomputed and matching the site to rounding).

## Gate 1 summary

| Scorecard target | SOTA / reference number | Primary source | Status |
|---|---|---|---|
| S1 harness validity | MiniCheck-Flan-T5-L **75.0** BAcc (11 datasets, LLM-AggreFact test 29,320, threshold 0.5); paper: **74.7** (10 datasets, 13K test, no RAGTruth). Per-dataset values identical in both | leaderboard data file `5c43d7b5`; arXiv 2404.10774v2 Table 2 | VERIFIED |
| S2 current gate on news subsets | No published number (MAPNAI-specific). Context: CNN / XSum / MediaS for MiniCheck-FT5 = 69.9 / 74.3 / 73.6 | leaderboard | VERIFIED (context); target: none (as specified) |
| S3 CAFG-L+M vs MiniCheck-alone | Reference = our own MiniCheck-FT5 run (S1). Closest prior cascade on LLM-AggreFact: cascade 74.10 vs frontier LLM 73.83 on 495 claims | arXiv 2610.20634 v1 | VERIFIED |
| S5 ceiling | Bespoke-MiniCheck-7B **77.4** (CNN 65.5 / XSum 77.8 / MediaS 76.0). Overall #1 = nimble-v4-max **79.5** (27B, API only) | leaderboard | VERIFIED; our run PENDING (Colab) |
| S6 clustering | B³ F1 **94.76** (P 94.28 / R 95.25) Saravanakumar 2021; 94.41 Staykovski 2019; 92.36 Miranda 2018, English subset | EACL 2021 PDF, Table 1 (p. 7) | VERIFIED. Data downloadable; **data licence UNVERIFIED**; download not approved → optional |
| (optional) MIND ranking | Official leaderboard #1 (team "zetik"): AUC 0.7326 · MRR 0.3780 · nDCG@5 0.4175 · nDCG@10 0.4735. This is the **MIND-large test** leaderboard; **no official MIND-small leaderboard** | msnews.github.io | VERIFIED; not comparable to any MIND-small number |

Gate 1: **PASS.** Every §S target has a primary-source number or a stated alternative (S2 has no target by design; S4 is MAPNAI-internal).

---

## 1a. LLM-AggreFact

### Sources

| Source | URL | Retrieved | Notes |
|---|---|---|---|
| Leaderboard site | https://llm-aggrefact.github.io/ | 2026-10-23 | 42 models, 14 shown by default. No date on the page |
| Leaderboard data file | https://github.com/llm-aggrefact/llm-aggrefact.github.io/blob/5c43d7b5ea8cb46163327c99ef9aafbf7a26d0cc/src/app/data.tsx | 2026-10-23 | Commit 2026-10-22T02:44Z added nimble-v4-max, Jev 1.1.3.0, nimble-v4. sha256 of file `b6af8082…2b52e` |
| MiniCheck repo | https://github.com/Liyan06/MiniCheck @ `b58b9fa69acbd1015ec970fa65dd752413a053d2` (2025-08-27) | 2026-10-23 | Pin for install (Phase 2) |
| MiniCheck paper | https://arxiv.org/abs/2404.10774 (v2, 2024-10-01); EMNLP 2024 | 2026-10-23 | Table 2 |
| Dataset card | https://huggingface.co/datasets/lytang/LLM-AggreFact | 2026-10-23 | dev 30,420 / test 29,320; CC-BY-ND-4.0; **gated**; evaluation only |

### Top 5 (11-dataset average, fixed threshold, test split)

| # | System | Size | Avg BAcc | Weights | Cost evidence |
|---|---|---|---|---|---|
| 1 | nimble-v4-max | 27B | 79.5 | API only (Bespoke console) | UNVERIFIED |
| 2 | Jev 1.1.3.0 | not stated | 78.7 | API only (typesafe.ai) | arXiv 2610.20634 (495-claim subset, not the full test): "≈ 187× cheaper" than its frontier-LLM comparator, which costs USD 8.93 per 1k claims → Jev ≈ USD 0.048 per 1k (**derived as 8.93 / 187, not quoted**) |
| 3 | nimble-v4 | 9B | 77.8 | API only | UNVERIFIED |
| 4 | **Bespoke-MiniCheck-7B** | 7B (HF metadata: 8B params) | 77.4 | Open, **CC BY-NC 4.0**, safetensors BF16, `custom_code` (internlm2) | ≈ 50 min for the 29K test on one A6000 48 GB (repo notebook) |
| 5 | Claude-3.5 Sonnet | – | 77.2 | API | UNVERIFIED |

Best **open-weight** checker: Bespoke-MiniCheck-7B (77.4). Next open: Granite Guardian 3.3 8B (76.5; licence not checked).

### Small checkers (≤ 1B), fixed threshold 0.5

| System | Size | Avg (11) | CNN | XSum | MediaS | News-3 mean | Weights (HF, revision) | Licence |
|---|---|---|---|---|---|---|---|---|
| FactCG-DeBERTa-L | 0.4B | **75.6** | 70.1 | 73.9 | 72.3 | 72.10 | `yaxili96/FactCG-DeBERTa-v3-Large` @ `0430e350…`, **safetensors** | MIT |
| MiniCheck-Flan-T5-L | 0.8B | 75.0 | 69.9 | 74.3 | 73.6 | **72.60** | `lytang/MiniCheck-Flan-T5-Large` @ `96eafd01…`, **pickle `.bin` only** | MIT |
| MiniCheck-RoBERTa-L | 0.4B | 73.5 | 63.7 | 70.8 | 71.9 | 68.80 | `lytang/MiniCheck-RoBERTa-Large` | not checked |
| MiniCheck-DeBERTa-L | 0.4B | 73.1 | 64.2 | 71.0 | 69.3 | 68.17 | `lytang/MiniCheck-DeBERTa-v3-Large` @ `2f2d01a5…`, **pickle `.bin` only** | MIT |
| HHEM-2.1-open | 0.1B | 71.8 | 62.8 | 67.8 | 67.2 | 65.93 | not checked | – |
| AlignScore | 0.4B | 70.5 | 52.4 | 71.4 | 69.2 | 64.33 | not checked | – |
| SummaC-ZS | 0.1B | 67.7 | 51.1 | 61.5 | 69.5 | 60.70 | not checked | – |

- **Has anything ≤ 1B overtaken MiniCheck-FT5?** Yes, on the 11-dataset average: **FactCG-DeBERTa-L, 75.6 vs 75.0** (fixed 0.5; FactCG paper Appendix A.3 confirms 75.6 at threshold 0.5). On the three news subsets, MiniCheck-FT5 is higher (72.60 vs 72.10).
- **News subsets:** the best News-3 mean on the whole board is nimble-v4-max at 73.17, then Bespoke-7B 73.10, nimble-v4 72.93, **MiniCheck-FT5 72.60**. On news, the 0.8B checker is within 0.57 BAcc of the best system listed.
- **Off-leaderboard claims:** FactCG paper Table 3 reports **77.2** for FactCG-DBT, but with **per-dataset thresholds tuned on dev** (a different protocol; see below). Paladin-mini (3.8B, arXiv 2506.20384) claims grounding SOTA, but the abstract gives no LLM-AggreFact number: UNVERIFIED. A search for 2026 claims found none above the leaderboard.

### Exact evaluation protocol (MiniCheck repo `b58b9fa`, `benchmark_evaluation_demo.ipynb` and `minicheck/inference.py`)

1. Data: `load_dataset("lytang/LLM-AggreFact")["test"]`; fields `dataset, doc, claim, label` (1 = supported).
2. Prediction: `pred = 1 if max_support_prob > 0.5 else 0` (strict `>`, fixed threshold, **no tuning**; the paper calls this the zero-shot deployable setting).
3. Chunking: document split with NLTK `sent_tokenize` per newline block; greedy chunks of ≈ 500 tokens (Flan-T5) / 400 (DeBERTa, RoBERTa); claim scored against every chunk; **max over chunks**. `max_model_len` 2048 (FT5, DeBERTa), 512 (RoBERTa); Bespoke-7B 32,768 with chunk = max_len − 300.
4. Metric: `sklearn.metrics.balanced_accuracy_score × 100` per `dataset`; **Average = unweighted mean over the 11 datasets**.
5. Subsets (11): AggreFact-CNN, AggreFact-XSum, TofuEval-MediaS, TofuEval-MeetB, WiCE, REVEAL, ClaimVerify, FactCheck-GPT, ExpertQA, LFQA, RAGTruth.
6. **Two protocols exist and must never be mixed:** (P-fixed) threshold 0.5, the leaderboard's protocol; (P-tuned) per-dataset thresholds tuned on dev, as in FactCG Table 3 (77.2 vs 75.6 under P-fixed).

## 1b. News-relevant subsets

| System | AggreFact-CNN | AggreFact-XSum | TofuEval-MediaS |
|---|---|---|---|
| nimble-v4-max | 67.6 | 78.6 | 73.3 |
| Bespoke-MiniCheck-7B | 65.5 | 77.8 | **76.0** |
| gpt-4o-2024-05-13 | 68.1 | 76.8 | 71.4 |
| FactCG-DeBERTa-L (P-fixed) | **70.1** | 73.9 | 72.3 |
| MiniCheck-Flan-T5-L | 69.9 | 74.3 | 73.6 |
| MiniCheck-DeBERTa-L | 64.2 | 71.0 | 69.3 |
| AlignScore | 52.4 | 71.4 | 69.2 |

All 42 rows are in the JSON snapshot. Origins: AggreFact (Tang et al., ACL 2023, 10.18653/v1/2023.acl-long.650); TofuEval (Tang et al., NAACL 2024, 10.18653/v1/2024.naacl-long.251). MediaS is interview-transcript summarization, so it is news-adjacent rather than news text; this caveat goes into the report.

## 1c. Prior art on cascades and risk-controlled gating: is CAFG novel?

| Work | What it does | Relation to CAFG |
|---|---|---|
| FrugalGPT, Chen, Zaharia, Zou, arXiv 2305.05176 (2023) | Learned cascade over LLMs, cheapest first | Generic cheap-first cascading is established |
| Dekoninck, Baader, Vechev, ICML 2025 (PMLR 267:12987–13010) | Unified, provably optimal cascade routing; quality estimators are the critical factor | Cascade/routing theory exists |
| **Do Rosario & Atef, arXiv 2610.20634 (2026-09-30)** | Confidence-gated cascade on LLM-AggreFact (495 claims): non-generative verifier → frontier LLM. Cascade 74.10 vs LLM 73.83; **a matched random-escalation control performs about as well as confidence gating** | **Near-identical in structure** for the learned-checker part. No lexical stage, no compression/omission handling |
| Valentin et al., arXiv 2407.21424 (2024, AWS) | Choose a subset of detection scores under a compute budget | Budgeted scoring; not escalation |
| Lei et al., arXiv 2310.03951 (CoNLI, 2023) | Hierarchical NLI + entity-level hallucination detection | Multi-stage, but not cost-ordered (as far as the abstract states) |
| Mohri & Hashimoto, arXiv 2402.10978 (2024) | Conformal factuality guarantees by backing off claims | Risk-controlled output; not a serve/fallback gate |
| vLLM HaluGate blog (2025-12-14) | Production two-stage: request classifier → token detector + NLI | Engineering precedent, not peer-reviewed |

**Verdict (honest):** a cheap-first **cascade** is **not novel**, and a confidence-gated small-checker → large-model cascade on LLM-AggreFact already exists. What we did not find in prior work: (i) a **deterministic lexical stage** (numbers, names, months) that makes hard reject decisions before any learned checker; (ii) **compression awareness**, i.e. separating omission forced by a reader's length budget from addition/distortion, in a serve-or-fallback gate; (iii) evaluation of such a gate on **style-personalized news rewrites**. CAFG is therefore re-scoped in `PREREG.md` as an **application/combination (A + EE), not a new cascade method**, and the random-escalation control from 2610.20634 becomes mandatory. Any claim must be about (i)–(iii), not about cascading itself. Residual risk: searches were limited to web search on 2026-10-23.

## 1d. Stream news clustering

- Code: `github.com/priberam/news-clustering` (BSD-3 for the **software**; superseded by `Priberam/projected-news-clustering`).
- Data: `ftp://ftp.priberam.pt/SUMMAPublic/Corpora/Clustering/2018.0/dataset/` with login `ftp.priberam.pt|anonymous`. Listing confirmed 2026-10-23: `dataset.test.json` 49,284,104 B and `dataset.dev.json` 57,925,165 B (2018-11-27). The plain `anonymous` login fails (530, "Valid hostname is expected"). **Not downloaded** (not on the approved list).
- **Data licence: not stated** in the repo; the files contain third-party news articles → H4 if pursued.
- Published B³ (English subset, test; Saravanakumar et al. EACL 2021 Table 1, PDF p. 7): Miranda 2018 F1 92.36 (P 94.27 / R 90.25; 326 clusters); Staykovski 2019 94.41 (95.16 / 93.66; 484); Saravanakumar best 94.76 (94.28 / 95.25); 5-run mean 94.75 ± 0.59 (p. 8). No newer result found in one extended search (UNVERIFIED that none exists).
- Decision: the public-benchmark claim is **kept as optional and conditional** (requires download approval + data-terms check); D2-1 held-out pairs remain the primary clustering evidence.

## 1e. MIND (optional)

- msnews.github.io: research-only download under the Microsoft Research License; the official leaderboard is for MIND-large test. #1: AUC 0.7326, MRR 0.3780, nDCG@5 0.4175, nDCG@10 0.4735. MIND-small has no official test set or leaderboard, so **no SOTA comparison is possible on MIND-small**; any MIND-small ranking number would be descriptive only.

## Supply-chain notes for Phase 2

- `lytang/MiniCheck-Flan-T5-Large` and `-DeBERTa-v3-Large` ship **only pickle `pytorch_model.bin`**. Third-party safetensors PRs exist (`refs/pr/1`, `refs/pr/2`) but have unknown authors and will not be used. Plan: download `main` at the pinned sha, load with `torch.load(weights_only=True)`, convert locally to safetensors, verify bit-identical predictions on the smoke set.
- `transformers ≥ 4.50` refuses `.bin` loading on `torch < 2.6`; the app venv pins torch 2.3.0 → the checkers need a **separate venv** (`~/.venvs/mapnai-checkers`) so the app's pinned environment stays untouched.
- `minicheck` declares unpinned dependencies (`torch, transformers, datasets, nltk, pandas, numpy, openai`); we pin them ourselves.
- Bespoke-7B requires `trust_remote_code` (`modeling_internlm2.py`, 80 KB) and vLLM (Linux only) → Colab only, code to be read before use.
