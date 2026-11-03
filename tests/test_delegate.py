"""Background subagents: liveness filtering and the start guardrails."""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))

import dashboard as D


def test_delegated_live_keeps_only_running_pids(tmp_path, monkeypatch):
    monkeypatch.setattr(D, "DELEGATED_DIR", str(tmp_path))
    monkeypatch.setattr(D, "LOGS", str(tmp_path))
    (tmp_path / "alive.log").write_text("x")
    (tmp_path / "alive.json").write_text(json.dumps(
        {"id": "a", "title": "alive", "log": "alive", "pid": os.getpid()}))
    (tmp_path / "dead.json").write_text(json.dumps(
        {"id": "b", "title": "dead", "log": "dead", "pid": 99999999}))
    live = D.delegated_live()
    assert [x["title"] for x in live] == ["alive"]


def test_delegate_rejects_an_empty_task():
    assert "error" in D.delegate_start("   ")


def test_delegate_respects_the_concurrency_cap(monkeypatch):
    monkeypatch.setattr(D, "DELEGATED_MAX", 1)
    monkeypatch.setattr(D, "delegated_live", lambda: [{"title": "busy"}])
    r = D.delegate_start("do something")
    assert "already running" in r["error"]
