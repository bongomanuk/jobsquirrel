"""Canonical fact wording: normalize at ingest/render and fail stale documents."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))
import canonical as C  # noqa: E402


def test_normalize_and_violations(monkeypatch):
    monkeypatch.setattr(C, "RULES", {
        "replace": [{"wrong": r"\bold name\b", "right": "New Name"}],
        "forbidden": [r"\bold name\b"],
    })
    assert C.normalize("an old name here") == "an New Name here"
    assert C.violations("an old name here") == ["old name"]
    assert C.violations("a New Name here") == []
    assert C.normalize("a New Name here") == "a New Name here"


def test_normalize_data_recurses(monkeypatch):
    monkeypatch.setattr(C, "RULES", {
        "replace": [{"wrong": r"\bold\b", "right": "new"}],
        "forbidden": [],
    })
    assert C.normalize_data({"a": ["old", {"b": "old"}]}) == {"a": ["new", {"b": "new"}]}
