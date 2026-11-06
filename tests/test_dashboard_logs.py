"""The Settings log browser needs size/age/running, newest first."""
import gzip
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))

import dashboard as D  # noqa: E402


class FakeWQ:
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
