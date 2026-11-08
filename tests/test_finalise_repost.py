import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))

import finalise_docs as FD


def test_a_live_application_is_not_downgraded_without_repost(monkeypatch):
    monkeypatch.setattr(FD.REG, "find_row",
                        lambda company, role: {"status": "IN_PROGRESS", "date": "2026-10-08"})
    called = []
    monkeypatch.setattr(FD, "run", lambda cmd: called.append(cmd) or (0, ""))
    result, why = FD.record_prepared("Acme", "Engineer", "cv.docx", "", False, False)
    assert result == "skip"
    assert why == "IN_PROGRESS"
    assert called == []


def test_a_repost_records_prepared_and_keeps_the_earlier_status(monkeypatch):
    monkeypatch.setattr(FD.REG, "find_row",
                        lambda company, role: {"status": "IN_PROGRESS", "date": "2026-10-08"})
    called = []
    monkeypatch.setattr(FD, "run", lambda cmd: called.append(cmd) or (0, ""))
    result, why = FD.record_prepared("Acme", "Engineer", "cv.docx", "", False, True)
    assert result == "ok"
    assert why == "PREPARED"
    cmd = called[0]
    assert "--status" in cmd and "PREPARED" in cmd
    assert "--repost" in cmd
    note = cmd[cmd.index("--notes") + 1]
    assert "review: cv.docx" in note
    assert "earlier application still IN_PROGRESS since 2026-10-08" in note
    assert "new documents prepared, not submitted" in note
