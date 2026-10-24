"""
MAPNAI — tests/test_ner_labels.py
F6: the CoNLL MISC label (nationalities, events, works of art) was stored as "Product". NER_MISC_LABEL=Misc stores it
as "Misc"; the default keeps "Product" until the data migration is approved (scripts/migrate_ner_misc_types.py).
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents import ner_agent
from agents.ner_utils import ENTITY_TYPES, deduplicate_and_merge_entities
from config.settings import Settings


class FakePipeline:
    def __init__(self, out):
        self.out = out

    def __call__(self, text):
        return self.out


def agent_with(label_map, out):
    agent = object.__new__(ner_agent.NERAgent)          # no model, no Mongo, no Neo4j
    agent.label_map, agent.ner_pipeline = label_map, FakePipeline(out)
    return agent


RAW = [{"entity_group": "PER", "word": "Ang Lee", "start": 0, "end": 7, "score": 0.99},
       {"entity_group": "MISC", "word": "Taiwanese", "start": 12, "end": 21, "score": 0.98},
       {"entity_group": "B-MISC", "word": "Oscar", "start": 30, "end": 35, "score": 0.97}]


def test_the_default_keeps_product():
    assert Settings(_env_file=None).ner_misc_label == "Product"
    assert ner_agent.label_map() == ner_agent.LABEL_MAP
    assert ner_agent.label_map()["MISC"] == "Product"


def test_misc_label_maps_only_misc():
    m = ner_agent.label_map("Misc")
    assert m["MISC"] == "Misc"
    assert {k: v for k, v in m.items() if k != "MISC"} == {k: v for k, v in ner_agent.LABEL_MAP.items() if k != "MISC"}


def test_extract_uses_the_configured_label():
    raw, _ = agent_with(ner_agent.label_map("Misc"), RAW)._extract("Ang Lee, the Taiwanese director, won an Oscar.")
    assert [(e["text"], e["label"]) for e in raw] == [("Ang Lee", "Person"), ("Taiwanese", "Misc"), ("Oscar", "Misc")]
    raw, _ = agent_with(ner_agent.label_map(), RAW)._extract("…")
    assert [e["label"] for e in raw] == ["Person", "Product", "Product"]


def test_migration_summary_counts_only_product():
    from scripts.migrate_ner_misc_types import summarize
    docs = [{"entities": [{"name": "Oscar", "type": "Product"}, {"name": "Ang Lee", "type": "Person"}],
             "ner_metadata": {"model_used": "BERT-finetuned"}},
            {"entities": [{"name": "iPhone", "type": "Product/Technology"}]},
            {"entities": [{"name": "Oscar", "type": "Product"}, {"name": "Taiwanese", "type": "Product"}]},
            {"entities": None}]
    s = summarize(docs)
    assert (s["documents_scanned"], s["documents_to_change"], s["entities_to_relabel"]) == (4, 2, 3)
    assert s["entities_by_model_used"] == {"BERT-finetuned": 1, "unknown": 2}
    assert s["top_names"][0] == ("Oscar", 2) and s["distinct_names"] == 2


def test_migration_apply_needs_confirm(capsys):
    from scripts.migrate_ner_misc_types import main
    assert main(["--apply"]) == 2                       # refuses before connecting to anything
    assert "needs --confirm" in capsys.readouterr().err


def test_misc_entities_survive_deduplication():
    assert "Misc" in ENTITY_TYPES
    ents = [{"text": "Taiwanese", "label": "Misc", "start": 12, "end": 21}]
    out = deduplicate_and_merge_entities(ents, 60, "entertainment_movies")
    assert [(e["name"], e["type"]) for e in out] == [("Taiwanese", "Misc")]


def test_research_inline_label_map_matches_production():
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "research",
                                    "experiments"))
    from e21_gate_aggrefact import LABEL_MAP
    assert LABEL_MAP == ner_agent.label_map()
