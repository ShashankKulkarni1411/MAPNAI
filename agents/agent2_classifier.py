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
from typing import Optional

from storage.mongo_store import MongoStore
from utils.groq_client import init_groq_llm
from agents.pipeline_bridge import mongo_doc_to_agent1_payload
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

    def __init__(self, mongo_store: Optional[MongoStore] = None):
        self.client, self.model_name = init_groq_llm("[Agent 2]", "Classification")
        self.mongo = mongo_store or MongoStore()

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

    def _call_llm_classification(
        self,
        title: str,
        body: str,
        entities: list,
        similar_articles: Optional[list] = None,
    ) -> dict:
        """Performs the OpenAI API call and parses the JSON."""
        if not self.client:
            return self._fallback_classification()

        truncated_body = body[:4000]

        user_payload = {
            "title": title,
            "body": truncated_body,
            "entities": entities,
        }
        if similar_articles:
            user_payload["similar_articles"] = similar_articles

        user_content = json.dumps(user_payload, indent=2)

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
        2. Classifies via LLM
        3. Updates the processed_article in MongoDB
        4. Merges and returns the payload to pass to Agent 3
        """
        agent1_output = self._resolve_article_fields(agent1_output)
        article_id = agent1_output.get("article_id")
        title = agent1_output.get("title", "")
        body = agent1_output.get("body", "")
        entities = agent1_output.get("entities", [])
        similar_articles = agent1_output.get("similar_articles")

        if not article_id:
            logger.warning("[Agent 2] Received payload without article_id.")
            return agent1_output

        logger.info(f"[Agent 2] Classifying article: {article_id}")

        classification_result = self._call_llm_classification(
            title, body, entities, similar_articles=similar_articles
        )
        
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

    def close(self):
        self.mongo.close()


# ── Standalone Testing ──────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Agent 2 — classify from MongoDB")
    parser.add_argument("--article-id", type=str, help="Classify one article by ID")
    parser.add_argument("--limit", type=int, default=1, help="Max pending articles")
    args = parser.parse_args()

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
