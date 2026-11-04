#!/usr/bin/env python3
"""Render a cover letter from a small JSON brief.

The agent writes the role-specific prose once, then this command renders the
standard letter (header, date, salutation, practical details, signature) so it
does not have to inspect or re-implement cv_builder for every role.

Usage:
  python3 tools/render_letter.py --key <key> --json state/letters/<key>.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import cv_builder as B


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--key", required=True)
    ap.add_argument("--json", required=True)
    ap.add_argument("--out", default=os.path.join(ROOT, "documents", "applications"))
    args = ap.parse_args()
    data = json.load(open(args.json, encoding="utf-8"))
    role = dict(data)
    role["key"] = args.key
    for field in ("headline", "title", "opening", "fit"):
        if not str(role.get(field) or "").strip():
            print(f"LETTER FAIL: missing {field}", file=sys.stderr)
            return 2
    B.OUT = args.out
    B.render_motivation(role)
    path = os.path.join(args.out, f"{B.CV_PREFIX}_Motivation_{args.key}.docx")
    print("LETTER", path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
