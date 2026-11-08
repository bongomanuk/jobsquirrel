#!/usr/bin/env bash
# Focused HUMAN-ASSIST runner.
#
# For each role blocked ONLY by a human step, this opens it in a VISIBLE
# (headful) Camoufox browser, pre-fills everything (identity, CV, cover letter),
# then PAUSES so YOU solve the human challenge and click Submit. One role at a
# time. It never solves/evades a CAPTCHA.
#
# Browser: Camoufox (tools/camoufox_server.py --headful + tools/camoufox_browser.py).
# Agent: opencode, Claude Code or any CLI (tools/agent_run.sh; AGENT=claude to pick).
# The --manual path opens the URL in YOUR real browser (xdg-open, or open on
# macOS); no pipeline browser or agent is involved there.
#
# Usage:
#   bash tools/human_assist.sh                 # pre-fill via headful Camoufox
#   HUMAN_SERVER=http://127.0.0.1:9871 bash tools/human_assist.sh
#   AGENT=claude bash tools/human_assist.sh
#   bash tools/human_assist.sh --build         # refresh state/queue-human.tsv first
#   bash tools/human_assist.sh --manual        # open each role in your real browser
set -u
ROOT="${ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
cd "$ROOT" || exit 1   # the prompts and the agent use repo-relative paths

# Use the project venv (tools/install.sh) when there is one and none is active,
# so python3 has python-docx, camoufox etc. for the runner and the agent alike.
if [ -z "${VIRTUAL_ENV:-}" ] && [ -x "$ROOT/.venv/bin/python3" ]; then
  VIRTUAL_ENV="$ROOT/.venv"; PATH="$VIRTUAL_ENV/bin:$PATH"; export VIRTUAL_ENV
fi
# macOS has no flock/setsid/timeout, so tools/compat provides portable stand-ins.
# They go LAST on PATH: the real commands win wherever they exist. The agent is
# told the full path to the stand-in, because its shell may rebuild PATH.
TIMEOUT_CMD=timeout
command -v timeout >/dev/null 2>&1 || TIMEOUT_CMD="$ROOT/tools/compat/timeout"
PATH="$PATH:$ROOT/tools/compat"; export PATH
# The user's own browser: `open` on macOS, xdg-open elsewhere.
OPEN_CMD=xdg-open
[ "$(uname)" = "Darwin" ] && OPEN_CMD=open

QUEUE="${QUEUE:-$ROOT/state/queue-human.tsv}"
DONE="${DONE:-$ROOT/state/queue-human.done}"
LOGS="$ROOT/state/logs"
PROFILE="${HUMAN_PROFILE:-human}"
PORT="${HUMAN_PORT:-9874}"
mkdir -p "$LOGS"; touch "$QUEUE" "$DONE"
# Publish the active pointers so the normal pipeline viewer (watch_queue.sh)
# follows the human-assist run, not the (separate) main queue.
printf '%s\n' "$QUEUE" > "$ROOT/state/active_queue"
printf '%s\n' "$DONE" > "$ROOT/state/active_done"
printf '1\n' > "$ROOT/state/active_parallel"
MANUAL="${MANUAL:-0}"
CAPTCHA_ONLY=0
DO_BUILD=0
while [ $# -gt 0 ]; do
  case "$1" in
    --manual)       MANUAL=1 ;;
    --captcha-only) CAPTCHA_ONLY=1; DO_BUILD=1 ;;
    --build)        DO_BUILD=1 ;;
  esac
  shift
done
if [ "$DO_BUILD" = "1" ]; then
  if [ "$CAPTCHA_ONLY" = "1" ]; then
    python3 "$ROOT/tools/build_human_queue.py" --only captcha
  else
    python3 "$ROOT/tools/build_human_queue.py"
  fi
fi

# MANUAL mode: open each role in the user's REAL browser (no automation at all, so
# nothing gets flagged). The pipeline browser is not used in this mode.
if [ "$MANUAL" = "1" ]; then
  echo "MANUAL mode: opening each role in your real browser (via $OPEN_CMD). No automation."
  while IFS= read -r row; do
    # A tab is IFS whitespace, so `read -r` would collapse an empty letter field
    # and shift the reason into it. Read the line, then split on a non-whitespace
    # separator so every field, including an empty one, is preserved.
    IFS=$'\x1f' read -r company role url cv letter reason <<< "${row//$'\t'/$'\x1f'}"
    [ -z "${company:-}" ] && continue
    case "$company" in \#*) continue ;; esac
    grep -qxF "$company|$role" "$DONE" && continue
    python3 "$ROOT/tools/human_status.py" set --company "$company" --role "$role" --state awaiting --note "apply in your own browser: $reason" >/dev/null
    echo
    echo "================================================================"
    echo " $company — $role"
    echo " blocker : $reason"
    echo " url     : $url"
    echo " cv      : $cv"
    echo " letter  : $letter"
    echo "================================================================"
    [ -n "$url" ] && "$OPEN_CMD" "$url" >/dev/null 2>&1 &
    echo "-- Apply in your own browser, then come back here."
    printf "    press Enter when done (or 's'+Enter to skip): "
    read -r ans || ans=""
    if [ "${ans:-}" != "s" ]; then
      echo "$company|$role" >> "$DONE"
      python3 "$ROOT/tools/human_status.py" set --company "$company" --role "$role" --state done --note "submitted manually" >/dev/null
    fi
  done < "$QUEUE"
  echo "manual human-assist complete $(date +%H:%M:%S)"
  exit 0
