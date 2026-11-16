#!/usr/bin/env python3
"""Append a completed-run summary to the dashboard agent transcript.

Runs are detached from the chat, so without this the operator only sees the
runner badge stop and has to go digging. The dashboard reads
`state/logs/dashboard-chat.log`; a `> [run] ...` line is rendered as a status
segment in the Agent pane.

Usage:
  python3 tools/notify_agent.py --queue state/queue.tsv --summary /tmp/run.md --parallel 3
"""
from __future__ import annotations

import argparse
import os
import re
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG = os.environ.get("DASHBOARD_CHAT_LOG") or os.path.join(
    ROOT, "state", "logs", "dashboard-chat.log")
HISTORY = os.path.join(ROOT, "state", "logs", "run-complete.log")
sys.path.insert(0, os.path.join(ROOT, "tools"))
try:
    import register as REG
except Exception:  # notification must never break the runner
    REG = None


def clean(text, limit=400):
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    return text[:limit]


def read_summary(path):
    """Keep the last outcome per company/role (retries produce several lines)."""
    rows, order = {}, []
    try:
        lines = open(path, encoding="utf-8", errors="ignore").read().splitlines()
    except OSError:
        return []
    for line in lines:
        line = line.strip()
        if not line.startswith("- "):
            continue
        body = line[2:]
        # "Company — Role: STATUS (reason)"; the register is the source of truth
        # if an orphaned worker finished after the runner's own outcome line.
        company, role, status, reason = "", "", "", ""
        if " — " in body and ": " in body.split(" — ", 1)[1]:
            company, rest = body.split(" — ", 1)
            role, status_reason = rest.split(": ", 1)
            status, _, reason = status_reason.partition(" (")
            reason = reason.rstrip(")")
            if REG is not None:
                try:
                    row = REG.find_row(company, role)
                    if row and row.get("status"):
                        if (row["status"] != status and
                                row["status"] in ("PREPARED", "SUBMITTED", "INTERVIEW",
                                                  "OFFER", "IN_PROGRESS")):
                            reason = ""
                        status = row["status"]
                except Exception:
                    pass
            body = f"{company} — {role}: {status}" + (f" ({reason})" if reason else "")
        key = (company + "|" + role) if company else body.split(":", 1)[0]
        if key not in rows:
            order.append(key)
        rows[key] = body
    return [rows[k] for k in order]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--queue", default="")
    ap.add_argument("--summary", default="")
    ap.add_argument("--parallel", default="1")
    ap.add_argument("--label", default="")
    args = ap.parse_args()

    queue = clean(args.queue, 140) or "queue"
    if "bench" in os.path.basename(queue).lower():
        return 0
    label = clean(args.label, 80) or f"run complete — {os.path.basename(queue)} (PARALLEL={args.parallel})"
    rows = read_summary(args.summary) if args.summary else []
    lines = [f"run complete — {os.path.basename(queue)} (PARALLEL={args.parallel})"]
    if rows:
        lines += ["  " + row for row in rows]
    else:
        lines.append("  no task outcomes were recorded")
    text = "\n".join("> [run] " + ln for ln in lines) + "\n"
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    with open(LOG, "a", encoding="utf-8") as fh:
        fh.write("\n" + text)
    with open(HISTORY, "a", encoding="utf-8") as fh:
        fh.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S')} {label}\n{text}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
