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
from typing import Optional

from storage.mongo_store import MongoStore
from utils.groq_client import init_groq_llm
from agents.pipeline_bridge import mongo_doc_to_agent1_payload
from utils.logger import logger


class SummarizationAgent:
    """
    Agent 3 pipeline agent.
    Generates persona-aware context summaries and pushes to DB securely.
    """

    def __init__(self, mongo_store: Optional[MongoStore] = None):
        self.client, self.model_name = init_groq_llm("[Agent 3]", "Summarization")
        self.mongo = mongo_store or MongoStore()

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

    def _call_llm_summarization(
        self,
        title: str,
        body: str,
        entities: list,
        domain: str,
        sentiment: float,
        urgency_flag: bool,
        similar_articles: Optional[list] = None,
    ) -> dict:
        """Performs the OpenAI API call enforcing JSON returns."""
        if not self.client:
            return self._fallback_summarization()

        truncated_body = body[:5000]

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

    def _resolve_article_fields(self, payload: dict) -> dict:
        """Load title/body/entities/classification from MongoDB when missing."""
        article_id = payload.get("article_id")
        title = payload.get("title", "")
        body = payload.get("body", "")

        if (not title or not body) and article_id:
            doc = self.mongo.get_article_by_id(article_id)
            if doc:
                base = mongo_doc_to_agent1_payload(doc)
                payload = {**base, **{k: v for k, v in payload.items() if v is not None}}

        if article_id and "sentiment" not in payload:
            doc = self.mongo.get_article_by_id(article_id)
            if doc and doc.get("sentiment_score") is not None:
                payload = payload.copy()
                payload["sentiment"] = float(doc["sentiment_score"])
            if doc and "domain" not in payload and doc.get("domain"):
                payload = payload.copy()
                payload.setdefault("domain", doc["domain"])
            if doc and "urgency_flag" not in payload:
                payload = payload.copy()
                payload.setdefault("urgency_flag", doc.get("urgency_flag", False))

        return payload

    def process_article(self, combined_payload: dict) -> dict:
        """
        Main entry pipeline function:
        1. Takes Agent 1 + Agent 2 JSON payload
        2. Generates summaries via LLM
        3. Updates the processed_article in MongoDB (only summary fields)
        4. Merges and returns the payload to pass to Agent 4
        """
        combined_payload = self._resolve_article_fields(combined_payload)
        article_id = combined_payload.get("article_id")
        title = combined_payload.get("title", "")
        body = combined_payload.get("body", "")
        entities = combined_payload.get("entities", [])
        domain = combined_payload.get("domain", "general")
        sentiment = float(
            combined_payload.get(
                "sentiment",
                combined_payload.get("sentiment_score", 0.0),
            )
        )
        urgency_flag = combined_payload.get("urgency_flag", False)
        similar_articles = combined_payload.get("similar_articles")

        if not article_id:
            logger.warning("[Agent 3] Received payload without article_id.")
            return combined_payload

        logger.info(f"[Agent 3] Summarizing article: {article_id}")

        summary_result = self._call_llm_summarization(
            title,
            body,
            entities,
            domain,
            sentiment,
            urgency_flag,
            similar_articles=similar_articles,
        )
        
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

    def close(self):
        self.mongo.close()


# ── Standalone Testing ──────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Agent 3 — summarize from MongoDB")
    parser.add_argument("--article-id", type=str, help="Summarize one article by ID")
    parser.add_argument("--limit", type=int, default=1, help="Max pending articles")
    args = parser.parse_args()

    mongo = MongoStore()
    agent = SummarizationAgent(mongo_store=mongo)

    if args.article_id:
        doc = mongo.get_article_by_id(args.article_id)
        if not doc:
            print(colored(f"No article found: {args.article_id}", "red"))
            raise SystemExit(1)
        pending = [doc]
    else:
        pending = mongo.get_articles_pending_summarization(limit=args.limit)
        if not pending:
            print(colored("No articles pending summarization. Run Agent 2 first.", "yellow"))
            raise SystemExit(0)

    for doc in pending:
        payload = mongo_doc_to_agent1_payload(doc)
        payload["domain"] = doc.get("domain", "general")
        payload["category"] = doc.get("category", "Other")
        payload["sentiment"] = float(doc.get("sentiment_score", 0.0))
        payload["urgency_flag"] = doc.get("urgency_flag", False)
        payload["classification_confidence"] = doc.get("classification_confidence", 0.0)
        payload["taxonomy_version"] = doc.get("taxonomy_version", "1.0.0")

        print(colored(f"\n--- Agent 3: {payload['article_id']} ---", "yellow"))
        result = agent.process_article(payload)
        print(colored("--- Output ---", "green"))
        print(json.dumps(result, indent=2))

    agent.close()
    mongo.close()
