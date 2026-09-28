from unittest.mock import MagicMock

from pipeline import _collect_pending_docs, _process_one_article
import run_mapnai


def test_agents_receive_merged_payload_in_order():
    article = {
        "article_id": "article-1",
        "title": "Central bank decision",
        "body": "The central bank changed interest rates.",
        "domain": "finance",
    }
    ner = MagicMock()
    ner.process.return_value = {
        "entities": [{"text": "Central bank", "label": "Organization"}],
        "_metadata": {"entity_count": 1},
    }
    classifier = MagicMock()
    classifier.process_article.side_effect = lambda payload: {
        **payload,
        "domain": "finance",
        "sentiment": -0.2,
    }
    summarizer = MagicMock()
    summarizer.process_article.side_effect = lambda payload: {
        **payload,
        "summary_short": "Rates changed.",
        "summary_long": "The central bank changed interest rates.",
    }
    risk_scorer = MagicMock()
    risk_scorer.process_article.side_effect = lambda payload: {
        **payload,
        "risk_score": 42,
    }
    stats = {
        "ner_processed": 0,
        "total_entities": 0,
        "classified": 0,
        "summarized": 0,
        "risk_scored": 0,
        "articles_ok": 0,
        "failed": 0,
        "errors": [],
    }

    _process_one_article(
        article,
        ner_agent=ner,
        classifier=classifier,
        summarizer=summarizer,
        risk_scorer=risk_scorer,
        faiss_store=None,
        agents={1, 2, 3, 4},
        stats=stats,
    )

    classified_input = classifier.process_article.call_args.args[0]
    summary_input = summarizer.process_article.call_args.args[0]
    risk_input = risk_scorer.process_article.call_args.args[0]
    assert classified_input["entities"][0]["text"] == "Central bank"
    assert summary_input["sentiment"] == -0.2
    assert risk_input["summary_short"] == "Rates changed."
    assert stats["articles_ok"] == 1
    assert stats["failed"] == 0


def test_full_runner_invokes_ingestion_before_agents(monkeypatch):
    calls = []
    ingestion = MagicMock()
    ingestion.model_dump.return_value = {"total_stored": 3}
    batches = iter([
        {
            "pending_found": 3,
            "articles_ok": 3,
            "failed": 0,
            "ner_processed": 3,
            "classified": 3,
            "summarized": 3,
            "risk_scored": 3,
            "total_entities": 4,
            "errors": [],
        },
        {"pending_found": 0, "articles_ok": 0},
    ])

    monkeypatch.setattr(
        run_mapnai,
        "run_ingestion_pipeline",
        lambda: calls.append("ingestion") or ingestion,
    )
    monkeypatch.setattr(
        run_mapnai,
        "run_agent_pipeline",
        lambda limit: calls.append(("agents", limit)) or next(batches),
    )

    result = run_mapnai.run_full_pipeline(limit=7)

    assert calls == ["ingestion", ("agents", 7), ("agents", 7)]
    assert result == {
        "ingestion": {"total_stored": 3},
        "agents": {
            "articles_ok": 3,
            "failed": 0,
            "ner_processed": 3,
            "classified": 3,
            "summarized": 3,
            "risk_scored": 3,
            "out_of_scope": 0,
            "total_entities": 4,
            "batches": 2,
            "remaining_pending": {
                "remaining_pending_ner": 0,
                "remaining_pending_classification": 0,
                "remaining_pending_summarization": 0,
                "remaining_pending_risk_scoring": 0,
            },
            "errors": [],
        },
    }


def test_collect_pending_docs_falls_through_to_downstream_queue():
    mongo = MagicMock()
    mongo.get_articles_pending_ner.return_value = []
    mongo.get_articles_pending_classification.return_value = [{"article_id": "a1"}]

    docs = _collect_pending_docs(mongo, agents={1, 2, 3, 4}, limit=10, skip=0)

    assert docs == [{"article_id": "a1"}]
    mongo.get_articles_pending_summarization.assert_not_called()


def test_full_runner_stops_when_pending_queues_do_not_change(monkeypatch):
    ingestion = MagicMock()
    ingestion.model_dump.return_value = {}
    pending_batch = {
        "pending_found": 1,
        "articles_ok": 1,
        "remaining_pending_ner": 1,
        "remaining_pending_classification": 0,
        "remaining_pending_summarization": 0,
        "remaining_pending_risk_scoring": 0,
    }
    agent_pipeline = MagicMock(side_effect=[pending_batch, pending_batch])
    monkeypatch.setattr(run_mapnai, "run_ingestion_pipeline", lambda: ingestion)
    monkeypatch.setattr(run_mapnai, "run_agent_pipeline", agent_pipeline)

    result = run_mapnai.run_full_pipeline()

    assert agent_pipeline.call_count == 2
    assert result["agents"]["remaining_pending"]["remaining_pending_ner"] == 1

def test_out_of_scope_article_skips_agents_3_and_4():
    article = {"article_id": "article-2", "title": "Rate hike", "body": "Rates rose.", "domain": "finance"}
    ner = MagicMock()
    ner.process.return_value = {"entities": [], "_metadata": {"entity_count": 0}}
    classifier = MagicMock()
    classifier.process_article.side_effect = lambda payload: {
        **payload, "domain": "other", "in_scope": False, "out_of_scope_reason": "off_topic",
    }
    summarizer, risk_scorer = MagicMock(), MagicMock()
    stats = {
        "ner_processed": 0, "total_entities": 0, "classified": 0, "summarized": 0,
        "risk_scored": 0, "out_of_scope": 0, "articles_ok": 0, "failed": 0, "errors": [],
    }

    _process_one_article(
        article, ner_agent=ner, classifier=classifier, summarizer=summarizer,
        risk_scorer=risk_scorer, faiss_store=None, agents={1, 2, 3, 4}, stats=stats,
    )

    summarizer.process_article.assert_not_called()
    risk_scorer.process_article.assert_not_called()
    assert stats["out_of_scope"] == 1
    assert stats["articles_ok"] == 1


def test_agent_pipeline_stops_early_when_mongo_is_down(monkeypatch):
    import pipeline

    store = MagicMock()
    store.is_available.return_value = False
    monkeypatch.setattr(pipeline, "MongoStore", lambda: store)
    ner_cls = MagicMock()
    monkeypatch.setattr(pipeline, "NERAgent", ner_cls)

    stats = pipeline.run_agent_pipeline(limit=5)

    assert stats["pending_found"] == 0
    assert stats["errors"] == [{"error": "MongoDB unavailable"}]
    ner_cls.assert_not_called()          # no model loading when there's no queue to read
    store.get_articles_pending_ner.assert_not_called()
