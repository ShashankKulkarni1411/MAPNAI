"""Checks for n06_twoway. Run: ~/.venvs/mapnai-research/Scripts/python research2/test_n06.py"""
import sys
from pathlib import Path

import numpy as np
from sklearn.metrics import roc_auc_score

sys.path.insert(0, str(Path(__file__).resolve().parent))
from n05_clicks import grouped_auc  # noqa: E402
from n06_twoway import Sorted, perm_test  # noqa: E402


def make(seed=3, G=400, A=150):
    rng = np.random.default_rng(seed)
    sizes = rng.integers(1, 30, G)
    g = np.repeat(np.arange(G), sizes)
    a = rng.integers(0, A, len(g))
    y = (rng.random(len(g)) < 0.2).astype(np.int8)
    return rng, g, a, y, A


def test_unweighted_equals_grouped_auc():
    rng, g, a, y, A = make()
    s = rng.integers(1, 6, A).astype(float)[a]
    G = g.max() + 1
    np.testing.assert_allclose(Sorted(g, a, y, s, G).auc(), grouped_auc(g, s, y, G), equal_nan=True, atol=1e-12)


def test_integer_weights_equal_row_duplication():
    rng, g, a, y, A = make(4)
    s_art = rng.integers(1, 6, A).astype(float)
    w = rng.poisson(1.0, A).astype(float)
    G = g.max() + 1
    got = Sorted(g, a, y, s_art[a], G).auc(w)
    for i in range(G):
        m = g == i
        rows = np.repeat(np.flatnonzero(m), w[a[m]].astype(int))
        yy, ss = y[rows], s_art[a[rows]]
        if len(rows) and 0 < yy.sum() < len(yy):
            assert abs(got[i] - roc_auc_score(yy, ss)) < 1e-12, i
        else:
            assert np.isnan(got[i]), i


def test_permutation_obs_matches_and_null_centred():
    rng, g, a, y, A = make(5, G=3000, A=400)
    s_art = rng.integers(1, 6, A).astype(float)
    d = {"g": g, "a": a, "y": y, "ncand": np.zeros(g.max() + 1)}
    res = perm_test(d, s_art, 200, np.random.default_rng(0))
    G = g.max() + 1
    auc = grouped_auc(g, s_art[a], y, G)
    assert abs(res["auc"] - np.nanmean(auc)) < 1e-4
    assert abs(res["null_mean"] - 0.5) < 0.01


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
