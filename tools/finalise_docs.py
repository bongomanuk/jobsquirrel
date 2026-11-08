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
import letter_need


def run(cmd):
    r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
    out = (r.stdout or "") + (r.stderr or "")
    print(out.rstrip())
    return r.returncode, out


LIVE_STATUSES = ("SUBMITTED", "INTERVIEW", "IN_PROGRESS", "OFFER")


def record_prepared(company, role, cv, letter, need_letter, repost=False):
    """Record PREPARED for a review, returning (result, reason).

    A live application is normally not downgraded: the row still means the
    application we sent. A repost is different. The user is preparing a new
    attempt at the same role, so PREPARED is the current state of that attempt;
    the earlier status is kept in the note, where the drawer and the grid tag
    can still show it. Without --repost the old behaviour is unchanged.
    """
    row = REG.find_row(company, role)
    status = ((row or {}).get("status") or "").upper()
    if row and status in LIVE_STATUSES and not repost:
        return "skip", status
    note = (f"review: {cv} | {letter}" if need_letter
            else f"review: {cv} (CV only; no cover letter required)")
    if repost and row and status in LIVE_STATUSES:
        since = row.get("date") or "unknown"
        note += (f" | repost: earlier application still {status} since {since}; "
                 f"new documents prepared, not submitted")
    cmd = [sys.executable, "tools/register.py", "--set",
           "--company", company, "--role", role,
           "--status", "PREPARED",
           "--notes", note]
    if repost:
        cmd.append("--repost")
    rc, out = run(cmd)
    return ("ok", "PREPARED") if rc == 0 else ("fail", out.strip()[-300:])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--key", required=True)
    ap.add_argument("--company", required=True)
    ap.add_argument("--role", required=True)
    ap.add_argument("--jd", default="")
    ap.add_argument("--ats", default="")
    ap.add_argument("--engagement", default="fulltime")
    ap.add_argument("--record-prepared", action="store_true")
    ap.add_argument("--repost", action="store_true",
                    help="the review is a new attempt at a role that already has a live "
                         "application; record PREPARED and keep the earlier status in the note")
    ap.add_argument("--skip-cv", action="store_true")
    ap.add_argument("--skip-letter", action="store_true")
    ap.add_argument("--letter-mode", choices=("auto", "yes", "no"), default="auto",
                    help="auto: follow the advert; yes: force a cover letter; no: CV only")
    args = ap.parse_args()

    key = args.key
    jd = args.jd or os.path.join(ROOT, "state", "job-descriptions", f"{key}.md")
    ats = args.ats or os.path.join(ROOT, "state", "ats", f"{key}.txt")
    content = os.path.join(ROOT, "state", "cv-content", f"{key}.json")
    letter_json = os.path.join(ROOT, "state", "letters", f"{key}.json")
    cv = os.path.join(ROOT, "documents", "applications", f"{B.CV_PREFIX}_CV_{key}.docx")
    letter = os.path.join(ROOT, "documents", "applications", f"{B.CV_PREFIX}_Motivation_{key}.docx")

    # The advert decides. Most roles do not ask for a cover letter: render the CV
    # only, gate the CV only, and record that in the notes. --letter-mode yes is
    # for an application form that turns out to require one.
    jd_text = ""
    try:
        jd_text = open(jd, encoding="utf-8", errors="ignore").read()
    except OSError:
        pass
    if args.letter_mode == "auto":
        need_letter, letter_why = letter_need.required(jd_text)
    else:
        need_letter, letter_why = args.letter_mode == "yes", "forced by --letter-mode"
    if args.skip_letter:
        need_letter = False
    # Keep the recorded decision in step with the renderer: a letter forced by
    # the application form is "required" for the submit run that follows.
    try:
        os.makedirs(os.path.dirname(letter_json), exist_ok=True)
        with open(os.path.join(os.path.dirname(letter_json), key + ".need"), "w", encoding="utf-8") as fh:
            fh.write(("required: " if need_letter else "optional: ") + letter_why + "\n")
    except OSError:
        pass
    if need_letter and not os.path.exists(letter_json):
        print(f"FINALISE FAIL: missing letter brief {letter_json}", file=sys.stderr)
        return 2
    if not need_letter and os.path.exists(letter_json):
        print(f"FINALISE: cover letter not required ({letter_why}); CV only")
    if not args.skip_cv:
        rc, _ = run([sys.executable, "tools/cv_target.py", "--key", key,
                     "--content", content, "--require-fill"])
        if rc:
            print("FINALISE FAIL: cv_target did not pass the fill check", file=sys.stderr)
            return rc
    if need_letter:
        rc, _ = run([sys.executable, "tools/render_letter.py", "--key", key,
                     "--json", letter_json])
        if rc:
            print("FINALISE FAIL: letter render failed", file=sys.stderr)
            return rc

    gate = [sys.executable, "tools/check_documents.py", "--cv", cv, "--company", args.company,
            "--jd", jd, "--ats-keywords", ats, "--engagement", args.engagement, "--record"]
    if need_letter:
        gate[2:2] = ["--letter", letter]
    rc, out = run(gate)
    if rc or "RESULT: PASS" not in out:
        print("FINALISE FAIL: pre-submit gate did not pass", file=sys.stderr)
        return rc or 2

    if args.record_prepared:
        result, why = record_prepared(args.company, args.role, cv, letter,
                                      need_letter, args.repost)
        if result == "skip":
            print(f"FINALISE: {why} already recorded; not downgrading to PREPARED")
            return 0
        if result != "ok":
            print(f"FINALISE FAIL: could not record PREPARED: {why}", file=sys.stderr)
            return 2
    state = "PREPARED" if args.record_prepared else "GATE PASS"
    print(f"FINALISE PASS {args.company} | {args.role} | {state} | letter={'yes' if need_letter else 'no'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
