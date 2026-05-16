"""
MAPNAI — agents/agent3_summarizer.py
Agent 3: Summarization Agent (Layer 2)

Receives the combined JSON dictionary from Agent 1 (Entities) and Agent 2 (Classification).
Generates persona-aware summaries based on the article's domain, urgency, and sentiment.
Uses a configured LLM prompt. Updates only `summary_short` and `summary_long` in DB.
Outputs the fully merged JSON payload downstream for Agent 4.
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


class SummarizationAgent:
    """
    Agent 3 pipeline agent.
    Generates persona-aware context summaries and pushes to DB securely.
    """

    def __init__(self):
        # Match Agent 2's initialization routing
        if not OpenAI or not settings.openai_api_key:
            logger.warning("[Agent 3] OpenAI not configured or missing (OPENAI_API_KEY). Summarization will fallback.")
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

    def _build_system_prompt(self, domain: str, sentiment: float, urgency_flag: bool) -> str:
        """Constructs a persona-aware system prompt mapping tone to article metrics."""
        
        # ── Persona Logic ──
        persona_instructions = "Write clearly and objectively."
        
        if domain == "finance":
            persona_instructions = "Adopt a precise, analytical tone native to finance professionals. Retain exact numerical details, metrics, and percentages."
        elif domain == "geopolitics":
            if urgency_flag:
                persona_instructions = "Adopt a crisp, high-alert, briefing-style tone. Emphasize immediate geopolitical stakes and breaking developments."
            else:
                persona_instructions = "Adopt a measured, diplomatic, analytical tone. Focus on policy alignment and strategic long-term outcomes."
        elif domain == "health":
            persona_instructions = "Adopt an accessible but scientifically accurate tone. Ensure clarity on public safety guidelines without hyperbole."
        elif domain == "technology":
            persona_instructions = "Adopt a forward-looking, tech-literate tone. Focus on innovation impacts, cybersecurity risks, or regulatory shifts."
        elif domain == "supply_chain":
            persona_instructions = "Adopt an operational and logistical tone. Focus on disruptions, capacity, trade flow, and cascading downstream effects."
            
        if urgency_flag and domain not in ["geopolitics"]:
            persona_instructions += " The report is flagged as URGENT: make the summary exceptionally direct concerning immediate risks or breaking disruptions."
            
        system_prompt = f"""You are the Summarization Agent (Agent 3) in the MAPNAI pipeline.
Your job is to read a news article (its Title, Body) alongside its extracted context (Entities, Domain, Sentiment) and write two distinct summaries.

DOMAIN CONTEXT: {domain}
SENTIMENT SCORE: {sentiment}
URGENCY: {urgency_flag}

PERSONA INSTRUCTIONS:
{persona_instructions}

Look closely at the entities provided in the input, and ensure the most salient ones are contextually preserved in your summaries.

Output a strictly formatted JSON object with exactly these fields:
{{
  "summary_short": "<A 2-3 sentence overview utilizing the requested persona>",
  "summary_long": "<A detailed paragraph-length summary (5-8 sentences) utilizing the requested persona>"
}}

