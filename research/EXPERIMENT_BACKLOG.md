# MAPNAI — Experiment Suite and Implementation Roadmap (Phase 7)

**Date:** 2026-10-23 · **Primary direction:** D3 (`PROPOSED_RESEARCH_PLAN.md`) · **Status key:** ✅ executed · ⏳ proposed · ⛔ blocked pending approval

No experiment assumes the proposed method wins. Each one states how a negative result is read.

---

## 0. Already executed (Phase 5)

| ID | Name | Status | Output |
|---|---|---|---|
| E01 | Clustering pair rule: CIs, LOOCV, ablations, dedup baseline | ✅ | `experiments/results/e01_cluster_pairs_2026-10-23.json` (+ sweep CSV) |
| E02 | **SYNTHETIC** gate stress test on 1,843 real summaries | ✅ | `experiments/results/e02_gate_perturbation_2026-10-23.json` (+ items CSV) |
| E03 | Live descriptives (read-only) | ✅ | `experiments/results/e03_live_descriptives_2026-10-23.json` |
| — | `scripts/calibrate_clustering.py` reproduction; partial test-suite run | ✅ (Phase 1) | Documented in `PROJECT_AUDIT.md` |

---

## 1. Minimum credible experiment suite (D3)

### EXP-1 · Baseline validation on natural rewrites (pilot)

| Field | Content |
|---|---|
| Experiment | Reproduce the production render path offline and measure the current gate on real rewrites |
| Research question | Precondition for RQ1–RQ3: can the baseline be evaluated reproducibly, and does the synthetic E02 profile appear on natural data? |
| Dataset | 80 MAPNAI sources (stratified: domain × ≤ 50 / > 50 words) from `data/e02_gate_sources_2026-10-23.jsonl` |
| Baseline | Current gate `factcheck.verify` with production inputs |
| Proposed method | None (baseline only) |
| Metrics | Serve rate, gate reasons, length compliance, generation latency / errors |
| Procedure | 1. `e10_select_sources.py --n 80 --seed 13`. 2. `e11_generate_rewrites.py --cells short,medium × plain/low --model openai/gpt-oss-120b --prompt r2` (160 rewrites; uses `render.build_messages`, no cache writes). 3. `e14_score_gates.py --gates v1`. 4. Compare the serve rate against E03's 4/12. |
| Expected output | `rewrites_pilot.jsonl`, `scores_pilot.jsonl`, a serve-rate table by length |
| Success criteria | The harness re-creates production behaviour: the same prompt version and model, and the gate decision is identical when re-run |
| Failure interpretation | If the Groq model or rate limits prevent the run, stop and choose a model before anything else. If the serve rate is ≈ 100%, the problem may be smaller than E02 suggests; RQ2(b) is then at risk |
| Dependencies | Groq key (present); ≈ 160 LLM calls |

### EXP-2 · Annotation pilot and agreement

| Field | Content |
|---|---|
| Experiment | Validate the faithfulness guideline |
| Research question | Can the ground truth be labelled reliably? |
| Dataset | The 160 EXP-1 rewrites (80 sampled for double annotation) |
| Baseline | n/a |
| Proposed method | `research/annotation/GUIDELINES_D3.md` (taxonomy after [Devaraj2022], plus salient/minor omission) |
| Metrics | Cohen's κ (faithful vs unfaithful; omission salient vs minor), raw agreement, per-type confusion |
| Procedure | 1. Write and freeze the guideline. 2. Export blind CSV (`e12_export_annotation.py`). 3. Two annotators label independently. 4. `e13_import_annotation.py` computes κ. 5. Adjudicate. 6. Revise the guideline once if κ < 0.6, then re-pilot on fresh items. |
| Expected output | κ report; adjudicated pilot labels; **first natural FRR / FAR of the current gate** |
| Success criteria | κ ≥ 0.6 on faithful vs unfaithful |
| Failure interpretation | κ < 0.6 after one revision means "salient omission" is ill-defined. Narrow the paper to additions and distortions, where agreement is usually higher, and report omission descriptively |
| Dependencies | EXP-1; 2–3 annotators × ~6 h |

