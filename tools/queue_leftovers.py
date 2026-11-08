#!/usr/bin/env python3
"""Find and clear finished queue rows that never became a register row.

A queue is work to do, not an application. When a row finishes, its key or
"company|role" goes into state/queue.done. If no register row was ever created,
the old grid invented a NO RESULT application for it, which read like a real
state and could not be explained. A finished queue row with no register row is a
**queue leftover**: the work was attempted (or at least queued), but there is no
application identity to track.

The register stays the only place an application state lives. This tool lists
the leftovers with the artifacts that survive, so you can re-queue a live role
or leave it closed. `--drop` removes only the leftover rows from the active
queue files; state/queue.done and every artifact stay.

Usage:
  python3 tools/queue_leftovers.py                 # report
  python3 tools/queue_leftovers.py --write         # also write state/queue-leftovers.md
  python3 tools/queue_leftovers.py --drop          # remove the leftovers from the active queues
  python3 tools/queue_leftovers.py --drop --write
"""
from __future__ import annotations

import argparse
import glob
import os
import sys
from datetime import date

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import register as REG  # noqa: E402

QUEUES = ("state/queue.tsv", "state/queue.retry", "state/queue-human.tsv")
DONE = os.path.join(ROOT, "state", "queue.done")
QUARANTINE = os.path.join(ROOT, "state", "queue-leftovers.done")
QUARANTINE_TSV = os.path.join(ROOT, "state", "queue-leftovers.tsv")
REPORT = os.path.join(ROOT, "state", "queue-leftovers.md")
STATE = os.path.join(ROOT, "state")


def _done() -> set[str]:
    try:
        return {line.strip() for line in open(DONE, encoding="utf-8") if line.strip()}
    except OSError:
        return set()


def _queue_rows() -> list[dict]:
    rows = []
    for rel in QUEUES:
        path = os.path.join(ROOT, rel)
        if not os.path.exists(path):
            continue
        for lineno, line in enumerate(open(path, encoding="utf-8"), 1):
            if not line.strip() or line.startswith("#"):
                continue
            f = (line.rstrip("\n").split("\t") + [""] * 6)[:6]
            rows.append({
                "path": rel, "lineno": lineno, "company": f[0], "role": f[1],
                "url": f[2], "cv": f[3], "ats": f[4], "key": f[5],
            })
    return rows


def _artifacts(key: str) -> list[str]:
    if not key:
        return []
    found = []
    for rel in ("state/job-descriptions", "state/ats", "state/kb-context", "state/cv-content"):
        for ext in (".md", ".txt", ".json"):
            p = os.path.join(ROOT, rel, key + ext)
            if os.path.exists(p):
                found.append(os.path.relpath(p, ROOT))
    for p in glob.glob(os.path.join(ROOT, "documents", "applications", f"*_CV_{key}.docx")):
        found.append(os.path.relpath(p, ROOT))
    for p in glob.glob(os.path.join(ROOT, "documents", "applications", f"*_Motivation_{key}.docx")):
        found.append(os.path.relpath(p, ROOT))
    return found


def find_leftovers() -> list[dict]:
    done = _done()
    registered = {(r.get("company", "").strip().lower(), r.get("role", "").strip().lower())
                  for r in REG.load()}
    out = []
    for row in _queue_rows():
        ck = (row["company"].strip().lower(), row["role"].strip().lower())
        if ck in registered:
            continue
        pair = f"{row['company']}|{row['role']}"
        if pair not in done and (not row["key"] or row["key"] not in done):
            continue
        row["artifacts"] = _artifacts(row["key"])
        out.append(row)
    return out


