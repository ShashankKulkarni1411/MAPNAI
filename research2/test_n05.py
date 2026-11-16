"""Checks for n05_clicks statistics. Run: ~/.venvs/mapnai-research/Scripts/python research2/test_n05.py"""
import math
import sys
from pathlib import Path

import numpy as np
from sklearn.metrics import roc_auc_score

sys.path.insert(0, str(Path(__file__).resolve().parent))
from n05_clicks import conditional_logit, grouped_auc, holm  # noqa: E402


def test_grouped_auc_matches_sklearn():
    rng = np.random.default_rng(1)
    G = 300
    sizes = rng.integers(1, 40, G)
    g = np.repeat(np.arange(G), sizes)
    s = rng.integers(1, 6, len(g)).astype(float)       # heavy ties, like 1-5 scores
    s[::7] = rng.random(len(s[::7]))                     # some continuous values
    y = (rng.random(len(g)) < 0.15).astype(int)
    perm = rng.permutation(len(g))                       # input order must not matter
    auc = grouped_auc(g[perm], s[perm], y[perm], G + 2)  # +2 empty groups -> NaN
    for i in range(G):
        m = g == i
        if 0 < y[m].sum() < m.sum():
            assert math.isclose(auc[i], roc_auc_score(y[m], s[m]), abs_tol=1e-12), i
        else:
            assert math.isnan(auc[i])
    assert np.isnan(auc[G:]).all()


def test_holm():
    out = holm({"a": 0.01, "b": 0.04, "c": 0.03})
    assert math.isclose(out["a"], 0.03) and math.isclose(out["c"], 0.06) and math.isclose(out["b"], 0.06)


def test_conditional_logit_recovers_beta():
    rng = np.random.default_rng(2)
    n_art, k, G = 2000, 2, 6000
    Z = rng.standard_normal((n_art, k))
    true = np.array([0.8, -0.4])
    g, a, y = [], [], []
    for i in range(G):
        cand = rng.choice(n_art, 12, replace=False)
        p = np.exp(Z[cand] @ true)
        c = rng.choice(12, p=p / p.sum())
        for j, art in enumerate(cand):
            g.append(i); a.append(art); y.append(int(j == c))
    d = {"g": np.array(g), "a": np.array(a), "y": np.array(y, np.int8), "ncand": np.full(G, 12),
         "uimp": np.arange(G) % 500, "n_users": np.array(500)}
    res = conditional_logit(d, Z, ["x1", "x2"])
    # Unbiased over seeds 2-11 (mean 0.795, -0.397); seed 2 alone is a 2-SE draw, so allow 4 SE.
    for name, t in zip(("x1", "x2"), true):
        c = res["coef"][name]
        assert abs(c["beta"] - t) < 4 * c["se_cluster_user"], (name, c)


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