### EXP-3 · Style-factorial generation and labelling (RQ1)

| Field | Content |
|---|---|
| Experiment | Error rates by style cell and model |
| Research question | RQ1 |
| Dataset | 480 MAPNAI sources (+ 120 MIND abstracts for EXP-7); 8 cells × 2 models ≈ 7,700 rewrites; ~1,000 labelled (stratified, plus an oversample of gate rejects with weights) |
| Baseline | Identity; extractive lead-k within the budget |
| Proposed method | n/a (measurement) |
| Metrics | Per-cell rates (Wilson CIs); odds ratios from mixed-effects logistic regression; length compliance |
| Procedure | Generate all cells. Draw the stratified label sample with a recorded seed. Annotate under the frozen guideline. Fit the pre-registered model `error ~ tone + length + jargon + model + src_len + (1 \| source)`. |
| Expected output | Table 1 (rates per cell); Figure 1 (odds ratios); generation cost table |
| Success criteria | H1 as pre-registered |
| Failure interpretation | No style effect is itself a finding: reader styles are "safe" with this prompt. Report it, and keep RQ2 as the main contribution |
| Dependencies | EXP-2 passes; Groq budget; annotation (~2–3 person-weeks) |

### EXP-4 · Checker comparison (RQ2)

| Field | Content |
|---|---|
| Experiment | Gate vs learned checkers on identical items |
| Research question | RQ2 |
| Dataset | EXP-3 labelled items, test split (70%, grouped by source) |
| Baseline | Current gate; always-serve; always-fallback |
| Proposed method | n/a (comparison of existing checkers): entity precision, SummaC-ZS, AlignScore-large, MiniCheck-Flan-T5-L, cross-family LLM judge (optional Bespoke-MiniCheck-7B on Colab) |
| Metrics | FRR, FAR, per-type recall, AUROC, ms per check, LLM calls |
| Procedure | Install the checkers (⛔ download approval). Tune each threshold on dev for balanced accuracy, and freeze. Score test. Paired bootstrap over sources; McNemar on decisions; Holm correction. |
| Expected output | Table 2 (checker × metric); Figure 2 (FRR vs FAR scatter with cost as marker size) |
| Success criteria | H2(a), H2(b) |
| Failure interpretation | If the current gate is comparable, a cheap lexical gate is adequate for short news items. That is a useful negative result and lowers the case for CAFG-L+M |
| Dependencies | EXP-3; torch + checkpoints (≈ 1.5–3 GB) |

### EXP-5 · CAFG vs baselines (RQ3), the proposed-improvement experiment

| Field | Content |
|---|---|
| Experiment | Compression-aware cascade gate |
| Research question | RQ3 |
| Dataset | Same test split |
| Baseline | Current gate; best single checker from EXP-4 |
| Proposed method | CAFG-L (lexical, steps 0–2) and CAFG-L+M (plus the small checker), from `research/faithgate/cafg.py` |
| Metrics | FRR, FAR (overall and by type), serve rate, checker calls per 1k, latency |
| Procedure | Tune `core` parameters (k) and θ on dev only. Freeze. Score test once. Non-inferiority test on lexical-type FAR (margin 2 points); superiority on FRR (≥ 10 points). |
| Expected output | Table 3; Figure 3 (operating points of every gate on the FRR–FAR plane) |
| Success criteria | H3(a), H3(b) |
| Failure interpretation | If FRR does not fall, the omission problem is not addressable by a simple core-fact rule and needs a learned salience model (future work). If FAR rises, step 1 (addition checks) is insufficient; inspect which additions slip through |
| Dependencies | EXP-4 |

### EXP-6 · Ablation of CAFG

