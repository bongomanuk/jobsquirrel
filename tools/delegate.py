#!/usr/bin/env python3
"""Hand a task to a background agent subagent and return immediately.

The dashboard chat agent uses this for work that should not block the
conversation (preparing documents, a queue run, reconciling mail, research).
The subagent runs detached, logs to state/logs/delegated-<id>.log and appears in
the dashboard's Activity pane.

Usage:
  python3 tools/delegate.py --title "Scan new roles" --prompt "Find ..."
  python3 tools/delegate.py --title "Reconcile" --prompt-file /tmp/task.md

It talks to the running dashboard (JOBSQUIRREL_URL, JOBSQUIRREL_TOKEN, both
exported to the chat agent). Exit codes: 0 started, 1 failed.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request


def main() -> int:
    ap = argparse.ArgumentParser(description="Start a background agent subagent.")
    ap.add_argument("--title", default="", help="short label for the Activity pane")
    ap.add_argument("--prompt", default="", help="the task to run")
    ap.add_argument("--prompt-file", default="", help="read the task from a file instead")
    args = ap.parse_args()

    prompt = args.prompt
    if args.prompt_file:
        try:
            prompt = open(args.prompt_file, encoding="utf-8").read()
        except OSError as exc:
            print(f"delegate: cannot read {args.prompt_file}: {exc}", file=sys.stderr)
            return 1
    prompt = (prompt or "").strip()
    if not prompt:
        print("delegate: give --prompt or --prompt-file", file=sys.stderr)
        return 1

    url = (os.environ.get("JOBSQUIRREL_URL") or "http://127.0.0.1:8765").rstrip("/")
    token = os.environ.get("JOBSQUIRREL_TOKEN", "")
    body = json.dumps({"title": args.title, "prompt": prompt}).encode()
    req = urllib.request.Request(
        url + "/api/delegate", data=body, method="POST",
        headers={"Content-Type": "application/json", "X-Session": token})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            data = json.load(r)
    except (urllib.error.URLError, OSError, ValueError) as exc:
        print(f"delegate: dashboard not reachable at {url}: {exc}", file=sys.stderr)
        return 1
    if data.get("error"):
        print(f"delegate: {data['error']}", file=sys.stderr)
        return 1
    print(json.dumps(data, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
