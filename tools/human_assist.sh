#!/usr/bin/env bash
# Focused HUMAN-ASSIST runner.
#
# For each role blocked ONLY by a human step, this opens it in a VISIBLE
# (headful) Camoufox browser, pre-fills everything (identity, CV, cover letter),
# then PAUSES so YOU solve the human challenge and click Submit. One role at a
# time. It never solves/evades a CAPTCHA.
#
# Browser: Camoufox (tools/camoufox_server.py --headful + tools/camoufox_browser.py).
# The --manual path opens the URL in YOUR real Firefox (xdg-open); no pipeline
# browser is involved there.
#
# Usage:
#   bash tools/human_assist.sh                 # pre-fill via headful Camoufox
#   HUMAN_SERVER=http://127.0.0.1:9871 bash tools/human_assist.sh
#   bash tools/human_assist.sh --build         # refresh state/queue-human.tsv first
#   bash tools/human_assist.sh --manual        # open each role in your real browser
set -u
ROOT="${ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
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
  echo "MANUAL mode: opening each role in your real browser (Firefox via xdg-open). No automation."
  while IFS=$'\t' read -r company role url cv letter reason; do
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
    [ -n "$url" ] && xdg-open "$url" >/dev/null 2>&1 &
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

# --- ensure a HEADFUL Camoufox instance for human work ------------------------
if [ -z "${HUMAN_SERVER:-}" ]; then
  HUMAN_SERVER="http://127.0.0.1:$PORT"
fi
if ! curl -s -m 3 "$HUMAN_SERVER/health" >/dev/null 2>&1; then
  echo "starting headful camoufox server on port $PORT ..."
  setsid nohup python3 "$ROOT/tools/camoufox_server.py" --port "$PORT" --headful \
    --os "${HUMAN_OS:-linux}" --profile "${HUMAN_PROFILE:-$HOME/.config/job-search/human-profile}" \
    --disable-coop --main-world-eval \
    >> "$LOGS/camoufox_server.log" 2>&1 < /dev/null &
  disown
  for _ in $(seq 1 20); do
    curl -s -m 3 "$HUMAN_SERVER/health" >/dev/null 2>&1 && break
    sleep 1
  done
fi
echo "Human-assist browser: $HUMAN_SERVER (VISIBLE Camoufox). Queue: $QUEUE"

build_prompt() {
  local company="$1" role="$2" url="$3" cv="$4" letter="$5" reason="$6" key="$7"
  cat <<EOF
You are helping the candidate described in config/profile.md finish ONE application that is blocked only by a HUMAN step. Repo: $ROOT (cwd).
Company: $company
Role: $role
Blocker (a human must act): $reason
Apply URL: $url
If Apply URL is empty, find the employer's OWN apply URL with a web search (Lever/Greenhouse/Ashby/Workday/Teamtailor/their careers site) and go straight there - do NOT grep or explore the repo to find it. Work fast: your only job is to pre-fill this one form.
CV: $cv
Cover letter: $letter
EEO/diversity questions: read config/profile.md first and use its identity, work-authorisation, pay and standard diversity/EEO answers exactly - never decline these or choose "prefer not to say" unless profile.md says so.

Browser: run every command as \`python3 tools/camoufox_browser.py --server $HUMAN_SERVER <cmd>\` (nav/snap/click/fill/select/check/upload/value/eval/wait). Prefix \`timeout 30\`. This browser is VISIBLE to the human.

Steps:
1. Open the Apply URL. Pre-fill EVERYTHING so the human only has to solve the challenge: identity (name/email/phone, location, work authorisation, pay) from config/profile.md, upload the CV and cover letter, and answer any questions truthfully. Identify the Submit button now (e.g. \`python3 tools/camoufox_browser.py --server $HUMAN_SERVER eval "(()=>JSON.stringify([...document.querySelectorAll('button,input[type=submit]')].map((b,i)=>({i,t:(b.innerText||b.value||'').trim().slice(0,40)})).filter(x=>/apply|submit/i.test(x.t)))())"\`). At the very start run: \`python3 tools/human_status.py set --company "$company" --role "$role" --state filling --note "pre-filling the form"\`
2. With every field filled, CLICK SUBMIT ONCE to trigger the challenge (hCaptcha/reCAPTCHA on ATS forms are usually INVISIBLE until submit - the token only appears after you click). Do NOT solve, bypass or evade the challenge. If the submit instead succeeds (thank-you page), skip to step 5.
3. Announce it (this fires a desktop notification + the focused viewer): \`python3 tools/human_status.py set --company "$company" --role "$role" --state awaiting --note "<one line, e.g. tick the 'I'm not a robot' box>"\`, then print a LOUD banner: ">>> SOLVE THE CHALLENGE IN THE VISIBLE BROWSER - everything else is already done for you <<<".
4. WAIT for the human to solve it. Every ~5s run: \`python3 tools/camoufox_browser.py --server $HUMAN_SERVER eval "(()=>{const q=s=>document.querySelector(s);const v=(q('textarea[name=g-recaptcha-response]')||q('textarea[name=h-captcha-response]')||q('input[name=cf-turnstile-response]')||{}).value||'';return JSON.stringify({solved:v.length>0});})()"\`. Treat it as solved when solved=true (or when the challenge text disappears). Poll up to 20 minutes.
5. ONCE SOLVED (token non-empty): wait ~3s. hCaptcha/reCAPTCHA normally submit the form itself on solve - do NOT click Submit again if the page has moved on. Only if you are still on the same /apply form after ~3s, click Submit ONCE. NEVER click Submit while the token is empty (that is what causes "error verifying your application"). Then confirm the success/thank-you page and record. The pre-submit gate must pass first (it writes the receipt record_submission.py requires); if there is no letter file, run the record with \`GATE_ENFORCE=0\` and say why:
   \`python3 tools/check_documents.py --letter "$letter" --cv "$cv" --company "$company" --record\`  (must print RESULT: PASS)
   \`python3 tools/human_status.py set --company "$company" --role "$role" --state done --note "captcha solved; auto-submitted"\`
   \`python3 tools/record_submission.py --company "$company" --role "$role" --ats "human-assisted" --url "$url" --cv "$cv" --letter "$letter" --status SUBMITTED --evidence "<exact thank-you text/URL>"\`
6. If it is still unsolved after 20 minutes, or Submit fails, run \`python3 tools/human_status.py set --company "$company" --role "$role" --state done --note "not completed"\` and leave the register row BLOCKED with note "human step not completed".
Never fabricate; never solve or evade a CAPTCHA yourself.

Return exactly one line: STATUS <Company> | $role | SUBMITTED|BLOCKED | <reason>
EOF
}

while IFS=$'\t' read -r company role url cv letter reason; do
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
  timeout 1500 opencode run "$(build_prompt "$company" "$role" "$url" "$cv" "$letter" "$reason" "$key")" 2>&1 | tee -a "$log"
  echo "$company|$role" >> "$DONE"
  echo "-- done. next role in a moment (Ctrl-C to stop) --"
  if [ -t 0 ]; then read -r _ < /dev/tty || true; else sleep 2; fi
done < "$QUEUE"
echo "human-assist queue complete $(date +%H:%M:%S)" | tee -a "$LOGS/human_assist.out"
