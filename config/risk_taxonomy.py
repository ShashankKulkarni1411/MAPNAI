"""
MAPNAI — config/risk_taxonomy.py
Single source of truth for Agent 4's offline event-type label space.

Shared by scripts/risk/train_event_model.py and agents/risk_model.py so the trained
model's classes always map to the severities the scorer expects. Matches the v2 labelling
prompt in scripts/risk/label_*.ipynb (doping and match_fixing merged into "integrity").
"""

import re
from typing import Dict, List, Tuple

# event type → typical event_severity sub-score (0–25)
EVENT_SEVERITY: Dict[str, int] = {
    "routine": 2,
    "controversy": 8,
    "injury": 12,
    "legal": 16,
    "ban_suspension": 17,
    "cancellation": 18,
    "integrity": 21,
    "death_tragedy": 25,
}
EVENT_TYPES: List[str] = list(EVENT_SEVERITY)

# Labels from the v1 prompt that the v2 taxonomy merged
LEGACY_EVENT_TYPES = {"doping": "integrity", "match_fixing": "integrity"}

# Keyword fallback used when the trained model file is missing. Checked in this order: the first match wins.
# Measured against 4,062 v1 LLM labels: 76% accuracy, macro-F1 0.56 (the TF-IDF model: 82%, 0.64).
_KEYWORD_RULES: List[Tuple[str, str]] = [
    ("death_tragedy", r"\b(dies|died|dead|death|deaths|killed|kills|fatal(ly)?|passed away|murder(ed)?|shot dead"
                      r"|stampede|suicide|funeral|obituary|tragedy|terror(ist)? attack|bomb(ing)?|massacre)\b"),
    ("integrity", r"\b(doping|drugs? tests?|tested positive|failed (a )?(drugs? |dope )?test|banned substance|steroids?"
                  r"|anti-doping|wada|usada|meldonium|performance.enhancing|match.fixing|spot.fixing|illegal betting"
                  r"|betting scandal|bribe(s|d|ry)?|corruption)\b"),
    ("ban_suspension", r"\b(suspended|suspension|banned|bans|ban for|fined|sanction(s|ed)?|disqualified|expelled"
                       r"|censor(ed|ship)?|blacklist(ed)?)\b"),
    ("cancellation", r"\b(postponed|postpones?|called off|cancell?ed|cancels?|cancell?ation|rained off|washed out"
                     r"|abandoned|lockout|scrapped|shelved|delayed)\b"),
    ("legal", r"\b(lawsuit|sued|sues|suing|arrested|arrest|charged with|indicted|convicted|sentenced|trial|court"
              r"|pleads? (not )?guilty|jail(ed)?|prison|police|investigation|allegations?|accused|assault)\b"),
    ("injury", r"\b(injur(y|ies|ed)|hurt|surgery|torn|fractured?|sprain(ed)?|concussion|hamstring|knee|ankle"
               r"|ruled out|sidelined|hospitali[sz]ed|illness|cancer|diagnosed|rehab)\b"),
    ("controversy", r"\b(controvers(y|ial)|backlash|slams?|blasts?|criticis(m|ed|es)|criticiz(ed|es)|outrage|feud"
                    r"|racist|racism|sexist|homophobic|offensive|apologi[sz]es?|apology|boycott|row|furious|angry"
                    r"|scandal|accuses|fires back)\b"),
]
KEYWORD_RULES = [(t, re.compile(p, re.I)) for t, p in _KEYWORD_RULES]

# Unambiguous doping / fixing terms. Training relabels LLM labels of controversy / legal / ban_suspension that
# match this to integrity (the labelling LLM often missed doping cases). Same as the DistilRoBERTa notebook.
INTEGRITY_FIX_RX = re.compile(
    r"\b(?:doping|tested positive|failed (?:a )?(?:drugs? |dope )?test|drugs? tests?|banned substance"
    r"|steroids?|anti-doping|wada|usada|performance.enhancing|match.fixing|spot.fixing|illegal betting)\b", re.I)
INTEGRITY_FIX_FROM = ("controversy", "legal", "ban_suspension")


def keyword_event(text: str) -> Tuple[str, str]:
    """(event_type, matched words) from the keyword rules; ("routine", "") when nothing matches."""
    for event_type, rx in KEYWORD_RULES:
        m = rx.search(text)
        if m:
            return event_type, m.group(0)
    return "routine", ""


def event_text(title: str, body: str, max_chars: int = 1500) -> str:
    """The text the event model is trained and run on."""
    return f"{(title or '').strip()}. {(body or '').strip()[:max_chars]}".strip()
