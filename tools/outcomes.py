#!/usr/bin/env python3
"""Outcome feedback: what is actually converting.

Reads the register (state/applications.csv) joined with the provenance ledger
(state/submissions.csv) and reports the funnel plus response rates broken down by
source (ATS/site), CV, and posting source. Use it to steer effort: stop pouring
applications into channels that never convert, and double down on the ones that do.

Usage:
  python3 tools/outcomes.py
  python3 tools/outcomes.py --min 5        # only channels with >=5 submissions
"""
import argparse
import csv
import os
import re
import sys
from collections import defaultdict
from urllib.parse import urlparse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APPS = os.environ.get("APPLICATIONS_CSV", os.path.join(ROOT, "state", "applications.csv"))
SUBS = os.environ.get("SUBMISSIONS_CSV", os.path.join(ROOT, "state", "submissions.csv"))

SUBMITTED_STATES = {"SUBMITTED", "INTERVIEW", "OFFER", "REJECTED"}
RESPONDED_STATES = {"INTERVIEW", "OFFER"}


def _load(path):
    if not os.path.isfile(path):
        return []
    with open(path, newline="", encoding="utf-8") as fh:
        return [{k: (v or "") for k, v in r.items()} for r in csv.DictReader(fh)]


def _cv_token(path):
    base = os.path.basename(path or "")
    m = re.search(r"_CV_(.+?)\.(docx|pdf)$", base, re.IGNORECASE)
    return m.group(1) if m else (os.path.splitext(base)[0] or "(unknown)")


def _source(row, sub):
    ats = (row.get("ats") or (sub or {}).get("ats") or "").strip()
    if ats:
        return ats.lower()
    url = (sub or {}).get("apply_url", "")
    host = urlparse(url).netloc.lower()
    return host or "(unknown)"


def _rate(responded, submitted):
    return (responded / submitted) if submitted else 0.0


def _table(title, buckets, min_n):
    print(f"\n{title}")
    print(f"  {'channel':<28} {'sent':>5} {'resp':>5} {'rate':>6}")
    rows = [(k, s, r) for k, (s, r) in buckets.items() if s >= min_n]
    for k, s, r in sorted(rows, key=lambda x: (_rate(x[2], x[1]), x[1]), reverse=True):
        print(f"  {k[:28]:<28} {s:>5} {r:>5} {_rate(r, s):>5.0%}")
    if not rows:
        print("  (not enough data yet)")


def main():
    ap = argparse.ArgumentParser(description="Report application outcomes / conversion.")
    ap.add_argument("--min", type=int, default=1, help="minimum submissions per channel to show")
    args = ap.parse_args()

    apps = _load(APPS)
    if not apps:
        print(f"no register yet: {os.path.relpath(APPS, ROOT)}")
        return 0

    subs_by_key = {}
    for s in _load(SUBS):
        subs_by_key[(s.get("company", ""), s.get("role", ""))] = s

    funnel = defaultdict(int)
    by_source = defaultdict(lambda: [0, 0])
    by_cv = defaultdict(lambda: [0, 0])

    for a in apps:
        status = (a.get("status") or "").upper()
        funnel[status] += 1
        if status not in SUBMITTED_STATES:
            continue
        sub = subs_by_key.get((a.get("company", ""), a.get("role", "")))
        src = _source(a, sub)
        cv = _cv_token((sub or {}).get("cv_file", ""))
        responded = 1 if status in RESPONDED_STATES else 0
        for bucket, key in ((by_source, src), (by_cv, cv)):
            bucket[key][0] += 1
            bucket[key][1] += responded

    total_submitted = sum(funnel[s] for s in SUBMITTED_STATES)
    total_responded = sum(funnel[s] for s in RESPONDED_STATES)

    print("Application outcomes")
    print("=" * 44)
    print(f"  total rows        {len(apps)}")
    for s in ("SUBMITTED", "INTERVIEW", "OFFER", "REJECTED", "BLOCKED",
              "MANUAL", "PREPARED", "IN_PROGRESS", "CLOSED"):
        if funnel.get(s):
            print(f"  {s:<16} {funnel[s]}")
    print(f"\n  reached an employer   {total_submitted}")
    print(f"  responded (interview+) {total_responded}  ({_rate(total_responded, total_submitted):.0%})")

    _table("By source (ATS / site)", by_source, args.min)
    _table("By CV", by_cv, args.min)
    print("\nUse this to invest where it converts. Response = INTERVIEW or OFFER.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