def report(rows: list[dict]) -> str:
    lines = [
        "# Queue leftovers",
        "",
        f"Generated {date.today().isoformat()}. These are finished queue rows with no",
        "register row. They are **not application states**. A queue is work to do;",
        "the register is the application record. Each entry shows the artifacts that",
        "survive so you can re-queue a live role or leave it closed.",
        "",
        f"Total: {len(rows)}",
        "",
        "| Company | Role | Apply URL | CV / ATS | Key | Artifacts |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for r in rows:
        arts = "<br>".join(r["artifacts"]) if r["artifacts"] else "none"
        lines.append(
            f"| {r['company']} | {r['role']} | {r['url']} | {r['cv']} / {r['ats']} | "
            f"`{r['key']}` | {arts} |"
        )
    if not rows:
        lines.append("| — | — | — | — | — | — |")
    lines.extend([
        "",
        "The full rows are kept in `state/queue-leftovers.tsv`. Add a row back to",
        "`state/queue.tsv` to re-queue it, or leave it here. `--drop` removes these rows",
        "from the active queue files and keeps the done entries and all artifacts.",
        "",
    ])
    return "\n".join(lines)


def drop(rows: list[dict]) -> int:
    # Keep the full queue row, not just the key: a URL/CV/ATS is what makes a
    # later re-queue possible. state/queue-leftovers.done keeps the completion
    # entries; this TSV keeps the work.
    if rows:
        exists = os.path.exists(QUARANTINE_TSV)
        with open(QUARANTINE_TSV, "a", encoding="utf-8") as fh:
            if not exists:
                fh.write("# finished queue rows with no register row; append a line to state/queue.tsv to re-queue\n")
            for r in rows:
                fh.write("\t".join([r["company"], r["role"], r["url"], r["cv"], r["ats"], r["key"]]) + "\n")
    by_path: dict[str, set[int]] = {}
    for r in rows:
        by_path.setdefault(r["path"], set()).add(r["lineno"])
    removed = 0
    for rel, line_numbers in by_path.items():
        path = os.path.join(ROOT, rel)
        lines = open(path, encoding="utf-8").read().splitlines(True)
        kept = [line for i, line in enumerate(lines, 1) if i not in line_numbers]
        removed += len(lines) - len(kept)
        with open(path, "w", encoding="utf-8") as fh:
            fh.writelines(kept)
    return removed


def prune_done() -> int:
    """Move completed entries that have no register row and no active queue row.

    The audit rightly treats a queue.done key without a register row as a lost
    role. A quarantined leftover is not lost: its report is kept and its queue
    row is gone. Moving the entry here keeps the audit honest and lets a later
    re-queue run normally.
    """
    try:
        done_lines = [line.rstrip("\n") for line in open(DONE, encoding="utf-8") if line.strip()]
    except OSError:
        return 0
    rows = REG.load()
    registered = {(r.get("company", "").strip().lower(), r.get("role", "").strip().lower())
                  for r in rows}
    keys = {str(r.get("key") or "").strip() for r in rows if r.get("key")}
    active = set()
    for r in _queue_rows():
        active.add(r["key"])
        active.add(f"{r['company']}|{r['role']}")
    keep, moved = [], []
    for line in done_lines:
        if line in active:
            keep.append(line)
            continue
        if "|" in line:
            co, role = line.split("|", 1)
            if (co.strip().lower(), role.strip().lower()) in registered:
                keep.append(line)
            else:
                moved.append(line)
        elif line in keys:
            keep.append(line)
        else:
            moved.append(line)
    if not moved:
        return 0
    with open(DONE, "w", encoding="utf-8") as fh:
        fh.write("".join(line + "\n" for line in keep))
    exists = os.path.exists(QUARANTINE)
    with open(QUARANTINE, "a", encoding="utf-8") as fh:
        if not exists:
            fh.write("# finished queue entries with no register row (queue leftovers)\n")
        fh.write("".join(line + "\n" for line in moved))
    return len(moved)


def main() -> int:
    ap = argparse.ArgumentParser(description="Report or clear finished queue rows that never became a register row.")
    ap.add_argument("--drop", action="store_true", help="remove the leftovers from the active queue files")
    ap.add_argument("--write", action="store_true", help=f"write {os.path.relpath(REPORT, ROOT)}")
    ap.add_argument("--prune-done", action="store_true",
                    help="move finished entries with no register row to state/queue-leftovers.done")
    ap.add_argument("--out", default=REPORT)
    args = ap.parse_args()

    rows = find_leftovers()
    text = report(rows)
    print(text)
    if args.write:
        os.makedirs(os.path.dirname(args.out), exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(text + "\n")
        print(f"\nwrote {os.path.relpath(args.out, ROOT)}")
    if args.drop and rows:
        n = drop(rows)
        print(f"removed {n} leftover row(s) from the active queue")
        args.prune_done = True
    elif args.drop:
        print("nothing to drop")
    if args.prune_done:
        n = prune_done()
        print(f"quarantined {n} finished entry(ies) in {os.path.relpath(QUARANTINE, ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
