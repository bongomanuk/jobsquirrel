#!/usr/bin/env python3
"""Lint release notes before they go to the public GitHub repo.

The public project must never carry the candidate's personal data or live
pipeline state. This reads the private config/state when present (name, email,
phone, location, pay figures, employers, live companies) and also checks for
generic public-safety leaks (country/currency names, live counts, interview
dates, contact details).

    python3 tools/release_lint.py --text-file /tmp/notes.md
    echo "notes..." | python3 tools/release_lint.py

Exit 0 when clean; 1 when it finds something to remove or rephrase.
Use --allow TERM for a known-safe word (e.g. a product name that is also a
company in the register). The rule is simple: if in doubt, leave it out.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Words that are also companies in some registers but are ordinary prose/platform
# names here. Keeping them out avoids noise; the live name/employers still match.
STOP = {
    "remote", "hybrid", "generic", "stream", "canonical", "appear", "tbd", "unknown",
    "workday", "greenhouse", "lever", "ashby", "teamtailor", "jobylon", "deel",
    "linkedin", "google", "amazon", "microsoft", "apple", "meta", "openai",
    "anthropic", "nvidia", "rain", "buffer", "linear", "notion",
}

# Deliberately broad: public release notes should not name a market or currency.
MARKET = re.compile(
    r"\b(sweden|swedish|stockholm|stuvsta|sek|eur|usd|gbp|nok|dkk|chf|cad)\b", re.I)
COUNT = re.compile(
    r"\b\d+\s+(?:need you|needs you|ongoing|to apply|done|focus|submitted|applications?)\b", re.I)
WHEN = re.compile(r"\b20\d{2}-\d{2}-\d{2}[ T]\d{2}:\d{2}\b")
CONTACT = re.compile(r"(?:\+46|linkedin\.com/in/|@[a-z0-9.-]+\.[a-z]{2,})", re.I)


def _read(path):
    try:
        with open(path, encoding="utf-8", errors="ignore") as fh:
            return fh.read()
    except OSError:
        return ""


def _add(terms, value):
    value = (value or "").strip()
    if len(value) < 3 or value.lower() in STOP:
        return
    terms.add(value)
    for part in re.split(r"[,;|]", value):
        part = part.strip()
        if len(part) >= 3:
            terms.add(part)


def _private_terms():
    """Terms from the live profile/CV/register (empty in the public clone)."""
    terms = set()
    profile = _read(os.path.join(ROOT, "config", "profile.md"))
    wanted = {
        "full name", "email", "phone", "location (city, country)", "linkedin",
        "github / portfolio / website", "other websites (comma-separated)",
        "salary target", "contract rate (ex vat)", "based in",
    }
    for line in profile.splitlines():
        m = re.match(r"\s*-\s*([^:]+):\s*(.+)", line)
        if not m or m.group(1).strip().lower() not in wanted:
            continue
        value = m.group(2).strip()
        _add(terms, value)
        for num in re.findall(r"\d[\d., ]*\s*[kKmM]?", value):
            _add(terms, num.strip())
    name = ""
    try:
        cv = json.loads(_read(os.path.join(ROOT, "config", "cv.json")) or "{}")
        name = (cv.get("name") or "").strip()
        _add(terms, name)
        for exp in cv.get("experience") or []:
            _add(terms, exp.get("employer", ""))
    except (ValueError, AttributeError):
        pass
    if name:
        for part in name.split():
            _add(terms, part)
    try:
        with open(os.path.join(ROOT, "state", "applications.csv"),
                  newline="", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                _add(terms, row.get("company", ""))
    except OSError:
        pass
    return terms


def main():
    ap = argparse.ArgumentParser(description="Check release notes for personal data.")
    ap.add_argument("--text-file", help="file with the release notes")
    ap.add_argument("--allow", action="append", default=[], metavar="TERM",
                    help="known-safe term to ignore (repeatable)")
    args = ap.parse_args()
    text = _read(args.text_file) if args.text_file else sys.stdin.read()
    if not text.strip():
        print("release_lint: no notes given", file=sys.stderr)
        return 2

    allow = {a.lower() for a in args.allow}
    terms = {t for t in _private_terms() if t.lower() not in allow}
    patterns = [("market/currency", MARKET), ("live count", COUNT),
                ("interview date/time", WHEN), ("contact detail", CONTACT)]

    hits = []
    for n, line in enumerate(text.splitlines(), 1):
        low = line.lower()
        for term in terms:
            if term.lower() in allow or not term or term.lower() in {"https:", "http:", "//"}:
                continue
            word = re.search(r"(?<![\w])" + re.escape(term) + r"(?![\w])", line, re.I)
            if word:
                hits.append((n, "private term", term, line.strip()))
        for label, pat in patterns:
            for m in pat.finditer(line):
                hits.append((n, label, m.group(0), line.strip()))

    if not hits:
        print("RESULT: PASS - release notes look public-safe")
        return 0
    print("RESULT: FAIL - remove or rephrase these before publishing:")
    seen = set()
    for n, label, term, line in hits:
        key = (n, label, term)
        if key in seen:
            continue
        seen.add(key)
        print(f"  line {n}: {label}: {term!r}")
        print(f"    {line[:200]}")
    print("\nRelease notes, tags and commit messages are public. Use generic "
          "examples (Acme, ExampleCorp) and no live register numbers.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
