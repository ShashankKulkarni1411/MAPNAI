"""
MAPNAI — agents/agent4_risk_scorer.py
Agent 4: Risk Scoring Agent (Layer 2)

Receives the fully merged JSON dictionary from Agent 3 (Summarization),
which contains all fields from Agents 1, 2, and 3.
Applies a ReAct-style multi-step reasoning chain across four explicit risk
factors to produce a final 0–100 risk score, confidence percentage, and
a one-sentence action recommendation.
Updates only the risk fields in MongoDB via $set and passes the enriched
dictionary downstream to Agent 5.
"""

import json
from termcolor import colored
try:
    from openai import OpenAI
except ImportError:
    OpenAI = None

from config.settings import settings
from storage.mongo_store import MongoStore
from utils.logger import logger


# ── Agent 4 Implementation ──────────────────────────────────────

class RiskScoringAgent:
    """
    Agent 4 pipeline agent.
    Applies ReAct reasoning across four risk factors and merges
    risk fields into the pipeline record.
    """

    def __init__(self):
        # Mirror Agent 2 / Agent 3 initialization and Groq routing
        if not OpenAI or not settings.openai_api_key:
            logger.warning(
                "[Agent 4] OpenAI not configured or missing (OPENAI_API_KEY). "
                "Risk scoring will fallback."
            )
            self.client = None
            self.model_name = None
        else:
            api_key = settings.openai_api_key
            if api_key.startswith("gsk_"):
                self.client = OpenAI(
                    api_key=api_key,
                    base_url="https://api.groq.com/openai/v1"
                )
                self.model_name = "llama-3.3-70b-versatile"
            else:
                self.client = OpenAI(api_key=api_key)
                self.model_name = "gpt-4o-mini"

        self.mongo = MongoStore()

    # ── Prompt Construction ─────────────────────────────────────

    def _build_system_prompt(
        self,
        domain: str,
        urgency_flag: bool,
        sentiment: float,
        summary_short: str,
        entities: list,
    ) -> str:
        """
        Constructs the ReAct-style system prompt.
        Injects upstream Agent 1–3 context so the LLM reasons with full
        pipeline information before committing to a final score.
        """
        # Format top entities (by salience, descending)
        sorted_entities = sorted(entities, key=lambda e: e.get("salience", 0), reverse=True)
        top_entities_str = json.dumps(sorted_entities[:10], indent=2)

        system_prompt = f"""You are the Risk Scoring Agent (Agent 4) in the MAPNAI pipeline.
Your task is to rigorously evaluate the risk of the provided news article by reasoning
step-by-step through FOUR explicit risk factors before producing a final score.

=== UPSTREAM CONTEXT (from Agents 1, 2, 3) ===
DOMAIN        : {domain}
URGENCY FLAG  : {urgency_flag}
SENTIMENT     : {sentiment}   (scale: -1.0 very negative → +1.0 very positive)
SUMMARY       : {summary_short}
TOP ENTITIES  :
{top_entities_str}

=== REACT REASONING CHAIN (mandatory — do NOT skip any step) ===

You MUST explicitly reason through all four factors below before producing any score.
For each factor, write your Thought, then your numerical sub-score.

**Factor 1 — Event Severity (0–25)**
Thought: Assess the raw magnitude of the described event.
- Rate changes above 50 bps, military action, multi-node supply chain disruption → score higher.
- Minor announcements, routine earnings → score lower.
Provide your Event Severity sub-score.

**Factor 2 — Entity Salience (0–25)**
Thought: Assess the prominence and systemic reach of the key entities involved.
- Globally systemic entities (Federal Reserve, NATO, WHO, G7) → score higher.
- Regional or local entities → score lower.
Use the TOP ENTITIES list above to support your reasoning.
Provide your Entity Salience sub-score.

**Factor 3 — Temporal Urgency (0–25)**
Thought: Assess how immediately this event demands a response.
- Breaking events, declared emergencies, active conflicts → score higher.
- Scheduled reviews, anticipated announcements → score lower.
Use the URGENCY FLAG and SENTIMENT above to support your reasoning.
Provide your Temporal Urgency sub-score.

**Factor 4 — Domain Criticality (0–25)**
Thought: Assess the inherent risk weight of the article's domain.
- Geopolitics and health emergencies are weighted HIGH by default.
- Finance and supply chain are MEDIUM.
- Technology is MEDIUM-LOW unless cybersecurity.
- General is LOW.
Use the DOMAIN above to support your reasoning.
Provide your Domain Criticality sub-score.

=== FINAL OUTPUT ===

After completing all four reasoning steps, sum the four sub-scores to get the final
risk_score (0–100). Then output ONLY the following JSON object — no markdown, no
explanations outside the JSON, no additional keys:

{{
  "risk_reasoning": {{
    "event_severity": <integer 0–25>,
    "entity_salience": <integer 0–25>,
    "temporal_urgency": <integer 0–25>,
    "domain_criticality": <integer 0–25>
  }},
  "risk_score": <integer 0–100, must equal the sum of the four sub-scores>,
  "risk_confidence": <float 0.0–1.0, your confidence that this score is well-calibrated>,
  "action_recommendation": "<One concise sentence recommending the immediate action an analyst or system should take based on this risk level>"
}}

RULES:
1. You MUST reason through ALL four factors before writing the JSON.
2. risk_score MUST equal event_severity + entity_salience + temporal_urgency + domain_criticality.
3. Return ONLY valid JSON. No markdown fences, no extra keys.
4. action_recommendation must be a single sentence under 30 words.
"""
        return system_prompt

    # ── LLM Call ────────────────────────────────────────────────

    def _call_llm_risk(
        self,
        title: str,
        body: str,
        domain: str,
        urgency_flag: bool,
        sentiment: float,
        summary_short: str,
        entities: list,
    ) -> dict:
        """Calls the LLM with ReAct system prompt and returns parsed risk dict."""
        if not self.client:
            return self._fallback_risk()

        # Truncate body to save tokens — summary carries the key context
        truncated_body = body[:4000]

        user_content = json.dumps({
            "title": title,
            "body": truncated_body,
        }, indent=2)

        try:
            response = self.client.chat.completions.create(
                model=self.model_name,
                messages=[
                    {
                        "role": "system",
                        "content": self._build_system_prompt(
                            domain, urgency_flag, sentiment, summary_short, entities
                        )
                    },
                    {"role": "user", "content": user_content}
                ],
                response_format={"type": "json_object"},
                temperature=0.1
            )

            raw_json = response.choices[0].message.content
            return json.loads(raw_json)

        except Exception as e:
            logger.error(f"[Agent 4] LLM API or JSON parse failed: {e}")
            return self._fallback_risk()

    # ── Fallback ────────────────────────────────────────────────

    def _fallback_risk(self) -> dict:
        """Returns safe zero-state risk dict if LLM errors out — pipeline never halts."""
        return {
            "risk_score": 0,
            "risk_confidence": 0.0,
            "action_recommendation": "Unable to assess risk.",
            "risk_reasoning": {
                "event_severity": 0,
                "entity_salience": 0,
                "temporal_urgency": 0,
                "domain_criticality": 0,
            }
        }

    # ── Main Pipeline Entry ─────────────────────────────────────

    def process_article(self, combined_payload: dict) -> dict:
        """
        Main entry pipeline function:
        1. Receives the fully merged dict from Agents 1 + 2 + 3
        2. Builds ReAct prompt with upstream context
        3. Calls LLM for risk scoring
        4. Writes risk fields to MongoDB via $set
        5. Merges new keys into combined dict and returns to Agent 5
        """
        article_id   = combined_payload.get("article_id")
        title        = combined_payload.get("title", "")
        body         = combined_payload.get("body", "")
        entities     = combined_payload.get("entities", [])
        domain       = combined_payload.get("domain", "general")
        sentiment    = combined_payload.get("sentiment", 0.0)
        urgency_flag = combined_payload.get("urgency_flag", False)
        summary_short = combined_payload.get("summary_short", "")

        logger.info(f"[Agent 4] Risk scoring article: {article_id}")

        # 1. Run LLM risk scoring via ReAct reasoning chain
        risk_result = self._call_llm_risk(
            title, body, domain, urgency_flag, sentiment, summary_short, entities
        )

        # 2. Write only Agent 4 fields to MongoDB via $set
        if article_id:
            db_success = self.mongo.update_article_risk(article_id, risk_result)
            if not db_success:
                logger.warning(
                    f"[Agent 4] Could not update MongoDB risk for {article_id}. "
                    "It may not exist in Layer 1."
                )
        else:
            logger.warning("[Agent 4] Received payload without article_id.")

        # 3. Merge results for downstream Agent 5 payload
        merged_payload = combined_payload.copy()
        merged_payload.update(risk_result)

        logger.info(
            f"[Agent 4] Risk scoring complete for {article_id} → "
            f"Score: {risk_result.get('risk_score')} | "
            f"Confidence: {risk_result.get('risk_confidence')}"
        )
        return merged_payload


