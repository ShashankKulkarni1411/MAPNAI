"""n05: news values vs clicks. A1 (H1-H3) and exploratory E1-E5 from HYPOTHESES.md v1.

Runs after the validity gate (results/n04_validity_<tag>.json), which decides which values are
confirmatory. Needs numpy/scipy, so it runs in ~/.venvs/mapnai-research:
  ~/.venvs/mapnai-research/Scripts/python research2/n05_clicks.py \
      --scores research2/data/nv_scores_kaggle-2026-11-15.jsonl \
      --gate research2/results/n04_validity_2026-11-16.json --tag 2026-11-16

Definitions (fixed here before the first run):
  * Within-impression AUC: for each impression, the AUC of a score separating clicked from
    non-clicked candidates, ties = 0.5; only impressions with >= 1 click and >= 1 non-click.
    Reported value = mean over impressions (MIND's convention).
  * CIs: 1,000 bootstrap resamples of users, seed 13. All measures in a split share the same
    resamples, so differences are paired. Two-sided bootstrap p vs 0.5 = 2*min(share <= 0.5,
    share >= 0.5), floored at 1/(B+1).
  * H1: Holm over m = 3 (entertainment, prominence, surprise) as written in v1; a value is
    confirmatory only if it passed the gate. Supported if AUC > 0.5 and Holm p < 0.05.
  * H3 / E3 click rate: (clicks_train + clicks_dev) / (imps_train + imps_dev), articles with
    >= 50 impressions; 1,000 article bootstraps, seed 13.
  * E2: multinomial logit per click; alternatives = the clicked item plus the impression's
    non-clicked items (dev). Values standardised over the 22,771 scored articles. Newton fit,
    standard errors clustered by user (sandwich).
  * E3: per-category AUC uses only candidates of that category within each impression; a
    category is reported if it has >= 100 usable impressions (AUC) or >= 30 articles (rho).
    Quadrants (articles >= 50 impressions): "important but ignored" = importance >= 4 and
    click rate <= 25th percentile; "clicked but unimportant" = importance <= 2 and click rate
    >= 75th percentile. Example headlines go to data/ (git-ignored), never to results/.
  * E4: dev candidates with >= 1 train-period impression get their train click rate as a score;
    news values and the sum of all seven are compared on the same restricted candidate set.
  * E5: impressions with <= 10 candidates; candidates with an empty abstract removed;
    E2 without gate-failing values.
  * Sanity check: a seeded random per-article score must give AUC ~ 0.5.
Output: results/n05_clicks_<tag>.json (statistics and counts only).
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from scipy.stats import spearmanr

from nv_common import (DATA, REPO, RESULTS, SEED, VALUES, iter_impressions, load_scores, read_jsonl,
                       sha256_file, write_json)

N_BOOT = 1000
H1_VALUES = ["entertainment", "prominence", "surprise"]
MIN_IMPS_CTR = 50
MIN_CAT_IMPRESSIONS = 100
MIN_CAT_ARTICLES = 30
CACHE = DATA / "cache"


# ---------------------------------------------------------------- core statistics
def grouped_auc(g: np.ndarray, s: np.ndarray, y: np.ndarray, n_groups: int) -> np.ndarray:
    """AUC of score s for label y within each group id in g (0..n_groups-1); ties = 0.5.
    NaN for groups without both a positive and a negative."""
    order = np.lexsort((s, g))
    g2, s2, y2 = g[order], s[order], y[order].astype(float)
    n = len(g2)
    if n == 0:
        return np.full(n_groups, np.nan)
    gstart = np.searchsorted(g2, np.arange(n_groups))
    pos = np.arange(n) - gstart[g2]
    new = np.ones(n, bool)
    new[1:] = (g2[1:] != g2[:-1]) | (s2[1:] != s2[:-1])
    first = np.flatnonzero(new)
    last = np.r_[first[1:] - 1, n - 1]
    rank = ((pos[first] + pos[last]) / 2 + 1)[np.cumsum(new) - 1]
    p = np.bincount(g2, weights=y2, minlength=n_groups)
    tot = np.bincount(g2, minlength=n_groups)
    q = tot - p
    r = np.bincount(g2, weights=rank * y2, minlength=n_groups)
    with np.errstate(invalid="ignore", divide="ignore"):
        auc = (r - p * (p + 1) / 2) / (p * q)
    auc[(p == 0) | (q == 0)] = np.nan
    return auc


def boot_p(boot: np.ndarray, null: float) -> float:
    b = boot[~np.isnan(boot)]
    share = min(np.mean(b <= null), np.mean(b >= null))
    return float(max(2 * share, 1 / (len(b) + 1)))


def holm(pvals: dict) -> dict:
    items = sorted(pvals.items(), key=lambda kv: kv[1])
    m, out, running = len(items), {}, 0.0
    for i, (k, p) in enumerate(items):
        running = max(running, min(1.0, (m - i) * p))
        out[k] = running
    return out


def ci(x: np.ndarray) -> list:
    x = x[~np.isnan(x)]
    return [round(float(np.percentile(x, 2.5)), 4), round(float(np.percentile(x, 97.5)), 4)]


def r4(x) -> float:
    return round(float(x), 4)


# ---------------------------------------------------------------- data
def parse_split(split: str, art_index: dict) -> dict:
    """Flat arrays for one split, cached in data/cache (git-ignored)."""
    CACHE.mkdir(parents=True, exist_ok=True)
    f = CACHE / f"imps_{split}.npz"
    if f.exists():
        z = np.load(f, allow_pickle=False)
        return {k: z[k] for k in z.files}
    g, a, y, users, ncand = [], [], [], [], []
    for i, (_, uid, _, _, cands) in enumerate(iter_impressions(split)):
        users.append(uid)
        ncand.append(len(cands))
        for nid, lab in cands:
            g.append(i)
            a.append(art_index[nid])
            y.append(lab)
    uniq, ucode = np.unique(np.array(users), return_inverse=True)
    d = {"g": np.array(g, np.int32), "a": np.array(a, np.int32), "y": np.array(y, np.int8),
         "uimp": ucode.astype(np.int32), "ncand": np.array(ncand, np.int32),
         "n_users": np.array(len(uniq))}
    np.savez(f, **d)
    return d


class Family:
    """Per-impression AUC columns for one split, aggregated per user for the bootstrap."""

    def __init__(self, d: dict):
        self.d = d
        self.G = len(d["ncand"])
        self.U = int(d["n_users"])
        self.cols, self.S, self.N = [], [], []

    def add(self, name: str, score_rows: np.ndarray, mask: np.ndarray | None = None) -> np.ndarray:
        g, y = self.d["g"], self.d["y"]
        if mask is not None:
            g, y, score_rows = g[mask], y[mask], score_rows[mask]
        auc = grouped_auc(g, score_rows.astype(float), y, self.G)
        ok = ~np.isnan(auc)
        u = self.d["uimp"]
        self.cols.append(name)
        self.S.append(np.bincount(u[ok], weights=auc[ok], minlength=self.U))
        self.N.append(np.bincount(u[ok], minlength=self.U).astype(float))
        return auc

    def bootstrap(self, seed: int) -> tuple:
        S, N = np.array(self.S).T, np.array(self.N).T
        point = S.sum(0) / N.sum(0)
        rng = np.random.default_rng(seed)
        boot = np.empty((N_BOOT, len(self.cols)))
        for b0 in range(0, N_BOOT, 50):
            k = min(50, N_BOOT - b0)
            W = np.stack([np.bincount(rng.integers(0, self.U, self.U), minlength=self.U) for _ in range(k)])
            with np.errstate(invalid="ignore", divide="ignore"):
                boot[b0:b0 + k] = (W @ S) / (W @ N)
        n_imp = N.sum(0)
        return ({c: point[i] for i, c in enumerate(self.cols)},
                {c: boot[:, i] for i, c in enumerate(self.cols)},
                {c: int(n_imp[i]) for i, c in enumerate(self.cols)})


def conditional_logit(d: dict, Z: np.ndarray, names: list, max_iter: int = 50, wa: np.ndarray | None = None,
                      wu: np.ndarray | None = None, beta0: np.ndarray | None = None,
                      beta_only: bool = False):
    """Multinomial logit per click (alternatives: that click + the impression's non-clicks).
    Optional bootstrap weights: wa per article (scales every row of that article), wu per user
    (scales that user's clicks). Without weights the result is the plain estimate."""
    g, y, u_imp = d["g"], d["y"].astype(bool), d["uimp"]
    G = len(d["ncand"])
    P = np.bincount(g, weights=y, minlength=G)
    Q = np.bincount(g, weights=~y, minlength=G)
    keep = ((P > 0) & (Q > 0))[g]
    g, y = g[keep], y[keep]
    arts = d["a"][keep]
    X = Z[arts]
    k = X.shape[1]
    neg, posr = ~y, y
    gc, Xc = g[posr], X[posr]
    rw = np.ones(len(g)) if wa is None else wa[arts].astype(float)
    cw = rw[posr] * (1.0 if wu is None else wu[u_imp[gc]])
    rn = rw[neg]
    beta = np.zeros(k) if beta0 is None else beta0.copy()
    gn, Xn = g[neg], X[neg]
    for it in range(max_iter):
        e = np.exp(X @ beta)
        en = e[neg] * rn
        negsum = np.bincount(gn, weights=en, minlength=G)
        negx = np.stack([np.bincount(gn, weights=Xn[:, j] * en, minlength=G) for j in range(k)], 1)
        ec = e[posr]
        D = ec + negsum[gc]
        m = (Xc * ec[:, None] + negx[gc]) / D[:, None]
        score = Xc - m
        grad = (score * cw[:, None]).sum(0)
        # Hessian: sum_c cw_c [E_c(xx') - m_c m_c'], with the non-click part of E_c(xx') collected
        # per impression: sum_c cw_c/D_c * sum_{j in imp(c), non-click} e_j x_j x_j'.
        f = np.bincount(gc, weights=cw / D, minlength=G)
        exx = (Xc * (cw * ec / D)[:, None]).T @ Xc + (Xn * (en * f[gn])[:, None]).T @ Xn
        H = -(exx - (m * cw[:, None]).T @ m)
        step = np.linalg.solve(H, grad)
        beta = beta - step
        if np.max(np.abs(step)) < 1e-8:
            break
    if beta_only:
        return beta
    ll = float((Xc @ beta - np.log(D)).sum())
    Hinv = np.linalg.inv(-H)
    users = u_imp[gc]
    Gu = np.stack([np.bincount(users, weights=score[:, j], minlength=int(d["n_users"])) for j in range(k)], 1)
    V = Hinv @ (Gu.T @ Gu) @ Hinv
    se_r, se_m = np.sqrt(np.diag(V)), np.sqrt(np.diag(Hinv))
    return {"n_clicks": int(len(gc)), "n_impressions": int(np.unique(gc).size), "iterations": it + 1,
            "loglik": round(ll, 2), "loglik_null": round(float(-np.log(1 + negsum[gc]).sum()), 2),
            "coef": {n: {"beta": r4(beta[i]), "se_cluster_user": r4(se_r[i]), "se_model": r4(se_m[i]),
                         "ci95": [r4(beta[i] - 1.96 * se_r[i]), r4(beta[i] + 1.96 * se_r[i])],
                         "odds_ratio_per_sd": r4(np.exp(beta[i])), "z": r4(beta[i] / se_r[i])}
                     for i, n in enumerate(names)}}


def rho(x, y) -> float:
    return float(spearmanr(x, y).statistic)


def rel(p: Path) -> str:
    try:
        return p.resolve().relative_to(REPO).as_posix()
    except ValueError:
        return p.name


# ---------------------------------------------------------------- main
def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scores", type=Path, required=True)
    ap.add_argument("--gate", type=Path, required=True)
    ap.add_argument("--tag", required=True)
    args = ap.parse_args()

    gate = json.loads(args.gate.read_text(encoding="utf-8"))
    passed = set(gate["gate_pass"])
    raw = load_scores(args.scores)
    arts = read_jsonl(DATA / "articles_to_score.jsonl")
    ids = [r["id"] for r in arts]
    assert all(raw.get(i) is not None for i in ids), "unscored candidate article"
    art_index = {nid: i for i, nid in enumerate(ids)}
    Sc = np.array([[raw[i][v] for v in VALUES] for i in ids], dtype=float)
    Z = (Sc - Sc.mean(0)) / Sc.std(0)
    empty_abs = np.array([not (r.get("abstract") or "").strip() for r in arts])
    meta = {}
    import csv
    with open(DATA / "article_meta.csv", encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            meta[r["id"]] = r
    cat = np.array([meta[i]["category"] for i in ids])
    it_, ct_ = (np.array([float(meta[i][k]) for i in ids]) for k in ("imps_train", "clicks_train"))
    id_, cd_ = (np.array([float(meta[i][k]) for i in ids]) for k in ("imps_dev", "clicks_dev"))
    rand = np.random.default_rng(SEED + 1).random(len(ids))
    sum7 = Sc.sum(1)
    vix = {v: j for j, v in enumerate(VALUES)}
    out = {"meta": {"script": "research2/n05_clicks.py", "tag": args.tag, "plan": "HYPOTHESES.md v1",
                    "run_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    "n_boot": N_BOOT, "seed": SEED, "gate_pass": sorted(passed),
                    "inputs_sha256": {rel(p): sha256_file(p) for p in
                                      (args.scores, args.gate, DATA / "articles_to_score.jsonl",
                                       DATA / "article_meta.csv")}}}

    # ---- A1 / H1 / H2 / E1 / E4 / E5 / E3-AUC, per split
    for split in ("dev", "train"):
        d = parse_split(split, art_index)
        fam = Family(d)
        a = d["a"]
        for v in VALUES:
            fam.add(v, Sc[a, vix[v]])
        fam.add("sum7", sum7[a])
        fam.add("random", rand[a])
        if split == "dev":
            small = d["ncand"][d["g"]] <= 10
            nonempty = ~empty_abs[a]
            covered = it_[a] >= 1
            for v in VALUES:
                fam.add(f"E5_le10cand:{v}", Sc[a, vix[v]], small)
                fam.add(f"E5_noemptyabs:{v}", Sc[a, vix[v]], nonempty)
                fam.add(f"E4_covered:{v}", Sc[a, vix[v]], covered)
            fam.add("E4_covered:sum7", sum7[a], covered)
            with np.errstate(invalid="ignore", divide="ignore"):
                ctr_train = np.where(it_ > 0, ct_ / it_, np.nan)
            fam.add("E4_covered:train_ctr", ctr_train[a], covered)
            for c in sorted(set(cat)):
                mc = cat[a] == c
                for v in VALUES:
                    fam.add(f"E3_cat:{c}:{v}", Sc[a, vix[v]], mc)
        point, boot, nimp = fam.bootstrap(SEED)
        res = {"n_impressions_total": fam.G, "n_users": fam.U, "n_candidate_rows": int(len(a)),
               "n_impressions_usable": nimp[VALUES[0]],
               "mean_candidates_per_impression": r4(d["ncand"].mean()),
               "click_rate_rows": r4(d["y"].mean()), "auc": {}}
        for c in fam.cols:
            if c.startswith("E3_cat:") and nimp[c] < MIN_CAT_IMPRESSIONS:
                continue
            res["auc"][c] = {"auc": r4(point[c]), "ci95": ci(boot[c]), "p_vs_0.5": r4(boot_p(boot[c], 0.5)),
                             "n_impressions": nimp[c]}
        if split == "dev":
            res["E4_coverage"] = {"candidate_rows_with_train_ctr": r4(covered.mean()),
                                  "impressions_usable": nimp["E4_covered:train_ctr"]}
            res["E3_categories_dropped_lt_min_impressions"] = sorted(
                {c.split(":")[1] for c in fam.cols if c.startswith("E3_cat:") and nimp[c] < MIN_CAT_IMPRESSIONS})
        # H1 (primary split only for the test; train reported as replication)
        pv = {v: boot_p(boot[v], 0.5) for v in H1_VALUES}
        ph = holm(pv)
        res["H1"] = {v: {"auc": r4(point[v]), "ci95": ci(boot[v]), "p": r4(pv[v]), "p_holm_m3": r4(ph[v]),
                         "confirmatory": v in passed,
                         "supported": bool(point[v] > 0.5 and ph[v] < 0.05)} for v in H1_VALUES}
        diff = boot["importance"] - boot["entertainment"]
        res["H2"] = {"auc_importance_minus_entertainment": r4(point["importance"] - point["entertainment"]),
                     "ci95": ci(diff), "confirmatory": {"importance", "entertainment"} <= passed,
                     "supported": bool(np.percentile(diff, 97.5) < 0)}
        res["paired_diffs_vs_importance"] = {
            v: {"diff": r4(point[v] - point["importance"]), "ci95": ci(boot[v] - boot["importance"])}
            for v in VALUES if v != "importance"}
        if split == "dev":
            res["E4_paired_diffs_vs_train_ctr"] = {
                v: {"diff": r4(point[f"E4_covered:{v}"] - point["E4_covered:train_ctr"]),
                    "ci95": ci(boot[f"E4_covered:{v}"] - boot["E4_covered:train_ctr"])}
                for v in VALUES + ["sum7"]}
        out[split] = res
        print(f"[{split}] usable impressions {res['n_impressions_usable']:,} of {fam.G:,}; users {fam.U:,}")
        for c in VALUES + ["sum7", "random"]:
            x = res["auc"][c]
            print(f"   {c:13s} AUC {x['auc']:.4f} [{x['ci95'][0]:.4f}, {x['ci95'][1]:.4f}]")

        if split == "dev":
            # ---- E2 conditional logit (all seven, as planned) and E5 without gate-failing values
            out["E2"] = conditional_logit(d, Z, VALUES)
            keep = [v for v in VALUES if v in passed]
            out["E5_E2_gate_passing_only"] = conditional_logit(d, Z[:, [vix[v] for v in keep]], keep)
            print("   E2 betas:", {k: v["beta"] for k, v in out["E2"]["coef"].items()})

    # ---- H3 and E3 (article level, pooled click rate)
    imps = it_ + id_
    clicks = ct_ + cd_
    sel = imps >= MIN_IMPS_CTR
    ctr = clicks[sel] / imps[sel]
    Ssel, csel = Sc[sel], cat[sel]
    rng = np.random.default_rng(SEED)
    n = int(sel.sum())
    bidx = rng.integers(0, n, size=(N_BOOT, n))
    rho_pt = {v: rho(Ssel[:, vix[v]], ctr) for v in VALUES}
    rho_bt = {v: np.array([rho(Ssel[b, vix[v]], ctr[b]) for b in bidx]) for v in VALUES}
    dh3 = rho_bt["importance"] - rho_bt["entertainment"]
    out["H3"] = {"n_articles": n, "rho_ctr": {v: {"rho": r4(rho_pt[v]), "ci95": ci(rho_bt[v])} for v in VALUES},
                 "rho_importance_minus_entertainment": r4(rho_pt["importance"] - rho_pt["entertainment"]),
                 "ci95": ci(dh3), "confirmatory": {"importance", "entertainment"} <= passed,
                 "supported": bool(np.percentile(dh3, 97.5) < 0)}
    per_cat = {}
    for c in sorted(set(csel)):
        m = csel == c
        if m.sum() < MIN_CAT_ARTICLES:
            continue
        per_cat[c] = {"n_articles": int(m.sum()),
                      "rho_importance_ctr": r4(rho(Ssel[m, vix["importance"]], ctr[m])),
                      "rho_entertainment_ctr": r4(rho(Ssel[m, vix["entertainment"]], ctr[m]))}
    q1, q3 = np.percentile(ctr, [25, 75])
    imp = Ssel[:, vix["importance"]]
    ignored = (imp >= 4) & (ctr <= q1)
    clickbait = (imp <= 2) & (ctr >= q3)
    sel_ids = np.array(ids)[sel]
    out["E3_article_level"] = {
        "per_category_rho": per_cat,
        "quadrants": {"ctr_q1": r4(q1), "ctr_q3": r4(q3),
                      "important_but_ignored": {"n": int(ignored.sum()),
                                                "by_category": {c: int(((csel == c) & ignored).sum()) for c in sorted(set(csel)) if ((csel == c) & ignored).any()},
                                                "ids": sel_ids[ignored].tolist()},
                      "clicked_but_unimportant": {"n": int(clickbait.sum()),
                                                  "by_category": {c: int(((csel == c) & clickbait).sum()) for c in sorted(set(csel)) if ((csel == c) & clickbait).any()},
                                                  "ids": sel_ids[clickbait].tolist()},
                      "share_high_importance_ge4": r4((imp >= 4).mean()),
                      "share_low_importance_le2": r4((imp <= 2).mean())}}
    titles = {r["id"]: r["title"] for r in arts}
    ex = {}
    for name, m in (("important_but_ignored", ignored), ("clicked_but_unimportant", clickbait)):
        order = np.argsort(ctr[m])
        order = order if name == "important_but_ignored" else order[::-1]
        ex[name] = [{"id": sel_ids[m][i], "category": csel[m][i], "ctr": r4(ctr[m][i]),
                     "importance": int(imp[m][i]), "headline": titles[sel_ids[m][i]]} for i in order[:15]]
    write_json(DATA / f"n05_quadrant_examples_{args.tag}.json", ex)  # MIND text: git-ignored

    path = RESULTS / f"n05_clicks_{args.tag}.json"
    write_json(path, out)
    print("H1 dev:", {v: (x["auc"], x["p_holm_m3"], x["confirmatory"], x["supported"]) for v, x in out["dev"]["H1"].items()})
    print("H2 dev:", out["dev"]["H2"])
    print("H3:", {k: out["H3"][k] for k in ("n_articles", "rho_importance_minus_entertainment", "ci95", "supported")})
    print("wrote", path)


if __name__ == "__main__":
    main()
