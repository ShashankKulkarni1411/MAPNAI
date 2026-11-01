"""
E22 (S3) — CAFG-L+M vs MiniCheck-FT5 alone on LLM-AggreFact, as pre-registered in research/PREREG.md §3 (S3), §4 and
§9 (v2). App venv (personalization.factcheck); no model is loaded: Stage 3 reuses the S1 FT5 probabilities.

Steps
  features --split S   per row: added number, added name, lexical coverage (cafg.decide / cafg.coverage) →
                       cache/e22_features_<split>.jsonl (no text). Validated against cafg.decide on a random sample.
  tune     --tag T     dev only: the 12-point grid (τ_acc ∈ {0.80, 0.85, 0.90, 0.95, 1.00, off} × added names on/off),
                       the §4 selection rule → results/e22_cafg_dev_grid_<T>.json and the frozen configuration
                       research/faithgate/configs/cafg_aggrefact_<T>.json.
  test     --config C --tag T
                       refuses unless C's sha256 is in LEDGER.md and C is committed unchanged; scores test once:
                       paired bootstrap vs FT5, call rates, random-escalation control (20 seeds), the grid (descriptive)
                       → results/e22_cafg_test_<T>.json + _preds.jsonl.gz.

Decision for a row under (τ, names): reject if Stage 1 reports an added number (or, with names on, an added name);
else accept without a learned call if τ is set and coverage ≥ τ; else escalate → FT5 pred (prob > 0.5).
"""

import argparse
import gzip
import hashlib
import json
import random
import subprocess
import time

import numpy as np

from _common import EXP_DIR, ROOT, run_metadata, utf8_stdout, write_json

CACHE = EXP_DIR / "cache"
CONFIGS = ROOT / "research" / "faithgate" / "configs"
FT5_TAG = "kaggle-2026-10-31"
TAUS = [0.80, 0.85, 0.90, 0.95, 1.00, None]
NAMES = [True, False]
N_BOOT, SEED = 2000, 13
RANDOM_SEEDS = list(range(13, 33))


def cfg_for(names: bool, tau=None):
    from research.faithgate.cafg import CAFGConfig
    return CAFGConfig(normalize_entities=True, added_names=names, added_months=False, lexical_accept=tau,
                      require_retention=False, learned=False)


def load_rows(split: str):
    """Data rows (dataset, label) aligned with the FT5 probabilities; checks the alignment against S1's preds file."""
    from e21_gate_aggrefact import load_split
    df = load_split(split)
    probs = {}
    for line in (CACHE / f"e20_minicheck-ft5_{split}_{FT5_TAG}.jsonl").open(encoding="utf-8"):
        r = json.loads(line)
        probs[r["row"]] = r["prob"]
    assert len(probs) == len(df), (len(probs), len(df))
    with gzip.open(EXP_DIR / "results" / f"e20_minicheck-ft5_{split}_{FT5_TAG}_preds.jsonl.gz", "rt",
                   encoding="utf-8") as fh:
        for line in fh:
            r = json.loads(line)
            i = r["row"]
            assert df.dataset[i] == r["dataset"] and int(df.label[i]) == r["label"], f"row {i} misaligned"
    return df, np.array([probs[i] for i in range(len(df))])


# ---------------------------------------------------------------- features

def step_features(split: str):
    from research.faithgate.cafg import coverage, decide
    df, _ = load_rows(split)
    out = CACHE / f"e22_features_{split}.jsonl"
    if out.exists():
        raise SystemExit(f"{out} exists")
    on, off = cfg_for(True), cfg_for(False)
    t0, feats = time.time(), []
    with out.open("w", encoding="utf-8") as fh:
        for i, (doc, claim) in enumerate(zip(df.doc, df.claim)):
            d_off = decide(doc, claim, [], off)
            d_on = decide(doc, claim, [], on)
            f = {"row": i, "add_num": not d_off.accept, "add_any": not d_on.accept,
                 "cov": round(coverage(claim, doc), 6)}
            assert f["add_any"] or not f["add_num"]
            feats.append(f)
            fh.write(json.dumps(f) + "\n")
            if (i + 1) % 2000 == 0:
                print(f"  {i + 1}/{len(df)}  {(i + 1) / (time.time() - t0):.0f} rows/s", flush=True)
    # validation: the derived decision equals cafg.decide with lexical_accept set, on a random sample
    rng = random.Random(SEED)
    sample = rng.sample(range(len(df)), min(600, len(df)))
    bad = 0
    for i in sample:
        for names in NAMES:
            for tau in TAUS:
                d = decide(df.doc[i], df.claim[i], [], cfg_for(names, tau))
                stage, _ = route(feats[i], names, tau)
                expect = {"reject": ("addition", False), "accept": ("lexical_accept", True),
                          "escalate": ("no_retention", True)}[stage]
                bad += (d.stage, d.accept) != expect
    print(f"{len(df)} rows in {time.time() - t0:.0f} s; decide() cross-check: {bad} mismatches on "
          f"{len(sample)} rows × 12 configs")
    if bad:
        raise SystemExit("feature derivation disagrees with cafg.decide")


