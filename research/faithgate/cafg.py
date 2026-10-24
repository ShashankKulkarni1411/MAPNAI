"""
CAFG — compression-aware cascade gate (research/PREREG.md §1, §4; research/PROPOSED_RESEARCH_PLAN.md §6.4). Pure.

    stage 0  normalize      entity names compared after factcheck.normalize_name (F2)                  normalize_entities
    stage 1  additions      a number, capitalized name or month the source lacks → hard reject         added_names / added_months
                            (added numbers are always checked, as in factcheck.verify)
    stage 1b lexical accept every content word of the text is in one source sentence → accept,          lexical_accept (τ)
                            no learned call (claim mode)
    stage 2  retention      every source fact must survive (as factcheck.verify), unless the source is   require_retention,
                            longer than the length budget: then only core facts must (first sentence ∪   budget_words, core_k
                            the core_k most-mentioned entities); non-core omissions are logged
    stage 3  learned        what passed the lexical stages goes to a checker (support probability per    learned, theta
                            sentence of the text, minimum over sentences); below θ → reject

With every option off (CAFGConfig() defaults), decide() equals factcheck.verify bit-for-bit (the equivalence test).
A checker is any callable (document, [claims]) → [support probabilities].
"""

import re
from dataclasses import dataclass, field
from typing import Callable, Dict, Iterable, List, Optional, Sequence

from personalization import factcheck

_SENT = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"“‘(])")
_TOKEN = re.compile(r"[a-z0-9]+")
_STOP = set("a an the and or but of in on at to for from by with as is are was were be been being it its this that these "
            "those he she they them his her their we our you your i not no so than then there here who whom which what "
            "when where why how all any both each few more most other some such only own same too very can will just "
            "also into over after before about up down out off again further once has have had do does did said says "
            "say".split())


@dataclass(frozen=True)
class CAFGConfig:
    normalize_entities: bool = False
    added_names: bool = False
    added_months: bool = False
    lexical_accept: Optional[float] = None
    require_retention: bool = True
    budget_words: Optional[int] = None
    core_k: int = 3
    learned: bool = False
    theta: float = 0.5


@dataclass
class Decision:
    accept: bool
    stage: str            # "addition" | "lexical_accept" | "core_omission" | "learned" | "lexical" | "no_retention"
    missing: List[str] = field(default_factory=list)
    added: List[str] = field(default_factory=list)
    omitted_noncore: List[str] = field(default_factory=list)
    checker_called: bool = False
    support: Optional[float] = None


def sentences(text: str) -> List[str]:
    return [s for s in _SENT.split((text or "").strip()) if s]


def content_tokens(text: str) -> set:
    return {t for t in _TOKEN.findall((text or "").lower()) if t not in _STOP}


def coverage(text: str, source: str) -> float:
    """Share of the text's content words found in its best-matching source sentence (1.0 for an empty text)."""
    toks = content_tokens(text)
    if not toks:
        return 1.0
    return max((len(toks & content_tokens(s)) / len(toks) for s in sentences(source) or [source]), default=0.0)


def _entity_present(name: str, text: str, normalize: bool) -> bool:
    if normalize:
        n = factcheck.normalize_name(name)
        return bool(re.search(rf"(?<!\w){re.escape(n)}(?!\w)", factcheck.normalize_text(text)))
    return bool(factcheck.entities_in(text, [name]))


def _source_entities(source: str, names: Sequence[str], normalize: bool) -> List[str]:
    if normalize:
        return [n for n, _ in factcheck._normalized_entities(source, names)]
    return factcheck.entities_in(source, names)


def _core(source: str, names: Sequence[str], cfg: CAFGConfig) -> Dict[str, set]:
    """Facts that must survive compression: those of the first sentence, plus the core_k entities mentioned most."""
    first = (sentences(source) or [source])[0]
    facts = factcheck.extract_facts(first, [])
    ents = _source_entities(source, names, cfg.normalize_entities)
    counts = {e: len(re.findall(rf"(?<!\w){re.escape(e)}(?!\w)", source, re.I)) for e in ents}
    top = sorted(ents, key=lambda e: (-counts[e], ents.index(e)))[: cfg.core_k]
    return {"numbers": set(facts["numbers"]), "dates": set(facts["dates"]), "months": set(facts["months"]),
            "entities": {e for e in ents if _entity_present(e, first, cfg.normalize_entities)} | set(top)}


def decide(source: str, text: str, entity_names: Iterable[str], cfg: CAFGConfig = CAFGConfig(),
           checker: Optional[Callable[[str, List[str]], List[float]]] = None) -> Decision:
    names = list(entity_names or [])

    # stage 1: additions (hard reject)
    _, missing_all, added = factcheck.verify(source, text, names, normalize_entities=cfg.normalize_entities,
                                             check_added_names=cfg.added_names)
    if cfg.added_months:
        added += [f"month:{m}" for m in sorted(factcheck.months(text, strict=True) -
                                               factcheck.months(source, strict=False))]
    if added:
        return Decision(False, "addition", missing_all, added)

    # stage 1b: lexical accept
    if cfg.lexical_accept is not None and coverage(text, source) >= cfg.lexical_accept:
        return Decision(True, "lexical_accept")

    # stage 2: retention, relaxed to core facts when the budget forces compression
    omitted = []
    if cfg.require_retention:
        if cfg.budget_words is not None and len(source.split()) > cfg.budget_words:
            core = _core(source, names, cfg)
            missing, omitted = [], []
            for f in missing_all:
                kind, value = f.split(":", 1)
                key = {"number": "numbers", "date": "dates", "month": "months", "entity": "entities"}[kind]
                (missing if value in core[key] else omitted).append(f)
        else:
            missing = missing_all
        if missing:
            return Decision(False, "core_omission", missing, [], omitted)

    # stage 3: learned checker on what passed
    if cfg.learned:
        if checker is None:
            raise ValueError("cfg.learned needs a checker")
        probs = checker(source, sentences(text) or [text])
        support = min(probs) if probs else 1.0
        return Decision(support >= cfg.theta, "learned", [], [], omitted, True, support)
    return Decision(True, "lexical" if cfg.require_retention else "no_retention", [], [], omitted)
