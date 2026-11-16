import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))

import queue_clean as QC


def test_plan_keeps_only_pending_work(tmp_path, monkeypatch):
    queue = tmp_path / "queue.tsv"
    queue.write_text(
        "# header\n"
        "Done Co\tEngineer\thttps://x/1\tcv.docx\tats\tkdone\n"
        "Submitted Co\tEngineer\thttps://x/2\tcv.docx\tats\tksub\n"
        "Queued Co\tEngineer\thttps://x/3\tcv.docx\tats\tkqueued\n"
        "New Co\tEngineer\thttps://x/4\tcv.docx\tats\tknew\n")
    done = tmp_path / "queue.done"
    done.write_text("Done Co|Engineer\nkdone\n")
    monkeypatch.setattr(QC, "QUEUE", str(queue))
    monkeypatch.setattr(QC, "DONE", str(done))
    monkeypatch.setattr(QC.REG, "load", lambda: [
        {"company": "Submitted Co", "role": "Engineer", "status": "SUBMITTED", "key": "ksub"},
        {"company": "Queued Co", "role": "Engineer", "status": "QUEUED", "key": "kqueued"},
    ])
    remove, keep = QC.plan()
    assert [x[0] for x in remove] == [2, 3]
    text = "".join(keep)
    assert "# header" in text
    assert "Queued Co" in text and "kqueued" in text
    assert "New Co" in text and "knew" in text
    assert "Done Co" not in text and "Submitted Co" not in text
