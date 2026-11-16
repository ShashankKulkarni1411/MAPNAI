"""n06: corrected inference for within-impression AUC and E2 (HYPOTHESES.md, Change 1).

Why: under the planned user-only bootstrap (n05), a random per-article score had CIs excluding
0.5, because the same articles recur across thousands of impressions. Here:
  * two-way (users x articles) Poisson(1) bootstrap, the "pigeonhole" bootstrap (Owen 2007;
    Owen & Eckles 2012): every row is weighted by its article's weight, every impression by
    its user's weight; per-impression weighted AUC, then the user-weighted mean;
  * article-level permutation test on dev for the H1 p-values (scores shuffled across articles);
  * E2 CIs from the same two-way bootstrap.
Point estimates are identical to n05. Seed 13. B: 400 (dev main), 200 (train), 100 (exploratory
subsets and E2), 50 (E2 without gate-failing values), 500 permutations. Runs in 6 worker
processes. Acceptance check: the random score's CI must include 0.5 in both splits.

  ~/.venvs/mapnai-research/Scripts/python research2/n06_twoway.py \
      --scores research2/data/nv_scores_kaggle-2026-11-15.jsonl \
      --gate research2/results/n04_validity_2026-11-16.json --tag 2026-11-16
Output: results/n06_twoway_<tag>.json (statistics only). Progress log on stdout.
"""
from __future__ import annotations

import argparse
import csv
import json
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from n05_clicks import (H1_VALUES, MIN_CAT_IMPRESSIONS, conditional_logit, holm, parse_split, r4, rel)
from nv_common import DATA, RESULTS, SEED, VALUES, load_scores, read_jsonl, sha256_file, write_json

B_MAIN, B_TRAIN, B_EXPL, B_E2, B_E2_GATE, B_PERM = 400, 200, 100, 100, 50, 500
WORKERS = 6
T0 = time.time()


def log(*a) -> None:
    print(f"[{time.time() - T0:7.1f}s]", *a, flush=True)


class Sorted:
    """One score column, pre-sorted within impressions, so each bootstrap replicate is O(n)."""

    def __init__(self, g, a, y, s, G):
        o = np.lexsort((s, g))
        self.g, self.a, self.y = g[o], a[o], y[o].astype(float)
        s2 = s[o]
        n = len(o)
        new = np.ones(n, bool)
        new[1:] = (self.g[1:] != self.g[:-1]) | (s2[1:] != s2[:-1])
        self.blk = np.cumsum(new) - 1
        first = np.flatnonzero(new)
        self.nb = len(first)
        bg = self.g[first]
        self.fbb = np.searchsorted(bg, np.arange(G))[bg]  # first block of each block's group
        self.G = G

    def auc(self, wa=None) -> np.ndarray:
        wr = np.ones(len(self.a)) if wa is None else wa[self.a].astype(float)
        wp = wr * self.y
        wn = wr - wp
        nblk = np.bincount(self.blk, weights=wn, minlength=self.nb)
        cs = np.cumsum(nblk) - nblk
        below = cs - cs[self.fbb]
        num = np.bincount(self.g, weights=wp * (below[self.blk] + 0.5 * nblk[self.blk]), minlength=self.G)
        P = np.bincount(self.g, weights=wp, minlength=self.G)
        N = np.bincount(self.g, weights=wn, minlength=self.G)
        with np.errstate(invalid="ignore", divide="ignore"):
            out = num / (P * N)
        out[(P == 0) | (N == 0)] = np.nan
        return out


def wmean(auc: np.ndarray, w_imp: np.ndarray) -> float:
    ok = ~np.isnan(auc)
    den = w_imp[ok].sum()
    return float((w_imp[ok] * auc[ok]).sum() / den) if den > 0 else float("nan")


def ci(x) -> list:
    x = np.asarray(x)
    x = x[~np.isnan(x)]
    return [r4(np.percentile(x, 2.5)), r4(np.percentile(x, 97.5))]


