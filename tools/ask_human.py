#!/usr/bin/env python3
"""Ask the human for something only they have: a 2FA/SMS code, or an approval.

This is the handoff the runner uses when a sign-in is stopped by a checkpoint it
must not solve: LinkedIn's "App Challenge" (tap Yes in the app), an SMS code, a
device-verification prompt. The pipeline does NOT guess, reuse or work around
these; it asks.

  python3 tools/ask_human.py --reason "LinkedIn 2FA: enter the 6-digit code sent to your phone" --timeout 600

Behaviour, in order:
  1. Pings the desktop and marks state/human/current.json as "awaiting" (the same
     channel the CAPTCHA handoff uses, so the dashboard and watch_human.py show it).
  2. If the dashboard is running (JOBSQUIRREL_URL + JOBSQUIRREL_TOKEN in the run
     environment), posts /api/agent/ask and blocks until the human answers. The
     answer appears in an input in the approval modal.
  3. Otherwise, if stdin is a terminal, prompts for it there.
  4. Otherwise prints a timeout result and exits 2.

Exit codes: 0 answer provided, 2 no answer (timeout / no channel / cancelled).
On success the ONLY line on stdout is JSON: {"ok": true, "answer": "..."} so the
agent can read the code without a transcript of prose. A cancelled/empty answer
is {"ok": false, "timeout": true}.

Never pass a code back through the shell history: the runner tells the agent to
read it from the JSON and fill the field, not to echo it.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.request

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))


def notify(reason: str, detail: str) -> None:
    """Desktop ping + the human-status channel, so it is visible without a terminal.

    One ping per question per 120s: several workers hitting the same checkpoint
    must not turn into a stack of notifications the human has to dismiss.
    """
    marker = os.path.join(ROOT, "state", "human", "last-notify.json")
    now = time.time()
    try:
        prev = json.load(open(marker))
    except Exception:
        prev = {}
    if prev.get("reason") == reason and now - float(prev.get("ts") or 0) < 120:
        return
    try:
        os.makedirs(os.path.dirname(marker), exist_ok=True)
        json.dump({"reason": reason, "ts": now}, open(marker, "w"))
    except Exception:
        pass
    try:
        subprocess.run([sys.executable, os.path.join(ROOT, "tools", "human_status.py"),
                        "set", "--company", "sign-in", "--role", reason[:80],
                        "--state", "awaiting", "--note", detail or reason],
                       capture_output=True, timeout=10)
    except Exception:
        pass
    try:
        subprocess.run(["notify-send", "-u", "critical", "-a", "job-search",
                        "Action needed: " + reason[:80],
                        detail or "Enter the code in the dashboard"],
                       capture_output=True, timeout=5)
    except Exception:
        pass


def _discover_dashboard():
    """Find the running dashboard and its session token.

    A runner started from the dashboard inherits JOBSQUIRREL_URL/TOKEN. One
    started from a terminal does not, and still needs the dialog - so read the
    token from the local page. It is the same secret the browser already has, on
    loopback only, and nothing is written to disk.
    """
    url = os.environ.get("JOBSQUIRREL_URL", "").rstrip("/")
    tok = os.environ.get("JOBSQUIRREL_TOKEN", "")
    if url and tok:
        return url, tok
    port = os.environ.get("JOBSQUIRREL_PORT", "8765")
    for candidate in ([url] if url else []) + [f"http://127.0.0.1:{port}"]:
        try:
            with urllib.request.urlopen(candidate + "/", timeout=3) as r:
                html = r.read().decode("utf-8", "ignore")
            m = re.search(r'data-session-token="([^"]+)"', html)
            if m:
                return candidate, m.group(1)
        except Exception:
            continue
    return "", ""


def ask_dashboard(reason: str, detail: str, timeout: float, mode: str = "code") -> dict:
    url, tok = _discover_dashboard()
    if not url or not tok:
        return {"ok": False, "no_dashboard": True}
    body = json.dumps({"question": reason, "detail": detail,
                       "timeout": timeout, "mode": mode}).encode()
    last = ""
    for attempt in (1, 2):
        req = urllib.request.Request(url + "/api/agent/ask", data=body, method="POST",
                                     headers={"Content-Type": "application/json",
                                              "X-Session": tok})
        try:
            with urllib.request.urlopen(req, timeout=timeout + 20) as r:
                out = json.loads(r.read().decode() or "{}")
            answer = str(out.get("answer") or "").strip()
            return {"ok": bool(answer), "answer": answer,
                    "timeout": bool(out.get("timeout")) or not answer}
        except Exception as e:
            # A dropped request must not crash the task: retry once, then report
            # a clean timeout so the agent records BLOCKED instead of dying here.
            last = f"{type(e).__name__}: {e}"
            if attempt == 1:
                time.sleep(1)
    return {"ok": False, "timeout": True, "error": f"dashboard ask failed: {last}"}


def ask_tty(reason: str, detail: str, mode: str = "code") -> dict:
    if not sys.stdin.isatty():
        return {"ok": False, "no_tty": True}
    print(f"\n[ACTION NEEDED] {reason}", file=sys.stderr)
    if detail:
        print(f"  {detail}", file=sys.stderr)
    try:
        prompt = ("  approve it in your phone/app, then type 'done' (blank to cancel): "
                  if mode == "approve" else
                  "  enter the code (or 'done'), blank to cancel: ")
        answer = input(prompt).strip()
    except (EOFError, KeyboardInterrupt):
        answer = ""
    return {"ok": bool(answer), "answer": answer, "timeout": not answer}


def main() -> int:
    ap = argparse.ArgumentParser(description="Ask the human for a 2FA code / approval.")
    ap.add_argument("--reason", required=True, help="one line: what is blocked and what is needed")
    ap.add_argument("--detail", default="", help="context shown under the reason")
    ap.add_argument("--timeout", type=float, default=600, help="seconds to wait (default 600)")
    ap.add_argument("--mode", choices=["code", "approve"], default="code",
                    help="code: type a texted/emailed code; approve: the human taps "
                         "Yes in their own app (LinkedIn 'was this you?')")
    a = ap.parse_args()

    # The agent must not be able to fake an answer: it may only ask.
    notify(a.reason, a.detail)
    result = ask_dashboard(a.reason, a.detail, a.timeout, a.mode)
    if result.get("no_dashboard"):
        result = ask_tty(a.reason, a.detail, a.mode)
        if result.get("no_tty"):
            result = {"ok": False, "timeout": True,
                      "error": "no dashboard and no terminal to ask on"}
    print(json.dumps(result, separators=(",", ":")))
    return 0 if result.get("ok") else 2


if __name__ == "__main__":
    sys.exit(main())
