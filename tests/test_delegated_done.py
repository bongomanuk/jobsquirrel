"""A subagent whose log has its final RESULT/EXIT line is finished, even if
the CLI process is still winding down."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))
import dashboard as D  # noqa: E402


def _log(tmp_path, monkeypatch, text):
    monkeypatch.setattr(D, "LOGS", str(tmp_path))
    (tmp_path / "delegated-test.log").write_text(text, encoding="utf-8")
    return "delegated-test"


def test_final_result_is_done(tmp_path, monkeypatch):
    log = _log(tmp_path, monkeypatch, "> build\nRESULT: done\nEXIT:0\n> build\n")
    assert D._delegated_done(log) is True


def test_tool_after_result_is_not_done(tmp_path, monkeypatch):
    log = _log(tmp_path, monkeypatch, "RESULT: FAIL\n$ python3 tools/x.py\n> build\n")
    assert D._delegated_done(log) is False


def test_no_result_is_not_done(tmp_path, monkeypatch):
    log = _log(tmp_path, monkeypatch, "> build\n$ sleep 5\n> build\n")
    assert D._delegated_done(log) is False
