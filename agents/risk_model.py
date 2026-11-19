"""
MAPNAI — agents/risk_model.py
Agent 4's offline risk scorer: no LLM calls. See AGENT4_RISK_ARCHITECTURE.md.

event_severity comes from an event-type classifier with three tiers, each used only when the one
above it cannot load or run:
    1. DistilRoBERTa  — models/risk_event/  (scripts/risk/train_event_distilroberta.ipynb)
    2. TF-IDF + LR    — models/risk/event_model.joblib  (python -m scripts.risk.train_event_model)
    3. keyword rules  — config/risk_taxonomy.py, always available
entity_salience, temporal_urgency and domain_criticality are formulas over Agent 1–3 outputs.
"""

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from config.risk_taxonomy import EVENT_SEVERITY, EVENT_TYPES, event_text, keyword_event
from utils.logger import logger

HIGH_SEVERITY = 16                 # legal and above
GUARD_MIN_PROB = 0.20              # keyword rule may raise severity when the model gives its type this much
DOMAIN_BASE = {"sports": 12, "entertainment_movies": 8}
DOMAIN_BASE_OTHER = 5
URGENT_WORDS = re.compile(r"\b(breaking|today|tonight|ruled out|imminent|just in|live updates?)\b", re.I)


def _clamp(x: float) -> int:
    return max(0, min(25, int(round(x))))


# ── Event-type tiers ─────────────────────────────────────────────

class DistilRobertaTier:
    """Fine-tuned DistilRoBERTa with temperature-scaled softmax."""

    def __init__(self, model_dir: str):
        import torch
        from transformers import AutoModelForSequenceClassification, AutoTokenizer

        model_dir = Path(model_dir)
        self.config = json.loads((model_dir / "label_config.json").read_text(encoding="utf-8"))
        if self.config["event_types"] != EVENT_TYPES:
            raise ValueError(f"{model_dir} was trained on a different taxonomy: {self.config['event_types']}")
        self._torch = torch
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.tokenizer = AutoTokenizer.from_pretrained(model_dir)
        self.model = AutoModelForSequenceClassification.from_pretrained(model_dir).to(self.device).eval()
        self.temperature = float(self.config.get("temperature", 1.0))
        self.name = f"distilroberta:event-v{self.config.get('label_prompt_version', '?')}"

    def predict(self, text: str) -> Dict[str, float]:
        enc = self.tokenizer(text, truncation=True, max_length=self.config.get("max_len", 256),
                             return_tensors="pt").to(self.device)
        with self._torch.no_grad():
            probs = (self.model(**enc).logits[0] / self.temperature).softmax(-1).tolist()
        return dict(zip(EVENT_TYPES, probs))


class TfidfTier:
    """TF-IDF + logistic regression pipeline saved by scripts/risk/train_event_model.py."""

    def __init__(self, path: str):
        import joblib

        bundle = joblib.load(path)
        self.pipeline = bundle["pipeline"]
        unknown = set(self.pipeline.classes_) - set(EVENT_TYPES)
        if unknown:
            raise ValueError(f"{path} has classes outside the taxonomy: {sorted(unknown)}")
        self.name = "tfidf:event"

    def predict(self, text: str) -> Dict[str, float]:
        probs = dict.fromkeys(EVENT_TYPES, 0.0)
        probs.update(zip(self.pipeline.classes_, self.pipeline.predict_proba([text])[0].tolist()))
        return probs


class KeywordTier:
    """Last resort: the first matching keyword rule gets all the probability."""

    name = "rules:v1"

    def predict(self, text: str) -> Dict[str, float]:
        event_type, _ = keyword_event(text)
        return {t: float(t == event_type) for t in EVENT_TYPES}


# ── Scorer ───────────────────────────────────────────────────────

