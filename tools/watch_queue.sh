#!/usr/bin/env bash
# Live dashboard for the queue run currently in progress (curses TUI).
# Shows only the active run's tasks — never the historical/applied jobs.
# Keys: q/Esc quit, r refresh.  Usage: bash tools/watch_queue.sh [--queue PATH]
set -u
ROOT="${ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
exec python3 "$ROOT/tools/watch_queue.py" "$@"
