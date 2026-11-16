import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP = os.path.join(ROOT, "tools", "web", "app.js")
sys.path.insert(0, os.path.join(ROOT, "tools"))

import dashboard as D  # noqa: E402


def _app():
    with open(APP, encoding="utf-8") as fh:
        return fh.read()


def test_action_and_finished_task_cards_are_inserted_in_the_transcript():
    app = _app()
    # The card remembers the absolute segment index where it started or
    # finished and is emitted at that boundary, not appended after the whole
    # transcript.
    assert "let ACT_AT = 0, ACT_KEY = '', ACT_SEQ = 0, CARD_SEQ = 1;" in app
    assert "function chatAbsLen()" in app
    assert "const at = chatAbsLen();" in app
    assert "const cardAt = (abs) =>" in app
    assert "for (const c of chunks) { emit(c.start); h += c.html; }" in app
    assert "emit(segs.length);" in app


def test_cards_survive_the_servers_segment_window():
    app = _app()
    # The server trims the transcript to a window; the UI subtracts the window
    # base so an old card cannot drift to the bottom as new segments arrive.
    assert "CHAT_BASE = d.base || 0" in app
    assert "- base, segs.length)" in app
    assert "cards.push({ at: Math.min(ACT_AT, segs.length)" not in app


def test_page_load_does_not_replay_an_old_finished_task_at_the_bottom():
    app = _app()
    assert "DONE_CARDS = done.slice(0, 1)" not in app
    assert "DELEGATED_DONE_SEEN = doneIds;" in app
    # A fresh completion is still placed at the point it finished.
    assert "const at = chatAbsLen();" in app
    assert "DONE_CARDS.push(...freshDone.slice(-3)" in app


def test_an_old_token_total_stays_with_its_own_turn(monkeypatch):
    monkeypatch.setattr(D, "load_agent_cfg", lambda: {"agent": "opencode"})
    text = "\n".join([
        '{"type":"step_finish","part":{"tokens":{"total":123},"cost":0}}',
        "> a newer message",
    ])
    segs = D.chat_parse_json(text)
    assert segs[-1] == {"t": "user", "body": "a newer message"}
    assert segs[-2]["body"].startswith("123 tokens")      # before the newer turn, not after it


def test_the_current_turn_still_reports_its_token_total(monkeypatch):
    monkeypatch.setattr(D, "load_agent_cfg", lambda: {"agent": "opencode"})
    text = "\n".join([
        '{"type":"text","part":{"text":"done"}}',
        '{"type":"step_finish","part":{"tokens":{"total":123},"cost":0}}',
    ])
    assert D.chat_parse_json(text)[-1]["body"].startswith("123 tokens")


def test_chat_stream_reports_the_segment_window_base(tmp_path, monkeypatch):
    log = tmp_path / "chat.log"
    log.write_text("\n".join(
        json.dumps({"type": "text", "part": {"text": f"message {i}"}}) for i in range(450)
    ), encoding="utf-8")
    monkeypatch.setattr(D, "CHAT_LOG", str(log))
    monkeypatch.setattr(D, "CHAT_SESSION", str(tmp_path / "chat.session"))
    monkeypatch.setattr(D, "_chat_pump", lambda: None)
    monkeypatch.setattr(D, "_record_chat_session", lambda text: None)
    monkeypatch.setattr(D, "_chat_running", lambda: False)
    monkeypatch.setattr(D, "_CHAT", {"proc": None, "queue": []})
    got = D.chat_stream("chat", 0)
    assert got["total"] == 450
    assert got["base"] == 50
    assert len(got["segments"]) == 400
    assert got["segments"][-1]["body"] == "message 449"


def test_a_finished_subagent_summary_reaches_the_agent_console(tmp_path, monkeypatch):
    monkeypatch.setattr(D, "LOGS", str(tmp_path))
    (tmp_path / "delegated-x.log").write_text(
        "$ curl something\n"
        '{"json": true}\n'
        "**Answer**\n"
        "* first finding\n"
        "* second finding\n"
        "\n"
        "**Today:** do the follow-ups.\n"
        "\n"
        "RESULT: done\n",
        encoding="utf-8",
    )
    summary = D._delegated_summary("delegated-x")
    assert "**Answer**" in summary
    assert "first finding" in summary
    assert "Today:" in summary
    assert "RESULT:" not in summary