def load_features(split: str):
    rows = [json.loads(l) for l in (CACHE / f"e22_features_{split}.jsonl").open(encoding="utf-8")]
    assert [r["row"] for r in rows] == list(range(len(rows)))
    return rows


def route(f, names: bool, tau):
    if f["add_any"] if names else f["add_num"]:
        return "reject", 0
    if tau is not None and f["cov"] >= tau:
        return "accept", 1
    return "escalate", None


# ---------------------------------------------------------------- metrics

def system_preds(feats, ft5_pred, names, tau):
    pred, esc = np.empty(len(feats), dtype=np.int8), np.zeros(len(feats), dtype=bool)
    for i, f in enumerate(feats):
        stage, p = route(f, names, tau)
        if stage == "escalate":
            esc[i], pred[i] = True, ft5_pred[i]
        else:
            pred[i] = p
    return pred, esc


def bacc(y, p):
    pos, neg = y == 1, y == 0
    vals = [(p[pos] == 1).mean() if pos.any() else np.nan, (p[neg] == 0).mean() if neg.any() else np.nan]
    return float(np.nanmean(vals) * 100)


class Groups:
    def __init__(self, datasets, labels):
        from e20_aggrefact_eval import NEWS3
        self.names = sorted(set(datasets))
        self.idx = {d: np.flatnonzero(np.asarray(datasets) == d) for d in self.names}
        self.y = np.asarray(labels)
        self.news3 = [d for d in NEWS3 if d in self.idx]

    def per_dataset(self, pred):
        return {d: bacc(self.y[ix], pred[ix]) for d, ix in self.idx.items()}

    def summary(self, pred, esc=None):
        per = self.per_dataset(pred)
        out = {"news3": round(np.mean([per[d] for d in self.news3]), 2), "avg11": round(np.mean(list(per.values())), 2),
               "per_dataset": {d: round(v, 2) for d, v in per.items()}}
        if esc is not None:
            n3 = np.concatenate([self.idx[d] for d in self.news3])
            out["call_rate_news3"] = round(float(esc[n3].mean()), 4)
            out["call_rate_all"] = round(float(esc.mean()), 4)
            out["calls_news3"], out["calls_all"] = int(esc[n3].sum()), int(esc.sum())
        return out

    def paired(self, pa, pb):
        """BAcc(a) − BAcc(b): point, 95% bootstrap interval (same resampled rows for both), News-3 and all 11."""
        rng = np.random.default_rng(SEED)
        reps = {d: np.empty(N_BOOT) for d in self.names}
        for b in range(N_BOOT):
            for d in self.names:
                ix = self.idx[d][rng.integers(0, len(self.idx[d]), len(self.idx[d]))]
                reps[d][b] = bacc(self.y[ix], pa[ix]) - bacc(self.y[ix], pb[ix])
        pa_, pb_ = self.per_dataset(pa), self.per_dataset(pb)

        def agg(sel):
            r = np.mean([reps[d] for d in sel], axis=0)
            return {"diff": round(float(np.mean([pa_[d] - pb_[d] for d in sel])), 2),
                    "ci95": [round(float(np.percentile(r, 2.5)), 2), round(float(np.percentile(r, 97.5)), 2)]}

        return {"news3": agg(self.news3), "avg11": agg(self.names),
                "per_dataset": {d: agg([d]) for d in self.names}}


