"""Unit tests for the shared prompt and parser.  Run:  python research2/test_nv_common.py"""
from nv_common import VALUES, build_messages, parse_scores, prompt_sha256, truncate

FULL = {k: i % 5 + 1 for i, k in enumerate(VALUES)}


def test_clean_json():
    import json
    assert parse_scores(json.dumps(FULL)) == FULL


def test_json_with_prose_and_fence():
    import json
    text = "Sure, here it is:\n```json\n" + json.dumps(FULL) + "\n```"
    assert parse_scores(text) == FULL


def test_string_digits_and_float():
    d = {k: str(v) for k, v in FULL.items()}
    d["conflict"] = 1.0
    got = parse_scores(__import__("json").dumps(d))
    assert got is not None and got["conflict"] == 1


def test_out_of_range_rejected():
    import json
    d = dict(FULL, utility=6)
    assert parse_scores(json.dumps(d)) is None
    d = dict(FULL, utility=0)
    assert parse_scores(json.dumps(d)) is None


def test_missing_key_rejected():
    import json
    d = dict(FULL)
    del d["importance"]
    assert parse_scores(json.dumps(d)) is None


def test_bool_rejected():
    import json
    assert parse_scores(json.dumps(dict(FULL, surprise=True))) is None


def test_regex_fallback_on_broken_json():
    text = '{"conflict": 2, "magnitude": 3, "prominence": 4, "surprise": 1, "utility": 5, "entertainment": 2, "importance": 3'
    assert parse_scores(text) == {"conflict": 2, "magnitude": 3, "prominence": 4, "surprise": 1,
                                  "utility": 5, "entertainment": 2, "importance": 3}


def test_empty():
    assert parse_scores("") is None and parse_scores(None) is None and parse_scores("no json") is None


def test_messages():
    m = build_messages(" A headline ", "")
    assert m[0]["role"] == "system" and m[1]["role"] == "user"
    assert "Headline: A headline\n" in m[1]["content"] and "Abstract: (none)" in m[1]["content"]
    assert '{"conflict": <1-5>' in m[1]["content"]          # braces survived .format()


def test_prompt_hash_stable():
    assert prompt_sha256() == prompt_sha256() and len(prompt_sha256()) == 64


def test_truncate():
    assert truncate("a  b\n c") == "a b c"
    long = "word " * 200
    t = truncate(long, 50)
    assert t.endswith(" …") and len(t) <= 52


if __name__ == "__main__":
    n = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            n += 1
    print(f"{n} tests passed")
