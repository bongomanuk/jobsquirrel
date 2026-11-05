"""Action requests leave the chat and become background subagent tasks."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))
import dashboard as D  # noqa: E402


def test_action_detection_keeps_questions_in_chat():
    assert D._looks_like_action("fix the grid fit")
    assert D._looks_like_action("prepare documents for the role")
    assert D._looks_like_action("can you run the queue?")
    assert D._looks_like_action("look at the logs")
    assert not D._looks_like_action("why does the grid not show a fit?")
    assert not D._looks_like_action("what is outstanding?")
    assert not D._looks_like_action("show me the CV")
    assert not D._looks_like_action("how does the graph work?")


def test_chat_start_hands_actions_to_a_subagent(monkeypatch):
    seen = {}

    def fake_delegate(prompt, title=""):
        seen["prompt"] = prompt
        seen["title"] = title
        return {"ok": "started", "id": "task-1", "title": title}

    monkeypatch.setattr(D, "delegate_start", fake_delegate)
    monkeypatch.setattr(D, "_chat_echo", lambda message: None)
    monkeypatch.setattr(D, "_chat_status", lambda text: None)
    res = D.chat_start("fix the grid fit")
    assert res.get("delegated") is True
    assert res.get("id") == "task-1"
    assert seen["prompt"] == "fix the grid fit"