fi

# The coding agent that pre-fills each form: opencode | claude | any command.
# No default MODEL here: each agent uses its own unless MODEL=... is set.
AGENT="$(bash "$ROOT/tools/agent_run.sh" --which)" || exit 1
export AGENT TIMEOUT_CMD

# --- ensure a HEADFUL Camoufox instance for human work ------------------------
if [ -z "${HUMAN_SERVER:-}" ]; then
  HUMAN_SERVER="http://127.0.0.1:$PORT"
fi
if ! curl -s -m 3 "$HUMAN_SERVER/health" >/dev/null 2>&1; then
  echo "starting headful camoufox server on port $PORT ..."
  # camoufox may live outside the project venv, so start the server with an
  # interpreter that can actually import it.
  HUMAN_PY=""
  for _p in python3 /usr/bin/python3 "$ROOT/.venv/bin/python3"; do
    command -v "$_p" >/dev/null 2>&1 || continue
    "$_p" -c 'import camoufox' >/dev/null 2>&1 && { HUMAN_PY="$_p"; break; }
  done
  HUMAN_PY="${HUMAN_PY:-python3}"
  setsid nohup "$HUMAN_PY" "$ROOT/tools/camoufox_server.py" --port "$PORT" --headful \
    --os "${HUMAN_OS:-linux}" --profile "${HUMAN_PROFILE:-$HOME/.config/job-search/human-profile}" \
    --disable-coop --main-world-eval \
    >> "$LOGS/camoufox_server.log" 2>&1 < /dev/null &
  disown
  # give it time to launch the visible browser
  for _ in $(seq 1 30); do
    curl -s -m 3 "$HUMAN_SERVER/health" >/dev/null 2>&1 && { echo "browser ready"; break; }
    sleep 1
  done
  if ! curl -s -m 3 "$HUMAN_SERVER/health" >/dev/null 2>&1; then
    echo "WARN: camoufox server did not come up on $PORT — see $LOGS/camoufox_server.log" >&2
  fi
fi
echo "Human-assist browser: $HUMAN_SERVER (VISIBLE Camoufox). Queue: $QUEUE"

