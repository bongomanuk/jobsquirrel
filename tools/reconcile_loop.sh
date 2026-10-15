#!/usr/bin/env bash
# Reconcile the pipeline against Gmail on a loop and keep the counts up to date.
#
# Each cycle:
#   1. tools/gmail_reconcile.py --apply   (mark INTERVIEW / REJECTED / SUBMITTED, upgrade PREPARED)
#   2. tools/register.py --render         (regenerate applications-register.md)
#   3. tools/register.py --check           (consistency check)
#   4. tools/register.py --stats           (write state/counts.md)
#
# Usage:
#   bash tools/reconcile_loop.sh              # loop every INTERVAL seconds (default 600)
#   bash tools/reconcile_loop.sh --once       # run a single cycle and exit
#   INTERVAL=300 bash tools/reconcile_loop.sh
set -u
ROOT="${ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
PY="$ROOT/.venv/bin/python"
INTERVAL="${INTERVAL:-600}"
LOGS="$ROOT/state/logs"
mkdir -p "$LOGS"
ONCE=0
[ "${1:-}" = "--once" ] && ONCE=1

cycle() {
  local ts; ts=$(date '+%Y-%m-%d %H:%M:%S')
  echo "=== reconcile $ts ===" >> "$LOGS/reconcile.log"
  "$PY" "$ROOT/tools/gmail_reconcile.py" --apply >> "$LOGS/reconcile.log" 2>&1
  "$PY" "$ROOT/tools/register.py" --render >> "$LOGS/reconcile.log" 2>&1
  "$PY" "$ROOT/tools/register.py" --check >> "$LOGS/reconcile.log" 2>&1
  {
    echo "# Application counts"
    echo
    echo "_Updated: $ts — source: Gmail reconcile loop_"
    echo
    echo '```'
    "$PY" "$ROOT/tools/register.py" --stats
    echo
    "$PY" "$ROOT/tools/register.py" --check
    echo '```'
  } > "$ROOT/state/counts.md"
}

while true; do
  cycle
  [ "$ONCE" = 1 ] && break
  sleep "$INTERVAL"
done