def perm_test(d, s_art: np.ndarray, B: int, rng) -> dict:
    """Article-level permutation null for the mean within-impression AUC of a 1-5 score."""
    g, a, y = d["g"], d["a"], d["y"].astype(float)
    G = len(d["ncand"])
    P = np.bincount(g, weights=y, minlength=G)
    N = np.bincount(g, minlength=G) - P
    ok = (P > 0) & (N > 0)

    def mean_auc(lev):
        idx = g.astype(np.int64) * 5 + (lev - 1)
        cp = np.bincount(idx, weights=y, minlength=G * 5).reshape(G, 5)
        cn = np.bincount(idx, weights=1 - y, minlength=G * 5).reshape(G, 5)
        below = np.cumsum(cn, 1) - cn
        num = (cp * (below + 0.5 * cn)).sum(1)
        return float((num[ok] / (P[ok] * N[ok])).mean())

    s_int = s_art.astype(np.int64)
    obs = mean_auc(s_int[a])
    null = np.array([mean_auc(s_int[rng.permutation(len(s_int))][a]) for _ in range(B)])
    p = (1 + np.sum(np.abs(null - 0.5) >= abs(obs - 0.5))) / (B + 1)
    return {"auc": r4(obs), "null_mean": r4(null.mean()), "null_sd": r4(null.std()),
            "null_ci95": ci(null), "p_perm": r4(p), "B": B}


# ---------------------------------------------------------------- shared state (one copy per worker)
W: dict = {}


