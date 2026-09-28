"""
MAPNAI — tests/test_pers_keys.py
Pure tests for personalization/keys.py and the Beta helpers in personalization/interest.py.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest

from config.personalization import PersonalizationSettings
from personalization import interest
from personalization.keys import beta_key, decode_key, encode_key, entity_key

CFG = PersonalizationSettings(_env_file=None)


class TestEntityKey:
    def test_trim_collapse_lower(self):
        assert entity_key("  Manchester   City ") == "manchester city"

    def test_variants_share_a_key(self):
        assert entity_key("Manchester City") == entity_key("Manchester city") == "manchester city"

    def test_tabs_and_newlines(self):
        assert entity_key("New\tYork\nCity") == "new york city"

    def test_empty(self):
        assert entity_key("") == "" and entity_key(None) == ""


class TestEncodeKey:
    @pytest.mark.parametrize("raw", ["entity:u.s", "entity:$money", "entity:100%", "entity:a%2Eb", "topic:sports"])
    def test_roundtrip(self, raw):
        assert decode_key(encode_key(raw)) == raw

    def test_mongo_safe(self):
        enc = encode_key("entity:u.s.$x")
        assert "." not in enc and "$" not in enc

    def test_literal_percent_sequence_is_not_confused(self):
        # "a%2Eb" is a real name; it must not decode to "a.b"
        assert encode_key("a%2Eb") != encode_key("a.b")


class TestBetaKey:
    def test_topic(self):
        assert beta_key("topic", " Sports ") == "topic:sports"

    def test_entity_is_canonical(self):
        assert beta_key("entity", "Manchester  City") == "entity:manchester city"

    def test_bad_kind(self):
        with pytest.raises(ValueError):
            beta_key("person", "x")


class TestBeta:
    def test_prior_high(self):
        assert interest.prior(1.0, CFG) == [4.0, 1.0]

    def test_prior_zero_and_clamp(self):
        assert interest.prior(0.0, CFG) == [1.0, 4.0]
        assert interest.prior(2.0, CFG) == [4.0, 1.0]

    def test_theta(self):
        assert interest.theta([4, 1]) == 0.8
        assert interest.theta([0, 0]) == 0.5

    def test_more_updates_topic_and_top3_entities(self):
        d = interest.beta_updates("more", None, "sports", ["a", "b", "c", "d"], CFG)
        assert d == {"topic:sports": [1, 0], "entity:a": [1, 0], "entity:b": [1, 0], "entity:c": [1, 0]}

    def test_less(self):
        assert interest.beta_updates("less", None, "sports", [], CFG) == {"topic:sports": [0, 1]}

    def test_dwell_threshold(self):
        assert interest.beta_updates("dwell", 5, "sports", [], CFG) == {}
        assert interest.beta_updates("dwell", 20, "sports", [], CFG) == {"topic:sports": [0.5, 0]}

    def test_no_delta_types(self):
        assert interest.beta_updates("save", None, "sports", ["a"], CFG) == {}

    def test_merge(self):
        merged = interest.merge_deltas([{"topic:x": [1, 0]}, {"topic:x": [0, 1], "topic:y": [1, 0]}])
        assert merged == {"topic:x": [1, 1], "topic:y": [1, 0]}
