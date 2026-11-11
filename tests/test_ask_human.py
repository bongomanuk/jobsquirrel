"""The 2FA handoff: the agent asks the human for a code and carries on.

Two halves are tested here:
  * the dashboard's ask_request -> permission_pending -> permission_decide
    round-trip (the modal the human types into), and
  * tools/ask_human.py, the CLI the runner calls, against a stub dashboard.

The point of the feature is that a LinkedIn App Challenge / SMS code stops the
agent and asks, instead of dropping the role into BLOCKED.
"""
import json
import os
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))

import dashboard as D

ASK = os.path.join(ROOT, "tools", "ask_human.py")


def _wait_pending(question, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        for p in D.permission_pending():
            if p["category"] == question:
                return p
        time.sleep(0.02)
    raise AssertionError(f"no pending ask for {question!r}")


def test_ask_round_trip_returns_the_typed_answer():
    q = "LinkedIn sign-in: code needed"
    box = {}
    t = threading.Thread(target=lambda: box.update(
        D.ask_request(q, "Acme / Engineer", timeout=10)), daemon=True)
    t.start()
    p = _wait_pending(q)
    assert p["ask"] is True
    assert p["rememberable"] is False          # never remembered, never reused
    assert p["detail"] == "Acme / Engineer"
    D.permission_decide(p["id"], "allow", answer="482913")
    t.join(5)
    assert box["answer"] == "482913"
    assert box["timeout"] is False


def test_ask_with_no_answer_times_out_rather_than_hanging():
    out = D.ask_request("device check", timeout=0.2)
    assert out["answer"] == ""
    assert out["timeout"] is True


def test_cancelling_the_ask_returns_no_answer():
    q = "device check cancelled"
    box = {}
    t = threading.Thread(target=lambda: box.update(D.ask_request(q, timeout=10)), daemon=True)
    t.start()
    p = _wait_pending(q)
    D.permission_decide(p["id"], "deny")       # Cancel in the modal
    t.join(5)
    assert box["answer"] == ""
    assert box["timeout"] is True


class _Stub(BaseHTTPRequestHandler):
    answer = "771234"

    def log_message(self, *a):
        pass

    def do_GET(self):
        # The dashboard page carries the session token in a data attribute; that
        # is how a terminal-launched runner discovers the dialog endpoint.
        body = b'<html><body data-session-token="tok123">dashboard</body></html>'
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        self.rfile.read(n)
        body = json.dumps({"answer": self.answer, "timeout": False}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture()
def stub_dashboard():
    srv = HTTPServer(("127.0.0.1", 0), _Stub)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{srv.server_port}"
    srv.shutdown()


def test_cli_returns_the_code_as_machine_readable_json(stub_dashboard):
    env = dict(os.environ, JOBSQUIRREL_URL=stub_dashboard, JOBSQUIRREL_TOKEN="t")
    r = subprocess.run([sys.executable, ASK, "--reason", "LinkedIn sign-in: code needed",
                        "--detail", "Acme / Engineer", "--timeout", "5"],
                       capture_output=True, text=True, env=env, timeout=30)
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout.strip().splitlines()[-1])
    assert out["ok"] is True and out["answer"] == "771234"


def test_cli_discovers_a_local_dashboard_without_env(stub_dashboard):
    """A runner started from a terminal has no JOBSQUIRREL_* env: it finds the
    dashboard on its port and scrapes the session token from the page."""
    port = stub_dashboard.rsplit(":", 1)[1]
    env = {k: v for k, v in os.environ.items()
           if k not in ("JOBSQUIRREL_URL", "JOBSQUIRREL_TOKEN")}
    env["JOBSQUIRREL_PORT"] = port
    r = subprocess.run([sys.executable, ASK, "--reason", "code needed", "--timeout", "5"],
                       capture_output=True, text=True, env=env, timeout=30)
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout.strip().splitlines()[-1])
    assert out["ok"] is True and out["answer"] == "771234"


def test_cli_without_a_dashboard_or_terminal_fails_softly():
    env = {k: v for k, v in os.environ.items()
           if k not in ("JOBSQUIRREL_URL", "JOBSQUIRREL_TOKEN")}
    env["JOBSQUIRREL_PORT"] = "1"              # nothing listens there
    r = subprocess.run([sys.executable, ASK, "--reason", "code needed", "--timeout", "1"],
                       capture_output=True, text=True, env=env, timeout=30)
    assert r.returncode == 2
    out = json.loads(r.stdout.strip().splitlines()[-1])
    assert out["ok"] is False and out["timeout"] is True
