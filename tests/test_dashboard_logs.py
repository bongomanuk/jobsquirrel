"""The Settings log browser needs size/age/running, newest first."""
import gzip
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))

import dashboard as D  # noqa: E402


class FakeWQ:
    def __init__(self, active=True):
        self.active = active

    def runner_active(self):
        return self.active

    def live_tasks(self):
        return ["Acme|Engineer"]


def test_log_items_include_metadata(tmp_path, monkeypatch):
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "plain.log").write_text("line\n", encoding="utf-8")
    with gzip.open(logs / "zipped.log.gz", "wt", encoding="utf-8") as fh:
        fh.write("old line\n")

    monkeypatch.setattr(D, "LOGS", str(logs))
    monkeypatch.setattr(D, "WQ", None)
    items = {x["name"]: x for x in D.task_log_items()}

    assert set(items) == {"plain", "zipped"}
    assert items["plain"]["size"] == 5
    assert items["plain"]["running"] is False
    assert items["plain"]["age"] >= 0
    assert items["zipped"]["size"] > 0


def test_live_log_wins_over_packed_copy_and_is_marked_running(tmp_path, monkeypatch):
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "Acme-Engineer.log").write_text("live\n", encoding="utf-8")
    with gzip.open(logs / "Acme-Engineer.log.gz", "wt", encoding="utf-8") as fh:
        fh.write("packed\n")

    monkeypatch.setattr(D, "LOGS", str(logs))
    monkeypatch.setattr(D, "WQ", FakeWQ())
    items = D.task_log_items()

    assert [x["name"] for x in items] == ["Acme-Engineer"]
    assert items[0]["running"] is True
    assert items[0]["size"] == 5


def test_finished_run_does_not_leave_a_row_running(tmp_path, monkeypatch):
    """A lingering agent process after the queue finished must not read as RUN.

    The grid used to keep a row on "Being worked on" for up to five minutes
    while the Activity pane already said idle, because the finished worker's
    log was still fresh.
    """
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "Acme-Engineer.log").write_text("live\n", encoding="utf-8")

    monkeypatch.setattr(D, "LOGS", str(logs))
    monkeypatch.setattr(D, "WQ", FakeWQ(active=False))
    items = D.task_log_items()

    assert items[0]["running"] is False


def test_log_items_are_newest_first_and_limited(tmp_path, monkeypatch):
    logs = tmp_path / "logs"
    logs.mkdir()
    for i, name in enumerate(("old", "middle", "new")):
        p = logs / (name + ".log")
        p.write_text("x\n", encoding="utf-8")
        os.utime(p, (1000 + i, 1000 + i))

    monkeypatch.setattr(D, "LOGS", str(logs))
    monkeypatch.setattr(D, "WQ", None)

    assert [x["name"] for x in D.task_log_items()] == ["new", "middle", "old"]
    assert [x["name"] for x in D.task_log_items(limit=1)] == ["new"]


def test_action_log_reports_only_the_latest_action(tmp_path, monkeypatch):
    """Successive actions share one log; a capped or restarted slice must not
    leak an older action's START/STATUS lines into the Activity report."""
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "dashboard-action.log").write_text(
        "=== 2026-01-01T10:00:00 prepare 1 role(s) (review) ===" + "\n"
        "START 10:00:01 Old Co | Old Role" + "\n"
        "STATUS Old Co | Old Role | PREPARED | old" + "\n"
        "=== 2026-01-01T10:10:00 submit 3 prepared role(s) ===" + "\n"
        "START 10:10:01 New Co | New Role" + "\n"
        "STATUS New Co | New Role | CLOSED | posting gone" + "\n",
        encoding="utf-8")
    monkeypatch.setattr(D, "LOGS", str(logs))
    monkeypatch.setitem(D._ACT, "offset", 0)
    monkeypatch.setitem(D._ACT, "t0", 0)
    monkeypatch.setitem(D._ACT, "name", "")
    lines = D.action_log(100)
    text = "\n".join(lines)
    assert "New Co" in text
    assert "Old Co" not in text