class OfflineRiskScorer:
    """Scores a merged Agents 1–3 payload into Agent 4's output contract."""

    # risk_confidence = top-class probability × this, per tier
    CONFIDENCE_SCALE = {"distilroberta": 1.0, "tfidf": 0.9}

    def __init__(self, event_model_dir: str, tfidf_model_path: str):
        self.tiers = []
        for label, factory, path in (("DistilRoBERTa", DistilRobertaTier, event_model_dir),
                                     ("TF-IDF", TfidfTier, tfidf_model_path)):
            if not Path(path).exists():
                logger.warning(f"[Agent 4] {label} event model not found at {path}; skipping that tier.")
                continue
            try:
                self.tiers.append(factory(path))
            except Exception as e:
                logger.warning(f"[Agent 4] {label} event model at {path} failed to load ({e}); skipping that tier.")
        self.tiers.append(KeywordTier())
        logger.info(f"[Agent 4] Offline risk scorer tiers: {' -> '.join(t.name for t in self.tiers)}")

    @property
    def primary(self) -> str:
        return self.tiers[0].name

    # ── event type ──

    def classify_event(self, text: str) -> Tuple[Dict[str, float], str]:
        """(probabilities per event type, tier name). A tier that raises hands the article to the next one."""
        for tier in self.tiers:
            try:
                return tier.predict(text), tier.name
            except Exception as e:
                logger.error(f"[Agent 4] {tier.name} failed on an article ({e}); trying the next tier.")
        raise RuntimeError("unreachable: the keyword tier never fails")

    @staticmethod
    def pick_event(probs: Dict[str, float], text: str) -> Tuple[str, str]:
        """(event_type, keyword evidence). A keyword match for a more severe type wins when the model gives
        that type at least GUARD_MIN_PROB — trades a few false alarms for fewer missed serious events."""
        top = max(probs, key=probs.get)
        kw_type, kw_match = keyword_event(text)
        if EVENT_SEVERITY[kw_type] > EVENT_SEVERITY[top] and probs.get(kw_type, 0.0) >= GUARD_MIN_PROB:
            return kw_type, kw_match
        return top, kw_match if kw_type == top else ""

    # ── factors ──

    @staticmethod
    def entity_salience(entities: List[dict]) -> int:
        if not entities:
            return 5
        top = max(entities, key=lambda e: float(e.get("salience") or 0))
        salience = min(1.0, max(0.0, float(top.get("salience") or 0)))
        mentions = min(1.0, float(top.get("mention_count") or 1) / 5)
        return _clamp(25 * (0.6 * salience + 0.4 * mentions))

    @staticmethod
    def temporal_urgency(urgency_flag: bool, sentiment: float, published_at, text: str,
                         now: Optional[datetime] = None) -> int:
        score = 3 + (10 if urgency_flag else 0) + round(8 * max(0.0, -float(sentiment or 0)))
        age_h = _age_hours(published_at, now or datetime.now(timezone.utc))
        if age_h is not None:
            score += 4 if age_h <= 24 else 2 if age_h <= 72 else 0
        if URGENT_WORDS.search(text):
            score += 3
        return _clamp(score)

    @staticmethod
    def domain_criticality(domain: str, p_routine: float) -> int:
        return _clamp(DOMAIN_BASE.get(domain, DOMAIN_BASE_OTHER) + 8 * (1 - p_routine))

    # ── main entry ──

    def score(self, payload: dict, now: Optional[datetime] = None) -> dict:
        from agents.agent4_risk_scorer import risk_level  # avoids a circular import at module load

        text = event_text(payload.get("title", ""), payload.get("body", ""))
        probs, tier = self.classify_event(text)
        event_type, evidence = self.pick_event(probs, text)
        entities = payload.get("entities") or []

        reasoning = {
            "event_severity": EVENT_SEVERITY[event_type],
            "entity_salience": self.entity_salience(entities),
            "temporal_urgency": self.temporal_urgency(payload.get("urgency_flag", False),
                                                      payload.get("sentiment", 0.0),
                                                      payload.get("published_at"), text, now),
            "domain_criticality": self.domain_criticality(str(payload.get("domain", "")),
                                                          probs.get("routine", 0.0)),
        }
        score = sum(reasoning.values())
        level = risk_level(score)

        family = tier.split(":")[0]
        if family in self.CONFIDENCE_SCALE:
            confidence = probs[event_type] * self.CONFIDENCE_SCALE[family]
        else:
            confidence = 0.5 if evidence else 0.4

        top_entity = max(entities, key=lambda e: float(e.get("salience") or 0)).get("name") if entities else None
        return {
            "risk_reasoning": reasoning,
            "risk_score": score,
            "risk_confidence": round(min(1.0, max(0.0, confidence)), 3),
            "risk_level": level,
            "action_recommendation": recommendation(level, event_type, evidence, top_entity),
            "risk_model": tier,
            "risk_event_type": event_type,
        }


def _age_hours(published_at, now: datetime) -> Optional[float]:
    if not published_at:
        return None
    try:
        ts = published_at if isinstance(published_at, datetime) else \
            datetime.fromisoformat(str(published_at).replace("Z", "+00:00"))
    except ValueError:
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return max(0.0, (now - ts).total_seconds() / 3600)


# ── Action recommendation templates ──────────────────────────────

_EVENT_PHRASE = {
    "routine": "routine coverage",
    "controversy": "a developing controversy",
    "injury": "an injury or health issue",
    "legal": "legal action",
    "ban_suspension": "a ban or sanction",
    "cancellation": "a cancellation or postponement",
    "integrity": "a possible integrity case (doping, fixing or corruption)",
    "death_tragedy": "a death or tragedy",
}
_LEVEL_ACTION = {
    "ESCALATE": "Escalate now: {what}{about}{ev}; verify with official sources and brief stakeholders.",
    "ALERT": "Track closely: {what}{about}{ev}; review for impact within 24 hours.",
    "MONITOR": "Monitor: {what}{about}{ev}; no immediate action needed.",
}


def recommendation(level: str, event_type: str, evidence: str = "", entity: Optional[str] = None) -> str:
    return _LEVEL_ACTION[level].format(
        what=_EVENT_PHRASE[event_type],
        about=f" involving {entity}" if entity else "",
        ev=f' ("{evidence}")' if evidence else "",
    )
