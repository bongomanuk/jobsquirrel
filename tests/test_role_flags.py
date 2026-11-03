"""Per-role triage flags: dismiss from lists and pin to the top."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))

import dashboard as D


def test_dismiss_and_restore(tmp_path, monkeypatch):
    monkeypatch.setattr(D, "ROLE_FLAGS", str(tmp_path / "role-flags.json"))
    assert D.set_role_flags("role-a", dismissed=True)["ok"]
    assert D.role_flags()["role-a"]["dismissed"] is True
    assert D.set_role_flags("role-a", dismissed=False)["ok"]
    assert D.role_flags() == {}


def test_pin_and_unpin(tmp_path, monkeypatch):
    monkeypatch.setattr(D, "ROLE_FLAGS", str(tmp_path / "role-flags.json"))
    D.set_role_flags("role-b", pinned=True)
    assert D.role_flags()["role-b"]["pinned"] is True
    D.set_role_flags("role-b", dismissed=True)
    assert D.role_flags()["role-b"] == {"pinned": True, "dismissed": True}
    D.set_role_flags("role-b", pinned=False, dismissed=False)
    assert D.role_flags() == {}


def test_key_is_required():
    assert "error" in D.set_role_flags("")
