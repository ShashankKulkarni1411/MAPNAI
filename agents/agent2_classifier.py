"""
MAPNAI — agents/agent2_classifier.py
Agent 2: Event Classifier (Layer 2)

Receives the structured JSON output from Agent 1 (NER & Entity Extraction).
Classifies the article into domain, category, sentiment, and urgency_flag.
Uses a configured LLM prompt and Taxonomy. Updates the 'processed_articles' table.
Outputs the merged JSON payload downstream for Agent 3.
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

# ── Dynamic Taxonomy Configuration ──────────────────────────────

TAXONOMY_VERSION = "1.0.0"

TAXONOMY = {
    "finance": ["Markets", "Corporate", "Economy", "Banking", "Cryptocurrency"],
    "geopolitics": ["Elections", "Conflict", "Diplomacy", "Policy", "Trade"],
    "technology": ["AI", "Cybersecurity", "Startups", "Hardware", "Regulation"],
    "supply_chain": ["Logistics", "Manufacturing", "Shipping", "Shortages", "Trade Deals"],
    "health": ["Public Health", "Pharma", "Research", "Hospitals", "Policy"],
    "general": ["Other"]
}

# ── Agent 2 Implementation ──────────────────────────────────────

class EventClassifierAgent:
    """
    Agent 2 pipeline agent.
    Applies LLM classification and merges the result to the pipeline record.
    """

    def __init__(self):
        if not OpenAI or not settings.openai_api_key:
            logger.warning("[Agent 2] OpenAI not configured or missing (OPENAI_API_KEY). Classification will fallback.")
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

    def _build_system_prompt(self) -> str:
        """Constructs the system prompt dynamically from the TAXONOMY."""
        tax_str = json.dumps(TAXONOMY, indent=2)
        system_prompt = f"""You are the Event Classifier (Agent 2) in the MAPNAI pipeline.
Your job is to analyze a news article (its Title, Body) and its pre-extracted Entities, and classify it.

Here is the TAXONOMY of domains and categories:
{tax_str}

Output a strictly formatted JSON object with exactly these fields:
{{
  "domain": "<One of the top-level keys from the TAXONOMY>",
  "category": "<One of the categories in the chosen domain's list>",
  "sentiment": <A float between -1.0 (very negative) and 1.0 (very positive)>,
  "urgency_flag": <true or false. Set true ONLY if the event signals an immediate risk, crisis, or breaking major event>,
  "classification_confidence": <A float between 0.0 and 1.0 representing your confidence in this classification>
}}

RULES:
1. ONLY use domains and categories provided in the TAXONOMY. If unsure, use "general" and "Other".
2. You MUST return valid JSON. Do not return markdown, do not include explanations. Only the JSON object.
3. The sentiment must be a numerical float.
"""
        return system_prompt

    def _call_llm_classification(self, title: str, body: str, entities: list) -> dict:
        """Performs the OpenAI API call and parses the JSON."""
        if not self.client:
            return self._fallback_classification()

        # Truncate body if it's exceptionally long to save tokens
        truncated_body = body[:4000]

        user_content = json.dumps({
            "title": title,
            "body": truncated_body,
            "entities": entities
        }, indent=2)

        try:
            response = self.client.chat.completions.create(
                model=self.model_name,
                messages=[
                    {"role": "system", "content": self._build_system_prompt()},
                    {"role": "user", "content": user_content}
                ],
                response_format={ "type": "json_object" },
                temperature=0.1
            )
            
            raw_json = response.choices[0].message.content
            return json.loads(raw_json)
            
        except Exception as e:
            logger.error(f"[Agent 2] LLM API or JSON parse failed: {e}")
            return self._fallback_classification()

    def _fallback_classification(self) -> dict:
        """Returns safe default classification if LLM routing fails."""
        return {
            "domain": "general",
            "category": "Other",
            "sentiment": 0.0,
            "urgency_flag": False,
            "classification_confidence": 0.0
        }

    def process_article(self, agent1_output: dict) -> dict:
        """
        Main entry pipeline function:
        1. Takes Agent 1 JSON payload
        2. Classifies via LLM
        3. Updates the processed_article in MongoDB
        4. Merges and returns the payload to pass to Agent 3
        """
        article_id = agent1_output.get("article_id")
        title = agent1_output.get("title", "")
        body = agent1_output.get("body", "")
        entities = agent1_output.get("entities", [])
        
        logger.info(f"[Agent 2] Classifying article: {article_id}")

        # 1. Run LLM Classification
        classification_result = self._call_llm_classification(title, body, entities)
        
        # 2. Add Taxonomy version wrapper
        classification_result["taxonomy_version"] = TAXONOMY_VERSION

        # 3. Write purely the agent 2 fields to MongoDB processed_articles
        # Note: the article_id is required to find the document.
        if article_id:
            db_success = self.mongo.update_article_classification(article_id, classification_result)
            if not db_success:
                logger.warning(f"[Agent 2] Could not update MongoDB for {article_id}. It may not exist in Layer 1.")
        else:
            logger.warning("[Agent 2] Received payload without article_id.")
            
        # 4. Merge results for downstream Agent 3 payload
        merged_payload = agent1_output.copy()
        merged_payload.update(classification_result)

        logger.info(f"[Agent 2] Classification complete for {article_id} -> Domain: {classification_result.get('domain')} | Urgency: {classification_result.get('urgency_flag')}")
        return merged_payload


# ── Standalone Testing ──────────────────────────────────────────

if __name__ == "__main__":
    # Test harness payload simulating downstream pass from Agent 1 (Pipeline)
    import uuid
    from datetime import datetime

    mock_agent1_payload = {
        "article_id": str(uuid.uuid4()),
        "title": "Fed rate cut sparks unexpected crypto rally; supply chains brace for impact",
        "body": "The Federal Reserve surprised markets today by cutting interest rates by 50 basis points. In response, Bitcoin surged past critical resistance levels. Concurrently, major logistics firms express worry that increased consumer demand may overwhelm shipping pipelines currently struggling with East Coast port strikes.",
        "entities": [
            {"name": "Federal Reserve", "type": "ORG", "salience": 0.95},
            {"name": "Bitcoin", "type": "PRODUCT", "salience": 0.8},
            {"name": "East Coast", "type": "LOC", "salience": 0.6}
        ],
        "source": "Financial Times",
        "published_at": datetime.utcnow().isoformat()
    }

    # Ensure to print colored output for easy local debug
    print(colored("--- Mock Agent 1 Input Payload ---", "cyan"))
    print(json.dumps(mock_agent1_payload, indent=2))
    
    agent = EventClassifierAgent()
    
    print(colored("\n--- Processing via Agent 2 (Event Classifier) ---", "yellow"))
    final_payload = agent.process_article(mock_agent1_payload)
    
    print(colored("\n--- Agent 2 Output (Merged for Agent 3) ---", "green"))
    print(json.dumps(final_payload, indent=2))