# ── Standalone Testing ──────────────────────────────────────────

if __name__ == "__main__":
    import uuid
    from datetime import datetime

    # Mock payload simulating the full Agent 1 + 2 + 3 merged output
    mock_combined_payload = {
        "article_id": str(uuid.uuid4()),
        "title": "Fed rate cut sparks unexpected crypto rally; supply chains brace for impact",
        "body": (
            "The Federal Reserve surprised markets today by cutting interest rates by 50 basis "
            "points. In response, Bitcoin surged past critical resistance levels. Concurrently, "
            "major logistics firms express worry that increased consumer demand may overwhelm "
            "shipping pipelines currently struggling with East Coast port strikes."
        ),
        "entities": [
            {"name": "Federal Reserve", "type": "ORG",     "salience": 0.95},
            {"name": "Bitcoin",         "type": "PRODUCT", "salience": 0.80},
            {"name": "East Coast",      "type": "LOC",     "salience": 0.60},
        ],
        "source": "Financial Times",
        "published_at": datetime.utcnow().isoformat(),
        # Agent 2 fields
        "domain": "finance",
        "category": "Markets",
        "sentiment": -0.3,
        "urgency_flag": True,
        "classification_confidence": 0.89,
        "taxonomy_version": "1.0.0",
        # Agent 3 fields
        "summary_short": (
            "The Federal Reserve cut rates by 50 bps, triggering a Bitcoin rally while East "
            "Coast port strikes threaten to overwhelm shipping pipelines."
        ),
        "summary_long": (
            "In a move that surprised financial markets, the Federal Reserve announced an "
            "aggressive 50 basis-point interest rate cut today, sending shockwaves across asset "
            "classes. Bitcoin responded immediately, breaching key resistance levels as risk "
            "appetite surged. However, the consumer demand spike expected to follow the rate cut "
            "is raising alarm among major logistics operators, who warn that already-strained "
            "East Coast shipping infrastructure — currently impacted by port strikes — may face "
            "severe capacity shortfalls in the coming weeks, creating a compounding macro risk."
        ),
    }

    print(colored("--- Mock Upstream Payload (Agent 1 + 2 + 3) ---", "cyan"))
    print(json.dumps(mock_combined_payload, indent=2, default=str))

    agent = RiskScoringAgent()

    print(colored("\n--- Processing via Agent 4 (Risk Scoring Agent) ---", "yellow"))
    final_payload = agent.process_article(mock_combined_payload)

    print(colored("\n--- Agent 4 Output (Merged for Agent 5) ---", "green"))
    print(json.dumps(final_payload, indent=2, default=str))
