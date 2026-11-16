"""n04: validity gate. Human-human reliability and LLM-human validity for each news value.

Plan: HYPOTHESES.md v1, section "Validity of the scores". Run BEFORE any click analysis.
  - Human reliability per value: quadratic-weighted Cohen's kappa between labeller A1 and A2.
  - LLM validity per value: Spearman rho between the LLM score and the mean of A1 and A2.
  - 95% CIs: 2,000 bootstrap resamples of items, seed 13.
  - Gate: a value enters H1-H3 only if rho >= 0.40 AND kappa >= 0.40 (point estimates).
Items missing any score from either labeller are dropped and listed in the output.

Inputs are the CSVs written by `n03_annotation_workbook.py read <xlsx>` (system Python has
openpyxl; this script needs numpy/scipy, so it runs in ~/.venvs/mapnai-research):
  python research2/n04_validity.py --a1 research2/annotation/nv_labels_A1_completed.csv \
      --a2 "research2/annotation/nv_labels_A2_complete (1).csv" \
      --scores research2/data/nv_scores_kaggle-2026-11-15.jsonl --tag 2026-11-16
Output: results/n04_validity_<tag>.json (statistics and ids only, no MIND text).
"""
from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from scipy.stats import spearmanr

from nv_common import DATA, RESULTS, REPO, SEED, VALUES, load_scores, sha256_file, write_json

N_BOOT = 2000
GATE_RHO = 0.40
GATE_KAPPA = 0.40
K = 5  # scale 1..5


def qwk(a: np.ndarray, b: np.ndarray, k: int = K) -> float:
    """Quadratic-weighted Cohen's kappa for integer ratings 1..k. NaN if undefined."""
    a = np.asarray(a, dtype=int) - 1
    b = np.asarray(b, dtype=int) - 1
    o = np.zeros((k, k))
    np.add.at(o, (a, b), 1)
    i, j = np.indices((k, k))
    w = (i - j) ** 2 / (k - 1) ** 2
    e = np.outer(o.sum(1), o.sum(0)) / o.sum()
    den = (w * e).sum()
    return float("nan") if den == 0 else float(1 - (w * o).sum() / den)


def rho(x: np.ndarray, y: np.ndarray) -> float:
    if np.all(x == x[0]) or np.all(y == y[0]):
        return float("nan")
    return float(spearmanr(x, y).statistic)


