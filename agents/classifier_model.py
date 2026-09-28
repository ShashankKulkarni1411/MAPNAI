"""
MAPNAI — agents/classifier_model.py
MAPNAI's own multi-task news classifier (Agent 2's model).

One shared transformer encoder (DistilRoBERTa by default) with three heads:
  - domain        : softmax over DOMAINS (entertainment_movies, sports, other)
  - urgency_flag  : single logit (sigmoid)
  - sentiment     : single value in [-1, 1] (tanh)
The reported category is the domain.

Models trained with the older sub-category taxonomy (v2, `categories` in label_config.json)
still load: their extra category head is kept only so the weights match, and is ignored.

This file is self-contained (torch + transformers + safetensors only) because the
same file is uploaded to Google Colab for training — do not import project modules here.
Saved model folder layout (models/classifier/):
    config.json, tokenizer files   — encoder config + tokenizer (no internet needed to load)
    model.safetensors              — full weights (encoder + heads)
    label_config.json              — domain list, max_length, urgency threshold, version
"""

import json
from pathlib import Path
from typing import Dict, List

import torch
import torch.nn as nn
import torch.nn.functional as F
from safetensors.torch import load_file, save_file
from transformers import AutoConfig, AutoModel, AutoTokenizer

LABEL_CONFIG_FILE = "label_config.json"
WEIGHTS_FILE = "model.safetensors"


class MultiTaskNewsClassifier(nn.Module):
    def __init__(self, encoder: nn.Module, n_domains: int, n_legacy_categories: int = 0,
                 dropout: float = 0.1):
        super().__init__()
        self.encoder = encoder
        hidden = encoder.config.hidden_size
        self.dropout = nn.Dropout(dropout)
        self.domain_head = nn.Linear(hidden, n_domains)
        self.urgency_head = nn.Linear(hidden, 1)
        self.sentiment_head = nn.Linear(hidden, 1)
        # Only present when loading a v2 (sub-category) model; never used for predictions.
        if n_legacy_categories:
            self.category_head = nn.Linear(hidden, n_legacy_categories)

    def forward(self, input_ids, attention_mask) -> Dict[str, torch.Tensor]:
        hidden = self.encoder(input_ids=input_ids, attention_mask=attention_mask).last_hidden_state
        # Mean-pool over real tokens (more stable than CLS for short news snippets)
        mask = attention_mask.unsqueeze(-1).to(hidden.dtype)
        pooled = self.dropout((hidden * mask).sum(1) / mask.sum(1).clamp(min=1e-6))
        return {
            "domain": self.domain_head(pooled),
            "urgency": self.urgency_head(pooled).squeeze(-1),
            "sentiment": torch.tanh(self.sentiment_head(pooled)).squeeze(-1),
        }


def compute_loss(out: Dict[str, torch.Tensor], batch: Dict[str, torch.Tensor],
                 urgency_pos_weight: float = 1.0,
                 domain_weight: torch.Tensor = None) -> torch.Tensor:
    """Sum of the three task losses (used in training).
    domain_weight: optional per-class weights if the domains are imbalanced."""
    pos_weight = torch.tensor(urgency_pos_weight, device=out["urgency"].device)
    return (
        F.cross_entropy(out["domain"], batch["domain"], weight=domain_weight)
        + F.binary_cross_entropy_with_logits(out["urgency"], batch["urgency"].float(), pos_weight=pos_weight)
        + F.mse_loss(out["sentiment"], batch["sentiment"].float())
    )


def build_new(base_model: str, label_config: dict) -> MultiTaskNewsClassifier:
    """Create an untrained classifier on top of a pretrained Hugging Face encoder."""
    encoder = AutoModel.from_pretrained(base_model)
    return MultiTaskNewsClassifier(encoder, len(label_config["domains"]))


def save_model(model: MultiTaskNewsClassifier, tokenizer, label_config: dict, out_dir: str):
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    model.encoder.config.save_pretrained(out)
    tokenizer.save_pretrained(out)
    state = {k: v.detach().cpu().contiguous() for k, v in model.state_dict().items()}
    save_file(state, str(out / WEIGHTS_FILE))
    (out / LABEL_CONFIG_FILE).write_text(json.dumps(label_config, indent=2), encoding="utf-8")


class NewsClassifierPredictor:
    """Loads a saved model folder and classifies articles. Works offline, CPU or GPU."""

    def __init__(self, model_dir: str, device: str = None):
        model_dir = Path(model_dir)
        self.labels = json.loads((model_dir / LABEL_CONFIG_FILE).read_text(encoding="utf-8"))
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        self.tokenizer = AutoTokenizer.from_pretrained(model_dir)
        encoder = AutoModel.from_config(AutoConfig.from_pretrained(model_dir))
        self.model = MultiTaskNewsClassifier(
            encoder, len(self.labels["domains"]), len(self.labels.get("categories", []))
        )
        self.model.load_state_dict(load_file(str(model_dir / WEIGHTS_FILE)))
        self.model.to(self.device).eval()

    @staticmethod
    def format_text(title: str, body: str) -> str:
        return f"{(title or '').strip()}. {(body or '').strip()}".strip(". ")

    def _batches(self, texts: List[str], batch_size: int):
        for start in range(0, len(texts), batch_size):
            enc = self.tokenizer(
                texts[start:start + batch_size], truncation=True, padding=True,
                max_length=self.labels["max_length"], return_tensors="pt",
            ).to(self.device)
            yield self.model(enc["input_ids"], enc["attention_mask"])

    @torch.no_grad()
    def urgency_probabilities(self, texts: List[str], batch_size: int = 16) -> List[float]:
        """Raw P(urgent) per text — used to tune urgency_threshold on validation data."""
        return [p for out in self._batches(texts, batch_size) for p in torch.sigmoid(out["urgency"]).tolist()]

    @torch.no_grad()
    def predict(self, texts: List[str], batch_size: int = 16) -> List[dict]:
        threshold = self.labels.get("urgency_threshold", 0.5)
        results = []
        for out in self._batches(texts, batch_size):
            p_domain = out["domain"].softmax(-1)
            conf, dom_idx = p_domain.max(-1)
            p_urgent = torch.sigmoid(out["urgency"])
            for i in range(len(dom_idx)):
                domain = self.labels["domains"][dom_idx[i].item()]
                results.append({
                    "domain": domain,
                    "category": domain,
                    "sentiment": round(out["sentiment"][i].item(), 3),
                    "urgency_flag": bool(p_urgent[i].item() >= threshold),
                    "classification_confidence": round(conf[i].item(), 3),
                })
        return results