RULES:
1. You MUST return valid JSON. Do not return markdown, do not include explanations. Only the JSON object.
2. Ensure you strictly adhere to the Persona Instructions above.
3. Do not invent facts outside the provided article Body.
"""
        return system_prompt

    def _call_llm_summarization(self, title: str, body: str, entities: list, domain: str, sentiment: float, urgency_flag: bool) -> dict:
        """Performs the OpenAI API call enforcing JSON returns."""
        if not self.client:
            return self._fallback_summarization()

        # Truncate body if it's exceptionally long to save tokens
        truncated_body = body[:5000]

        user_content = json.dumps({
            "title": title,
            "body": truncated_body,
            "entities": entities
        }, indent=2)

        try:
            response = self.client.chat.completions.create(
                model=self.model_name,
                messages=[
                    {"role": "system", "content": self._build_system_prompt(domain, sentiment, urgency_flag)},
                    {"role": "user", "content": user_content}
                ],
                response_format={ "type": "json_object" },
                temperature=0.3
            )
            
            raw_json = response.choices[0].message.content
            return json.loads(raw_json)
            
        except Exception as e:
            logger.error(f"[Agent 3] LLM API or JSON parse failed: {e}")
            return self._fallback_summarization()

    def _fallback_summarization(self) -> dict:
        """Returns safe default empty summaries if LLM routing fails."""
        return {
            "summary_short": "",
            "summary_long": ""
        }

    def process_article(self, combined_payload: dict) -> dict:
        """
        Main entry pipeline function:
        1. Takes Agent 1 + Agent 2 JSON payload
        2. Generates summaries via LLM
        3. Updates the processed_article in MongoDB (only summary fields)
        4. Merges and returns the payload to pass to Agent 4
        """
        article_id = combined_payload.get("article_id")
        title = combined_payload.get("title", "")
        body = combined_payload.get("body", "")
        entities = combined_payload.get("entities", [])
        domain = combined_payload.get("domain", "general")
        sentiment = combined_payload.get("sentiment", 0.0)
        urgency_flag = combined_payload.get("urgency_flag", False)
        
        logger.info(f"[Agent 3] Summarizing article: {article_id}")

        # 1. Run LLM Summarization
        summary_result = self._call_llm_summarization(title, body, entities, domain, sentiment, urgency_flag)
        
        # 2. Write natively defined fields (summary_short, summary_long) to MongoDB processed_articles
        # Note: the article_id is required to find the document.
        if article_id:
            db_success = self.mongo.update_article_summaries(article_id, summary_result)
            if not db_success:
                logger.warning(f"[Agent 3] Could not update MongoDB summaries for {article_id}. It may not exist in Layer 1.")
        else:
            logger.warning("[Agent 3] Received payload without article_id.")
            
        # 3. Merge results for downstream Agent 4 payload
        merged_payload = combined_payload.copy()
        merged_payload.update(summary_result)

        logger.info(f"[Agent 3] Summarization complete for {article_id}.")
        return merged_payload


# ── Standalone Testing ──────────────────────────────────────────

if __name__ == "__main__":
    # Test harness payload simulating downstream pass from Agent 2 (Pipeline)
    import uuid
    from datetime import datetime

    mock_combined_payload = {
        "article_id": str(uuid.uuid4()),
        "title": "Fed rate cut sparks unexpected crypto rally; supply chains brace for impact",
        "body": "The Federal Reserve surprised markets today by cutting interest rates by 50 basis points. In response, Bitcoin surged past critical resistance levels. Concurrently, major logistics firms express worry that increased consumer demand may overwhelm shipping pipelines currently struggling with East Coast port strikes.",
        "entities": [
            {"name": "Federal Reserve", "type": "ORG", "salience": 0.95},
            {"name": "Bitcoin", "type": "PRODUCT", "salience": 0.8},
            {"name": "East Coast", "type": "LOC", "salience": 0.6}
        ],
        "source": "Financial Times",
        "published_at": datetime.utcnow().isoformat(),
        "domain": "finance",
        "category": "Markets",
        "sentiment": 0.5,
        "urgency_flag": True,
        "classification_confidence": 0.89,
        "taxonomy_version": "1.0.0"
    }

    print(colored("--- Mock Upstream Payload (Agent 1 + Agent 2) ---", "cyan"))
    print(json.dumps(mock_combined_payload, indent=2))
    
    agent = SummarizationAgent()
    
    print(colored("\n--- Processing via Agent 3 (Summarization Agent) ---", "yellow"))
    final_payload = agent.process_article(mock_combined_payload)
    
    print(colored("\n--- Agent 3 Output (Merged for Agent 4) ---", "green"))
    print(json.dumps(final_payload, indent=2))
