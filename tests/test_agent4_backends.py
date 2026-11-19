"""Agent 4 backend selection: Groq → local Ollama fallback, cooldown, risk_model, pending on total failure.
Offline: fake OpenAI-style clients and a fake Mongo store."""

import json
from types import SimpleNamespace

import pytest

import agents.agent4_risk_scorer as a4
from agents.agent4_risk_scorer import RiskScoringAgent

GOOD = {
    "risk_reasoning": {"event_severity": 20, "entity_salience": 10, "temporal_urgency": 5, "domain_criticality": 5},
    "risk_confidence": 0.8,
    "action_recommendation": "Watch it.",
}


class RateLimited(Exception):
    """Stands in for openai.RateLimitError (any non-parse exception is an API failure)."""


class FakeClient:
    def __init__(self, replies):
        self.replies = list(replies)   # str reply, or Exception instance to raise
        self.calls = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, model, messages, **kwargs):
        self.calls.append(model)
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=reply))])


class FakeMongo:
    def __init__(self):
        self.writes = []

    def update_article_risk(self, article_id, data):
        self.writes.append((article_id, data))
        return True


def make_agent(monkeypatch, backend, groq=None, ollama=None, cooldown=900.0):
    monkeypatch.setattr(a4.settings, "risk_backend", backend)
    monkeypatch.setattr(a4.settings, "risk_groq_cooldown_seconds", cooldown)
    monkeypatch.setattr(a4, "init_groq_llm", lambda *a: (groq, "big-model") if groq else (None, None))
    monkeypatch.setattr(a4, "init_ollama_llm", lambda *a: (ollama, "local-model") if ollama else (None, None))
    return RiskScoringAgent(mongo_store=FakeMongo())


def score(agent):
    return agent._call_llm_risk("t", "b", "finance", False, 0.0, "s", [])


def test_groq_success_records_model(monkeypatch):
    groq, ollama = FakeClient([json.dumps(GOOD)]), FakeClient([])
    result = score(make_agent(monkeypatch, "auto", groq, ollama))
    assert result["risk_score"] == 40 and result["risk_model"] == "groq:big-model"
    assert ollama.calls == []


def test_groq_failure_falls_back_to_ollama_and_cools_down(monkeypatch):
    groq = FakeClient([RateLimited("429"), json.dumps(GOOD)])
    ollama = FakeClient([json.dumps(GOOD), json.dumps(GOOD)])
    agent = make_agent(monkeypatch, "auto", groq, ollama)

    first = score(agent)
    assert first["risk_model"] == "ollama:local-model"
    second = score(agent)                       # inside the cooldown: Groq not even tried
    assert second["risk_model"] == "ollama:local-model"
    assert groq.calls == ["big-model"] and ollama.calls == ["local-model", "local-model"]


def test_groq_retried_after_cooldown(monkeypatch):
    groq = FakeClient([RateLimited("429"), json.dumps(GOOD)])
    ollama = FakeClient([json.dumps(GOOD)])
    agent = make_agent(monkeypatch, "auto", groq, ollama, cooldown=0.0)
    assert score(agent)["risk_model"] == "ollama:local-model"
    assert score(agent)["risk_model"] == "groq:big-model"


def test_bad_json_tries_next_backend_without_cooldown(monkeypatch):
    groq = FakeClient(["not json", json.dumps(GOOD)])
    ollama = FakeClient([json.dumps(GOOD)])
    agent = make_agent(monkeypatch, "auto", groq, ollama)
    assert score(agent)["risk_model"] == "ollama:local-model"
    assert score(agent)["risk_model"] == "groq:big-model"   # no cooldown after a parse failure


def test_groq_only_mode_never_uses_ollama(monkeypatch):
    groq = FakeClient([RateLimited("429")])
    agent = make_agent(monkeypatch, "groq", groq, FakeClient([json.dumps(GOOD)]))
    assert agent.ollama_client is None
    assert score(agent).get("_fallback") is True


def test_ollama_only_mode(monkeypatch):
    ollama = FakeClient([json.dumps(GOOD)])
    agent = make_agent(monkeypatch, "ollama", FakeClient([]), ollama)
    assert agent.client is None
    assert score(agent)["risk_model"] == "ollama:local-model"


def test_all_backends_fail_leaves_article_pending(monkeypatch):
    agent = make_agent(monkeypatch, "auto", FakeClient([RateLimited("429")]), FakeClient([ConnectionError("down")]))
    out = agent.process_article({"article_id": "a1", "title": "t", "body": "b"})
    assert out["risk_skipped"] is True
    assert agent.mongo.writes == []


def test_success_writes_risk_model_to_mongo(monkeypatch):
    agent = make_agent(monkeypatch, "auto", FakeClient([json.dumps(GOOD)]), None)
    out = agent.process_article({"article_id": "a1", "title": "t", "body": "b"})
    assert "risk_skipped" not in out
    (article_id, data), = agent.mongo.writes
    assert article_id == "a1" and data["risk_model"] == "groq:big-model" and data["risk_score"] == 40


def test_backend_name_normalized(monkeypatch):
    agent = make_agent(monkeypatch, "AUTO", FakeClient([]), FakeClient([]))
    assert agent.backend == "auto"


def test_unknown_backend_uses_offline_model(monkeypatch, tmp_path):
    monkeypatch.setattr(a4.settings, "risk_event_model_dir", str(tmp_path / "none"))
    monkeypatch.setattr(a4.settings, "risk_tfidf_model_path", str(tmp_path / "none.joblib"))
    agent = make_agent(monkeypatch, "bogus", FakeClient([]), FakeClient([]))
    assert agent.backend == "model" and agent.client is None and agent.ollama_client is None