| Field | Content |
|---|---|
| Experiment | Which CAFG part matters |
| Research question | RQ3 (mechanism) |
| Dataset | Test split |
| Baseline | Full CAFG-L+M |
| Proposed method | Remove one at a time: entity normalization; added-name check; core-fact relaxation; month fix; learned stage |
| Metrics | ΔFRR, ΔFAR versus full CAFG |
| Procedure | Re-score with each component disabled (flags in `cafg.py`); paired bootstrap of the differences |
| Expected output | Table 4 (ablation) |
| Success criteria | Each retained component has a CI on ΔFRR or ΔFAR that excludes 0 |
| Failure interpretation | A component with no effect is removed from the method (simpler is better) |
| Dependencies | EXP-5 |

### EXP-7 · Robustness and generalization

| Field | Content |
|---|---|
| Experiment | Does the result hold for another corpus, model, seed and prompt? |
| Research question | RQ1–RQ3 robustness; RQ4 (optional) |
| Dataset | 120 MIND news abstracts [Wu2020MIND] (⛔ download approval); second generator model; a 20% re-generation with a second seed; prompt r3 (fact-anchored) on the short cells |
| Baseline | The main-condition results |
| Proposed method | Same gates; for RQ4, prompt r3 |
| Metrics | The same metrics; the difference from main with CIs |
| Procedure | Repeat EXP-3 → EXP-5 scoring on each variant with the frozen thresholds (no re-tuning) |
| Expected output | Table 5 (robustness) |
| Success criteria | Direction of effects preserved; FRR/FAR within CI overlap |
| Failure interpretation | A corpus-specific effect means the findings are limited to MAPNAI-style synopses. State this as the scope |
| Dependencies | EXP-5; MIND licence acceptance |

### EXP-8 · Efficiency

| Field | Content |
|---|---|
| Experiment | Cost of each gate |
| Research question | RQ2 / RQ3 cost side |
| Dataset | All rewrites |
| Baseline | Current gate (0.5 ms p50 on CPU, from E02) |
| Proposed method | Checkers; CAFG-L+M |
| Metrics | Median / p95 ms per check (CPU and T4); checker calls per 1k; LLM tokens |
| Procedure | Time on fixed hardware, reporting the machine; warm-up excluded |
| Expected output | Table 6 |
| Success criteria | n/a (descriptive) |
| Failure interpretation | n/a |
| Dependencies | EXP-4 |

### EXP-9 · Error analysis

| Field | Content |
|---|---|
| Experiment | Where every gate fails |
| Research question | All |
| Dataset | Test errors of each gate |
| Baseline | n/a |
| Proposed method | n/a |
| Metrics | Counts by error sub-type, style cell, source length, domain |
| Procedure | Sample ≤ 50 false accepts and ≤ 50 false rejects per gate; two authors code the causes (entity fragment, paraphrase, modality, number format, …) |
| Expected output | Qualitative table with examples (paraphrased if licensing requires) |
| Success criteria | n/a |
| Failure interpretation | n/a |
| Dependencies | EXP-5 |

### EXP-10 · Synthetic sanity suite (non-tuning)

| Field | Content |
|---|---|
| Experiment | Re-run E02 on every gate variant |
| Research question | A regression check, not evidence for the hypotheses |
| Dataset | E02 snapshot |
| Baseline | E02 results for the current gate |
| Proposed method | CAFG variants |
| Metrics | Per-edit-type rejection rates |
| Procedure | `e02_gate_perturbation.py`, extended with a `--gate` flag (new tag; old results kept) |
| Expected output | Comparison table |
| Success criteria | Identity pass rate = 1.0; lexical-type detection not lower than baseline |
| Failure interpretation | A drop on a lexical type means CAFG lost a capability. Fix it before EXP-5 is reported. **Never tune on this suite** |
| Dependencies | `cafg.py` |

### Statistical analysis (cross-cutting)

Grouped dev/test split by source article; paired bootstrap (2,000) over sources; McNemar (exact when discordant pairs are < 25); Holm correction across checkers; mixed-effects logistic regression for RQ1; and pre-registration of H1–H3 margins in `PROPOSED_RESEARCH_PLAN.md` **before** EXP-3 labels are seen. Details are in `METRICS_AND_EVALUATION_AUDIT.md` §6.

