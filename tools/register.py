#!/usr/bin/env python3
"""Canonical application register.

`state/applications.csv` is the single source of truth for outcomes: one row per
(company, role). `state/applications-register.md` is GENERATED from it, so the
register can no longer drift or list the same role under two statuses.
`tools/record_submission.py` upserts here automatically after every submission.

Usage:
  python3 tools/register.py --stats
  python3 tools/register.py --list [--status SUBMITTED]
  python3 tools/register.py --show "<company>"
  python3 tools/register.py --check          # validate; exit 1 on problems
  python3 tools/register.py --render         # write state/applications-register.md
  python3 tools/register.py --set --company <Company> --role "Head of Engineering" \
      --status SUBMITTED --date 2026-10-02 --ats <ATS> --letter <path> --notes "..."
"""
import argparse
import contextlib
import csv
import fcntl
import os
import sys
import tempfile
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CSV_PATH = os.environ.get("APPLICATIONS_CSV", os.path.join(ROOT, "state", "applications.csv"))
MD_PATH = os.environ.get("APPLICATIONS_MD", os.path.join(ROOT, "state", "applications-register.md"))
LOCK_PATH = CSV_PATH + ".lock"
FIELDS = ["date", "company", "role", "ats", "status", "letter", "notes"]
STATUSES = ["QUEUED", "SUBMITTED", "INTERVIEW", "OFFER", "REJECTED", "BLOCKED", "MANUAL",
            "PREPARED", "IN_PROGRESS", "CLOSED"]
# Statuses that count as a live process - an application we have sent and are
# still awaiting an outcome on (not yet rejected/closed, not merely prepared).
PROCESS_STATUSES = ["SUBMITTED", "IN_PROGRESS", "INTERVIEW", "OFFER"]
GROUP_TITLES = {
    "QUEUED": "Queued - waiting to be applied",
    "SUBMITTED": "Submitted - confirmed",
    "INTERVIEW": "Interview in progress",
    "OFFER": "Offer",
    "REJECTED": "Rejected",
    "BLOCKED": "Blocked - needs a manual step (do not auto-retry)",
    "MANUAL": "Manual / login / email",
    "PREPARED": "Prepared - letter ready, not sent",
    "IN_PROGRESS": "In progress",
    "CLOSED": "Closed - do not pursue",
}


def load():
    if not os.path.isfile(CSV_PATH):
        return []
    with open(CSV_PATH, newline="", encoding="utf-8") as fh:
        return [{k: (r.get(k) or "") for k in FIELDS} for r in csv.DictReader(fh)]


@contextlib.contextmanager
def locked():
    """Exclusive cross-process lock so parallel agents cannot interleave a
    read-modify-write of the register (or clobber each other's writes)."""
    os.makedirs(os.path.dirname(LOCK_PATH), exist_ok=True)
    with open(LOCK_PATH, "w") as lf:
        fcntl.flock(lf, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lf, fcntl.LOCK_UN)


