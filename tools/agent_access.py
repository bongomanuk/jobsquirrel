#!/usr/bin/env python3
"""Agent-agnostic permission gate for the Jobsquirrel pipeline.

Any agent (opencode, Claude Code, Cursor, a custom CLI) can call this instead of
touching paths outside the repo, writing files, or running shell commands. It
consults the operator's policy (config/agent-permissions.json) and, when the
policy is "ask", asks the dashboard to prompt the human, blocking until they
answer (or the request times out).

    python3 tools/agent_access.py check <category> <detail>
    python3 tools/agent_access.py read   <path>          # prints the file on allow
    python3 tools/agent_access.py write  <path>          # writes stdin on allow
    python3 tools/agent_access.py run -- <cmd> [args...] # runs it on allow

Categories: read_repo, read_external, write_repo, write_external, bash, web, task.
Exit codes: 0 allowed, 3 denied, 2 error/usage.
"""
import json
import os
import subprocess
import sys
import urllib.request

ROOT = os.path.realpath(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PERMS = os.path.join(ROOT, "config", "agent-permissions.json")
DEFAULTS = {"read_repo": "allow", "write_repo": "allow", "read_external": "ask",
            "write_external": "ask", "bash": "ask", "web": "allow", "task": "ask"}


def policy():
    try:
        with open(PERMS, encoding="utf-8") as fh:
            return {**DEFAULTS, **json.load(fh)}
    except (OSError, ValueError):
        return dict(DEFAULTS)


def ask_dashboard(category, detail):
    url, tok = os.environ.get("JOBSQUIRREL_URL"), os.environ.get("JOBSQUIRREL_TOKEN")
    if not url or not tok:
        return "deny"                                   # no dashboard to ask -> fail closed
    req = urllib.request.Request(
        url.rstrip("/") + "/api/agent/permission",
        data=json.dumps({"category": category, "detail": detail}).encode(),
        headers={"Content-Type": "application/json", "X-Session": tok}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=320) as r:
            return json.load(r).get("decision", "deny")
    except Exception:
        return "deny"


def decide(category, detail):
    pol = policy().get(category, "ask")
    if pol == "ask":
        pol = ask_dashboard(category, detail)
    return pol


def in_repo(path):
    return os.path.realpath(path).startswith(ROOT + os.sep)


def main(argv):
    if len(argv) < 2:
        print(__doc__, file=sys.stderr)
        return 2
    cmd = argv[1]
    if cmd == "check" and len(argv) >= 4:
        cat, detail = argv[2], argv[3]
    elif cmd in ("read", "write") and len(argv) >= 3:
        path = argv[2]
        cat = ("read_repo" if cmd == "read" else "write_repo") if in_repo(path) else \
              ("read_external" if cmd == "read" else "write_external")
        detail = f"{cmd} {path}"
    elif cmd == "run":
        rest = argv[3:] if argv[2] == "--" else argv[2:]
        cat, detail = "bash", "run " + " ".join(rest)
    else:
        print(__doc__, file=sys.stderr)
        return 2

    decision = decide(cat, detail)
    print(f"[agent_access] {cat}: {detail} -> {decision}", file=sys.stderr)
    if decision != "allow":
        return 3

    if cmd == "read":
        with open(argv[2], encoding="utf-8", errors="ignore") as fh:
            sys.stdout.write(fh.read())
    elif cmd == "write":
        os.makedirs(os.path.dirname(os.path.realpath(argv[2])), exist_ok=True)
        with open(argv[2], "wb") as fh:
            fh.write(sys.stdin.buffer.read())
        print(f"wrote {argv[2]}")
    elif cmd == "run":
        return subprocess.call(rest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