build_prompt() {
  local company="$1" role="$2" url="$3" cv="$4" letter="$5" reason="$6" key="$7"
  local LETTER_LINE="" LETTER_ARG=""
  if [ -n "$letter" ] && [ "$letter" != "-" ] && [ -f "$letter" ]; then
    LETTER_LINE="Cover letter: $letter (upload this exact file)"
    LETTER_ARG="--letter \"$letter\""
  else
    LETTER_LINE="Cover letter: none (do not create or upload one)"
  fi
  cat <<EOF
You are helping the candidate described in config/profile.md finish ONE application. Repo: $ROOT (cwd).
Company: $company
Role: $role
Blocker (the part the pipeline could not do): ${reason:-none recorded}
Apply URL: $url
If Apply URL is empty, find the employer's OWN apply URL with a web search (Lever/Greenhouse/Ashby/Workday/Teamtailor/their careers site) and go straight there. Work fast.
CV: $cv
$LETTER_LINE
EEO/diversity questions: read config/profile.md first and use its identity, work-authorisation, pay and standard diversity/EEO answers exactly. Never decline these or choose "prefer not to say" unless profile.md says so.
The CV above is ALREADY PREPARED. Upload that exact file. Do NOT generate, re-render or edit any document, and do not run GraphRAG.

Browser: run every command as \`python3 tools/camoufox_browser.py --server $HUMAN_SERVER <cmd>\` (nav/snap/click/fill/select/check/upload/value/eval/wait). Prefix \`$TIMEOUT_CMD 30\`. This browser is VISIBLE to the human.
At the start run: \`python3 tools/human_status.py set --company "$company" --role "$role" --state filling --note "pre-filling the form"\`

Steps:
1. Open the Apply URL and pre-fill EVERYTHING: identity (name/email/phone, location, work authorisation, pay) from config/profile.md, the CV and cover letter above, and every question you can answer truthfully.
   ACCOUNT CREATION IS YOUR JOB, not a handoff:
   - Try \`python3 tools/accounts.py --get <site-host>\`.
   - If there is no entry, run \`python3 tools/accounts.py --for <site-host> --email <the candidate email in config/profile.md>\`. It generates a strong password and stores it in the encrypted secrets store. Fill the sign-in or create-account form with it.
   - NEVER print the password, NEVER invent one, and NEVER stop just because the form asks you to choose one.
   Identify the Submit button.
2. With every field filled, CLICK SUBMIT ONCE to trigger the challenge. The challenge is the ONLY human step: do not solve, bypass or evade it. If the submit succeeds, skip to step 5.
3. Announce ONLY the challenge (this fires a desktop notification + the focused viewer): \`python3 tools/human_status.py set --company "$company" --role "$role" --state awaiting --note "<the exact challenge: e.g. ByteDance slider, hCaptcha, 2FA code, email code>"\`, then print a LOUD banner: ">>> SOLVE THE CHALLENGE IN THE VISIBLE BROWSER - everything else is already done for you <<<".
4. WAIT for the human to solve that one step. Poll every ~5s and treat it as solved when ANY of these is true: the challenge container or frame is gone (\`#captcha_container\`, \`#slideValidatorV2\`, \`[class*=slide-wrapper]\`, \`iframe[src*=recaptcha]\`, \`iframe[src*=hcaptcha]\`, \`iframe[src*=turnstile]\`), the URL changed, the next step or a thank-you page is visible, or the site's token is present. Do not keep waiting for a reCAPTCHA token that this site does not use. Poll up to 20 minutes.
5. ONCE SOLVED, finish the application yourself. This includes any account password (from accounts.py), every remaining form field, the final Submit, the thank-you page, the gates and the record. Hand back ONLY a CAPTCHA/2FA/email code/verification link you cannot complete, or a decision profile.md does not answer. Do not stop at a password, an empty field or a new page.
   The pre-submit gate must pass first (it writes the receipt record_submission.py requires):
   \`python3 tools/check_documents.py $LETTER_ARG --cv "$cv" --company "$company" --record\`  (must print RESULT: PASS)
   \`python3 tools/human_status.py set --company "$company" --role "$role" --state done --note "submitted after the human cleared the challenge"\`
   \`python3 tools/record_submission.py --company "$company" --role "$role" --ats "human-assisted" --url "$url" --cv "$cv" $LETTER_ARG --status SUBMITTED --evidence "<exact thank-you text/URL>"\`
6. If it is still unsolved after 20 minutes, or Submit fails, run \`python3 tools/human_status.py set --company "$company" --role "$role" --state done --note "not completed"\` and leave the register row BLOCKED with note "human step not completed".
Never fabricate. Never submit a document that did not come from the pipeline. Never bypass or evade a challenge yourself.

Return exactly one line: STATUS <Company> | $role | SUBMITTED|BLOCKED | <reason> | CV: $cv | letter: ${LETTER_LINE#Cover letter: }
EOF
}

while IFS= read -r row; do
  # Preserve an empty cover-letter field; a tab-delimited `read` would drop it
  # and put the blocker text into $letter (it then reached the agent as a
  # cover letter and the record command).
  IFS=$'\x1f' read -r company role url cv letter reason <<< "${row//$'\t'/$'\x1f'}"
  [ -z "${company:-}" ] && continue
  case "$company" in \#*) continue ;; esac
  grep -qxF "$company|$role" "$DONE" && continue
  key="$(echo "$company-$role" | tr ' /|' '___')"
  log="$LOGS/$key.human.log"
  echo
  echo "================================================================"
  echo " $company — $role"
  echo " blocker : $reason"
  echo " url     : $url"
  echo " cv      : $cv"
  echo " letter  : $letter"
  echo "================================================================"
  "$TIMEOUT_CMD" 1500 bash "$ROOT/tools/agent_run.sh" \
    "$(build_prompt "$company" "$role" "$url" "$cv" "$letter" "$reason" "$key")" 2>&1 </dev/null | tee -a "$log"
  echo "$company|$role" >> "$DONE"
  echo "-- done. next role in a moment (Ctrl-C to stop) --"
  if [ -t 0 ]; then read -r _ < /dev/tty || true; else sleep 2; fi
done < "$QUEUE"
echo "human-assist queue complete $(date +%H:%M:%S)" | tee -a "$LOGS/human_assist.out"
