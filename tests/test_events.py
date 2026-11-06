"""The SSE revision stream only changes when state or live inputs change."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))

import dashboard as D  # noqa: E402


def test_revision_tracks_state_and_live_separately(tmp_path, monkeypatch):
    state = tmp_path / "state"
    logs = state / "logs"
    logs.mkdir(parents=True)
    apps = state / "applications.csv"
    apps.write_text("a\n", encoding="utf-8")
    task = logs / "task.log"
    task.write_text("one\n", encoding="utf-8")

    monkeypatch.setattr(D, "_STATE_FILES", (str(apps),))
    monkeypatch.setattr(D, "_STATE_DIRS", ())
    monkeypatch.setattr(D, "_LIVE_FILES", (str(task),))
    monkeypatch.setattr(D, "LOGS", str(logs))
    monkeypatch.setattr(D, "WQ", None)
    monkeypatch.setattr(D, "_REV", {"t": 0.0, "state": "", "live": ""})

    first = D._revision()
    assert first["state"] and first["live"]

    D._REV["t"] = 0.0
    apps.write_text("b\n", encoding="utf-8")
    second = D._revision()
    assert second["state"] != first["state"]
    assert second["live"] == first["live"]

    D._REV["t"] = 0.0
    task.write_text("two\n", encoding="utf-8")
    third = D._revision()
    assert third["live"] != second["live"]
    assert third["state"] == second["state"]
