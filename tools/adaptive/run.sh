#!/usr/bin/env bash
# Adaptive harness launcher. Runs a SEPARATE agent on a dedicated browser and
# profile to solve one unknown application-form blocker, then returns one JSON
# line. It never touches the main run's browser, lock or register.
#
#   bash tools/adaptive/run.sh --company "Acme" --role "Staff Engineer" \
#       --url "https://..." --cv documents/applications/Acme_CV_staff.docx \
#       --key acme-staff --blocker "unknown multi-step wizard"
#
# Env:
#   ADAPTIVE_PORT      default 9899
#   ADAPTIVE_PROFILE   default ~/.config/job-search/profiles/adaptive
#   ADAPTIVE_MODEL     default: the dashboard's configured model
#   ADAPTIVE_TIMEOUT   default 900 seconds
set -u
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT" || exit 1
LOGS="${LOGS:-$ROOT/state/logs}"
mkdir -p "$LOGS"

company="" role="" url="" cv="" key="" blocker=""
while [ $# -gt 0 ]; do
  case "$1" in
    --company) company="${2:-}"; shift 2 ;;
    --role) role="${2:-}"; shift 2 ;;
    --url) url="${2:-}"; shift 2 ;;
    --cv) cv="${2:-}"; shift 2 ;;
    --key) key="${2:-}"; shift 2 ;;
    --blocker) blocker="${2:-}"; shift 2 ;;
    -h|--help) sed -n '2,20p' "$0"; exit 0 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done
[ -n "$company" ] && [ -n "$role" ] && [ -n "$url" ] || {
  echo "usage: run.sh --company <c> --role <r> --url <u> [--cv <path>] [--key <k>] [--blocker <text>]" >&2
  exit 2
}
key="${key:-$(printf '%s-%s' "$company" "$role" | tr ' /|' '___' | tr -cd 'A-Za-z0-9._-')}"
port="${ADAPTIVE_PORT:-9899}"
server="http://127.0.0.1:$port"
profile="${ADAPTIVE_PROFILE:-$HOME/.config/job-search/profiles/adaptive}"
log="$LOGS/adaptive-$key.log"

# A dedicated browser on a dedicated profile: the main run's session is never
# reused, so a stuck page there cannot poison the adaptive attempt.
if ! curl -s -m 3 "$server/health" >/dev/null 2>&1; then
  py=""
  for _p in python3 /usr/bin/python3 "$ROOT/.venv/bin/python3"; do
    command -v "$_p" >/dev/null 2>&1 || continue
    "$_p" -c 'import camoufox' >/dev/null 2>&1 && { py="$_p"; break; }
  done
  py="${py:-python3}"
  mkdir -p "$profile"
  setsid nohup "$py" "$ROOT/tools/camoufox_server.py" --port "$port" --profile "$profile" \
    >> "$LOGS/adaptive-server-$port.log" 2>&1 < /dev/null 9>&- &
  disown
  for _ in $(seq 1 40); do
    curl -s -m 3 "$server/health" >/dev/null 2>&1 && break
    sleep 1
  done
  curl -s -m 3 "$server/health" >/dev/null 2>&1 || {
    printf '{"ok":false,"blocker":"adaptive browser did not start on %s","url":"%s"}\n' "$server" "$url"
    exit 1
  }
fi

prompt="$(cat <<EOF
You are the ADAPTIVE HARNESS, separate from the main pipeline. Read
$ROOT/tools/adaptive/AGENT.md first and obey its boundary: solve unknown forms
and widgets, never CAPTCHA, 2FA, rate limits, paywalls, fees or site terms.

Task
  company: $company
  role:    $role
  apply:   $url
  CV:      ${cv:-the prepared CV for this role, find it under documents/applications/}
  blocker: ${blocker:-unknown form blocker}

Browser (dedicated server and profile):
  python3 tools/camoufox_browser.py --server $server <cmd>

Candidate data: config/profile.md and config/cv.json. Use only real values.
Write only under tools/adaptive/ (recipes, adapters, notes). The main harness,
config/, state/applications.csv and the queue files are read-only.

If you solve it, verify a confirmation and save a recipe. Return exactly one
JSON line as described in AGENT.md.
EOF
)"

echo "adaptive: $company / $role -> $server (log: $log)" >&2
MODEL="${ADAPTIVE_MODEL:-${MODEL:-}}" timeout -k 30s "${ADAPTIVE_TIMEOUT:-900}" \
  bash "$ROOT/tools/agent_run.sh" "$prompt" >"$log" 2>&1
rc=$?

python3 - "$log" <<'PY'
import json, re, sys
try:
    text = open(sys.argv[1], encoding="utf-8", errors="ignore").read()
except OSError:
    text = ""
found = None
for line in reversed(text.splitlines()):
    line = line.strip()
    if line.startswith('{"ok"'):
        try:
            found = json.loads(line)
            break
        except ValueError:
            continue
if found is None:
    tail = " ".join(text.strip().splitlines()[-3:])[:300]
    print(json.dumps({"ok": False, "blocker": "adaptive agent returned no result",
                      "notes": tail}))
    sys.exit(1)
print(json.dumps(found, ensure_ascii=False))
sys.exit(0 if found.get("ok") else 3)
PY
