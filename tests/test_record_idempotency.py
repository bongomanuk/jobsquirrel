"""record_submission.py is idempotent: an identical re-run does not double-record."""
import csv
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REC = os.path.join(ROOT, "tools", "record_submission.py")

ARGS = ["--company", "Acme", "--role", "Engineer", "--status", "BLOCKED",
        "--evidence", "captcha wall at submit"]


def _env(tmp):
    return dict(os.environ,
                SUBMISSIONS_CSV=str(tmp / "subs.csv"),
                SUBMISSIONS_DIR=str(tmp / "snap"),
                APPLICATIONS_CSV=str(tmp / "apps.csv"),
                APPLICATIONS_MD=str(tmp / "apps.md"),
                GATE_ENFORCE="0")


def _record(env, *args):
    return subprocess.run([sys.executable, REC, *args], env=env, capture_output=True, text=True)


def _rows(tmp):
    with open(tmp / "subs.csv", newline="") as fh:
        return list(csv.DictReader(fh))


def test_identical_rerun_is_a_noop(tmp_path):
    env = _env(tmp_path)
    assert _record(env, *ARGS).returncode == 0
    second = _record(env, *ARGS)
    assert second.returncode == 0
    assert len(_rows(tmp_path)) == 1
    assert "already recorded" in second.stdout


def test_force_records_again(tmp_path):
    env = _env(tmp_path)
    _record(env, *ARGS)
    _record(env, *ARGS, "--force")
    assert len(_rows(tmp_path)) == 2
