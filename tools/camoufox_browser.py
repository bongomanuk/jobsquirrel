#!/usr/bin/env python3
"""Agent-facing CLI for the Camoufox pipeline browser (Camoufox/Firefox only — no Chromium).

The command surface the agent prompts use:
  status | nav <url> | snap [path] | click <ref|selector> [--force] |
  fill <sel> <text> | type <sel> <text> | select <sel> <value> |
  pick <option text> [open-selector] | fillmap '<json steps>' | press <key> [sel] |
  check <sel> | value <sel> | eval <js> | wait <ms> | upload <sel> <path> | headers

Custom ATS widgets (Workday, Greenhouse react-select, ...):
  - use `pick` to choose a listbox option: synthetic JS clicks are ignored.
  - use `press` for real key events (Enter commits type-aheads).
  - `click` falls back to a forced click automatically when an overlay blocks it.

All commands are forwarded to tools/camoufox_server.py over HTTP.

Usage:
  python3 tools/camoufox_browser.py --server http://127.0.0.1:9872 nav https://...
  python3 tools/camoufox_browser.py --server http://127.0.0.1:9872 fill '#email' 'x@y.z'
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request

DEFAULT_SERVER = "http://127.0.0.1:9872"


def post(server: str, payload: dict, timeout: float = 45.0) -> dict:
    req = urllib.request.Request(
        f"{server.rstrip('/')}/cmd",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read().decode())
        except Exception:
            return {"ok": False, "error": f"HTTP {e.code}"}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


def main() -> int:
    ap = argparse.ArgumentParser(description="Camoufox pipeline browser CLI")
    ap.add_argument("--server", default=DEFAULT_SERVER)
    ap.add_argument("cmd", help="status|nav|snap|click|fill|type|select|pick|fillmap|press|check|value|eval|wait|upload|download|headers")
    ap.add_argument("args", nargs="*", help="command arguments")
    ap.add_argument("--force", action="store_true", help="click: skip actionability checks")
    ns = ap.parse_args()

    cmd = ns.cmd.lower()
    a = ns.args
    payload: dict = {"cmd": cmd}

    if cmd == "status" or cmd == "headers":
        pass
    elif cmd == "nav":
        if not a:
            print("usage: nav <url>", file=sys.stderr)
            return 1
        payload["url"] = a[0]
    elif cmd == "snap":
        if a:
            payload["path"] = a[0]
    elif cmd == "click":
        if not a:
            print("usage: click <ref|selector>", file=sys.stderr)
            return 1
        payload["target"] = a[0]
        if ns.force:
            payload["force"] = True
    elif cmd == "fill":
        if len(a) < 2:
            print("usage: fill <selector> <text>", file=sys.stderr)
            return 1
        payload["selector"], payload["text"] = a[0], " ".join(a[1:])
    elif cmd == "type":
        if len(a) < 2:
            print("usage: type <selector> <text>", file=sys.stderr)
            return 1
        payload["selector"], payload["text"] = a[0], " ".join(a[1:])
    elif cmd == "select":
        if len(a) < 2:
            print("usage: select <selector> <value>", file=sys.stderr)
            return 1
        payload["selector"], payload["value"] = a[0], " ".join(a[1:])
    elif cmd == "press":
        if not a:
            print("usage: press <key> [selector]", file=sys.stderr)
            return 1
        payload["key"] = a[0]
        if len(a) > 1:
            payload["selector"] = a[1]
    elif cmd == "mouse":
        if len(a) < 2:
            print("usage: mouse <x> <y>", file=sys.stderr)
            return 1
        payload["x"], payload["y"] = int(a[0]), int(a[1])
    elif cmd == "pick":
        if not a:
            print("usage: pick <option text> [open-selector]", file=sys.stderr)
            return 1
        payload["text"] = a[0]
        if len(a) > 1:
            payload["open"] = a[1]
    elif cmd == "fillmap":
        if not a:
            print("usage: fillmap '<json steps>'", file=sys.stderr)
            return 1
        try:
            payload["steps"] = json.loads(" ".join(a))
        except Exception as e:
            print(f"fillmap: invalid JSON: {e}", file=sys.stderr)
            return 1
    elif cmd == "check":
        if not a:
            print("usage: check <selector>", file=sys.stderr)
            return 1
        payload["selector"] = a[0]
    elif cmd == "value":
        if not a:
            print("usage: value <selector>", file=sys.stderr)
            return 1
        payload["selector"] = a[0]
    elif cmd == "eval":
        if not a:
            print("usage: eval <js>", file=sys.stderr)
            return 1
        payload["js"] = " ".join(a)
    elif cmd == "wait":
        if not a:
            print("usage: wait <ms>", file=sys.stderr)
            return 1
        payload["ms"] = int(a[0])
    elif cmd == "upload":
        if len(a) < 2:
            print("usage: upload <selector> <path>", file=sys.stderr)
            return 1
        payload["selector"], payload["path"] = a[0], " ".join(a[1:])
    elif cmd == "download":
        if len(a) < 2:
            print("usage: download <url> <path>", file=sys.stderr)
            return 1
        payload["url"], payload["path"] = a[0], " ".join(a[1:])
    else:
        print(f"unknown cmd: {cmd}", file=sys.stderr)
        return 1

    out = post(ns.server, payload)
    # Compact JSON: the agent re-reads every command result, and pretty-printing
    # bloats the transcript by ~40% in tokens for no information gain.
    print(json.dumps(out, separators=(",", ":"), default=str))
    if out.get("blocked"):
        return 2
    if not out.get("ok"):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
