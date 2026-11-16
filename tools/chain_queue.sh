#!/usr/bin/env bash
# Wait for any running tools/run_queue.sh to finish, then start a fresh queue run.
# Used to chain a second batch (e.g. newly discovered roles) without running two
# pools at once against the single Camoufox browser server.
#
# Usage:  PARALLEL=5 bash tools/chain_queue.sh
set -u
ROOT="${ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
while pgrep -f 'run_queue[.]sh' >/dev/null 2>&1; do sleep 20; done
echo "chain: previous run finished, starting $(date '+%H:%M:%S')" >> "$ROOT/state/logs/run_queue.out"
cd "$ROOT" && PARALLEL="${PARALLEL:-5}" exec bash "$ROOT/tools/run_queue.sh"