def init(scores_path: str) -> None:
    raw = load_scores(Path(scores_path))
    arts = read_jsonl(DATA / "articles_to_score.jsonl")
    ids = [r["id"] for r in arts]
    W["ids"] = ids
    W["art_index"] = {nid: i for i, nid in enumerate(ids)}
    Sc = np.array([[raw[i][v] for v in VALUES] for i in ids], dtype=float)
    W["Sc"], W["Z"] = Sc, (Sc - Sc.mean(0)) / Sc.std(0)
    W["vix"] = {v: j for j, v in enumerate(VALUES)}
    W["empty_abs"] = np.array([not (r.get("abstract") or "").strip() for r in arts])
    meta = {}
    with open(DATA / "article_meta.csv", encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            meta[r["id"]] = r
    W["cat"] = np.array([meta[i]["category"] for i in ids])
    it_ = np.array([float(meta[i]["imps_train"]) for i in ids])
    ct_ = np.array([float(meta[i]["clicks_train"]) for i in ids])
    W["it"] = it_
    W["rand"] = np.random.default_rng(SEED + 1).random(len(ids))   # same random score as n05
    W["sum7"] = Sc.sum(1)
    with np.errstate(invalid="ignore", divide="ignore"):
        W["ctr_train"] = np.where(it_ > 0, ct_ / it_, np.nan)


def split_state(split: str) -> dict:
    if split not in W:
        d = parse_split(split, W["art_index"])
        rng = np.random.default_rng(SEED)
        Bmax = B_MAIN if split == "dev" else B_TRAIN
        W[split] = {"d": d, "WA": rng.poisson(1.0, (Bmax, len(W["ids"]))).astype(np.float32),
                    "WU": rng.poisson(1.0, (Bmax, int(d["n_users"]))).astype(np.float32)}
    return W[split]


def column_names(split: str, cats: list) -> list:
    names = VALUES + ["sum7", "random"]
    if split == "dev":
        for v in VALUES:
            names += [f"E5_le10cand:{v}", f"E5_noemptyabs:{v}", f"E4_covered:{v}"]
        names += ["E4_covered:sum7", "E4_covered:train_ctr"]
        names += [f"E3_cat:{c}:{v}" for c in cats for v in VALUES]
    return names


def column_spec(split: str, name: str):
    d = split_state(split)["d"]
    a, g = d["a"], d["g"]
    Sc, vix = W["Sc"], W["vix"]
    Bmain = B_MAIN if split == "dev" else B_TRAIN
    if name in VALUES:
        return Sc[a, vix[name]], None, Bmain
    if name == "sum7":
        return W["sum7"][a], None, Bmain
    if name == "random":
        return W["rand"][a], None, Bmain
    kind, rest = name.split(":", 1)
    if kind == "E3_cat":
        c, v = rest.split(":")
        return Sc[a, vix[v]], W["cat"][a] == c, B_EXPL
    if kind == "E5_le10cand":
        mask = d["ncand"][g] <= 10
    elif kind == "E5_noemptyabs":
        mask = ~W["empty_abs"][a]
    else:  # E4_covered
        mask = W["it"][a] >= 1
    if rest == "sum7":
        s = W["sum7"][a]
    elif rest == "train_ctr":
        s = W["ctr_train"][a]
    else:
        s = Sc[a, vix[rest]]
    return s, mask, B_EXPL


def task_auc(split: str, name: str):
    st = split_state(split)
    d = st["d"]
    s, mask, Bc = column_spec(split, name)
    g, a, y = d["g"], d["a"], d["y"]
    if mask is not None:
        g, a, y, s = g[mask], a[mask], y[mask], s[mask]
    G = len(d["ncand"])
    S = Sorted(g, a, y, s.astype(float), G)
    auc0 = S.auc()
    nimp = int((~np.isnan(auc0)).sum())
    if name.startswith("E3_cat:") and nimp < MIN_CAT_IMPRESSIONS:
        return ("auc", split, name, None, nimp, None)
    uimp = d["uimp"]
    boot = np.array([wmean(S.auc(st["WA"][b]), st["WU"][b][uimp].astype(float)) for b in range(Bc)])
    return ("auc", split, name, wmean(auc0, np.ones(G)), nimp, boot)


def task_perm(v: str):
    d = split_state("dev")["d"]
    rng = np.random.default_rng([SEED, VALUES.index(v)])
    return ("perm", v, perm_test(d, W["Sc"][:, W["vix"][v]], B_PERM, rng))


def task_e2(key: str, names: list, b0: list, b_from: int, b_to: int):
    st = split_state("dev")
    Zk = W["Z"][:, [W["vix"][v] for v in names]]
    out = [conditional_logit(st["d"], Zk, names, wa=st["WA"][b], wu=st["WU"][b], beta0=np.array(b0),
                             beta_only=True) for b in range(b_from, b_to)]
    return ("e2", key, b_from, np.array(out))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scores", type=Path, required=True)
    ap.add_argument("--gate", type=Path, required=True)
    ap.add_argument("--tag", required=True)
    args = ap.parse_args()
    passed = set(json.loads(args.gate.read_text(encoding="utf-8"))["gate_pass"])
    init(str(args.scores))
    cats = sorted(set(W["cat"]))
    for split in ("dev", "train"):
        parse_split(split, W["art_index"])      # make sure caches exist before workers start
    d_dev = split_state("dev")["d"]

    e2_specs = {"E2": (VALUES, B_E2), "E5_E2_gate_passing_only": ([v for v in VALUES if v in passed], B_E2_GATE)}
    e2_full = {key: conditional_logit(d_dev, W["Z"][:, [W["vix"][v] for v in names]], names)
               for key, (names, _) in e2_specs.items()}
    log("E2 point fits done")

    point = {"dev": {}, "train": {}}
    boot = {"dev": {}, "train": {}}
    nimp = {"dev": {}, "train": {}}
    perm, e2_boot = {}, {k: {} for k in e2_specs}
    with ProcessPoolExecutor(max_workers=WORKERS, initializer=init, initargs=(str(args.scores),)) as ex:
        futs = []
        for split in ("train", "dev"):                       # biggest jobs first
            for n in column_names(split, cats)[:9]:
                futs.append(ex.submit(task_auc, split, n))
        for v in VALUES:
            futs.append(ex.submit(task_perm, v))
        for key, (names, Bc) in e2_specs.items():
            b0 = [e2_full[key]["coef"][n]["beta"] for n in names]
            for b in range(0, Bc, 25):
                futs.append(ex.submit(task_e2, key, names, b0, b, min(b + 25, Bc)))
        for n in column_names("dev", cats)[9:]:
            futs.append(ex.submit(task_auc, "dev", n))
        for i, f in enumerate(as_completed(futs), 1):
            r = f.result()
            if r[0] == "auc":
                _, split, name, pt, ni, bt = r
                nimp[split][name] = ni
                if bt is not None:
                    point[split][name], boot[split][name] = pt, bt
                    if name in VALUES or name in ("sum7", "random"):
                        log(f"[{i}/{len(futs)}] {split} {name:14s} AUC {pt:.4f} CI {ci(bt)}")
            elif r[0] == "perm":
                perm[r[1]] = r[2]
                log(f"[{i}/{len(futs)}] perm {r[1]} p={r[2]['p_perm']}")
            else:
                e2_boot[r[1]][r[2]] = r[3]
                log(f"[{i}/{len(futs)}] {r[1]} replicates from {r[2]}")
    log("all tasks done")

    out = {"meta": {"script": "research2/n06_twoway.py", "tag": args.tag, "plan": "HYPOTHESES.md v1 + Change 1",
                    "run_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"), "seed": SEED,
                    "B": {"dev_main": B_MAIN, "train": B_TRAIN, "exploratory": B_EXPL, "E2": B_E2,
                          "E2_gate_only": B_E2_GATE, "permutation": B_PERM},
                    "bootstrap": "two-way Poisson(1): users x articles (Owen 2007; Owen & Eckles 2012)",
                    "gate_pass": sorted(passed),
                    "inputs_sha256": {rel(p): sha256_file(p) for p in
                                      (args.scores, args.gate, DATA / "articles_to_score.jsonl",
                                       DATA / "article_meta.csv")}}}
    for split in ("dev", "train"):
        P, Bt = point[split], boot[split]
        res = {"n_impressions_usable": nimp[split][VALUES[0]],
               "auc": {c: {"auc": r4(P[c]), "ci95_twoway": ci(Bt[c]), "n_impressions": nimp[split][c],
                           "B": len(Bt[c])} for c in column_names(split, cats) if c in P}}
        rnd = res["auc"]["random"]["ci95_twoway"]
        res["sanity_random_ci_includes_0.5"] = bool(rnd[0] <= 0.5 <= rnd[1])
        res["paired_diffs_vs_importance"] = {
            v: {"diff": r4(P[v] - P["importance"]), "ci95_twoway": ci(Bt[v] - Bt["importance"])}
            for v in VALUES if v != "importance"}
        diff = Bt["importance"] - Bt["entertainment"]
        res["H2"] = {"auc_importance_minus_entertainment": r4(P["importance"] - P["entertainment"]),
                     "ci95_twoway": ci(diff), "confirmatory": {"importance", "entertainment"} <= passed,
                     "supported": bool(np.percentile(diff, 97.5) < 0)}
        if split == "dev":
            res["permutation"] = {v: perm[v] for v in VALUES}
            ph = holm({v: perm[v]["p_perm"] for v in H1_VALUES})
            res["H1"] = {v: {"auc": r4(P[v]), "ci95_twoway": ci(Bt[v]), "p_perm": perm[v]["p_perm"],
                             "p_holm_m3": r4(ph[v]), "confirmatory": v in passed,
                             "supported": bool(P[v] > 0.5 and ph[v] < 0.05)} for v in H1_VALUES}
            res["E4_paired_diffs_vs_train_ctr"] = {
                v: {"diff": r4(P[f"E4_covered:{v}"] - P["E4_covered:train_ctr"]),
                    "ci95_twoway": ci(Bt[f"E4_covered:{v}"] - Bt["E4_covered:train_ctr"])}
                for v in VALUES + ["sum7"]}
            res["E3_categories_dropped_lt_min_impressions"] = sorted(
                {c.split(":")[1] for c in column_names("dev", cats) if c.startswith("E3_cat:") and c not in P})
            for key, (names, Bc) in e2_specs.items():
                bs = np.concatenate([e2_boot[key][b] for b in sorted(e2_boot[key])])
                full = e2_full[key]
                for i, n in enumerate(names):
                    full["coef"][n]["ci95_twoway"] = ci(bs[:, i])
                    full["coef"][n]["se_twoway"] = r4(bs[:, i].std(ddof=1))
                full["B_twoway"] = int(len(bs))
                res[key] = full
        out[split] = res
    path = RESULTS / f"n06_twoway_{args.tag}.json"
    write_json(path, out)
    log("sanity:", {s: out[s]["sanity_random_ci_includes_0.5"] for s in ("dev", "train")})
    log("H1:", out["dev"]["H1"])
    log("H2 dev:", out["dev"]["H2"])
    log("E2:", {n: (c["beta"], c["ci95_twoway"]) for n, c in out["dev"]["E2"]["coef"].items()})
    log("wrote", path)


if __name__ == "__main__":
    main()
