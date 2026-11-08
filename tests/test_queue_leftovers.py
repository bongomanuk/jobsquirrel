import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _tool(tmp_path, monkeypatch):
    import sys
    sys.path.insert(0, os.path.join(ROOT, "tools"))
    import queue_leftovers as QL
    state = tmp_path / "state"
    state.mkdir()
    (state / "queue.tsv").write_text(
        "Co\tRole\thttps://example.test/1\tcv.docx\tats\tk1\n"
        "Co2\tPending\thttps://example.test/2\tcv.docx\tats\tk2\n")
    (state / "queue.done").write_text("Co|Role\nk1\n")
    monkeypatch.setattr(QL, "ROOT", str(tmp_path))
    monkeypatch.setattr(QL, "QUEUES", ("state/queue.tsv",))
    monkeypatch.setattr(QL, "DONE", str(state / "queue.done"))
    monkeypatch.setattr(QL, "QUARANTINE", str(state / "queue-leftovers.done"))
    monkeypatch.setattr(QL, "QUARANTINE_TSV", str(state / "queue-leftovers.tsv"))
    monkeypatch.setattr(QL, "REPORT", str(state / "queue-leftovers.md"))
    monkeypatch.setattr(QL.REG, "load", lambda: [])
    return QL, state


def test_a_finished_row_without_a_register_row_is_a_leftover(tmp_path, monkeypatch):
    QL, state = _tool(tmp_path, monkeypatch)
    rows = QL.find_leftovers()
    assert len(rows) == 1
    assert rows[0]["role"] == "Role"
    text = QL.report(rows)
    assert "Queue leftovers" in text and "Co" in text and "Role" in text


def test_drop_removes_only_the_leftover_and_quarantines_its_done_entry(tmp_path, monkeypatch):
    QL, state = _tool(tmp_path, monkeypatch)
    rows = QL.find_leftovers()
    assert QL.drop(rows) == 1
    assert (state / "queue.tsv").read_text().splitlines() == [
        "Co2\tPending\thttps://example.test/2\tcv.docx\tats\tk2"]
    assert QL.prune_done() == 2
    assert (state / "queue.done").read_text().strip() == ""
    q = (state / "queue-leftovers.done").read_text()
    assert "Co|Role" in q and "k1" in q
    assert QL.find_leftovers() == []
