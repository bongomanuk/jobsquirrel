#!/usr/bin/env python3
"""Human-approval gate for risky actions (sending email, deleting mail, ...).

Policy: risky or irreversible actions require an explicit human approval each
time they are about to happen. Two ways to approve:

  - interactive (a terminal): a "Approve ...? [y/N]" prompt;
  - non-interactive: set APPROVE_<TOKEN> = 1 for that one command
    (e.g. APPROVE_SEND_EMAIL=1 ...), which is itself a deliberate act.

Every approval is appended to state/approvals.log. Callers must refuse the
action when `approved(...)` returns False.

Usage:
    import approval
    if not approval.approved("send email to alice@x", "SEND-EMAIL"):
        sys.exit("refused: not approved")
"""
import json
import os
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG = os.environ.get("APPROVALS_LOG", os.path.join(ROOT, "state", "approvals.log"))


def _record(purpose, how):
    try:
        os.makedirs(os.path.dirname(LOG), exist_ok=True)
        with open(LOG, "a", encoding="utf-8") as fh:
            fh.write(f"{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}\t{how}\t{purpose}\n")
    except OSError:
        pass


def _ask_dashboard(purpose, token, timeout=320):
    """Ask the running dashboard to show the operator a yes/no prompt; blocks until they answer."""
    url, sess = os.environ.get("JOBSQUIRREL_URL"), os.environ.get("JOBSQUIRREL_TOKEN")
    if not url or not sess:
        return None
    req = urllib.request.Request(
        url.rstrip("/") + "/api/approval/ask",
        data=json.dumps({"purpose": purpose, "token": token}).encode(),
        headers={"Content-Type": "application/json", "X-Session": sess}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.load(resp).get("decision")
    except Exception:
        return None


def approved(purpose, token, prompt=True):
    """True only with an explicit approval; records it. Never approves silently."""
    env_key = "APPROVE_" + "".join(c if c.isalnum() else "_" for c in token).upper()
    if os.environ.get(env_key, "").strip().lower() in ("1", "yes", "true", "y", "on"):
        _record(purpose, f"env:{env_key}")
        return True
    if prompt and sys.stdin.isatty():
        try:
            ans = input(f"Approve {purpose}? [y/N] ").strip().lower()
        except EOFError:
            ans = ""
        if ans in ("y", "yes"):
            _record(purpose, "prompt")
            return True
        _record(purpose, "REFUSED")
        return False
    decision = _ask_dashboard(purpose, token)
    if decision == "allow":
        _record(purpose, "dashboard")
        return True
    _record(purpose, "REFUSED" if decision else "REFUSED (no dashboard)")
    return False
