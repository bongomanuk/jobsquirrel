#!/usr/bin/env python3
"""Render a single cover letter .docx.

Identity (name, contact, links) is read from config/profile.md, so the letterhead
is always correct. Output name is <prefix>_Motivation_<key>.docx, where <prefix>
is CV_PREFIX ("First_Last" from profile.md, or $CV_PREFIX).

Usage:
  python3 tools/make_letter.py \
    --key Redpine_AI_Engineer_Cloud_Infra \
    --headline "AI Engineer, Cloud Infrastructure" \
    --title "AI Engineer, Cloud Infrastructure - Redpine" \
    --opening "First paragraph..." \
    --fit "Second paragraph..." \
    [--recipient "Kevin Libbos, Telenor"] [--salutation "Dear Kevin,"] [--out DIR]

Tip: prefer writing the letter text with a here-doc or a small Python snippet so
long paragraphs are easy to manage; run tools/check_documents.py afterwards.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cv_builder as B


def main():
    ap = argparse.ArgumentParser(description="Render one cover letter .docx.")
    ap.add_argument("--key", required=True, help="output key, e.g. Redpine_AI_Engineer_Cloud_Infra")
    ap.add_argument("--headline", required=True, help="line under the name in the letterhead")
    ap.add_argument("--title", required=True, help="role title used in the subject line")
    ap.add_argument("--opening", required=True, help="first body paragraph")
    ap.add_argument("--fit", required=True, help="second body paragraph")
    ap.add_argument("--recipient", default="", help="optional 'To:' line, e.g. 'Kevin Libbos, Telenor'")
    ap.add_argument("--salutation", default="Dear hiring team,", help="salutation line")
    ap.add_argument("--out", default="", help="output dir (default documents/applications or $CV_OUT)")
    args = ap.parse_args()

    B.OUT = args.out or os.environ.get(
        "CV_OUT", os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "documents", "applications"))
    os.makedirs(B.OUT, exist_ok=True)
    role = {
        "key": args.key,
        "headline": args.headline,
        "title": args.title,
        "opening": args.opening,
        "fit": args.fit,
    }
    if args.recipient:
        role["recipient"] = args.recipient
    if args.salutation:
        role["salutation"] = args.salutation
    B.render_motivation(role)
    print("wrote", os.path.join(B.OUT, B.CV_PREFIX + "_Motivation_" + args.key + ".docx"))


if __name__ == "__main__":
    main()