def read_labels(path: Path) -> dict:
    out = {}
    with open(path, encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            vals = {}
            for v in VALUES:
                s = (r[v] or "").strip()
                vals[v] = int(float(s)) if s else None
            out[r["news_id"]] = vals
    return out


def ci(boot: np.ndarray) -> list:
    ok = boot[~np.isnan(boot)]
    return [round(float(np.percentile(ok, 2.5)), 4), round(float(np.percentile(ok, 97.5)), 4)]


def rel(p: Path) -> str:
    try:
        return p.resolve().relative_to(REPO).as_posix()
    except ValueError:
        return p.name


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--a1", type=Path, required=True)
    ap.add_argument("--a2", type=Path, required=True)
    ap.add_argument("--scores", type=Path, required=True)
    ap.add_argument("--tag", required=True)
    args = ap.parse_args()

    sample = json.loads((DATA / "human_sample.json").read_text(encoding="utf-8"))["ids"]
    h1, h2 = read_labels(args.a1), read_labels(args.a2)
    llm = load_scores(args.scores)
    assert list(h1) == sample and list(h2) == sample, "label files are not the human sample in order"

    keep, dropped = [], []
    for nid in sample:
        why = [w for w, h in (("A1", h1), ("A2", h2)) if any(h[nid][v] is None for v in VALUES)]
        if llm.get(nid) is None:
            why.append("LLM")
        (dropped.append({"news_id": nid, "missing": why}) if why else keep.append(nid))
    n = len(keep)
    A = np.array([[h1[i][v] for v in VALUES] for i in keep])
    B = np.array([[h2[i][v] for v in VALUES] for i in keep])
    L = np.array([[llm[i][v] for v in VALUES] for i in keep])
    M = (A + B) / 2

    rng = np.random.default_rng(SEED)
    idx = rng.integers(0, n, size=(N_BOOT, n))
    per_value, gate_pass = {}, []
    for j, v in enumerate(VALUES):
        a, b, l, m = A[:, j], B[:, j], L[:, j], M[:, j]
        k_pt, r_pt = qwk(a, b), rho(l, m)
        k_bt = np.array([qwk(a[s], b[s]) for s in idx])
        r_bt = np.array([rho(l[s], m[s]) for s in idx])
        passed = bool(r_pt >= GATE_RHO and k_pt >= GATE_KAPPA)
        if passed:
            gate_pass.append(v)
        per_value[v] = {
            "human_kappa_qw": round(k_pt, 4), "human_kappa_ci95": ci(k_bt),
            "llm_rho_vs_human_mean": round(r_pt, 4), "llm_rho_ci95": ci(r_bt),
            "gate_pass": passed,
            "llm_rho_vs_A1": round(rho(l, a), 4), "llm_rho_vs_A2": round(rho(l, b), 4),
            "human_rho_A1_vs_A2": round(rho(a, b), 4),
            "human_exact_agree": round(float(np.mean(a == b)), 4),
            "human_within1_agree": round(float(np.mean(np.abs(a - b) <= 1)), 4),
            "mean_A1": round(float(a.mean()), 3), "mean_A2": round(float(b.mean()), 3),
            "mean_llm": round(float(l.mean()), 3),
            "dist_A1": np.bincount(a, minlength=6)[1:].tolist(),
            "dist_A2": np.bincount(b, minlength=6)[1:].tolist(),
            "dist_llm": np.bincount(l, minlength=6)[1:].tolist(),
            "boot_nan": {"kappa": int(np.isnan(k_bt).sum()), "rho": int(np.isnan(r_bt).sum())},
        }

    inputs = {}
    for p in (args.a1, args.a2):
        inputs[rel(p)] = sha256_file(p)
        x = p.with_suffix(".xlsx")
        if x.exists():
            inputs[rel(x)] = sha256_file(x)
    inputs[rel(args.scores)] = sha256_file(args.scores)
    inputs[rel(DATA / "human_sample.json")] = sha256_file(DATA / "human_sample.json")
    out = RESULTS / f"n04_validity_{args.tag}.json"
    write_json(out, {
        "meta": {"script": "research2/n04_validity.py", "tag": args.tag, "plan": "HYPOTHESES.md v1",
                 "run_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                 "n_boot": N_BOOT, "seed": SEED, "gate": {"rho_min": GATE_RHO, "kappa_min": GATE_KAPPA},
                 "inputs_sha256": inputs},
        "n_items": n, "dropped": dropped, "gate_pass": gate_pass,
        "gate_fail": [v for v in VALUES if v not in gate_pass], "per_value": per_value})

    print(f"items used: {n}   dropped: {dropped}")
    print(f"{'value':13s} {'kappa(A1,A2)':>22s} {'rho(LLM,mean)':>22s}  gate   rho(A1,A2) exact within1")
    for v in VALUES:
        d = per_value[v]
        print(f"{v:13s} {d['human_kappa_qw']:6.3f} [{d['human_kappa_ci95'][0]:6.3f},{d['human_kappa_ci95'][1]:6.3f}]"
              f"  {d['llm_rho_vs_human_mean']:6.3f} [{d['llm_rho_ci95'][0]:6.3f},{d['llm_rho_ci95'][1]:6.3f}]"
              f"  {'PASS' if d['gate_pass'] else 'fail'}   {d['human_rho_A1_vs_A2']:6.3f}"
              f"   {d['human_exact_agree']:.2f}  {d['human_within1_agree']:.2f}")
    print("gate pass:", gate_pass)
    print("wrote", out)


if __name__ == "__main__":
    main()
