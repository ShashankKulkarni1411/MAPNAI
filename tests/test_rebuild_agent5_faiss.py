"""
MAPNAI — tests/test_rebuild_agent5_faiss.py
F7: the Agent 5 index rebuild only ever writes a new index (never the live one) and reports coverage.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.rebuild_agent5_faiss import coverage, main


def test_coverage_counts_missing_and_stale():
    c = coverage(index_ids=["a", "b", "x", "b"], live_ids=["a", "b", "c", "d"])
    assert (c["live"], c["indexed_live"], c["missing"], c["stale_rows"], c["duplicate_rows"]) == (4, 2, 2, 1, 1)
    assert c["coverage"] == 0.5


def test_coverage_of_an_empty_corpus():
    assert coverage([], [])["coverage"] is None


def test_write_refuses_the_live_index(tmp_path, capsys):
    from config.settings import settings
    assert main(["--write", "--out-index", settings.faiss_index_path, "--out-metadata", str(tmp_path / "m.pkl")]) == 2
    assert "live index" in capsys.readouterr().err


def test_write_refuses_an_existing_file(tmp_path, capsys):
    idx = tmp_path / "new.faiss"
    idx.write_bytes(b"x")
    assert main(["--write", "--out-index", str(idx), "--out-metadata", str(tmp_path / "m.pkl")]) == 2
    assert "exists" in capsys.readouterr().err


def test_write_needs_both_paths(capsys):
    assert main(["--write"]) == 2
