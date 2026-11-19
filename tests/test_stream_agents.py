"""
MAPNAI — tests/test_stream_agents.py
The agent side of the stream: AgentPool keeps models loaded across runs, run_agent_pipeline on explicit article ids,
and Agent 4 risk sharing inside an event cluster.
"""

from unittest.mock import MagicMock

import pipeline
from pipeline import AgentPool, _process_one_article, _shared_risk


def stats():
    return {"ner_processed": 0, "total_entities": 0, "classified": 0, "summarized": 0, "risk_scored": 0,
            "risk_skipped": 0, "out_of_scope": 0, "articles_ok": 0, "failed": 0, "errors": []}


SIBLING = {"article_id": "sib-123456", "risk_score": 72, "risk_confidence": 0.8, "risk_level": "high",
           "risk_reasoning": "r", "action_recommendation": "a", "risk_model": "m", "risk_processed_at": "t"}


class TestRiskSharing:
    def test_shared_from_a_model_scored_cluster_mate(self):
        mongo = MagicMock()
        mongo.find_cluster_risk.return_value = SIBLING
        shared = _shared_risk({"article_id": "a1", "cluster_id": "c1"}, mongo)
        assert shared["risk_score"] == 72 and shared["risk_shared_from"] == "sib-123456"
        assert "risk_processed_at" not in shared
        mongo.find_cluster_risk.assert_called_once_with("c1", "a1")

    def test_nothing_to_share(self, monkeypatch):
        mongo = MagicMock()
        mongo.find_cluster_risk.return_value = None
        assert _shared_risk({"article_id": "a1", "cluster_id": "c1"}, mongo) is None
        assert _shared_risk({"article_id": "a1"}, mongo) is None                     # not clustered yet
        assert _shared_risk({"article_id": "a1", "cluster_id": "c1"}, None) is None
        monkeypatch.setattr(pipeline.settings, "risk_share_in_cluster", False)
        mongo.find_cluster_risk.return_value = SIBLING
        assert _shared_risk({"article_id": "a1", "cluster_id": "c1"}, mongo) is None

    def test_agent_4_is_skipped_when_the_score_is_shared(self):
        mongo = MagicMock()
        mongo.find_cluster_risk.return_value = SIBLING
        mongo.update_article_risk.return_value = True
        risk_scorer = MagicMock()
        s = stats()
        doc = {"article_id": "a1", "cluster_id": "c1", "title": "T", "body": "B", "domain": "sports",
               "ner_processed": True, "classified": True, "summarized": True, "in_scope": True}
        _process_one_article(doc, ner_agent=None, classifier=None, summarizer=None, risk_scorer=risk_scorer,
                             faiss_store=None, agents={4}, stats=s, mongo=mongo)
        risk_scorer.process_article.assert_not_called()
        assert s["risk_shared"] == 1 and s["risk_scored"] == 0 and s["articles_ok"] == 1
        mongo.update_article_risk.assert_called_once()
        assert mongo.update_article_risk.call_args.args[1]["risk_shared_from"] == "sib-123456"

    def test_agent_4_runs_when_nothing_is_shared(self):
        mongo = MagicMock()
        mongo.find_cluster_risk.return_value = None
        risk_scorer = MagicMock()
        risk_scorer.process_article.side_effect = lambda p: {**p, "risk_score": 10}
        s = stats()
        doc = {"article_id": "a1", "cluster_id": "c1", "title": "T", "body": "B", "domain": "sports",
               "ner_processed": True, "classified": True, "summarized": True, "in_scope": True}
        _process_one_article(doc, ner_agent=None, classifier=None, summarizer=None, risk_scorer=risk_scorer,
                             faiss_store=None, agents={4}, stats=s, mongo=mongo)
        risk_scorer.process_article.assert_called_once()
        assert s["risk_scored"] == 1 and s.get("risk_shared", 0) == 0


class TestAgentPool:
    def test_models_load_once_and_survive_runs(self, monkeypatch):
        ner_cls = MagicMock()
        ner_cls.return_value.process.return_value = {"entities": [], "_metadata": {"entity_count": 0}}
        monkeypatch.setattr(pipeline, "NERAgent", ner_cls)
        mongo = MagicMock()
        mongo.is_available.return_value = True
        mongo.get_articles_by_ids.side_effect = lambda ids: [{"article_id": i, "title": "T", "body": "B",
                                                              "domain": "sports"} for i in ids]
        pool = AgentPool(mongo=mongo)
        first = pipeline.run_agent_pipeline(agents={1}, pool=pool, article_ids=["a1", "a2"])
        second = pipeline.run_agent_pipeline(agents={1}, pool=pool, article_ids=["a3"])
        assert first["pending_found"] == 2 and first["ner_processed"] == 2 and second["ner_processed"] == 1
        assert ner_cls.call_count == 1                                     # loaded once
        ner_cls.return_value.close.assert_not_called()                     # a pooled run closes nothing
        mongo.get_articles_by_ids.assert_any_call(["a1", "a2"])
        pool.close()
        assert pool.ner_agent is None
