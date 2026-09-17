from agents.ner_agent import NERAgent
import json
agent = NERAgent()

sample_article = {
    "article_id": "test-001",
    "title": "RBI cuts interest rates amid global slowdown",
    "body": "The Reserve Bank of India announced a 25 basis point cut in interest rates on Friday. Governor Shaktikanta Das stated that the decision was influenced by rising inflation concerns and slowing GDP growth. The move is expected to impact HDFC Bank and SBI significantly.",
    "domain": "finance",
    "source": "test",
    "published_at": "2026-05-16T10:00:00"
}

output = agent.process(sample_article)
print(output)
print(json.dumps(output, indent=2))