def grid(groups, feats, ft5_pred):
    rows = []
    for names in NAMES:
        for tau in TAUS:
            pred, esc = system_preds(feats, ft5_pred, names, tau)
            rows.append({"added_names": names, "tau_acc": tau, **groups.summary(pred, esc)})
    return rows


# ---------------------------------------------------------------- tune (dev)

def step_tune(tag: str):
    df, probs = load_rows("dev")
    feats = load_features("dev")
    ft5 = (probs > 0.5).astype(np.int8)
    g = Groups(df.dataset, df.label)
    base = g.summary(ft5, np.ones(len(df), dtype=bool))
    pts = grid(g, feats, ft5)
    floor = round(base["news3"] - 1.0, 2)
    ok = [p for p in pts if p["news3"] >= floor]
    if ok:
        best = min(ok, key=lambda p: (p["call_rate_news3"], -p["news3"]))
        rule = "lowest News-3 call rate with dev News-3 BAcc ≥ FT5 − 1.0; ties → higher BAcc"
    else:
        best = max(pts, key=lambda p: p["news3"])
        rule = "no configuration qualified: highest dev News-3 BAcc (S3 expected to fail)"
    cfg = {"benchmark": "LLM-AggreFact", "prereg": "PREREG.md §4 + §9 (v2)", "tag": tag,
           "cafg_config": {"normalize_entities": True, "added_names": best["added_names"], "added_months": False,
                           "lexical_accept": best["tau_acc"], "require_retention": False, "learned": False},
           "stage3": {"checker": "minicheck-ft5 (MiniCheck-Flan-T5-Large @ 96eafd01)", "protocol": "P-fixed",
                      "threshold": "prob > 0.5", "probabilities": f"cache/e20_minicheck-ft5_<split>_{FT5_TAG}.jsonl"},
           "selected_on": "dev", "selection_rule": rule,
           "dev": {k: best[k] for k in ("news3", "avg11", "call_rate_news3", "call_rate_all")}}
    CONFIGS.mkdir(parents=True, exist_ok=True)
    cpath = CONFIGS / f"cafg_aggrefact_{tag}.json"
    if cpath.exists():
        raise SystemExit(f"{cpath} exists")
    cpath.write_text(json.dumps(cfg, indent=1) + "\n", encoding="utf-8", newline="\n")
    sha = hashlib.sha256(cpath.read_bytes()).hexdigest()
    payload = {"meta": run_metadata("research/experiments/e22_cafg_aggrefact.py", step="tune", split="dev", tag=tag,
                                    ft5_tag=FT5_TAG),
               "n": len(df), "ft5_alone": base, "news3_floor": floor, "grid": pts, "selected": best,
               "selection_rule": rule, "frozen_config": str(cpath.relative_to(ROOT)).replace("\\", "/"),
               "frozen_config_sha256": sha}
    print(write_json(f"e22_cafg_dev_grid_{tag}.json", payload))
    print(f"FT5 alone dev: News-3 {base['news3']}  avg11 {base['avg11']}  (floor {floor})")
    for p in pts:
        print(f"  names={p['added_names']!s:5} tau={p['tau_acc']!s:4}  News-3 {p['news3']:6.2f}  "
              f"avg11 {p['avg11']:6.2f}  calls News-3 {p['call_rate_news3']:.3f}  all {p['call_rate_all']:.3f}")
    print("SELECTED", {k: best[k] for k in ("added_names", "tau_acc", "news3", "call_rate_news3")})
    print(f"frozen config {cpath}\nsha256 {sha}")


# ---------------------------------------------------------------- test (once)

def check_frozen(cpath):
    sha = hashlib.sha256(cpath.read_bytes()).hexdigest()
    if sha not in (ROOT / "research" / "LEDGER.md").read_text(encoding="utf-8"):
        raise SystemExit(f"sha256 {sha} of {cpath.name} is not recorded in LEDGER.md: freeze first")
    rel = str(cpath.relative_to(ROOT)).replace("\\", "/")
    git = lambda *a: subprocess.run(["git", "-C", str(ROOT), *a], capture_output=True, text=True).stdout.strip()
    if not git("ls-files", rel) or git("status", "--porcelain", rel):
        raise SystemExit(f"{rel} is not committed unchanged: commit the frozen configuration first")
    return sha, git("log", "-1", "--format=%h", "--", rel)


