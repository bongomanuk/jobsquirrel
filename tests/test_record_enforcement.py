import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EVIDENCE = "Thank you for applying, your application was received"


def _env(tmp):
    e = dict(os.environ)
    e["GATES_DIR"] = str(tmp / "gates")
    e["SUBMISSIONS_CSV"] = str(tmp / "submissions.csv")
    e["SUBMISSIONS_DIR"] = str(tmp / "snapshot")
    e["APPLICATIONS_CSV"] = str(tmp / "applications.csv")
    return e


def _record(tmp, cv, letter, extra=None):
    cmd = [sys.executable, "tools/record_submission.py", "--company", "Acme",
           "--role", "Eng", "--cv", str(cv), "--letter", str(letter),
           "--status", "SUBMITTED", "--evidence", EVIDENCE]
    return subprocess.run(cmd + (extra or []), cwd=ROOT, env=_env(tmp),
                          capture_output=True, text=True)


def _emit(tmp, cv, letter):
    code = ("import sys; sys.path.insert(0, 'tools'); import gate_receipt as g;"
            f"g.emit('documents', {{'cv': r'{cv}', 'letter': r'{letter}'}})")
    subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=_env(tmp), check=True)


def test_refuses_submitted_without_receipt(tmp_path):
    cv = tmp_path / "cv.txt"
    cv.write_text("cv")
    letter = tmp_path / "letter.txt"
    letter.write_text("letter")
    r = _record(tmp_path, cv, letter)
    assert r.returncode == 3
    assert "refusing to record SUBMITTED" in r.stderr


def test_accepts_submitted_with_receipt(tmp_path):
    cv = tmp_path / "cv.txt"
    cv.write_text("cv")
    letter = tmp_path / "letter.txt"
    letter.write_text("letter")
    _emit(tmp_path, cv, letter)
    r = _record(tmp_path, cv, letter)
    assert r.returncode == 0, r.stderr


def test_mismatched_file_refused(tmp_path):
    cv = tmp_path / "cv.txt"
    cv.write_text("cv")
    letter = tmp_path / "letter.txt"
    letter.write_text("letter")
    _emit(tmp_path, cv, letter)
    other = tmp_path / "other.txt"
    other.write_text("different")
    r = _record(tmp_path, cv, other)
    assert r.returncode == 3


def test_gate_enforce_off_bypasses(tmp_path):
    cv = tmp_path / "cv.txt"
    cv.write_text("cv")
    letter = tmp_path / "letter.txt"
    letter.write_text("letter")
    env = _env(tmp_path)
    env["GATE_ENFORCE"] = "0"
    cmd = [sys.executable, "tools/record_submission.py", "--company", "Acme",
           "--role", "Eng", "--cv", str(cv), "--letter", str(letter),
           "--status", "SUBMITTED", "--evidence", EVIDENCE]
    r = subprocess.run(cmd, cwd=ROOT, env=env, capture_output=True, text=True)
    assert r.returncode == 0
