#!/usr/bin/env python3
"""Put the pipeline browser on screen so the human can sign in.

A headless Camoufox cannot show a login form, so a "please sign in" notification
is useless on its own: there is nothing to click. This replaces the headless
server on the SAME port and profile with a visible one, navigates to the page
that needs the human, and waits until they confirm.

  python3 tools/open_for_human.py --url https://accounts.google.com/... \
      --port 9879 --reason "Google sign-in" --detail "Acme / Engineer"

What happens:
  1. The headless server on --port is stopped (it holds the profile lock).
  2. A headful Camoufox starts on the same port with the SAME persistent profile,
     so the session survives: a sign-in done once is not asked for again.
  3. The page is opened, and the dashboard shows a blocking "done" dialog
     (tools/ask_human.py --mode approve). Press it when you have signed in.
  4. The visible server STAYS up on that port, so the agent's next command lands
     in the browser you just used.

Use --no-wait to only open the window (no dialog). Exit 0 when the human
confirmed, 2 on timeout, 3 when there is no display.
"""
from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
import urllib.request

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
BASE = os.environ.get("CAMOUFOX_PROFILE_DIR", os.path.expanduser("~/.config/job-search/profiles"))
SERVER = os.path.join(ROOT, "tools", "camoufox_server.py")


def health(port: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=2) as r:
            return r.status == 200
    except Exception:
        return False


def stop_server(port: int) -> None:
    """Stop whatever server owns this port, so the profile lock is free."""
    out = subprocess.run(["ss", "-ltnp"], capture_output=True, text=True).stdout
    for line in out.splitlines():
        if f":{port} " in line and "pid=" in line:
            pid = line.split("pid=")[1].split(",")[0]
            try:
                os.kill(int(pid), signal.SIGTERM)
            except Exception:
                pass
    for _ in range(40):
        if not health(port):
            return
        time.sleep(0.25)


def start_headful(port: int, profile: str) -> subprocess.Popen:
    os.makedirs(profile, exist_ok=True)
    log = open(os.path.join(ROOT, "state", "logs", f"camoufox_headful_{port}.log"), "a")
    p = subprocess.Popen([sys.executable, SERVER, "--port", str(port),
                          "--headful", "--profile", profile],
                         cwd=ROOT, stdout=log, stderr=log, start_new_session=True)
    for _ in range(60):
        if health(port):
            return p
        time.sleep(0.5)
    raise RuntimeError(f"headful server on {port} did not start (see state/logs/camoufox_headful_{port}.log)")


def nav(port: int, url: str) -> dict:
    payload = json.dumps({"cmd": "nav", "url": url}).encode()
    req = urllib.request.Request(f"http://127.0.0.1:{port}/cmd", data=payload,
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode())


def main() -> int:
    ap = argparse.ArgumentParser(description="Open the pipeline browser on screen for a human step.")
    ap.add_argument("--url", required=True)
    ap.add_argument("--port", type=int, default=int(os.environ.get("CAMOUFOX_PORT", "9872")))
    ap.add_argument("--profile", default="", help="profile dir (default: the one for this port)")
    ap.add_argument("--reason", default="Sign-in needed")
    ap.add_argument("--detail", default="")
    ap.add_argument("--timeout", type=float, default=900)
    ap.add_argument("--no-wait", action="store_true", help="open the window and return")
    a = ap.parse_args()

    if not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"):
        print(json.dumps({"ok": False, "error": "no display: run this on the desktop, not over ssh"}))
        return 3
    profile = a.profile or os.path.join(BASE, f"work-{a.port}")
    try:
        stop_server(a.port)
        start_headful(a.port, profile)
        page = nav(a.port, a.url)
    except Exception as e:
        print(json.dumps({"ok": False, "error": f"{type(e).__name__}: {e}"}))
        return 1

    print(json.dumps({"ok": True, "port": a.port, "profile": profile,
                      "url": page.get("url"), "title": page.get("title"),
                      "window": "visible Camoufox window"},
                     separators=(",", ":")), flush=True)
    if a.no_wait:
        return 0

    # Block until the human says they are done, in the same dashboard dialog the
    # 2FA handoff uses.
    r = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "ask_human.py"),
                        "--mode", "approve", "--reason", a.reason,
                        "--detail", a.detail or f"sign in in the visible Camoufox window (port {a.port}), then press done",
                        "--timeout", str(a.timeout)],
                       capture_output=True, text=True)
    out = (r.stdout or "").strip().splitlines()
    try:
        answer = json.loads(out[-1]) if out else {}
    except Exception:
        answer = {}
    if not answer.get("ok"):
        print(json.dumps({"ok": False, "timeout": True, "port": a.port}))
        return 2
    print(json.dumps({"ok": True, "confirmed": True, "port": a.port, "profile": profile}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
