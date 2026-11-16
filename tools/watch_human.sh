#!/usr/bin/env bash
ROOT="${ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
exec python3 "$ROOT/tools/watch_human.py" "$@"
