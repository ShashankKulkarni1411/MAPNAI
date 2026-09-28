"""
MAPNAI — personalization/explain.py
Plain-language text (pure). Phase 1: profile sentences. Why-line templates come in Phase 4.
"""

from typing import Dict, List

from personalization.scoring import topic_shares


def profile_sentences(exposures: List[Dict], topics: Dict[str, float], style: Dict, cfg) -> List[str]:
    """
    One sentence per exposure ("You own Manchester City (high)."), then declared topics
    as shares, then the reading style. Exposures are already grouped per entity key.
    """
    sentences: List[str] = []
    for exp in exposures:
        phrase = cfg.role_phrases.get(exp["role"], exp["role"].replace("_", " "))
        sentences.append(f"You {phrase} {exp['name']} ({exp['weight_label']}).")

    shares = topic_shares(topics)
    ranked = sorted(((t, s) for t, s in shares.items() if s > 0), key=lambda ts: (-ts[1], ts[0]))
    if ranked:
        parts = [f"{t.replace('_', ' ')} ({s:.0%})" for t, s in ranked]
        sentences.append(f"You are interested in {', '.join(parts)}.")

    if style:
        sentences.append(
            f"You prefer {style.get('length', '?')}, {style.get('tone', '?')} summaries "
            f"with {style.get('jargon', '?')} jargon."
        )
    return sentences
