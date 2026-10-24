"""
research/faithgate/test_cafg.py — unit tests for CAFG (run: python -m pytest research/faithgate/test_cafg.py).
The full equivalence check on every E02 item is research/faithgate/check_equivalence_e02.py (needs the snapshot).
"""

import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from personalization import factcheck                                  # noqa: E402
from research.faithgate.cafg import CAFGConfig, coverage, decide, sentences  # noqa: E402

SRC = ("Arsenal beat Chelsea 2-1 at the Emirates on 26 September. Bukayo Saka scored the winner. "
       "Mikel Arteta praised Declan Rice, who made 3 tackles.")
NAMES = ["Arsenal", "Chelsea", "Emirates", "Bukayo Saka", "Mikel Arteta", "Declan Rice", "Saka's"]

CASES = [
    SRC,
    "Arsenal beat Chelsea 2-1 on 26 September; Bukayo Saka scored.",
    "Arsenal beat Chelsea 3-1 at the Emirates on 26 September.",
    "Chelsea beat Arsenal 2-1 at the Emirates on 26 September. Bukayo Saka scored the winner. Mikel Arteta praised "
    "Declan Rice, who made 3 tackles.",
    "",
    "Arsenal won.",
]


@pytest.mark.parametrize("text", CASES)
def test_defaults_equal_the_production_gate(text):
    ok, missing, added = factcheck.verify(SRC, text, NAMES)
    d = decide(SRC, text, NAMES)
    assert (d.accept, d.missing, d.added) == (ok, missing, added)


def test_added_name_and_month_are_hard_rejects():
    text = SRC + " Kai Havertz watched in October."
    assert decide(SRC, text, NAMES).accept                              # v1 checks neither
    d = decide(SRC, text, NAMES, CAFGConfig(added_names=True, added_months=True))
    assert not d.accept and d.stage == "addition" and "month:october" in d.added
    assert any(a.startswith("name:") for a in d.added)


def test_budget_relaxes_non_core_omissions_only():
    short = "Arsenal beat Chelsea 2-1 at the Emirates on 26 September; Saka scored."
    cfg = CAFGConfig(normalize_entities=True, budget_words=12, core_k=2)
    assert not decide(SRC, short, NAMES).accept                         # v1: Rice, Arteta, 3 missing
    d = decide(SRC, short, NAMES, cfg)
    assert d.accept and d.stage == "lexical" and set(d.omitted_noncore) >= {"number:3"}


def test_budget_keeps_first_sentence_facts():
    text = "Bukayo Saka scored the winner as Arsenal beat Chelsea."   # drops 2-1, Emirates, 26 September
    d = decide(SRC, text, NAMES, CAFGConfig(normalize_entities=True, budget_words=12))
    assert not d.accept and d.stage == "core_omission" and "number:2" in d.missing


def test_no_relaxation_when_the_source_fits_the_budget():
    d = decide(SRC, "Arsenal beat Chelsea 2-1 at the Emirates on 26 September.", NAMES,
               CAFGConfig(normalize_entities=True, budget_words=200))
    assert not d.accept and d.stage == "core_omission"


def test_learned_stage_only_sees_lexical_passes():
    calls = []

    def checker(doc, claims):
        calls.append(claims)
        return [0.9 if "beat" in c else 0.2 for c in claims]

    cfg = CAFGConfig(learned=True, require_retention=False, added_names=True)
    assert not decide(SRC, "Arsenal beat Chelsea 4-1.", NAMES, cfg, checker).checker_called    # added number
    d = decide(SRC, "Arsenal beat Chelsea 2-1. Chelsea won.", NAMES, cfg, checker)
    assert d.checker_called and not d.accept and d.support == 0.2 and calls[-1] == ["Arsenal beat Chelsea 2-1.",
                                                                                    "Chelsea won."]
    with pytest.raises(ValueError):
        decide(SRC, SRC, NAMES, CAFGConfig(learned=True))                 # passes lexically, no checker


def test_lexical_accept_skips_the_checker():
    cfg = CAFGConfig(require_retention=False, lexical_accept=1.0, learned=True)
    d = decide(SRC, "Bukayo Saka scored the winner.", NAMES, cfg, lambda doc, c: pytest.fail("called"))
    assert d.accept and d.stage == "lexical_accept"
    assert coverage("Bukayo Saka scored the winner.", SRC) == 1.0
    assert coverage("Saka missed a penalty.", SRC) < 1.0


def test_sentences():
    assert sentences("One. Two! Three?") == ["One.", "Two!", "Three?"]
    assert sentences("") == []
