"""
MAPNAI — personalization/factcheck.py
Fact preservation for rendered rewrites (pure). PERSONALIZATION_PLAN.md §5 "Render":

  facts of the source   numbers (\\d[\\d,.]*%?), ISO dates, month names in a date context, and the article's
                        entity names that occur verbatim in the source
  the rewrite passes    iff it keeps every fact (numbers compared normalized: "1,200" = "1200", "5 per cent" = "5%";
                        months by name: "26 Sept" = "September 26") and brings in no number the source doesn't have
                        (a number written as a word in the source, "two", may come back as a digit)

Anything missing or added → the caller falls back to the source text.
"""

import re
from typing import Dict, Iterable, List, Set, Tuple

_NUM = re.compile(r"\d[\d,.]*%?")
_ISO = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
_PERCENT = re.compile(r"(\d)\s*(?:per\s?cent|percent)\b", re.I)
_MONTHS = {
    "january": "january", "jan": "january", "february": "february", "feb": "february", "march": "march",
    "mar": "march", "april": "april", "apr": "april", "may": "may", "june": "june", "jun": "june",
    "july": "july", "jul": "july", "august": "august", "aug": "august", "september": "september",
    "sept": "september", "sep": "september", "october": "october", "oct": "october", "november": "november",
    "nov": "november", "december": "december", "dec": "december",
}
_MONTH_WORD = r"(?:" + "|".join(sorted(_MONTHS, key=len, reverse=True)) + r")\.?"
# a capitalized month; "May"/"March" also are ordinary words, so those count only next to a number
_MONTH_ANY = re.compile(rf"\b({_MONTH_WORD})\b", re.I)
_MONTH_SOURCE = re.compile(rf"\b([A-Z][a-z]+)\.?(?=\W|$)")
_MONTH_BY_NUMBER = re.compile(rf"(?:\d{{1,2}}(?:st|nd|rd|th)?\s+({_MONTH_WORD}))|(?:\b({_MONTH_WORD})\s+\d)", re.I)
_AMBIGUOUS = {"may", "march"}
_WORDS = {w: str(i) for i, w in enumerate(
    "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen "
    "seventeen eighteen nineteen twenty".split())}
_WORDS.update({"thirty": "30", "forty": "40", "fifty": "50", "sixty": "60", "seventy": "70", "eighty": "80",
               "ninety": "90", "hundred": "100", "thousand": "1000"})


def _norm_number(tok: str) -> str:
    """"1,200." → "1200"; "2.50" stays; "5%" keeps its sign."""
    tok = tok.rstrip(".,")
    return tok.replace(",", "")


def numbers(text: str) -> Set[str]:
    """Normalized numbers outside ISO dates (each of those is one fact, see iso_kept)."""
    text = _PERCENT.sub(r"\1%", _ISO.sub(" ", text or ""))
    return {n for tok in _NUM.findall(text) if (n := _norm_number(tok))}


def number_words(text: str) -> Set[str]:
    """Numbers the text spells out ("two" → "2")."""
    return {_WORDS[w] for w in re.findall(r"[a-z]+", (text or "").lower()) if w in _WORDS}


def months(text: str, strict: bool) -> Set[str]:
    """Month names → canonical. strict (source side): capitalized, and May/March only beside a number."""
    text = text or ""
    if not strict:
        return {_MONTHS[m.lower().rstrip(".")] for m in _MONTH_ANY.findall(text)}
    found = {_MONTHS[w.lower()] for w in _MONTH_SOURCE.findall(text)
             if w.lower() in _MONTHS and w.lower() not in _AMBIGUOUS}
    for a, b in _MONTH_BY_NUMBER.findall(text):
        found.add(_MONTHS[(a or b).lower().rstrip(".")])
    return found


_MONTH_NAMES = ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
                "november", "december"]


def iso_parts(date: str) -> Tuple[str, str, str]:
    """"2026-09-06" → ("2026", "september", "6")."""
    y, m, d = date.split("-")
    return y, _MONTH_NAMES[int(m) - 1], str(int(d))


def iso_kept(date: str, rewrite: str, got_numbers: Set[str], got_months: Set[str]) -> bool:
    """An ISO date survives verbatim or spelled out ("6 September 2026", "September 6, 2026")."""
    if date in (rewrite or ""):
        return True
    y, month, d = iso_parts(date)
    return y in got_numbers and d in got_numbers and month in got_months


def entities_in(text: str, entity_names: Iterable[str]) -> List[str]:
    """The entity names that occur in the text as whole words (case-insensitive), in the given order."""
    out = []
    for name in dict.fromkeys(n.strip() for n in entity_names or [] if n and n.strip()):
        if re.search(rf"(?<!\w){re.escape(name)}(?!\w)", text or "", re.I):
            out.append(name)
    return out


def extract_facts(text: str, entity_names: Iterable[str]) -> Dict[str, List[str]]:
    """{numbers, dates, months, entities} of the source text, each sorted (entities in the given order)."""
    return {
        "numbers": sorted(numbers(text)),
        "dates": sorted(set(_ISO.findall(text or ""))),
        "months": sorted(months(text, strict=True)),
        "entities": entities_in(text, entity_names),
    }


def verify(source: str, rewrite: str, entity_names: Iterable[str]) -> Tuple[bool, List[str], List[str]]:
    """(ok, missing facts, added numbers) — facts as "number:1200", "date:2026-09-26", "month:september",
    "entity:Manchester City"."""
    facts = extract_facts(source, entity_names)
    got_numbers, got_months = numbers(rewrite), months(rewrite, strict=False)
    missing = [f"number:{n}" for n in facts["numbers"] if n not in got_numbers]
    missing += [f"date:{d}" for d in facts["dates"] if not iso_kept(d, rewrite, got_numbers, got_months)]
    missing += [f"month:{m}" for m in facts["months"] if m not in got_months]
    missing += [f"entity:{e}" for e in facts["entities"] if not entities_in(rewrite, [e])]
    allowed = set(facts["numbers"]) | number_words(source)
    allowed |= {n for d in facts["dates"] for n in iso_parts(d)[::2]}     # the year and day of a spelled-out date
    added = sorted(n for n in got_numbers if n not in allowed and n.rstrip("%") not in allowed)
    return not missing and not added, missing, added
