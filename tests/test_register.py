import os
import subprocess
import sys

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
