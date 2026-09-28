"""
MAPNAI — agents/classifier_model.py
MAPNAI's own multi-task news classifier (Agent 2's model).

One shared transformer encoder (DistilRoBERTa by default) with four heads:
  - domain        : softmax over DOMAINS
  - category      : softmax over CATEGORIES, restricted at inference to the predicted domain
  - urgency_flag  : single logit (sigmoid)
  - sentiment     : single value in [-1, 1] (tanh)

This file is self-contained (torch + transformers + safetensors only) because the
same file is uploaded to Google Colab for training — do not import project modules here.
Saved model folder layout (models/classifier/):
    config.json, tokenizer files   — encoder config + tokenizer (no internet needed to load)
    model.safetensors              — full weights (encoder + heads)
    label_config.json              — label lists, category->domain map, max_length, version
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
    def __init__(self, encoder: nn.Module, n_domains: int, n_categories: int, dropout: float = 0.1):
        super().__init__()
        self.encoder = encoder
        hidden = encoder.config.hidden_size
        self.dropout = nn.Dropout(dropout)
        self.domain_head = nn.Linear(hidden, n_domains)
        self.category_head = nn.Linear(hidden, n_categories)
        self.urgency_head = nn.Linear(hidden, 1)
        self.sentiment_head = nn.Linear(hidden, 1)

    def forward(self, input_ids, attention_mask) -> Dict[str, torch.Tensor]:
        hidden = self.encoder(input_ids=input_ids, attention_mask=attention_mask).last_hidden_state
        # Mean-pool over real tokens (more stable than CLS for short news snippets)
        mask = attention_mask.unsqueeze(-1).to(hidden.dtype)
        pooled = self.dropout((hidden * mask).sum(1) / mask.sum(1).clamp(min=1e-6))
        return {
            "domain": self.domain_head(pooled),
            "category": self.category_head(pooled),
            "urgency": self.urgency_head(pooled).squeeze(-1),
            "sentiment": torch.tanh(self.sentiment_head(pooled)).squeeze(-1),
        }


def compute_loss(out: Dict[str, torch.Tensor], batch: Dict[str, torch.Tensor],
                 urgency_pos_weight: float = 1.0,
                 category_weight: torch.Tensor = None) -> torch.Tensor:
    """Sum of the four task losses (used in training).
    category_weight: optional per-class weights so rare categories aren't drowned out."""
    pos_weight = torch.tensor(urgency_pos_weight, device=out["urgency"].device)
    return (
        F.cross_entropy(out["domain"], batch["domain"])
        + F.cross_entropy(out["category"], batch["category"], weight=category_weight)
        + F.binary_cross_entropy_with_logits(out["urgency"], batch["urgency"].float(), pos_weight=pos_weight)
        + F.mse_loss(out["sentiment"], batch["sentiment"].float())
    )


def build_new(base_model: str, label_config: dict) -> MultiTaskNewsClassifier:
    """Create an untrained classifier on top of a pretrained Hugging Face encoder."""
    encoder = AutoModel.from_pretrained(base_model)
    return MultiTaskNewsClassifier(encoder, len(label_config["domains"]), len(label_config["categories"]))


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
            encoder, len(self.labels["domains"]), len(self.labels["categories"])
        )
        self.model.load_state_dict(load_file(str(model_dir / WEIGHTS_FILE)))
        self.model.to(self.device).eval()

        domains, categories = self.labels["domains"], self.labels["categories"]
        cat_to_dom = self.labels["category_to_domain"]
        # For each domain, a boolean mask over categories that belong to it
        self._domain_cat_mask = torch.tensor(
            [[cat_to_dom[c] == d for c in categories] for d in domains], device=self.device
        )

    @staticmethod
    def format_text(title: str, body: str) -> str:
        return f"{(title or '').strip()}. {(body or '').strip()}".strip(". ")

    @torch.no_grad()
    def urgency_probabilities(self, texts: List[str], batch_size: int = 16) -> List[float]:
        """Raw P(urgent) per text — used to tune urgency_threshold on validation data."""
        probs = []
        for start in range(0, len(texts), batch_size):
            enc = self.tokenizer(
                texts[start:start + batch_size], truncation=True, padding=True,
                max_length=self.labels["max_length"], return_tensors="pt",
            ).to(self.device)
            probs += torch.sigmoid(self.model(enc["input_ids"], enc["attention_mask"])["urgency"]).tolist()
        return probs

    @torch.no_grad()
    def predict(self, texts: List[str], batch_size: int = 16) -> List[dict]:
        results = []
        for start in range(0, len(texts), batch_size):
            enc = self.tokenizer(
                texts[start:start + batch_size], truncation=True, padding=True,
                max_length=self.labels["max_length"], return_tensors="pt",
            ).to(self.device)
            out = self.model(enc["input_ids"], enc["attention_mask"])
            p_domain = out["domain"].softmax(-1)
            dom_idx = p_domain.argmax(-1)
            # Category must belong to the predicted domain
            cat_logits = out["category"].masked_fill(~self._domain_cat_mask[dom_idx], float("-inf"))
            p_cat = cat_logits.softmax(-1)
            cat_idx = p_cat.argmax(-1)
            p_urgent = torch.sigmoid(out["urgency"])

            for i in range(len(dom_idx)):
                d, c = dom_idx[i].item(), cat_idx[i].item()
                results.append({
                    "domain": self.labels["domains"][d],
                    "category": self.labels["categories"][c],
                    "sentiment": round(out["sentiment"][i].item(), 3),
                    "urgency_flag": bool(p_urgent[i].item() >= self.labels.get("urgency_threshold", 0.5)),
                    "classification_confidence": round(p_domain[i, d].item() * p_cat[i, c].item(), 3),
                })
        return results
