"""Offline checks for Agents 2-4 logic that doesn't need models, MongoDB or Groq."""

from agents.agent2_classifier import EventClassifierAgent
from agents.agent4_risk_scorer import normalize_risk, risk_level
from agents.extractive_summarizer import extractive_summarize, split_sentences


BODY = (
    "Virat Kohli scored a century as India beat Australia in the first Test in Perth. "
    "The match ended on the fourth day after Australia collapsed in their second innings. "
    "Jasprit Bumrah took eight wickets across both innings to lead the bowling attack. "
    "Fans packed the stadium for all four days of the contest. "
    "The second Test begins next week in Adelaide under lights. "
    "Australia's coach said the team would review its batting approach before then. "
    "Ticket sales for the Adelaide match have already crossed previous records. "
    "Weather forecasts suggest clear skies for the first three days of the game."
)


def test_extractive_summary_is_verbatim_and_ordered():
    entities = [{"name": "Virat Kohli", "salience": 0.9}, {"name": "India", "salience": 0.8}]
    result = extractive_summarize("Kohli century leads India to win over Australia", BODY, entities, "sports")

    sentences = split_sentences(BODY)
    short = split_sentences(result["summary_short"])
    long = split_sentences(result["summary_long"])
    assert len(short) == 3 and len(long) == 7
    assert all(s in sentences for s in long)
    assert [sentences.index(s) for s in long] == sorted(sentences.index(s) for s in long)
    assert short[0] == sentences[0]   # lead sentence with title + entity overlap wins


def test_extractive_summary_marks_urgent_and_handles_short_body():
    result = extractive_summarize("Match cancelled", "Tiny.", [], "sports", urgency_flag=True)
    assert result["summary_short"].startswith("[URGENT]")
    assert result["summary_long"] == "Tiny."


def test_risk_output_is_clamped_and_resummed():
    raw = {
        "risk_reasoning": {"event_severity": 30, "entity_salience": "12", "temporal_urgency": -4},
        "risk_score": 99,
        "risk_confidence": 1.7,
        "action_recommendation": " Monitor closely. ",
    }
    result = normalize_risk(raw)
    assert result["risk_reasoning"] == {
        "event_severity": 25, "entity_salience": 12, "temporal_urgency": 0, "domain_criticality": 0,
    }
    assert result["risk_score"] == 37
    assert result["risk_confidence"] == 1.0
    assert result["risk_level"] == "MONITOR"
    assert result["action_recommendation"] == "Monitor closely."


def test_risk_level_bands():
    assert [risk_level(s) for s in (0, 39, 40, 69, 70, 100)] == [
        "MONITOR", "MONITOR", "ALERT", "ALERT", "ESCALATE", "ESCALATE",
    ]


def test_classifier_scope_rules():
    scope = EventClassifierAgent._scope
    assert scope({"domain": "sports", "classification_confidence": 0.93})["in_scope"] is True
    assert scope({"domain": "sports", "classification_confidence": 0.41}) == {
        "in_scope": False, "out_of_scope_reason": "low_confidence",
    }
    assert scope({"domain": "other", "classification_confidence": 0.99}) == {
        "in_scope": False, "out_of_scope_reason": "off_topic",
    }
