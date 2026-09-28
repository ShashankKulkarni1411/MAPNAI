"""
Tests for MAPNAI's own Agent 2 classifier: taxonomy validation, the multi-task model's
save/load/predict path (with a tiny offline encoder), and Agent 2's model download / fallback.
"""

import json
from unittest.mock import MagicMock

import pytest
import torch
from tokenizers import Tokenizer, models, pre_tokenizers
from transformers import PreTrainedTokenizerFast, RobertaConfig, RobertaModel

import agents.agent2_classifier as agent2
from agents.classifier_model import (
    MultiTaskNewsClassifier,
    NewsClassifierPredictor,
    compute_loss,
    save_model,
)
from config import classifier_taxonomy as tax


# ── Taxonomy ────────────────────────────────────────────────

def test_two_categories_plus_reject_label():
    assert tax.DOMAINS == ["entertainment_movies", "sports", "other"]
    prompt = tax.build_label_prompt()
    assert all(d in prompt for d in tax.DOMAINS)


@pytest.mark.parametrize("raw,ok", [
    ({"domain": "sports", "sentiment": 0.3, "urgency_flag": False}, True),
    ({"domain": "entertainment_movies", "sentiment": -0.2, "urgency_flag": True}, True),
    ({"domain": "finance", "sentiment": 0.0, "urgency_flag": False}, False),
    ({"domain": "other", "sentiment": "x", "urgency_flag": False}, False),
    ({"domain": "other", "sentiment": 0.0, "urgency_flag": "yes"}, False),
    (None, False),
])
def test_validate_label(raw, ok):
    assert (tax.validate_label(raw) is not None) == ok


def test_validate_label_clamps_sentiment_and_drops_extra_fields():
    label = tax.validate_label({"domain": "other", "category": "Other", "sentiment": 4, "urgency_flag": True})
    assert label == {"domain": "other", "sentiment": 1.0, "urgency_flag": True}


# ── Model ───────────────────────────────────────────────────

def _tiny_model_and_tokenizer(n_legacy_categories: int = 0):
    vocab = {"[PAD]": 0, "[UNK]": 1, "kohli": 2, "injured": 3, "film": 4, "box": 5, "office": 6}
    tok = Tokenizer(models.WordLevel(vocab, unk_token="[UNK]"))
    tok.pre_tokenizer = pre_tokenizers.Whitespace()
    tokenizer = PreTrainedTokenizerFast(tokenizer_object=tok, pad_token="[PAD]", unk_token="[UNK]")
    config = RobertaConfig(vocab_size=len(vocab), hidden_size=16, num_hidden_layers=1,
                           num_attention_heads=2, intermediate_size=32,
                           max_position_embeddings=64, pad_token_id=0)
    torch.manual_seed(0)
    model = MultiTaskNewsClassifier(RobertaModel(config), len(tax.DOMAINS), n_legacy_categories)
    return model, tokenizer


def test_loss_backpropagates():
    model, tokenizer = _tiny_model_and_tokenizer()
    enc = tokenizer(["kohli injured", "film box office"], padding=True, return_tensors="pt")
    batch = {
        "domain": torch.tensor([tax.DOMAIN_TO_ID["sports"], tax.DOMAIN_TO_ID["entertainment_movies"]]),
        "urgency": torch.tensor([1, 0]),
        "sentiment": torch.tensor([-0.5, 0.4]),
    }
    out = model(enc["input_ids"], enc["attention_mask"])
    loss = compute_loss(out, batch, urgency_pos_weight=3.0, domain_weight=torch.tensor([1.0, 2.0, 0.5]))
    loss.backward()
    assert torch.isfinite(loss)
    assert model.domain_head.weight.grad is not None


def test_save_load_predict_roundtrip(tmp_path):
    model, tokenizer = _tiny_model_and_tokenizer()
    save_model(model, tokenizer, tax.label_config(max_length=32), str(tmp_path))

    predictor = NewsClassifierPredictor(str(tmp_path), device="cpu")
    results = predictor.predict(["kohli injured", "film box office", "unknown words here"], batch_size=2)

    assert len(results) == 3
    for r in results:
        assert r["domain"] in tax.DOMAINS
        assert r["category"] == r["domain"]
        assert 0.0 <= r["classification_confidence"] <= 1.0
        assert -1.0 <= r["sentiment"] <= 1.0
        assert isinstance(r["urgency_flag"], bool)


