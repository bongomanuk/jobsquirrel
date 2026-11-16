"""Per-role triage flags: pin to the top."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))

import dashboard as D


def test_pin_and_unpin(tmp_path, monkeypatch):
    monkeypatch.setattr(D, "ROLE_FLAGS", str(tmp_path / "role-flags.json"))
    D.set_role_flags("role-b", pinned=True)
    assert D.role_flags()["role-b"] == {"pinned": True}
    D.set_role_flags("role-b", pinned=False)
    assert D.role_flags() == {}


def test_old_dismissed_flag_is_ignored(tmp_path, monkeypatch):
    monkeypatch.setattr(D, "ROLE_FLAGS", str(tmp_path / "role-flags.json"))
    (tmp_path / "role-flags.json").write_text('{"old": {"dismissed": true}}', encoding="utf-8")
    assert D.role_flags() == {}


def test_key_is_required():
    assert "error" in D.set_role_flags("")
