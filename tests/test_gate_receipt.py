import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))


def _gr(tmp_path, monkeypatch):
    import gate_receipt as GR
    monkeypatch.setattr(GR, "GATES_DIR", str(tmp_path / "gates"))
    return GR


def test_emit_and_find(tmp_path, monkeypatch):
    GR = _gr(tmp_path, monkeypatch)
    cv = tmp_path / "cv.txt"
    cv.write_text("cv")
    letter = tmp_path / "letter.txt"
    letter.write_text("letter")

    path = GR.emit("documents", {"cv": str(cv), "letter": str(letter)})
    assert path and os.path.isfile(path)

    ok, why = GR.find_pass({"cv": str(cv), "letter": str(letter)})
    assert ok, why

    # subset: a receipt for {cv, letter} satisfies a query for {cv}
    ok2, _ = GR.find_pass({"cv": str(cv)})
    assert ok2

    # a different file must not match
    other = tmp_path / "other.txt"
    other.write_text("other")
    ok3, _ = GR.find_pass({"cv": str(cv), "letter": str(other)})
    assert not ok3


def test_no_receipts(tmp_path, monkeypatch):
    GR = _gr(tmp_path, monkeypatch)
    cv = tmp_path / "cv.txt"
    cv.write_text("cv")
    ok, why = GR.find_pass({"cv": str(cv)})
    assert not ok
    assert "no gate receipts" in why


def test_expiry(tmp_path, monkeypatch):
    GR = _gr(tmp_path, monkeypatch)
    cv = tmp_path / "cv.txt"
    cv.write_text("cv")
    GR.emit("documents", {"cv": str(cv)})
    time.sleep(0.05)
    ok, _ = GR.find_pass({"cv": str(cv)}, max_age_hours=0.0)  # 0 disables the age check
    assert ok
    ok2, _ = GR.find_pass({"cv": str(cv)}, max_age_hours=1e-6)
    assert not ok2
