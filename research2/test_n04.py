"""Checks for n04_validity statistics. Run: ~/.venvs/mapnai-research/Scripts/python research2/test_n04.py"""
import math
import sys
from pathlib import Path

import numpy as np
from sklearn.metrics import cohen_kappa_score

sys.path.insert(0, str(Path(__file__).resolve().parent))
from n04_validity import qwk, rho  # noqa: E402


def test_qwk_matches_sklearn():
    rng = np.random.default_rng(0)
    for _ in range(200):
        n = int(rng.integers(5, 120))
        a = rng.integers(1, 6, n)
        b = np.clip(a + rng.integers(-2, 3, n), 1, 5)
        ref = cohen_kappa_score(a, b, weights="quadratic", labels=[1, 2, 3, 4, 5])
        assert math.isclose(qwk(a, b), ref, abs_tol=1e-9), (qwk(a, b), ref)


def test_qwk_perfect_and_degenerate():
    a = np.array([1, 2, 3, 4, 5, 3])
    assert math.isclose(qwk(a, a), 1.0)
    assert math.isnan(qwk(np.array([3, 3, 3]), np.array([3, 3, 3])))


def test_rho():
    x = np.array([1, 2, 3, 4, 5])
    assert math.isclose(rho(x, x * 2.0), 1.0)
    assert math.isclose(rho(x, -x * 1.0), -1.0)
    assert math.isnan(rho(np.array([2, 2, 2]), x[:3]))


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