def step_test(config: str, tag: str):
    cpath = (ROOT / config).resolve()
    sha, commit = check_frozen(cpath)
    cfg = json.loads(cpath.read_text(encoding="utf-8"))["cafg_config"]
    names, tau = cfg["added_names"], cfg["lexical_accept"]
    df, probs = load_rows("test")
    feats = load_features("test")
    ft5 = (probs > 0.5).astype(np.int8)
    g = Groups(df.dataset, df.label)
    pred, esc = system_preds(feats, ft5, names, tau)
    cafg = g.summary(pred, esc)
    base = g.summary(ft5, np.ones(len(df), dtype=bool))
    paired = g.paired(pred, ft5)
    s3 = {"lower_bound_news3": paired["news3"]["ci95"][0], "margin": -2.0,
          "call_rate_news3": cafg["call_rate_news3"], "call_cap": 0.50,
          "pass": paired["news3"]["ci95"][0] > -2.0 and cafg["call_rate_news3"] <= 0.50}
    # random-escalation control: same per-dataset escalation counts, cheap-tier decision elsewhere
    cheap = np.array([0 if route(f, names, None)[0] == "reject" else 1 for f in feats], dtype=np.int8)
    ctrl = []
    for s in RANDOM_SEEDS:
        rng = np.random.default_rng(s)
        p = cheap.copy()
        for d, ix in g.idx.items():
            k = int(esc[ix].sum())
            pick = rng.choice(ix, size=k, replace=False)
            p[pick] = ft5[pick]
        ctrl.append(g.summary(p))
    control = {k: {"mean": round(float(np.mean([c[k] for c in ctrl])), 2),
                   "interval95": [round(float(np.percentile([c[k] for c in ctrl], 2.5)), 2),
                                  round(float(np.percentile([c[k] for c in ctrl], 97.5)), 2)]}
               for k in ("news3", "avg11")}
    control["seeds"] = RANDOM_SEEDS
    stages = {"reject_addition": int(sum(route(f, names, tau)[0] == "reject" for f in feats)),
              "lexical_accept": int(sum(route(f, names, tau)[0] == "accept" for f in feats)),
              "escalated": int(esc.sum())}
    payload = {"meta": run_metadata("research/experiments/e22_cafg_aggrefact.py", step="test", split="test", tag=tag,
                                    ft5_tag=FT5_TAG, frozen_config=config, frozen_config_sha256=sha,
                                    frozen_config_commit=commit),
               "n": len(df), "config": cfg, "cafg": cafg, "ft5_alone": base, "paired_cafg_minus_ft5": paired,
               "S3": s3, "random_escalation_control": control, "stages": stages,
               "grid_descriptive_only": grid(g, feats, ft5),
               "multiplicity": "single inferential comparison in the test family (PREREG §9): Holm = unadjusted"}
    name = f"e22_cafg_test_{tag}"
    print(write_json(f"{name}.json", payload))
    with gzip.open(EXP_DIR / "results" / f"{name}_preds.jsonl.gz", "wt", encoding="utf-8") as fh:
        for i in range(len(df)):
            fh.write(json.dumps({"row": i, "dataset": df.dataset[i], "label": int(df.label[i]), "pred": int(pred[i]),
                                 "escalated": bool(esc[i]), "ft5_pred": int(ft5[i])}) + "\n")
    print(json.dumps({"cafg": {k: cafg[k] for k in ("news3", "avg11", "call_rate_news3", "call_rate_all")},
                      "ft5": {k: base[k] for k in ("news3", "avg11")}, "paired": {k: paired[k] for k in ("news3", "avg11")},
                      "S3": s3, "control": control, "stages": stages}, indent=1))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--step", required=True, choices=["features", "tune", "test"])
    ap.add_argument("--split", default="dev", choices=["dev", "test"])
    ap.add_argument("--tag", default=None)
    ap.add_argument("--config", default=None)
    args = ap.parse_args()
    utf8_stdout()
    if args.step == "features":
        step_features(args.split)
    elif args.step == "tune":
        step_tune(args.tag or time.strftime("%Y-%m-%d"))
    else:
        if not args.config or not args.tag:
            raise SystemExit("--config and --tag are required for the test step")
        step_test(args.config, args.tag)


if __name__ == "__main__":
    main()
