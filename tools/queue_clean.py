#!/usr/bin/env python3
"""Keep the active queue to work that is actually pending.

`state/queue.tsv` accumulated every row ever queued. A row whose key or
company|role is in `state/queue.done`, or whose register row is already
SUBMITTED/INTERVIEW/OFFER/REJECTED/CLOSED/BLOCKED/MANUAL, is not work to do.
It made a prepared or submitted role look queued and let a stale row be picked
up again. This removes those rows and leaves:

- a row with no register row that is not finished (genuine pending work),
- a register row still at QUEUED, DRAFTING or PREPARED.

`queue.done` is the history and is never changed here.

Usage:
  python3 tools/queue_clean.py            # report
  python3 tools/queue_clean.py --apply    # rewrite state/queue.tsv
"""
from __future__ import annotations

import argparse
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import register as REG  # noqa: E402

QUEUE = os.path.join(ROOT, "state", "queue.tsv")
DONE = os.path.join(ROOT, "state", "queue.done")

PENDING_STATUSES = {"QUEUED", "DRAFTING", "PREPARED"}


def _done() -> set[str]:
    try:
        return {line.strip() for line in open(DONE, encoding="utf-8") if line.strip()}
    except OSError:
        return set()


def plan() -> tuple[list[tuple[int, str, str]], list[str]]:
    """Return (rows to remove, rows to keep) from the active queue."""
    done = _done()
    reg = {(r.get("company", "").strip().lower(), r.get("role", "").strip().lower()): r
           for r in REG.load()}
    remove, keep = [], []
    try:
        lines = open(QUEUE, encoding="utf-8").read().splitlines(True)
    except OSError:
        return [], []
    for lineno, line in enumerate(lines, 1):
        if not line.strip() or line.startswith("#"):
            keep.append(line)
            continue
        f = (line.rstrip("\n").split("\t") + [""] * 6)[:6]
        pair = f"{f[0]}|{f[1]}"
        row = reg.get((f[0].strip().lower(), f[1].strip().lower()))
        status = ((row or {}).get("status") or "").upper()
        if pair in done or (f[5] and f[5] in done):
            remove.append((lineno, line.rstrip("\n"), "finished"))
        elif row and status and status not in PENDING_STATUSES:
            remove.append((lineno, line.rstrip("\n"), f"register {status}"))
        else:
            keep.append(line)
    return remove, keep


def main() -> int:
    ap = argparse.ArgumentParser(description="Remove finished or already-recorded rows from the active queue.")
    ap.add_argument("--apply", action="store_true", help="rewrite state/queue.tsv")
    args = ap.parse_args()

    remove, keep = plan()
    print(f"active queue: {len(remove) + len([l for l in keep if l.strip() and not l.startswith('#')])} row(s)")
    print(f"remove: {len(remove)}  keep: {len([l for l in keep if l.strip() and not l.startswith('#')])}")
    for lineno, line, why in remove[:25]:
        f = line.split("\t")
        print(f"  {lineno}: {f[0]} | {f[1][:55]}  ({why})")
    if len(remove) > 25:
        print(f"  ... and {len(remove) - 25} more")
    if args.apply:
        with open(QUEUE, "w", encoding="utf-8") as fh:
            fh.writelines(keep)
        print("rewrote state/queue.tsv")
    else:
        print("dry run; add --apply to rewrite state/queue.tsv")
    return 0


if __name__ == "__main__":
    sys.exit(main())
