#!/usr/bin/env python3
"""Validate an adaptive-harness recipe before it is reused.

A recipe is a declarative list of browser steps. It is data, not code: the
adaptive harness may write one, but the main harness never imports it and it is
checked here before a run replays it.

    python3 tools/adaptive/validate.py tools/adaptive/recipes/<name>.json
    python3 tools/adaptive/validate.py --all
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
RECIPES = os.path.join(ROOT, "tools", "adaptive", "recipes")

OPS = {
    "nav": {"url"},
    "fill": {"selector", "value"},
    "type": {"selector", "value"},
    "select": {"selector", "value"},
    "check": {"selector"},
    "upload": {"selector", "path"},
    "press": {"key"},
    "click": {"target"},
    "pick": {"text"},
    "eval": {"js"},
    "waitfor": {"selector"},
    "waittext": {"text"},
    "waiturl": {"url"},
    "sleep": {"ms"},
    "snap": set(),
    "text": set(),
}
FORBIDDEN = ("http://", "https://", "curl ", "wget ", "bash ", "sh -c", "subprocess",
             "os.system", "open(", "exec(", "eval(")


def check(path: str) -> list[str]:
    errors: list[str] = []
    try:
        data = json.load(open(path, encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return [f"cannot read JSON: {exc}"]
    if not isinstance(data, dict):
        return ["top level must be an object"]
    for field in ("name", "host", "steps"):
        if not data.get(field):
            errors.append(f"missing {field}")
    steps = data.get("steps")
    if not isinstance(steps, list) or not steps:
        errors.append("steps must be a non-empty list")
        return errors
    if len(steps) > 200:
        errors.append("more than 200 steps")
    for i, step in enumerate(steps, 1):
        if not isinstance(step, dict):
            errors.append(f"step {i}: not an object")
            continue
        op = str(step.get("op") or "").strip()
        if op not in OPS:
            errors.append(f"step {i}: unknown op {op!r}")
            continue
        for field in OPS[op]:
            if field not in step:
                errors.append(f"step {i} ({op}): missing {field}")
        for key, value in step.items():
            if not isinstance(value, (str, int, float, bool)) and value is not None:
                errors.append(f"step {i}: {key} must be a scalar")
            if isinstance(value, str):
                if len(value) > 4000:
                    errors.append(f"step {i}: {key} is too long")
                if key == "js":
                    low = value.lower()
                    for bad in FORBIDDEN:
                        if bad in low:
                            errors.append(f"step {i}: js contains forbidden {bad!r}")
    return errors


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("paths", nargs="*", help="recipe JSON file(s)")
    ap.add_argument("--all", action="store_true", help="validate every recipe")
    args = ap.parse_args()
    paths = args.paths or (sorted(glob.glob(os.path.join(RECIPES, "*.json"))) if args.all else [])
    if not paths:
        print("no recipe files")
        return 2
    bad = 0
    for path in paths:
        errors = check(path)
        rel = os.path.relpath(path, ROOT)
        if errors:
            bad += 1
            print(f"FAIL {rel}")
            for e in errors:
                print(f"  - {e}")
        else:
            print(f"PASS {rel}")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
