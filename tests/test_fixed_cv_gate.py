"""Fixed-CV (LIGHT) runs: the CV-only pre-submit gate and the run end to end.

Everything runs in a throwaway ROOT with tools/ symlinked in, so config/,
state/ and the gate receipts are the sandbox's, never the real ones.
"""
import csv
import os
import stat
import subprocess
import sys

import pytest

docx = pytest.importorskip("docx")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

PROFILE = """# Profile
- full name: Jane Doe
- email: jane@doe.dev
- location (city, country): Zurich, Switzerland
"""
CV_JSON = ('{"experience": ['
           '{"employer": "Acme", "dates": "2021 - present", "title": "Engineer", '
           '"bullets": ["Built the billing platform"]}, '
           '{"employer": "Initech", "dates": "2015 - 2020", "title": "Developer", '
           '"bullets": ["Maintained the reporting tools"]}]}')


def _sandbox(tmp_path):
    root = tmp_path / "root"
    for d in ("config", "state", "documents"):
        (root / d).mkdir(parents=True)
    os.symlink(os.path.join(ROOT, "tools"), root / "tools")
    (root / "config" / "profile.md").write_text(PROFILE)
    (root / "config" / "cv.json").write_text(CV_JSON)
    return root


def _cv(path, name="JANE DOE", extra=()):
    """A CV laid out like cv_builder's: everything inside a two-column table."""
    d = docx.Document()
    left, right = d.add_table(rows=1, cols=2).rows[0].cells
    left.paragraphs[0].text = "jane@doe.dev"
    right.paragraphs[0].text = name
    for line in ("Profile", "Engineer who builds billing platforms.", *extra):
        right.add_paragraph(line)
    d.save(path)
    return path


def _env(root):
    env = dict(os.environ)
    env.pop("VIRTUAL_ENV", None)
    for k in ("GATES_DIR", "SUBMISSIONS_CSV", "SUBMISSIONS_DIR", "APPLICATIONS_CSV", "APPLICATIONS_MD"):
        env.pop(k, None)
    # `python3` in the runner and the stub must be this interpreter (it has python-docx).
    env["PATH"] = os.path.dirname(sys.executable) + os.pathsep + env["PATH"]
    return env


def _gate(root, *args):
    return subprocess.run([sys.executable, str(root / "tools" / "check_documents.py"), *args],
                          cwd=root, env=_env(root), capture_output=True, text=True)


def test_cv_alone_passes_and_writes_a_receipt(tmp_path):
    root = _sandbox(tmp_path)
    cv = _cv(root / "documents" / "cv.docx")
    r = _gate(root, "--cv", str(cv), "--record")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "RESULT: PASS" in r.stdout
    assert os.listdir(root / "state" / "gates"), "a PASS with --record writes a receipt"


@pytest.mark.parametrize("name, extra, why", [
    ("YOUR NAME", (), "CV does not carry the candidate's name"),
    ("JANE DOE", ("Contact: you@example.com",), "placeholder token present"),
    # Initech is a past employer in cv.json, so "currently ... at Initech" is false.
    ("JANE DOE", ("Currently maintaining the reporting tools at Initech",),
     "present-tense claim about past work"),
])
def test_cv_alone_failures(tmp_path, name, extra, why):
    root = _sandbox(tmp_path)
    cv = _cv(root / "documents" / "cv.docx", name=name, extra=extra)
    r = _gate(root, "--cv", str(cv), "--record")
    assert r.returncode == 1, r.stdout
    assert why in r.stdout
    assert not (root / "state" / "gates").exists(), "a FAIL writes no receipt"


def test_cv_alone_ignores_placeholder_words_inside_other_words(tmp_path):
    root = _sandbox(tmp_path)
    cv = _cv(root / "documents" / "cv.docx", extra=("Integrated Todoist and Lorem Ipsum Ltd",))
    r = _gate(root, "--cv", str(cv))
    assert "'todo'" not in r.stdout


def test_missing_cv_is_an_error_not_skipped(tmp_path):
    root = _sandbox(tmp_path)
    r = _gate(root, "--cv", str(root / "documents" / "nope.docx"))
    assert r.returncode == 2 and "CV not found" in r.stdout


STUB = """#!/bin/sh
company=$(printf '%s\\n' "$1" | sed -n 's/^Company: //p' | head -n1)
role=$(printf '%s\\n' "$1" | sed -n 's/^Role: //p' | head -n1)
python3 tools/record_submission.py --company "$company" --role "$role" --ats x --url u \\
  --cv "$FIXED_CV" --status SUBMITTED \\
  --evidence "Thanks for applying to $company, we have received your application" >> "$CALLS" 2>&1
echo "STATUS $company | $role | SUBMITTED | recorder exit $?"
"""


def _light_run(tmp_path, root, cv):
    (root / "state" / "queue.tsv").write_text("Acme\tEngineer\thttps://example.test/1\tcv\tats\tk1\n")
    agent = tmp_path / "stub-agent"
    agent.write_text(STUB)
    agent.chmod(agent.stat().st_mode | stat.S_IXUSR)
    # REVIEW=1 only so no browser is started; LIGHT still builds the fixed-CV prompt.
    env = dict(_env(root), ROOT=str(root), LIGHT="1", FIXED_CV=os.path.relpath(cv, root),
               REVIEW="1", PARALLEL="1", RETRY_LIMIT="0", AGENT=str(agent),
               CALLS=str(tmp_path / "calls"))
    return subprocess.run(["bash", os.path.join(ROOT, "tools", "run_queue.sh")],
                          env=env, capture_output=True, text=True, timeout=60)


def test_light_run_gates_the_fixed_cv_and_records_without_force(tmp_path):
    root = _sandbox(tmp_path)
    cv = _cv(root / "documents" / "fixed.docx")
    r = _light_run(tmp_path, root, cv)
    assert r.returncode == 0, r.stderr
    log = (root / "state" / "logs" / "run_queue.out").read_text()
    assert "recorder exit 0" in log, (tmp_path / "calls").read_text()
    with open(root / "state" / "submissions.csv", newline="") as fh:
        rows = list(csv.DictReader(fh))
    assert [(x["company"], x["status"]) for x in rows] == [("Acme", "SUBMITTED")]


def test_light_run_stops_before_anything_when_the_fixed_cv_fails(tmp_path):
    root = _sandbox(tmp_path)
    cv = _cv(root / "documents" / "fixed.docx", name="YOUR NAME")
    r = _light_run(tmp_path, root, cv)
    assert r.returncode == 1
    assert "failed the pre-submit gate" in r.stderr
    assert not (tmp_path / "calls").exists(), "no task may run with a failing CV"
