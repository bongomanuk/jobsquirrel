#!/usr/bin/env python3
"""Measure whether a rendered CV actually fills its two pages.

A CV can be two pages and still look thin: the second page stops halfway down
and both columns go blank. This reads the rendered PDF and reports where the
last page's text ends, so the generator (and the pre-submit gate) can tell the
difference between "two pages" and "two full pages".

Usage:
  python3 tools/cv_fill.py documents/applications/Peter_Hollas_CV_<key>.pdf
  python3 tools/cv_fill.py <pdf> --min-fill 0.75 --quiet   # exit 2 when thin

Exit codes: 0 full enough, 2 thin (or the wrong number of pages), 3 could not
measure (no poppler / unreadable file). Never edits a document.
"""
from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys

DEFAULT_MIN_FILL = 0.70   # last page must reach at least here (fraction of height)
DEFAULT_MIN_PAGES = 2
DEFAULT_MAX_PAGES = 2


def available() -> bool:
    return bool(shutil.which("pdftotext") and shutil.which("pdfinfo"))


def _run(cmd):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=60).stdout


def measure(pdf_path: str) -> dict | None:
    """Page count, words, and how far down each page the text reaches."""
    if not available():
        return None
    try:
        bbox = _run(["pdftotext", "-bbox", "-layout", pdf_path, "-"])
    except Exception:
        return None
    pages = re.findall(r'<page width="([\d.]+)" height="([\d.]+)">(.*?)</page>',
                       bbox, re.S)
    if not pages:
        return None
    out = []
    for width, height, body in pages:
        ys = [float(y) for y in re.findall(r'yMax="([\d.]+)"', body)]
        words = len(re.findall(r"<word ", body))
        h = float(height) or 1.0
        out.append({
            "height": h,
            "bottom": max(ys) if ys else 0.0,
            "fill": min(1.0, (max(ys) / h) if ys else 0.0),
            "words": words,
        })
    return {"pages": len(out), "page": out,
            "words": sum(p["words"] for p in out)}


def assess(pdf_path: str, min_pages: int = DEFAULT_MIN_PAGES,
           max_pages: int = DEFAULT_MAX_PAGES,
           min_fill: float = DEFAULT_MIN_FILL) -> tuple[bool, list[str], dict | None]:
    m = measure(pdf_path)
    if not m:
        return False, ["could not measure the PDF (poppler-utils missing?)"], None
    problems = []
    if m["pages"] < min_pages:
        problems.append(f"only {m['pages']} page(s); the CV should use {min_pages}")
    if m["pages"] > max_pages:
        problems.append(f"{m['pages']} pages; trim to {max_pages}")
    last = m["page"][-1]
    if m["pages"] >= min_pages and last["fill"] < min_fill:
        problems.append(
            f"the last page is only {last['fill']:.0%} full "
            f"(needs {min_fill:.0%}); add evidenced detail, do not pad")
    return (not problems), problems, m


def summary(m: dict) -> str:
    bits = [f"{m['pages']} page" + ("s" if m["pages"] != 1 else ""),
            f"{m['words']:,} words"]
    for i, p in enumerate(m["page"], 1):
        bits.append(f"p{i} {p['fill']:.0%}")
    return " · ".join(bits)


def main() -> int:
    ap = argparse.ArgumentParser(description="Check that a rendered CV fills two pages.")
    ap.add_argument("pdf")
    ap.add_argument("--min-pages", type=int, default=DEFAULT_MIN_PAGES)
    ap.add_argument("--max-pages", type=int, default=DEFAULT_MAX_PAGES)
    ap.add_argument("--min-fill", type=float, default=DEFAULT_MIN_FILL,
                    help="minimum fill of the last page, as a fraction (default 0.70)")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    ok, problems, m = assess(args.pdf, args.min_pages, args.max_pages, args.min_fill)
    if m and not args.quiet:
        print(f"FILL  {summary(m)}")
    if ok:
        if not args.quiet:
            print("RESULT: FILL PASS - the CV fills its pages")
        return 0
    for p in problems:
        print(f"  THIN  {p}")
    print("RESULT: FILL FAIL - a thin CV is rejected before it is sent")
    return 2 if m else 3


if __name__ == "__main__":
    sys.exit(main())
