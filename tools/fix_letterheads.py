#!/usr/bin/env python3
"""Normalise cover-letter letterheads to the real identity.

Fixes the two defects found in the audit: a `YOUR NAME` letterhead and missing
contact/link lines, both caused by building letters without identity loaded.
The identity comes from config/profile.md (via cv_builder), so the letterhead
always matches the rest of the pipeline.

Layout of a letter (produced by cv_builder.render_motivation):
    [0] name      [1] headline     [2] contact     [3] links
    [4] spacer    [5] date         ...
This script only rewrites paragraphs 0-3 when paragraph 5 is a date line, so it
is safe and idempotent. It can also strip a stray recipient line and reset the
salutation to the generic default; set the offending recipient via
$LETTER_WRONG_RECIPIENT or --wrong-recipient.

Usage:
  python3 tools/fix_letterheads.py                # documents/applications
  python3 tools/fix_letterheads.py <dir> [...]    # extra dirs to normalise
  python3 tools/fix_letterheads.py --check         # report only, no writes
"""
import glob
import os
import sys
from docx import Document
from docx.shared import Pt, RGBColor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cv_builder as B

GREY = RGBColor(0x55, 0x55, 0x55)
DARK = RGBColor(0x1A, 0x1A, 0x1A)
WRONG_RECIPIENT = os.environ.get("LETTER_WRONG_RECIPIENT", "")
DEFAULT_DIRS = ["documents/applications"]
_MONTHS = ("January", "February", "March", "April", "May", "June", "July",
           "August", "September", "October", "November", "December")


def _looks_like_date(text):
    """True if a paragraph looks like a letter date line (month + year)."""
    text = (text or "").strip()
    if not text:
        return False
    if text == B.LETTER_DATE:
        return True
    return any(m in text for m in _MONTHS) and any(c.isdigit() for c in text)


def set_para(par, text, size, color, bold=False):
    if par.runs:
        par.runs[0].text = text
        for extra in par.runs[1:]:
            extra.text = ""
        run = par.runs[0]
    else:
        run = par.add_run(text)
    run.font.size = Pt(size)
    run.font.color.rgb = color
    run.bold = bold


def normalise(path, check, fix_recipient):
    doc = Document(path)
    ps = doc.paragraphs
    if len(ps) < 6:
        return "skip (too short)"
    texts = [p.text for p in ps]
    if not _looks_like_date(texts[5]):
        return "skip (not a letter layout)"
    changed = []
    if texts[0] != B.NAME.upper():
        changed.append(f"name {texts[0]!r}->{B.NAME.upper()!r}")
        if not check:
            set_para(ps[0], B.NAME.upper(), 18, DARK, bold=True)
    if texts[2] != B.CONTACT_LINE:
        changed.append("contact")
        if not check:
            set_para(ps[2], B.CONTACT_LINE, 8.5, GREY)
    if texts[3] != B.LINKS_LINE:
        changed.append("links")
        if not check:
            set_para(ps[3], B.LINKS_LINE, 8.5, GREY)
    if fix_recipient and WRONG_RECIPIENT:
        first = WRONG_RECIPIENT.split()[0].lower() if WRONG_RECIPIENT.split() else ""
        for p in ps:
            if WRONG_RECIPIENT in p.text:
                changed.append("wrong recipient line")
                if not check:
                    p.text = ""
        for p in ps:
            if first and p.text.strip().lower().startswith("dear " + first):
                changed.append("stray salutation")
                if not check:
                    set_para(p, "Dear hiring team,", 9.5, DARK)
    if changed and not check:
        doc.save(path)
    return "; ".join(changed) if changed else "ok"


def main():
    import argparse
    ap = argparse.ArgumentParser(
        description="Normalise cover-letter letterheads to the real identity (repair tool).")
    ap.add_argument("dirs", nargs="*", default=DEFAULT_DIRS,
                    help="directories of .docx letters (default: documents/applications)")
    ap.add_argument("--check", action="store_true", help="report only, do not write")
    ap.add_argument("--fix-recipient", action="store_true",
                    help="also strip a stray recipient line and fix the salutation; "
                         "set the recipient via --wrong-recipient or $LETTER_WRONG_RECIPIENT")
    ap.add_argument("--wrong-recipient", default="",
                    help="name to strip from recipient lines (default: $LETTER_WRONG_RECIPIENT)")
    args = ap.parse_args()

    global WRONG_RECIPIENT
    if args.wrong_recipient:
        WRONG_RECIPIENT = args.wrong_recipient

    for d in args.dirs:
        for path in sorted(glob.glob(os.path.join(d, "*.docx"))):
            result = normalise(path, args.check, fix_recipient=args.fix_recipient)
            print(f"{os.path.basename(path)[:62]:62} {result}")


if __name__ == "__main__":
    main()
