"""
MAPNAI — agents/agent2_classifier.py
Agent 2: Event Classifier (Layer 2)

Receives the structured JSON output from Agent 1 (NER & Entity Extraction).
Classifies the article as entertainment_movies, sports or other (category = domain),
plus sentiment and urgency_flag, using
MAPNAI's own fine-tuned model (agents/classifier_model.py, weights in models/classifier/).
Runs fully offline — no LLM API. Label space: config/classifier_taxonomy.py.
Updates the 'processed_articles' table and outputs the merged payload for Agent 3.

Train / re-train the model with scripts/classifier/train_colab.ipynb.
If models/classifier/ is missing, the weights are downloaded once from Hugging Face.
"""

import json
import os
from pathlib import Path
from typing import Optional

from dotenv import dotenv_values
from termcolor import colored

from config.classifier_taxonomy import TAXONOMY_VERSION
from storage.mongo_store import MongoStore
from agents.pipeline_bridge import mongo_doc_to_agent1_payload
from utils.logger import logger

PROJECT_ROOT = Path(__file__).resolve().parent.parent
# Articles labelled "other", or classified below this confidence, are out of scope
# and are not sent to Agents 3-4.
IN_SCOPE_MIN_CONFIDENCE = 0.5
MODEL_DIR = PROJECT_ROOT / "models" / "classifier"
DEFAULT_MODEL_REPO = "satvik4577/mapnai-classifier"

# Loaded once per process and shared by every agent instance
_PREDICTOR = None


def _model_repo() -> str:
    """Hugging Face repo to download from: env var > .env > default. Empty string disables."""
    if "MAPNAI_CLASSIFIER_REPO" in os.environ:
        return os.environ["MAPNAI_CLASSIFIER_REPO"].strip()
    env_file = dotenv_values(PROJECT_ROOT / ".env")
    if "MAPNAI_CLASSIFIER_REPO" in env_file:
        return (env_file["MAPNAI_CLASSIFIER_REPO"] or "").strip()
    return DEFAULT_MODEL_REPO


def _download_model() -> bool:
    """Fetch the trained weights from Hugging Face into MODEL_DIR. Returns True on success."""
    repo = _model_repo()
    if not repo:
        return False
    try:
        from huggingface_hub import snapshot_download
        logger.info(f"[Agent 2] Classifier not found locally — downloading {repo} (~300 MB, one time)...")
        snapshot_download(repo_id=repo, local_dir=str(MODEL_DIR))
        return (MODEL_DIR / "label_config.json").exists()
    except Exception as e:
        logger.error(f"[Agent 2] Could not download classifier from {repo}: {e}")
        return False


def _get_predictor():
    global _PREDICTOR
    if _PREDICTOR is None:
        if not (MODEL_DIR / "label_config.json").exists() and not _download_model():
            logger.warning(
                f"[Agent 2] No trained classifier at {MODEL_DIR}. Download it with "
                f"`hf download {DEFAULT_MODEL_REPO} --local-dir models/classifier` or train it with "
                "scripts/classifier/train_colab.ipynb. Classification will fallback."
            )
            return None
        from agents.classifier_model import NewsClassifierPredictor
        _PREDICTOR = NewsClassifierPredictor(str(MODEL_DIR))
        logger.info(
            f"[Agent 2] Loaded MAPNAI classifier (taxonomy {_PREDICTOR.labels['taxonomy_version']}) "
            f"on {_PREDICTOR.device}."
        )
    return _PREDICTOR


