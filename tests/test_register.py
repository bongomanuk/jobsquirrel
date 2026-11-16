import os
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _register(tmp_path, *args):
    env = dict(os.environ, APPLICATIONS_CSV=str(tmp_path / "applications.csv"),
               APPLICATIONS_MD=str(tmp_path / "applications-register.md"))
    return subprocess.run([sys.executable, "tools/register.py", *args], cwd=ROOT, env=env,
                          capture_output=True, text=True)


def test_row_without_set_is_refused_not_silently_listed(tmp_path):
    r = _register(tmp_path, "--company", "Acme", "--role", "Eng",
                  "--status", "BLOCKED", "--notes", "captcha: hCaptcha")
    assert r.returncode == 2
    assert "need --set" in r.stderr
    assert not (tmp_path / "applications.csv").exists()


def test_set_records_the_row(tmp_path):
    r = _register(tmp_path, "--set", "--company", "Acme", "--role", "Eng",
                  "--status", "BLOCKED", "--notes", "captcha: hCaptcha")
    assert r.returncode == 0, r.stderr
    assert "BLOCKED" in (tmp_path / "applications.csv").read_text()


def test_status_alone_still_lists(tmp_path):
    _register(tmp_path, "--set", "--company", "Acme", "--role", "Eng", "--status", "BLOCKED")
    r = _register(tmp_path, "--status", "BLOCKED")
    assert r.returncode == 0 and "Acme" in r.stdout


def _temp_register(tmp_path, monkeypatch):
    import register as R
    monkeypatch.setattr(R, "CSV_PATH", str(tmp_path / "applications.csv"))
    monkeypatch.setattr(R, "MD_PATH", str(tmp_path / "applications-register.md"))
    monkeypatch.setattr(R, "LOCK_PATH", R.CSV_PATH + ".lock")
    monkeypatch.setattr(R, "COUNTS_PATH", str(tmp_path / "counts.md"))
    return R


def _row(R, company="Acme", role="Eng"):
    return [r for r in R.load() if r["company"] == company and r["role"] == role][0]


def test_a_passive_waiting_action_is_not_stored(tmp_path, monkeypatch):
    R = _temp_register(tmp_path, monkeypatch)
    R.upsert("Acme", "Eng", "MANUAL", notes="applied",
             action="await a reply from careers@acme.com")
    assert _row(R)["action"] == ""


def test_recording_a_reply_clears_the_follow_up_flag(tmp_path, monkeypatch):
    R = _temp_register(tmp_path, monkeypatch)
    R.upsert("Acme", "Eng", "MANUAL", notes="invited",
             action="Reply to Ray — interview")
    R.log_outbound("Acme", "Eng", "ray@acme.com", "Re: interview", "mid-1")
    assert _row(R)["action"] == ""


def test_an_unrelated_outbound_keeps_an_unrelated_flag(tmp_path, monkeypatch):
    R = _temp_register(tmp_path, monkeypatch)
    R.upsert("Acme", "Eng", "MANUAL", notes="invited", action="book a time for Friday")
    R.log_outbound("Acme", "Eng", "news@acme.com", "Company newsletter", "mid-2")
    assert _row(R)["action"] == "book a time for Friday"


def test_a_live_application_cannot_be_downgraded_to_prepared(tmp_path, monkeypatch):
    R = _temp_register(tmp_path, monkeypatch)
    monkeypatch.setattr(R, "_jd_guard", lambda *a, **k: None)
    monkeypatch.setattr(R, "_submitted_guard", lambda *a, **k: None)
    R.upsert("Acme", "Eng", "SUBMITTED", notes="applied")
    with pytest.raises(ValueError, match="refusing to downgrade a live SUBMITTED"):
        R.upsert("Acme", "Eng", "PREPARED", notes="review")
    R.upsert("Acme", "Eng", "PREPARED", notes="repost: earlier SUBMITTED", repost=True)
    assert _row(R)["status"] == "PREPARED"
    assert "earlier SUBMITTED" in _row(R)["notes"]
