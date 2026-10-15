#!/usr/bin/env python3
"""Tiny status channel for the human-assist run.

The assist agent records what it is doing here so the focused viewer can show ONLY
the human challenges.

  python3 tools/human_status.py set --company X --role Y --state filling|awaiting|done --note "..."
  python3 tools/human_status.py get
"""
import argparse
import json
import os
import subprocess
import sys
import time

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
DIR = os.path.join(ROOT, "state", "human")
CUR = os.path.join(DIR, "current.json")
HIST = os.path.join(DIR, "history.jsonl")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["set", "get"])
    ap.add_argument("--company", default="")
    ap.add_argument("--role", default="")
    ap.add_argument("--state", default="")
    ap.add_argument("--note", default="")
    a = ap.parse_args()
    os.makedirs(DIR, exist_ok=True)
    if a.cmd == "get":
        try:
            print(open(CUR).read())
        except OSError:
            print("{}")
        return
    rec = {"company": a.company, "role": a.role, "state": a.state,
           "note": a.note, "ts": time.strftime("%Y-%m-%dT%H:%M:%S")}
    with open(CUR, "w") as f:
        json.dump(rec, f)
    # Ping the user's desktop only when their action is actually required, so the
    # ONLY thing that ever interrupts them is a human challenge.
    if a.state == "awaiting":
        try:
            subprocess.run(["notify-send", "-u", "critical", "-a", "job-search",
                            f"CAPTCHA: {a.company} — {a.role}",
                            a.note or "solve the challenge in the visible browser"],
                           timeout=5)
        except Exception:
            pass
    with open(HIST, "a") as f:
        f.write(json.dumps(rec) + "\n")
    print(f"{a.state}: {a.company} — {a.role}")


if __name__ == "__main__":
    main()
