"""Shelved roles: a view overlay that never changes the register status."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))
import dashboard as D  # noqa: E402


def test_shelve_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(D, "SHELVED", str(tmp_path / "shelved.json"))
    assert D.shelved_roles() == {}
    D.set_shelved("k1", True, "not sure yet")
    assert "k1" in D.shelved_roles()
    D.set_shelved("k1", False)
    assert "k1" not in D.shelved_roles()


def test_shelved_is_separate_from_the_register(tmp_path, monkeypatch):
    monkeypatch.setattr(D, "SHELVED", str(tmp_path / "shelved.json"))
    D.set_shelved("k1", True)
    # The shelf file only holds the UI overlay; it has no status.
    import json
    data = json.load(open(tmp_path / "shelved.json"))
    assert "status" not in data["k1"]
