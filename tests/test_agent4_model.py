"""Agent 4 offline scorer (RISK_BACKEND=model): tier fallback, factor formulas, output contract.
Offline: no model files from models/ are needed — a tiny TF-IDF model is trained in a temp folder."""

from datetime import datetime, timezone

import joblib
import pytest
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline

import agents.agent4_risk_scorer as a4
from agents.agent4_risk_scorer import RISK_FACTORS, RiskScoringAgent
from agents.risk_model import OfflineRiskScorer, recommendation
from config.risk_taxonomy import EVENT_TYPES, keyword_event

NOW = datetime(2026, 11, 19, 12, 0, tzinfo=timezone.utc)
DOPING = {
    "title": "Sprinter tests positive for banned steroid",
    "body": "The Olympic champion faces a four-year ban after failing a drug test, the anti-doping agency said.",
    "domain": "sports", "urgency_flag": True, "sentiment": -0.7, "published_at": "2026-11-19T08:00:00Z",
    "entities": [{"name": "Sprinter X", "salience": 0.9, "mention_count": 5}],
}
ROUTINE = {"title": "Film crosses 100 crore at the box office", "body": "The comedy had a strong second weekend.",
           "domain": "entertainment_movies", "sentiment": 0.7}


class FakeMongo:
    def __init__(self):
        self.writes = []

    def update_article_risk(self, article_id, data):
        self.writes.append((article_id, data))
        return True


@pytest.fixture
def tfidf_path(tmp_path):
    texts = ["club wins the league title", "film releases trailer", "player tested positive doping ban",
             "athlete fails drug test", "star ruled out with knee injury", "striker injured hamstring"] * 3
    labels = ["routine", "routine", "integrity", "integrity", "injury", "injury"] * 3
    pipe = make_pipeline(TfidfVectorizer(), LogisticRegression(max_iter=500)).fit(texts, labels)
    path = tmp_path / "event_model.joblib"
    joblib.dump({"pipeline": pipe}, path)
    return str(path)


def rules_only(tmp_path):
    return OfflineRiskScorer(str(tmp_path / "missing_dir"), str(tmp_path / "missing.joblib"))


def test_missing_models_fall_back_to_keyword_rules(tmp_path):
    scorer = rules_only(tmp_path)
    assert scorer.primary == "rules:v1"
    out = scorer.score(DOPING, now=NOW)
    assert out["risk_model"] == "rules:v1" and out["risk_event_type"] == "integrity"
    assert out["risk_confidence"] == 0.5


def test_broken_distilroberta_folder_is_skipped(tmp_path, tfidf_path):
    bad = tmp_path / "risk_event"
    bad.mkdir()
    (bad / "label_config.json").write_text("{not json", encoding="utf-8")
    assert OfflineRiskScorer(str(bad), tfidf_path).primary == "tfidf:event"


def test_tier_that_raises_hands_article_to_next(tmp_path, tfidf_path):
    scorer = OfflineRiskScorer(str(tmp_path / "missing"), tfidf_path)

    def boom(text):
        raise RuntimeError("model crashed")

    scorer.tiers[0].predict = boom
    assert scorer.score(DOPING, now=NOW)["risk_model"] == "rules:v1"


def test_output_contract(tmp_path, tfidf_path):
    out = OfflineRiskScorer(str(tmp_path / "missing"), tfidf_path).score(DOPING, now=NOW)
    assert set(out["risk_reasoning"]) == set(RISK_FACTORS)
    assert all(0 <= v <= 25 for v in out["risk_reasoning"].values())
    assert out["risk_score"] == sum(out["risk_reasoning"].values())
    assert out["risk_level"] == a4.risk_level(out["risk_score"])
    assert 0 <= out["risk_confidence"] <= 1 and out["action_recommendation"]
    assert out["risk_model"] == "tfidf:event"


def test_serious_event_outranks_routine(tmp_path):
    scorer = rules_only(tmp_path)
    serious, routine = scorer.score(DOPING, now=NOW), scorer.score(ROUTINE, now=NOW)
    assert serious["risk_level"] == "ESCALATE" and routine["risk_level"] == "MONITOR"


def test_keyword_guard_raises_severity_only_with_model_support():
    text = "Player tested positive for steroids"
    assert keyword_event(text)[0] == "integrity"
    weak = dict.fromkeys(EVENT_TYPES, 0.0) | {"controversy": 0.9, "integrity": 0.1}
    strong = dict.fromkeys(EVENT_TYPES, 0.0) | {"controversy": 0.7, "integrity": 0.3}
    assert OfflineRiskScorer.pick_event(weak, text)[0] == "controversy"
    assert OfflineRiskScorer.pick_event(strong, text)[0] == "integrity"


def test_factor_formulas():
    assert OfflineRiskScorer.entity_salience([]) == 5
    assert OfflineRiskScorer.entity_salience([{"salience": 1.0, "mention_count": 9}]) == 25
    assert OfflineRiskScorer.temporal_urgency(False, 0.5, None, "quiet news", NOW) == 3
    assert OfflineRiskScorer.temporal_urgency(True, -1.0, "2026-11-19T10:00:00Z", "breaking", NOW) == 25
    assert OfflineRiskScorer.temporal_urgency(False, 0.0, "not a date", "", NOW) == 3
    assert OfflineRiskScorer.domain_criticality("sports", 1.0) == 12
    assert OfflineRiskScorer.domain_criticality("other", 0.0) == 13


def test_recommendation_mentions_entity_and_evidence():
    text = recommendation("ALERT", "injury", "ruled out", "Player Y")
    assert text.startswith("Track closely") and "Player Y" in text and '"ruled out"' in text


def test_agent_model_backend_writes_without_llm(monkeypatch, tmp_path, tfidf_path):
    monkeypatch.setattr(a4.settings, "risk_backend", "model")
    monkeypatch.setattr(a4.settings, "risk_event_model_dir", str(tmp_path / "missing"))
    monkeypatch.setattr(a4.settings, "risk_tfidf_model_path", tfidf_path)
    monkeypatch.setattr(a4, "init_groq_llm", lambda *a: pytest.fail("Groq must not be used"))
    monkeypatch.setattr(a4, "init_ollama_llm", lambda *a: pytest.fail("Ollama must not be used"))
    agent = RiskScoringAgent(mongo_store=FakeMongo())
    assert agent.available

    out = agent.process_article({"article_id": "a1", **DOPING})
    assert "risk_skipped" not in out and out["risk_event_type"] == "integrity"
    (article_id, data), = agent.mongo.writes
    assert article_id == "a1" and data["risk_model"] == "tfidf:event"
