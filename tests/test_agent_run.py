"""agent_run.sh resolves the agent to run, and reports it with --which.

No agent is actually launched here; these exercise the resolver only, using a
throwaway PATH so a real opencode/claude on the machine is never picked up.
"""
import os
import shutil
import stat
import subprocess

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AGENT_RUN = os.path.join(ROOT, "tools", "agent_run.sh")
# Resolve bash by absolute path: the child PATH is deliberately minimal, so the
# OS could not find `bash` for the child.
BASH = shutil.which("bash") or "/bin/bash"


def _fake_bin(tmp_path, name):
    p = tmp_path / name
    p.write_text("#!/bin/sh\nexit 0\n")
    p.chmod(p.stat().st_mode | stat.S_IXUSR)
    return p


def _which(tmp_path, agent=None, extra_path=""):
    env = dict(os.environ)
    env.pop("AGENT", None)
    env["PATH"] = str(tmp_path) + os.pathsep + extra_path
    if agent is not None:
        env["AGENT"] = agent
    return subprocess.run([BASH, AGENT_RUN, "--which"],
                          capture_output=True, text=True, env=env)


def test_which_reports_configured_agent_and_its_flags(tmp_path):
    _fake_bin(tmp_path, "mycli")
    r = _which(tmp_path, agent="mycli run --fast")
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "mycli run --fast"


def test_which_defaults_to_opencode_when_installed(tmp_path):
    _fake_bin(tmp_path, "opencode")
    r = _which(tmp_path)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "opencode"


def test_which_falls_back_to_claude(tmp_path):
    _fake_bin(tmp_path, "claude")
    r = _which(tmp_path)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "claude"


def test_which_errors_when_configured_agent_is_missing(tmp_path):
    r = _which(tmp_path, agent="definitely-not-installed-xyz")
    assert r.returncode == 127
    assert "is not installed" in r.stderr
