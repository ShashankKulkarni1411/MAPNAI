"""
MAPNAI — tests/conftest.py
Fixtures shared across test files.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pytest

from personalization.service import PersonalizationService
from tests.fakes import ARTICLES, CFG, NOW, PI, FakeMongo, FakeVectors, NamedExposures


@pytest.fixture
def dsvc():
    mongo = FakeMongo()
    mongo.db.processed_articles.insert_many([dict(a) for a in ARTICLES])
    mongo.db.personas.insert_one({
        "user_id": "u1", "name": "Ana", "topics": {"sports": 1.0}, "beta": {}, "history": [], "persona_version": 1,
        "pi_topk": [PI["acme"], PI["zeta"]], "alert_prefs": {"tz": "Asia/Kolkata"},
    })
    eye = np.eye(32, dtype=np.float32)
    vecs = {a["article_id"]: eye[i] for i, a in enumerate(ARTICLES)}
    fake = FakeVectors(vecs)
    fake.rows = dict(vecs)
    return PersonalizationService(mongo=mongo, exposures=NamedExposures([{"key": "acme", "role": "owns",
                                                                          "weight": 3}], {}),
                                  vectors=fake, cfg=CFG, clock=lambda: NOW)
