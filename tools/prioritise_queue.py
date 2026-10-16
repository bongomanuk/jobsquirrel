#!/usr/bin/env python3
"""Reorder a queue so the most senior roles are applied to first.

The queue file is tab-separated: company  role  url  cv  ats  key.
Rows are stable-sorted by the seniority of the role title, so at the same
company a "Director" / "Head of" role is applied to before an "Engineer" one,
while the original order is kept within a rank. Header comment lines stay on top.

Seniority ranks (higher first):
  6  Chief / CTO / CIO / CISO / CDO / CPO / SVP / VP / Vice President
  5  Director / Head of
  4  Principal / Staff
  3  Lead / Manager
  2  Senior / Sr
  1  everything else

Usage:
  python3 tools/prioritise_queue.py                 # reorder state/queue.tsv in place
  python3 tools/prioritise_queue.py --dry-run       # print the new order only
  python3 tools/prioritise_queue.py --queue state/queue-linkedin.tsv
  python3 tools/prioritise_queue.py --keep-file-order   # same as run_queue PRIORITISE=0
"""
import argparse
import os
import re
import sys

RANKS = [
    (6, ("chief", "cto", "cio", "ciso", "cdo", "cpo", "svp", "vice president", "vp")),
    (5, ("director", "head of")),
    (4, ("principal", "staff")),
    (3, ("lead", "manager")),
    (2, ("senior", "sr ")),
]


def seniority(role: str) -> int:
    # Whole words only, so "cto" does not match inside "director", "vector" or
    # "contractor". run_queue.sh's _seniority matches the same way.
    words = " " + re.sub(r"[^a-z0-9]+", " ", (role or "").lower()) + " "
    for rank, keys in RANKS:
        if any(f" {k.strip()} " in words for k in keys):
            return rank
    return 1


def main() -> int:
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    ap = argparse.ArgumentParser(description="Order a job queue most-senior-first.")
    ap.add_argument("--queue", default=os.path.join(root, "state", "queue.tsv"))
    ap.add_argument("--dry-run", action="store_true", help="print the new order, do not write")
    ap.add_argument("--keep-file-order", action="store_true",
                    help="no-op order (leave the file as-is)")
    args = ap.parse_args()

    if not os.path.isfile(args.queue):
        print(f"queue not found: {args.queue}", file=sys.stderr)
        return 2

    header, rows = [], []
    with open(args.queue, encoding="utf-8") as fh:
        for line in fh:
            s = line.rstrip("\n")
            if not s.strip():
                continue
            if s.lstrip().startswith("#"):
                header.append(s)
                continue
            fields = s.split("\t")
            if len(fields) < 2:
                continue
            rows.append(fields)

    ordered = rows if args.keep_file_order else sorted(rows, key=lambda f: -seniority(f[1]))

    out_lines = header + ["\t".join(f) for f in ordered]
    if args.dry_run:
        for i, f in enumerate(ordered, 1):
            print(f"  {seniority(f[1]):>2}  {f[0][:24]:<24} | {f[1]}")
        moved = sum(1 for a, b in zip(rows, ordered) if a != b)
        print(f"\n{len(ordered)} rows; {moved} would move (dry run, not written)")
        return 0

    with open(args.queue, "w", encoding="utf-8") as fh:
        fh.write("\n".join(out_lines) + "\n")
    print(f"reordered {len(ordered)} rows in {args.queue} (most senior first)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