def save(rows):
    os.makedirs(os.path.dirname(CSV_PATH), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(CSV_PATH), prefix=".applications.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=FIELDS)
            w.writeheader()
            for r in rows:
                w.writerow({k: r.get(k, "") for k in FIELDS})
        os.replace(tmp, CSV_PATH)  # atomic swap
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def _key(company, role):
    return (company.strip().lower(), role.strip().lower())


def upsert(company, role, status, day="", ats="", letter="", notes=""):
    """Insert or update the single row for (company, role). Returns the row."""
    with locked():
        rows = load()
        k = _key(company, role)
        for r in rows:
            if _key(r["company"], r["role"]) == k:
                r["status"] = status
                if day:
                    r["date"] = day
                if ats:
                    r["ats"] = ats
                if letter:
                    r["letter"] = letter
                if notes:
                    r["notes"] = notes
                save(rows)
                render(silent=True)
                return r
        r = {"date": day or date.today().isoformat(), "company": company, "role": role,
             "ats": ats, "status": status, "letter": letter, "notes": notes}
        rows.append(r)
        save(rows)
        render(silent=True)
        return r


def delete(company, role):
    """Remove a row (company+role). Returns how many were removed."""
    with locked():
        rows = load()
        k = _key(company, role)
        kept = [r for r in rows if _key(r["company"], r["role"]) != k]
        removed = len(rows) - len(kept)
        if removed:
            save(kept)
            render(silent=True)
        return removed


def set_row(company, role, status="", note=""):
    """Update exactly one row (company+role): set status and/or append a note."""
    with locked():
        rows = load()
        k = _key(company, role)
        n = 0
        for r in rows:
            if _key(r["company"], r["role"]) == k:
                if status:
                    r["status"] = status
                if note:
                    r["notes"] = (r["notes"] + " | " if r["notes"] else "") + note
                n += 1
        if n:
            save(rows)
            render(silent=True)
        return n


def add_note(needle, text, status=""):
    """Append a note (and optionally set status) on every row matching needle."""
    with locked():
        rows = load()
        changed = 0
        for r in rows:
            if needle.lower() in r["company"].lower() or needle.lower() in r["role"].lower():
                r["notes"] = (r["notes"] + " | " if r["notes"] else "") + text
                if status:
                    r["status"] = status
                changed += 1
        if changed:
            save(rows)
            render(silent=True)
        return changed


def stats():
    rows = load()
    counts = {s: 0 for s in STATUSES}
    for r in rows:
        counts[r["status"] if r["status"] in counts else "CLOSED"] += 1
    print(f"total: {len(rows)}")
    for s in STATUSES:
        if counts[s]:
            print(f"  {s:<12} {counts[s]}")
    in_process = sum(counts[s] for s in PROCESS_STATUSES)
    breakdown = " + ".join(f"{s} {counts[s]}" for s in PROCESS_STATUSES)
    print(f"  {'-' * 17}")
    print(f"  IN PROCESS   {in_process}  ({breakdown})")
    return rows


def listing(status=""):
    rows = load()
    if status:
        rows = [r for r in rows if r["status"].upper() == status.upper()]
    rows.sort(key=lambda r: (STATUSES.index(r["status"]) if r["status"] in STATUSES else 99,
                             r["company"].lower(), r["role"].lower()))
    for r in rows:
        print(f"{r['status']:<11} {r['date']:<10} {r['company']:<28} {r['role']}")
    print(f"({len(rows)} rows)")


def show(needle):
    needle = needle.lower()
    hits = [r for r in load() if needle in r["company"].lower() or needle in r["role"].lower()]
    for r in hits:
        print(f"{r['status']:<11} {r['date']:<10} {r['company']} — {r['role']}")
        if r["letter"]:
            print(f"            letter: {r['letter']}")
        if r["notes"]:
            print(f"            notes:  {r['notes']}")
    print(f"({len(hits)} matches)")


def check():
    rows = load()
    problems = []
    seen = {}
    for i, r in enumerate(rows, start=2):
        if not r["company"].strip() or not r["role"].strip():
            problems.append(f"row {i}: missing company or role")
        if r["status"] not in STATUSES:
            problems.append(f"row {i}: invalid status {r['status']!r} (allowed: {', '.join(STATUSES)})")
        k = _key(r["company"], r["role"])
        if k in seen:
            problems.append(f"row {i}: duplicate of row {seen[k]} -> {r['company']} / {r['role']}")
        else:
            seen[k] = i
    for p in problems:
        print("FAIL", p)
    print(f"{len(rows)} rows, {len(problems)} problems")
    return 1 if problems else 0


def render(silent=False):
    rows = load()
    lines = [
        "# Applications register - single source of truth",
        "",
        "GENERATED FILE. Do not edit by hand. Edit `state/applications.csv` (or run",
        "`tools/register.py --set ...`); `tools/record_submission.py` upserts it on every",
        "submission. Regenerate with `python3 tools/register.py --render`.",
        "",
        "Statuses: SUBMITTED | BLOCKED | MANUAL | PREPARED | IN_PROGRESS | CLOSED.",
        "Documents sent are recorded in `state/submissions.csv`.",
        "",
    ]
    for status in STATUSES:
        group = [r for r in rows if r["status"] == status]
        if not group:
            continue
        group.sort(key=lambda r: (r["date"], r["company"].lower(), r["role"].lower()))
        lines.append(f"## {GROUP_TITLES[status]} ({len(group)})")
        lines.append("")
        lines.append("| Date | Company | Role | ATS | Notes |")
        lines.append("|---|---|---|---|---|")
        for r in group:
            note = r["notes"]
            if r["letter"]:
                note = (note + " " if note else "") + f"letter: `{r['letter']}`"
            lines.append(f"| {r['date']} | {r['company']} | {r['role']} | {r['ats']} | {note} |")
        lines.append("")
    with open(MD_PATH, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))
    if not silent:
        print(f"wrote {os.path.relpath(MD_PATH, ROOT)} ({len(rows)} rows)")


def main():
    ap = argparse.ArgumentParser(description="Canonical application register.")
    ap.add_argument("--stats", action="store_true")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--status", default="")
    ap.add_argument("--show", default="")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--render", action="store_true")
    ap.add_argument("--set", action="store_true")
    ap.add_argument("--delete", action="store_true")
    ap.add_argument("--company", default="")
    ap.add_argument("--role", default="")
    ap.add_argument("--date", default="")
    ap.add_argument("--ats", default="")
    ap.add_argument("--letter", default="")
    ap.add_argument("--notes", default="")
    args = ap.parse_args()

    # --company/--role/--notes only mean something with --set or --delete. Without
    # them, `--company X --status BLOCKED` used to fall through to the listing
    # and record nothing, silently, so refuse instead.
    if (args.company or args.role or args.notes) and not (args.set or args.delete):
        ap.error("--company/--role/--notes need --set (to record a row) or --delete")

    if args.delete:
        if not args.company or not args.role:
            ap.error("--delete requires --company and --role")
        n = delete(args.company, args.role)
        print(f"deleted {n} row(s): {args.company} — {args.role}")
    elif args.set:
        if not args.company or not args.role or not args.status:
            ap.error("--set requires --company, --role and --status")
        row = upsert(args.company, args.role, args.status.upper(), args.date, args.ats, args.letter, args.notes)
        print(f"set {row['status']}: {row['company']} — {row['role']}")
    elif args.stats:
        stats()
    elif args.list or args.status:
        listing(args.status)
    elif args.show:
        show(args.show)
    elif args.check:
        sys.exit(check())
    elif args.render:
        render()
    else:
        ap.print_help()


if __name__ == "__main__":
    main()