### Secondary track (enabling; can run in parallel)

| ID | Name | Status | Note |
|---|---|---|---|
| D2-1 | Held-out clustering pair set (≥ 500 pairs: random + band) and re-selection of the clustering rule (cosine-only vs evidence-first vs current) | ⏳ | E01 shows the current threshold is over-fitted (LOOCV F1 0.40) |
| D2-2 | Public stream-clustering benchmark (B³) [Miranda2018] | ⛔ download | Compare against reported B³ F1 92–95 [Saravanakumar2021] |
| ENG-1 | Month-regex boundary fix in `factcheck.py` | ⏳ needs approval | Independent bug fix; re-run E02 identity check afterwards |
| ENG-2 | Rebuild the Agent 5 FAISS index (74% coverage) | ⏳ needs approval | Engineering |

---

## 2. Implementation roadmap

| Stage | Tasks | Relevant files | Dependencies | Deliverables | Completion criteria | Effort | Risks / blockers |
|---|---|---|---|---|---|---|---|
| **1. Baseline validation** | Generation harness; source selection; gate scoring of the production path; EXP-1 | new `research/experiments/e10_*.py`, `e11_*.py`, `e14_*.py`; imports `personalization/render.py`, `factcheck.py`, `utils/groq_client.py` | Groq key; plan approval | `rewrites_pilot.jsonl`, `scores_pilot.jsonl` | Re-running gives identical gate decisions; the prompt and model match production | 4–5 days | Groq model availability or rate limits |
| **2. Data preparation** | Guideline; annotation export/import; EXP-2 pilot; stratified sampling and grouped split; (⛔) MIND abstracts | `research/annotation/GUIDELINES_D3.md`, `e12_*.py`, `e13_*.py` | Stage 1 | Frozen guideline; κ report; labelled pilot; split file | κ ≥ 0.6 | 1.5–2 weeks | Low κ on omissions; annotator time |
| **3. Proposed improvement** | Implement CAFG-L (steps 0–2) and the cascade hook; unit tests incl. the equivalence test with the current gate; checker adapters | new `research/faithgate/cafg.py`, `checkers.py`, `test_cafg.py` | Stage 2 dev split | CAFG module + tests passing | Equivalence test passes; E02 identity = 1.0 under CAFG | 1 week | Overfitting `core` to dev (keep its parameters minimal) |
| **4. Controlled evaluation** | EXP-3 full generation and labelling; EXP-4; EXP-5 | `e11`, `e14`, `e15_analysis.py` | Stages 2–3; ⛔ checker downloads | Tables 1–3, Figures 1–3, stats JSON | Test split scored once; pre-registered tests reported | 3–4 weeks | Too few unfaithful items for per-type stats (mitigated by the reject oversample) |
| **5. Ablation and robustness** | EXP-6, EXP-7, EXP-8, EXP-10 | same | Stage 4 | Tables 4–6 | All variants scored with frozen parameters | 1.5 weeks | MIND licence; a second model unavailable |
| **6. Error analysis** | EXP-9 | `e15_analysis.py` + notebook | Stage 4 | Error taxonomy table with examples | ≥ 50 errors coded per gate | 3–4 days | — |
| **7. Paper preparation** | Methods, results, limitations, ethics (third-party text; no user data); reproducibility appendix; references | `research/paper/` (new), `REFERENCES.bib` | Stages 4–6 | Draft paper; artifact README | Every number traceable to a results file | 2–3 weeks | Novelty overlap discovered late (re-run the targeted literature search before writing) |

**Minimum viable research contribution** (if time runs short): Stages 1–2 plus EXP-3 on the production model only, and EXP-4 with the current gate, MiniCheck and the LLM judge. That yields RQ1 and RQ2 without CAFG and stands on its own as an evaluation paper (title 3 in the plan). CAFG (RQ3) and the robustness work are the extension.

**Do not start** Stage 1 until the plan is approved; checker or dataset downloads need separate approval. Production changes (ENG-1, the `render_gate` setting) are out of scope until the results exist.
