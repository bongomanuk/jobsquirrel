#!/usr/bin/env python3
"""Render and gate prepared documents in one deterministic command.

Used by REVIEW runs after the agent has tailored the CV pack and written the
small letter JSON. It renders the CV (with the fill check), renders the letter,
runs the pre-submit gate with --record, and records PREPARED only when the gate
passes.

Usage:
  python3 tools/finalise_docs.py --key <key> --company "Company" --role "Role" \
      [--jd ...] [--ats ...] [--engagement fulltime] [--record-prepared]
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import cv_builder as B
import register as REG


def run(cmd):
    r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
    out = (r.stdout or "") + (r.stderr or "")
    print(out.rstrip())
    return r.returncode, out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--key", required=True)
    ap.add_argument("--company", required=True)
    ap.add_argument("--role", required=True)
    ap.add_argument("--jd", default="")
    ap.add_argument("--ats", default="")
    ap.add_argument("--engagement", default="fulltime")
    ap.add_argument("--record-prepared", action="store_true")
    ap.add_argument("--skip-cv", action="store_true")
    ap.add_argument("--skip-letter", action="store_true")
    args = ap.parse_args()

    key = args.key
    jd = args.jd or os.path.join(ROOT, "state", "job-descriptions", f"{key}.md")
    ats = args.ats or os.path.join(ROOT, "state", "ats", f"{key}.txt")
    content = os.path.join(ROOT, "state", "cv-content", f"{key}.json")
    letter_json = os.path.join(ROOT, "state", "letters", f"{key}.json")
    cv = os.path.join(ROOT, "documents", "applications", f"{B.CV_PREFIX}_CV_{key}.docx")
    letter = os.path.join(ROOT, "documents", "applications", f"{B.CV_PREFIX}_Motivation_{key}.docx")

    if not args.skip_letter and not os.path.exists(letter_json):
        print(f"FINALISE FAIL: missing letter brief {letter_json}", file=sys.stderr)
        return 2
    if not args.skip_cv:
        rc, _ = run([sys.executable, "tools/cv_target.py", "--key", key,
                     "--content", content, "--require-fill"])
        if rc:
            print("FINALISE FAIL: cv_target did not pass the fill check", file=sys.stderr)
            return rc
    if not args.skip_letter:
        rc, _ = run([sys.executable, "tools/render_letter.py", "--key", key,
                     "--json", letter_json])
        if rc:
            print("FINALISE FAIL: letter render failed", file=sys.stderr)
            return rc

    rc, out = run([sys.executable, "tools/check_documents.py", "--letter", letter,
                   "--cv", cv, "--company", args.company, "--jd", jd,
                   "--ats-keywords", ats, "--engagement", args.engagement, "--record"])
    if rc or "RESULT: PASS" not in out:
        print("FINALISE FAIL: pre-submit gate did not pass", file=sys.stderr)
        return rc or 2

    if args.record_prepared:
        row = REG.find_row(args.company, args.role)
        if row and (row.get("status") or "").upper() in ("SUBMITTED", "INTERVIEW",
                                                         "IN_PROGRESS", "OFFER"):
            print(f"FINALISE: {row['status']} already recorded; not downgrading to PREPARED")
            return 0
        rc, _ = run([sys.executable, "tools/register.py", "--set",
                     "--company", args.company, "--role", args.role,
                     "--status", "PREPARED",
                     "--notes", f"review: {cv} | {letter}"])
        if rc:
            print("FINALISE FAIL: could not record PREPARED", file=sys.stderr)
            return rc
    state = "PREPARED" if args.record_prepared else "GATE PASS"
    print(f"FINALISE PASS {args.company} | {args.role} | {state}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
