"""
MAPNAI — agents/ner_utils.py
Utilities for the NER & Entity Extraction Agent (Agent 1).
Handles salience scoring, entity deduplication, and spaCy fallback logic.
"""

import math
import logging
from typing import List, Dict, Any

# The 8 custom types required for downstream agents
ENTITY_TYPES = {
    "Person",
    "Organization",
    "Location",
    "Financial Instrument",
    "Policy/Regulation",
    "Event",
    "Economic Indicator",
    "Product/Technology"
}

# Mapping spaCy default NER labels to our custom types
SPACY_TO_CUSTOM_MAP = {
    "PERSON": "Person",
    "ORG": "Organization",
    "GPE": "Location",
    "LOC": "Location",
    "FAC": "Location",
    "PRODUCT": "Product/Technology",
    "EVENT": "Event",
    "LAW": "Policy/Regulation",
    "MONEY": "Financial Instrument",
}

def calculate_salience(mentions: List[Dict[str, Any]], total_length: int) -> float:
    """
    Calculate salience (0.0 to 1.0) based on mention frequency and position weight.
    Earlier mentions in the text receive higher weight.
    """
    if not mentions or total_length == 0:
        return 0.0

    # Frequency score: assumes ~10 mentions is highly salient
    frequency_score = min(len(mentions) / 10.0, 1.0)
    
    position_weights = []
    for m in mentions:
        start_pos = m.get('start', 0)
        # Position relative to text length (0.0 = start, 1.0 = end)
        relative_pos = min(start_pos / total_length, 1.0)
        # Logarithmic decay for position weight
        weight = 1.0 - math.sqrt(relative_pos)
        position_weights.append(weight)
        
    avg_position_weight = sum(position_weights) / len(position_weights)
    
    # 60% frequency, 40% position
    salience = (0.6 * frequency_score) + (0.4 * avg_position_weight)
    return round(min(max(salience, 0.0), 1.0), 3)

def deduplicate_and_merge_entities(entities: List[Dict[str, Any]], text_length: int, domain: str) -> List[Dict[str, Any]]:
    """
    Merges duplicate entities within the same article, sums mention counts,
    calculates salience, and stamps the domain.
    """
    merged = {}
    
    for ent in entities:
        name = ent.get("text", "").strip()
        # Clean trailing punctuation
        name = name.rstrip(".,;:")
        label = ent.get("label")
        
        if not name or len(name) < 2 or label not in ENTITY_TYPES:
            continue
            
        key = (name.lower(), label)
        if key not in merged:
            merged[key] = {
                "name": name,
                "type": label,
                "mentions": []
            }
        
        merged[key]["mentions"].append({
            "start": ent.get("start", 0),
            "end": ent.get("end", 0)
        })

    final_entities = []
    for key, data in merged.items():
        mentions = data["mentions"]
        salience = calculate_salience(mentions, text_length)
        
        final_entities.append({
            "name": data["name"],
            "type": data["type"],
            "domain": domain,
            "salience": salience,
            "mention_count": len(mentions)
        })
        
    # Sort descending by salience
    return sorted(final_entities, key=lambda x: x["salience"], reverse=True)

def extract_entities_fallback(text: str) -> List[Dict[str, Any]]:
    """
    Fallback extraction using spaCy en_core_web_trf.
    Returns raw entity dicts to be passed to deduplicate_and_merge_entities.
    """
    try:
        import spacy
        try:
            # Prefer transformer model for accuracy
            nlp = spacy.load("en_core_web_trf")
        except OSError:
            logging.warning("[NER Utils] spaCy 'en_core_web_trf' not found. Falling back to 'en_core_web_sm'.")
            nlp = spacy.load("en_core_web_sm")
            
        # Limit text length to prevent memory exhaustion
        doc = nlp(text[:100000])
        
        raw_entities = []
        for ent in doc.ents:
            mapped_type = SPACY_TO_CUSTOM_MAP.get(ent.label_)
            if mapped_type:
                raw_entities.append({
                    "text": ent.text,
                    "label": mapped_type,
                    "start": ent.start_char,
                    "end": ent.end_char
                })
        return raw_entities
    except ImportError:
        logging.error("[NER Utils] spaCy not installed. Fallback failed.")
        return []
