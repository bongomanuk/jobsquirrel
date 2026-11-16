#!/usr/bin/env bash
# Re-queue tasks so a later run retries them.
#
# By default re-queues everything the register currently marks BLOCKED - use it
# after you have cleared a human step (e.g. signed into an account, solved a
# captcha) so the pipeline gets another go at them. Removes those (company|role)
# keys from state/queue.done, so the next tools/run_queue.sh picks them up again.
#
# Usage:
#   bash tools/requeue_blocked.sh                 # re-queue BLOCKED tasks
#   bash tools/requeue_blocked.sh --status CLOSED # re-queue another status
set -u
ROOT="${ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
STATUS="BLOCKED"
while [ $# -gt 0 ]; do
  case "$1" in
    --status) STATUS="${2:-BLOCKED}"; shift 2 ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
done

ROOT="$ROOT" STATUS="$STATUS" python3 - <<'PY'
import csv, os, sys
root = os.environ["ROOT"]
status = os.environ["STATUS"]
csv_path = os.path.join(root, "state", "applications.csv")
done_path = os.path.join(root, "state", "queue.done")

keys = set()
for r in csv.DictReader(open(csv_path)):
    if r.get("status") == status:
        keys.add(f"{r['company']}|{r['role']}")

lines = [l.rstrip("\n") for l in open(done_path)] if os.path.exists(done_path) else []
kept = [l for l in lines if l not in keys]
removed = len(lines) - len(kept)
with open(done_path, "w") as f:
    f.write("\n".join(kept) + ("\n" if kept else ""))
print(f"re-queued {removed} {status} task(s) - run tools/run_queue.sh to retry them")
PY
