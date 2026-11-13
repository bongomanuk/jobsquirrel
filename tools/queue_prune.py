#!/usr/bin/env python3
"""Park queue rows that are already applied to, blocked or closed.

The active queue should only contain work that is still worth spending a worker
and a model budget on. A row whose register status is SUBMITTED, INTERVIEW,
OFFER, REJECTED, CLOSED or BLOCKED is finished: keep it in the register (the
source of truth) and move the queue line to a parked file so a repost cannot
sneak it back into a run.

    python3 tools/queue_prune.py                 # report only
    python3 tools/queue_prune.py --apply         # move them
    python3 tools/queue_prune.py --queue state/queue-prepare.tsv --apply

The parked file keeps the six queue fields and adds the status and the date, so
"why is this not running" is answerable without opening the register.
"""
from __future__ import annotations

import argparse
import csv
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REGISTER = os.path.join(ROOT, "state", "applications.csv")
PARKED = os.path.join(ROOT, "state", "queue-parked.tsv")

FINISHED = {"SUBMITTED", "INTERVIEW", "OFFER", "REJECTED", "CLOSED", "BLOCKED"}
PARKED_HEADER = ["company", "role", "url", "cv", "ats", "key", "status", "date"]


def norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


def load_register() -> tuple[dict, dict]:
    by_key: dict[str, dict] = {}
    by_pair: dict[tuple[str, str], dict] = {}
    if not os.path.exists(REGISTER):
        return by_key, by_pair
    with open(REGISTER, newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            key = (row.get("key") or "").strip()
            if key:
                by_key[key] = row
            by_pair[(norm(row.get("company")), norm(row.get("role")))] = row
    return by_key, by_pair


def read_queue(path: str) -> list[list[str]]:
    rows: list[list[str]] = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.rstrip("\n")
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            rows.append(line.split("\t"))
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--queue", action="append", default=[],
                    help="queue file (repeatable); default state/queue.tsv")
    ap.add_argument("--parked", default=PARKED, help="parked output file")
    ap.add_argument("--apply", action="store_true", help="write the changes")
    args = ap.parse_args()

    queues = args.queue or [os.path.join(ROOT, "state", "queue.tsv")]
    by_key, by_pair = load_register()

    parked_rows: list[list[str]] = []
    seen_parked: set[str] = set()
    total_moved = 0

    for qpath in queues:
        if not os.path.exists(qpath):
            print(f"missing queue: {qpath}", file=sys.stderr)
            continue
        rows = read_queue(qpath)
        keep: list[list[str]] = []
        moved: list[list[str]] = []
        for f in rows:
            f = (f + [""] * 6)[:6]
            company, role, url, cv, ats, key = f
            reg = by_key.get(key) if key else None
            if reg is None:
                reg = by_pair.get((norm(company), norm(role)))
            status = (reg.get("status") if reg else "").strip().upper()
            if status in FINISHED:
                moved.append(f + [status, reg.get("date", "")])
                ident = key or f"{company}|{role}"
                if ident not in seen_parked:
                    seen_parked.add(ident)
                    parked_rows.append(f + [status, reg.get("date", "")])
            else:
                keep.append(f)
        total_moved += len(moved)
        print(f"{os.path.relpath(qpath, ROOT)}: {len(rows)} rows, "
              f"{len(moved)} to park, {len(keep)} kept")
        for f in moved:
            print(f"  park {f[6]:9} | {f[0]} | {f[1]}")
        if args.apply:
            tmp = qpath + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                for f in keep:
                    fh.write("\t".join(f[:6]) + "\n")
            os.replace(tmp, qpath)

    if args.apply and parked_rows:
        exists = os.path.exists(args.parked) and os.path.getsize(args.parked) > 0
        with open(args.parked, "a", encoding="utf-8") as fh:
            if not exists:
                fh.write("\t".join(PARKED_HEADER) + "\n")
            for f in parked_rows:
                fh.write("\t".join(f) + "\n")
    print(f"{'parked' if args.apply else 'would park'}: {len(parked_rows)} unique rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
