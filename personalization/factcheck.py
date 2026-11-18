"""
MAPNAI — personalization/factcheck.py
Fact preservation for rendered rewrites (pure). PERSONALIZATION_PLAN.md §5 "Render":

  facts of the source   numbers (\\d[\\d,.]*%?), ISO dates, month names in a date context, and the article's
                        entity names that occur verbatim in the source
  the rewrite passes    iff it keeps every fact (numbers compared normalized: "1,200" = "1200", "5 per cent" = "5%";
                        months by name: "26 Sept" = "September 26") and brings in no number the source doesn't have
                        (a number written as a word in the source, "two", may come back as a digit)

Anything missing or added → the caller falls back to the source text.

Gate versions (render_gate_version, default v1 = the rules above):
  v2-norm  entity names are compared after normalization (possessive, punctuation, case, a leading "the", hyphens,
           acronym dots, whitespace), so "Formula 1's" is kept by "Formula 1" and "The Beatles" by "Beatles".
           Not safe alone: a substituted mention passes when another spelling of the name survives (E02)
  v2       v2-norm + a capitalized name the source never uses is an addition (new_names below), reported in
           `added` as "name:<word>"
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
# (?!\w): the month must be a whole word, so "65 markets" and "1981 novel" are not March and November
_MONTH_BY_NUMBER = re.compile(rf"(?:\d{{1,2}}(?:st|nd|rd|th)?\s+({_MONTH_WORD})(?!\w))|(?:\b({_MONTH_WORD})\s+\d)",
                              re.I)
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


_QUOTES = str.maketrans({"’": "'", "‘": "'", "`": "'", "“": '"', "”": '"'})
_ACRONYM = re.compile(r"(?<!\w)(?:[a-z]\.)+[a-z]\.?(?!\w)", re.I)


def normalize_text(text: str) -> str:
    """Straight quotes, acronym dots dropped ("U.S." → "US"), hyphens as spaces, collapsed whitespace, casefolded."""
    text = (text or "").translate(_QUOTES)
    text = _ACRONYM.sub(lambda m: m.group(0).replace(".", ""), text)
    return re.sub(r"\s+", " ", text.replace("-", " ")).strip().casefold()


def normalize_name(name: str) -> str:
    """An entity name as v2-norm compares it: "Formula 1's" → "formula 1", "The Beatles" → "beatles". A leading "the"
    stays on a name it would shrink to one short word ("The Who"), which would otherwise match ordinary text."""
    n = re.sub(r"^\W+|\W+$", "", normalize_text(name))
    n = re.sub(r"'s?$", "", n).strip()
    if n.startswith("the ") and not re.fullmatch(r"the \w{1,3}", n):
        n = n[4:]
    return n


def _normalized_entities(text: str, entity_names: Iterable[str]) -> List[Tuple[str, str]]:
    """(name as given, normalized) for the names whose normalized form occurs in the normalized text, first
    spelling per normalized form."""
    norm_text, seen, out = normalize_text(text), set(), []
    for name in entity_names or []:
        n = normalize_name(name or "")
        if n and n not in seen and re.search(rf"(?<!\w){re.escape(n)}(?!\w)", norm_text):
            seen.add(n)
            out.append((name.strip(), n))
    return out


GATE_VERSIONS: Dict[str, Dict[str, bool]] = {
    "v1": {},
    "v2-norm": {"normalize_entities": True},
    "v2": {"normalize_entities": True, "check_added_names": True},
}


def extract_facts(text: str, entity_names: Iterable[str]) -> Dict[str, List[str]]:
    """{numbers, dates, months, entities} of the source text, each sorted (entities in the given order)."""
    return {
        "numbers": sorted(numbers(text)),
        "dates": sorted(set(_ISO.findall(text or ""))),
        "months": sorted(months(text, strict=True)),
        "entities": entities_in(text, entity_names),
    }


def verify(source: str, rewrite: str, entity_names: Iterable[str],
           normalize_entities: bool = False, check_added_names: bool = False) -> Tuple[bool, List[str], List[str]]:
    """(ok, missing facts, added numbers) — facts as "number:1200", "date:2026-09-26", "month:september",
    "entity:Manchester City". normalize_entities / check_added_names: gate v2-norm / v2 (module docstring);
    with check_added_names, `added` also lists "name:<word>"."""
    entity_names = list(entity_names or [])
    facts = extract_facts(source, [] if normalize_entities else entity_names)
    got_numbers, got_months = numbers(rewrite), months(rewrite, strict=False)
    missing = [f"number:{n}" for n in facts["numbers"] if n not in got_numbers]
    missing += [f"date:{d}" for d in facts["dates"] if not iso_kept(d, rewrite, got_numbers, got_months)]
    missing += [f"month:{m}" for m in facts["months"] if m not in got_months]
    if normalize_entities:
        norm_rewrite = normalize_text(rewrite)
        missing += [f"entity:{name}" for name, n in _normalized_entities(source, entity_names)
                    if not re.search(rf"(?<!\w){re.escape(n)}(?!\w)", norm_rewrite)]
    else:
        missing += [f"entity:{e}" for e in facts["entities"] if not entities_in(rewrite, [e])]
    allowed = set(facts["numbers"]) | number_words(source)
    allowed |= {n for d in facts["dates"] for n in iso_parts(d)[::2]}     # the year and day of a spelled-out date
    added = sorted(n for n in got_numbers if n not in allowed and n.rstrip("%") not in allowed)
    if check_added_names:
        added += [f"name:{w}" for w in new_names(source, rewrite, possessive_at_end=True)]
    return not missing and not added, missing, added


_NAME = re.compile(r"\b[A-Z][\w'’.-]*[\w]|\b[A-Z]\b")
_WORD = re.compile(r"[a-z0-9]+")
_SENTENCE_START =re.compile(r"(?:^|[.!?:;]\s+|\n)[\"'“‘(]*$")
# capitalized words that are not names: sentence openers the model may use mid-claim, and the scenario labels
_NOT_NAMES = {"i", "if", "a", "an", "the", "this", "that", "these", "those", "it", "its", "they", "he", "she",
              "we", "watch", "likely", "possible", "unlikely", "monday", "tuesday", "wednesday", "thursday",
              "friday", "saturday", "sunday", "ok"} | set(_MONTHS)    # months: checked as months


def new_names(source: str, text: str, possessive_at_end: bool = False) -> List[str]:
    """
    Capitalized words of the text (names, places, acronyms) the source never uses. A sentence's first word is
    skipped unless it is an acronym; "Indian" is allowed by "India" (one word is a prefix of the other, ≥ 4 letters).
    possessive_at_end: strip "'s" only at the end of a word. The default strips it anywhere, which turns
    "O'Sullivan" into "oullivan" and flags it as new; the default is kept for insights until that change is approved.
    """
    have = set(_WORD.findall((source or "").lower()))
    out = []
    for m in _NAME.finditer(text or ""):
        word = m.group(0).rstrip(".")
        acronym = len(word) >= 2 and word.isupper()
        if not acronym and _SENTENCE_START.search(text[: m.start()]):
            continue
        bare = (re.sub(r"['’]s$", "", word.lower()) if possessive_at_end
                else word.lower().replace("’s", "").replace("'s", ""))
        parts = _WORD.findall(bare)
        if not parts or word.lower() in _NOT_NAMES:
            continue
        for p in parts:
            if p in have or p.isdigit():
                continue
            if len(p) >= 4 and any(len(h) >= 4 and (p.startswith(h) or h.startswith(p)) for h in have):
                continue
            out.append(word)
            break
    return list(dict.fromkeys(out))
