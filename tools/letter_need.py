#!/usr/bin/env python3
"""Decide whether a job advert asks for a cover letter.

Most adverts do not. Preparing a letter for every role wastes a model turn and
produces a document the employer never reads, so the default is CV only. A
letter is prepared when the advert names one without saying it is optional.

Usage:
  python3 tools/letter_need.py <jd.md>          # prints "required" or "optional" + reason
  python3 tools/letter_need.py --json <jd.md>
"""
from __future__ import annotations

import argparse
import json
import re
import sys

SYNONYM = re.compile(
    r"(cover(?:ing)? letter|motivation(?:al)? letter|letter of motivation|"
    r"personal letter|ans[oö]kningsbrev|personlig\w* brev|motiveringsbrev|motivationsbrev)",
    re.I)

OPTIONAL = re.compile(
    r"\b(optional|not required|not mandatory|no need|if you (?:wish|want|like)|"
    r"nice to have|meriterande|frivilligt?|ej obligatorisk|inte obligatorisk|"
    r"om du vill|beh[oö]ver inte|no [^.]{0,40}?(?:required|needed|necessary))\b"
    r"|\b(?:without|utan|inget|ingen|ist[äa]llet f[oö]r|instead of)\b[^.]{0,60}?"
    r"(?:cover(?:ing)? letter|motivation(?:al)? letter|personlig\w* brev)"
    r"|(?:cover(?:ing)? letter|motivation(?:al)? letter|personlig\w* brev)[^.]{0,60}?"
    r"\b(?:inte|ej|utan|inget|ingen)\b", re.I)

NEGATED = re.compile(
    r"\b(?:do not|don't|does not|doesn't|no need to|not)\s+"
    r"(?:require|need|include|send|attach|enclose|upload)\b", re.I)

REQUIRED = re.compile(
    r"\b(required|mandatory|must|please (?:attach|include|upload|send)|"
    r"attach|enclose|upload|include|obligatorisk|kr[aä]vs|ska bifogas|"
    r"bifoga|skicka (?:in|med))\b", re.I)


def _sentences(text: str):
    return [s.strip() for s in re.split(r"(?<=[.!?;])\s+|\n+", text or "") if s.strip()]


def required(jd_text: str):
    """Return (needed: bool, evidence: str).

    A named letter counts as required unless the same sentence says optional or
    negates it. No mention at all means CV only.
    """
    mention = ""
    for sentence in _sentences(jd_text):
        if not SYNONYM.search(sentence):
            continue
        if OPTIONAL.search(sentence) or NEGATED.search(sentence):
            return False, sentence.strip()[:240]
        if not mention:
            mention = sentence.strip()
    if mention:
        return True, mention[:240]
    return False, "the advert does not mention a cover letter"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("jd")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    try:
        text = open(args.jd, encoding="utf-8", errors="ignore").read()
    except OSError as exc:
        print(f"LETTER-NEED FAIL: {exc}", file=sys.stderr)
        return 2
    need, why = required(text)
    if args.json:
        print(json.dumps({"required": need, "evidence": why}, ensure_ascii=False))
    else:
        print(("required" if need else "optional") + f": {why}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
