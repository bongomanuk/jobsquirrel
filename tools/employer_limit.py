#!/usr/bin/env python3
"""Employer-level application limits.

Some employers cap how many applications one candidate may send in a window
(Ashby: three per 90 days at one company, two per 30 days at another). The cap
is per employer, not per role, so the same-role duplicate guard never sees it
and the runner burns a worker on a form that will be refused.

This tool keeps a small, reviewable list in state/employer-limits.json:

    {"lovable": {"employer": "Lovable", "ats": "Ashby",
                 "until": "2027-01-08",
                 "reason": "three applications in 90 days; wait for review"}}

    python3 tools/employer_limit.py --check "Lovable AB"   # rc 0 + reason if limited
    python3 tools/employer_limit.py --list
    python3 tools/employer_limit.py --set "Lovable" 2027-01-08 "three applications in 90 days"
    python3 tools/employer_limit.py --clear "Lovable"

The runner calls --check before starting a task and logs SKIP-LIMIT instead of
opening the employer's form. A limit is time-bound: once `until` has passed the
role is allowed again and the entry can be cleared.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIMITS = os.path.join(ROOT, "state", "employer-limits.json")


def norm(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (value or "").casefold())


def load() -> dict:
    try:
        with open(LIMITS, encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save(data: dict) -> None:
    os.makedirs(os.path.dirname(LIMITS), exist_ok=True)
    tmp = LIMITS + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, sort_keys=True)
        fh.write("\n")
    os.replace(tmp, LIMITS)


def active(entry: dict, today: str) -> bool:
    until = str(entry.get("until") or "")
    return bool(until) and until >= today


def find(data: dict, company: str) -> tuple[str, dict] | tuple[None, None]:
    want = norm(company)
    if not want:
        return None, None
    for key, entry in data.items():
        names = {norm(key), norm(str(entry.get("employer") or ""))}
        if want in names:
            return key, entry
        # "Lovable AB" should match "lovable" and vice versa, but never match a
        # short token inside a different employer.
        if any(n and (want.startswith(n) or n.startswith(want)) and min(len(want), len(n)) >= 5
               for n in names):
            return key, entry
    return None, None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", metavar="COMPANY", help="exit 0 and print the reason when limited")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--set", nargs=3, metavar=("COMPANY", "UNTIL", "REASON"))
    ap.add_argument("--ats", default="", help="ATS name for --set")
    ap.add_argument("--clear", metavar="COMPANY")
    args = ap.parse_args()

    today = dt.date.today().isoformat()
    data = load()

    if args.set:
        company, until, reason = args.set
        try:
            dt.date.fromisoformat(until)
        except ValueError:
            print(f"bad date {until!r}; use YYYY-MM-DD", file=sys.stderr)
            return 2
        key = norm(company)
        data[key] = {"employer": company, "ats": args.ats, "until": until,
                     "reason": reason, "set": today}
        save(data)
        print(f"limited {company} until {until}: {reason}")
        return 0

    if args.clear:
        key, _ = find(data, args.clear)
        if not key:
            print(f"no limit for {args.clear}")
            return 1
        del data[key]
        save(data)
        print(f"cleared {args.clear}")
        return 0

    if args.list:
        if not data:
            print("no employer limits")
            return 0
        for key, entry in sorted(data.items()):
            state = "active" if active(entry, today) else "expired"
            print(f"{state:7} {entry.get('employer') or key} until {entry.get('until')} "
                  f"({entry.get('ats') or 'ATS'}): {entry.get('reason')}")
        return 0

    if args.check:
        _, entry = find(data, args.check)
        if entry and active(entry, today):
            print(f"{entry.get('employer') or args.check} until {entry.get('until')}: "
                  f"{entry.get('reason')}")
            return 0
        return 1

    ap.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