class EventClassifierAgent:
    """
    Agent 2 pipeline agent.
    Applies the local classifier and merges the result to the pipeline record.
    """

    def __init__(self, mongo_store: Optional[MongoStore] = None):
        self.predictor = _get_predictor()
        self.mongo = mongo_store or MongoStore()

    def classify(self, title: str, body: str) -> dict:
        """Classify one article. Returns the Agent 2 fields (never raises)."""
        if not self.predictor:
            return self._fallback_classification("classifier_unavailable")
        try:
            text = self.predictor.format_text(title, body)
            result = self.predictor.predict([text])[0]
            result["taxonomy_version"] = self.predictor.labels["taxonomy_version"]
            return {**result, **self._scope(result)}
        except Exception as e:
            logger.error(f"[Agent 2] Classifier inference failed: {e}")
            return self._fallback_classification("classifier_error")

    @staticmethod
    def _scope(result: dict) -> dict:
        """Decide whether Agents 3-4 should process this article."""
        if result["domain"] == "other":
            return {"in_scope": False, "out_of_scope_reason": "off_topic"}
        if result["classification_confidence"] < IN_SCOPE_MIN_CONFIDENCE:
            return {"in_scope": False, "out_of_scope_reason": "low_confidence"}
        return {"in_scope": True, "out_of_scope_reason": None}

    def _fallback_classification(self, reason: str) -> dict:
        """Safe default when the model can't run. Never written to MongoDB, so the
        article stays in the classification queue until the model is available."""
        return {
            "domain": "other",
            "category": "other",
            "sentiment": 0.0,
            "urgency_flag": False,
            "classification_confidence": 0.0,
            "taxonomy_version": TAXONOMY_VERSION,
            "in_scope": False,
            "out_of_scope_reason": reason,
            "_fallback": True,
        }

    def _resolve_article_fields(self, payload: dict) -> dict:
        """Ensure title, body, and entities are loaded from MongoDB when missing."""
        article_id = payload.get("article_id")
        title = payload.get("title", "")
        body = payload.get("body", "")
        entities = payload.get("entities", [])

        if (not title or not body) and article_id:
            doc = self.mongo.get_article_by_id(article_id)
            if doc:
                merged = mongo_doc_to_agent1_payload(doc, ner_result=payload)
                payload = {
                    **merged,
                    **{k: v for k, v in payload.items() if v is not None and v != ""},
                }
                title = payload.get("title", "")
                body = payload.get("body", "")
                entities = payload.get("entities", entities)

        return {
            **payload,
            "title": title,
            "body": body,
            "entities": entities,
        }

    def process_article(self, agent1_output: dict) -> dict:
        """
        Main entry pipeline function:
        1. Takes Agent 1 JSON payload
        2. Classifies via the local model
        3. Updates the processed_article in MongoDB
        4. Merges and returns the payload to pass to Agent 3
        """
        agent1_output = self._resolve_article_fields(agent1_output)
        article_id = agent1_output.get("article_id")

        if not article_id:
            logger.warning("[Agent 2] Received payload without article_id.")
            return agent1_output

        logger.info(f"[Agent 2] Classifying article: {article_id}")
        classification_result = self.classify(agent1_output.get("title", ""), agent1_output.get("body", ""))
        is_fallback = classification_result.pop("_fallback", False)

        # Write purely the agent 2 fields to MongoDB processed_articles
        if is_fallback:
            logger.warning(f"[Agent 2] Classifier unavailable — {article_id} left pending in MongoDB.")
        elif not self.mongo.update_article_classification(article_id, classification_result):
            logger.warning(f"[Agent 2] Could not update MongoDB for {article_id}. It may not exist in Layer 1.")

        # Merge results for downstream Agent 3 payload
        merged_payload = agent1_output.copy()
        merged_payload.update(classification_result)

        logger.info(
            f"[Agent 2] Classification complete for {article_id} -> "
            f"{classification_result['domain']} | "
            f"Urgency: {classification_result['urgency_flag']} | "
            f"Confidence: {classification_result['classification_confidence']} | "
            f"In scope: {classification_result['in_scope']}"
        )
        return merged_payload

    def close(self):
        self.mongo.close()


# ── Standalone Testing ──────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Agent 2 — classify articles")
    parser.add_argument("--text", type=str, help="Classify a piece of text directly (no MongoDB)")
    parser.add_argument("--article-id", type=str, help="Classify one article by ID")
    parser.add_argument("--limit", type=int, default=1, help="Max pending articles")
    args = parser.parse_args()

    if args.text:
        predictor = _get_predictor()
        if not predictor:
            raise SystemExit(1)
        print(json.dumps(predictor.predict([args.text])[0], indent=2))
        raise SystemExit(0)

    mongo = MongoStore()
    agent = EventClassifierAgent(mongo_store=mongo)

    if args.article_id:
        doc = mongo.get_article_by_id(args.article_id)
        if not doc:
            print(colored(f"No article found: {args.article_id}", "red"))
            raise SystemExit(1)
        pending = [doc]
    else:
        pending = mongo.get_articles_pending_classification(limit=args.limit)
        if not pending:
            print(colored("No articles pending classification. Run pipeline.py first.", "yellow"))
            raise SystemExit(0)

    for doc in pending:
        payload = mongo_doc_to_agent1_payload(doc)
        print(colored(f"\n--- Agent 2: {payload['article_id']} ---", "yellow"))
        result = agent.process_article(payload)
        print(colored("--- Output ---", "green"))
        print(json.dumps(result, indent=2))

    agent.close()
    mongo.close()
