import json
import logging
from agents.ner_agent import NERAgent

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

def run_pipeline(article: dict) -> dict:
    """
    Runs the agent pipeline on a single article dictionary.
    """
    # 1. Initialize Agents
    ner_agent = NERAgent()
    
    # 2. Process through NER Agent
    logging.info(f"Running NER Agent for article: {article.get('article_id')}")
    ner_output = ner_agent.process(article)
    
    # TODO: classifier_output = classifier_agent.process(ner_output)
    # TODO: summarizer_output = summarizer_agent.process(classifier_output)
    
    # Returning the final output (currently from NER agent)
    return ner_output

if __name__ == "__main__":
    # Sample article for testing the pipeline end-to-end
    sample_article = {
        "article_id": "test_article_123",
        "title": "RBI Announces New Monetary Policy Rates",
        "body": "The Reserve Bank of India today decided to keep the repo rate unchanged at 6.5%. The decision was made to ensure inflation aligns with the target. Several banks including State Bank of India will review their lending rates.",
        "domain": "finance"
    }
    
    print("Starting pipeline test...")
    result = run_pipeline(sample_article)
    print("\n--- Pipeline Output ---")
    print(json.dumps(result, indent=2))