def test_loads_older_subcategory_model(tmp_path):
    """v2 models (with a 14-way category head) still load; category is reported as the domain."""
    model, tokenizer = _tiny_model_and_tokenizer(n_legacy_categories=14)
    legacy_cfg = {**tax.label_config(max_length=32), "taxonomy_version": "2.0.0",
                  "categories": [f"c{i}" for i in range(14)]}
    save_model(model, tokenizer, legacy_cfg, str(tmp_path))

    r = NewsClassifierPredictor(str(tmp_path), device="cpu").predict(["film box office"])[0]
    assert r["domain"] in tax.DOMAINS and r["category"] == r["domain"]


def test_urgency_threshold_is_respected(tmp_path):
    model, tokenizer = _tiny_model_and_tokenizer()
    save_model(model, tokenizer, tax.label_config(max_length=32, urgency_threshold=0.0), str(tmp_path / "low"))
    save_model(model, tokenizer, tax.label_config(max_length=32, urgency_threshold=1.01), str(tmp_path / "high"))
    texts = ["kohli injured", "film box office"]

    low = NewsClassifierPredictor(str(tmp_path / "low"), device="cpu")
    probs = low.urgency_probabilities(texts)
    assert len(probs) == 2 and all(0.0 <= p <= 1.0 for p in probs)
    assert all(r["urgency_flag"] for r in low.predict(texts))
    assert not any(r["urgency_flag"] for r in NewsClassifierPredictor(str(tmp_path / "high"), device="cpu").predict(texts))


def test_format_text():
    assert NewsClassifierPredictor.format_text("Title", "Body") == "Title. Body"
    assert NewsClassifierPredictor.format_text("", "Body only") == "Body only"
    assert NewsClassifierPredictor.format_text("Title only", "") == "Title only"


# ── Agent 2 ─────────────────────────────────────────────────

def test_agent2_falls_back_without_model(tmp_path, monkeypatch):
    monkeypatch.setattr(agent2, "MODEL_DIR", tmp_path / "missing")
    monkeypatch.setattr(agent2, "_PREDICTOR", None)
    monkeypatch.setattr(agent2, "_download_model", lambda: False)  # e.g. offline
    mongo = MagicMock()
    mongo.update_article_classification.return_value = True

    agent = agent2.EventClassifierAgent(mongo_store=mongo)
    out = agent.process_article({"article_id": "a1", "title": "Kohli injured", "body": "Ruled out."})

    assert out["domain"] == "other" and out["category"] == "other"
    assert out["classification_confidence"] == 0.0
    assert out["title"] == "Kohli injured"
    assert out["in_scope"] is False and out["out_of_scope_reason"] == "classifier_unavailable"
    # Nothing is written, so the article is classified for real once the model is available
    mongo.update_article_classification.assert_not_called()


def test_agent2_downloads_missing_model(tmp_path, monkeypatch):
    """With no local model, Agent 2 pulls it from the Hub once and then uses it."""
    model_dir = tmp_path / "classifier"
    monkeypatch.setattr(agent2, "MODEL_DIR", model_dir)
    monkeypatch.setattr(agent2, "_PREDICTOR", None)
    monkeypatch.setenv("MAPNAI_CLASSIFIER_REPO", "someone/some-model")
    calls = []

    def fake_snapshot_download(repo_id, local_dir):
        calls.append(repo_id)
        model, tokenizer = _tiny_model_and_tokenizer()
        save_model(model, tokenizer, tax.label_config(max_length=32), local_dir)

    monkeypatch.setattr("huggingface_hub.snapshot_download", fake_snapshot_download)

    assert agent2._get_predictor() is not None
    assert agent2._get_predictor() is not None  # cached — no second download
    assert calls == ["someone/some-model"]


def test_agent2_download_can_be_disabled(tmp_path, monkeypatch):
    monkeypatch.setattr(agent2, "MODEL_DIR", tmp_path / "missing")
    monkeypatch.setattr(agent2, "_PREDICTOR", None)
    monkeypatch.setenv("MAPNAI_CLASSIFIER_REPO", "")
    monkeypatch.setattr("huggingface_hub.snapshot_download",
                        lambda **_: pytest.fail("should not download when disabled"))
    assert agent2._get_predictor() is None


def test_agent2_uses_trained_model(tmp_path, monkeypatch):
    model, tokenizer = _tiny_model_and_tokenizer()
    save_model(model, tokenizer, tax.label_config(max_length=32), str(tmp_path))
    monkeypatch.setattr(agent2, "MODEL_DIR", tmp_path)
    monkeypatch.setattr(agent2, "_PREDICTOR", None)

    agent = agent2.EventClassifierAgent(mongo_store=MagicMock())
    out = agent.process_article({"article_id": "a1", "title": "film box office", "body": "kohli"})

    assert out["domain"] in tax.DOMAINS and out["category"] == out["domain"]
    assert out["taxonomy_version"] == tax.TAXONOMY_VERSION
