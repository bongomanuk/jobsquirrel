#!/usr/bin/env bash
# Queue runner: keep $PARALLEL agents busy, each pulling the next pending
# task from state/queue.tsv and applying to one job end-to-end. When a worker
# finishes, the pool launches the next task. Finished tasks go to state/queue.done.
#
# Browser: Camoufox (tools/camoufox_server.py + tools/camoufox_browser.py).
# Agent: opencode, Claude Code or any CLI (tools/agent_run.sh; AGENT=claude to pick).
#
# Usage:  PARALLEL=5 bash tools/run_queue.sh
#         AGENT=claude PARALLEL=3 bash tools/run_queue.sh
# Queue format (TAB-separated): company  role  url  cv  ats  key
set -u

# If this shell exits early (a completed pool, a crash, Ctrl-C), take any
# still-running worker with it. Timeout alone does not guarantee the agent
# process dies, and an orphaned worker used to keep the dashboard "running".
trap 'for _p in $(jobs -p); do kill "$_p" 2>/dev/null; done' EXIT
ROOT="${ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
cd "$ROOT" || exit 1   # the prompts, the duplicate guard and the agent all use repo-relative paths

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

QUEUE="${QUEUE:-$ROOT/state/queue.tsv}"
DONE="${DONE:-$ROOT/state/queue.done}"
LOGS="$ROOT/state/logs"

# Human progress goes to the shared run log AND to stdout. A dashboard action
# captures its own stdout, so its Activity pane shows exactly this run, never a
# time-window guess at run_queue.out that can pick up a concurrent or later run.
runlog() { printf '%s\n' "$*" >> "$LOGS/run_queue.out"; printf '%s\n' "$*"; }
SUMMARY_FILE="${SUMMARY_FILE:-$LOGS/run-summary-$$.md}"
: > "$SUMMARY_FILE"
PARALLEL="${PARALLEL:-5}"
# A task that has produced no useful output for this long is stuck, not working:
# at ~3s per model turn a real application finishes well inside ten minutes. The
# old 1200s cap meant one stalled worker burned 20 minutes and then retried.
TASK_TIMEOUT="${TASK_TIMEOUT:-600}"
RETRY_LIMIT="${RETRY_LIMIT:-1}"
LIGHT="${LIGHT:-0}"                 # 1 = cheap run: one fixed CV, no per-role CV/letter
FIXED_CV="${FIXED_CV:-}"            # CV file to upload when LIGHT=1
REVIEW="${REVIEW:-0}"               # 1 = prepare documents only (gate PASS, record PREPARED, do NOT submit)
PREPARED="${PREPARED:-0}"           # 1 = submit documents that a REVIEW pass already generated (no re-generation)
CAPTCHA_ON=0                        # private build: on unless Settings -> CAPTCHA disables it
if python3 "$ROOT/tools/captcha_solver.py" --enabled >/dev/null 2>&1; then CAPTCHA_ON=1; fi
ELIGIBILITY_OVERRIDE="${ELIGIBILITY_OVERRIDE:-}"
PROFILE="${PROFILE:-$ROOT/config/profile.md}"   # identity / eligibility config
# The coding agent that applies to each role: opencode | claude | any command.
AGENT="$(bash "$ROOT/tools/agent_run.sh" --which)" || exit 1
# The model comes from Settings -> AI & agent (agent.json), resolved inside
# tools/agent_run.sh for every task. MODEL=... still overrides for one run.
MODEL="${MODEL:-}"
ENGAGEMENT="${ENGAGEMENT:-fulltime}"   # fulltime | contract (uses the contract CV/letter rules)
CAMOUFOX_SERVER="${CAMOUFOX_SERVER:-http://127.0.0.1:9872}"
CAMOUFOX_PORT="${CAMOUFOX_PORT:-9872}"

# CV/letter filename prefix: env CV_PREFIX, else First_Last from config/profile.md,
# else "CV". Generated files are named <prefix>_CV_<key>.docx / <prefix>_Motivation_<key>.docx.
if [ -z "${CV_PREFIX:-}" ] && [ -f "$PROFILE" ]; then
  _pname="$(grep -iE '^[[:space:]]*[-*][[:space:]]*full name[[:space:]]*:' "$PROFILE" | head -n1 | sed 's/^[^:]*:[[:space:]]*//')"
  CV_PREFIX="$(printf '%s' "$_pname" | tr ' ' '_' | tr -cd 'A-Za-z0-9_')"
fi
CV_PREFIX="${CV_PREFIX:-CV}"

mkdir -p "$LOGS"; touch "$DONE"

# One run at a time on this repo. Each worker drives its own Camoufox browser and
# the box has 8 cores: a second concurrent batch (an ad-hoc retry, a "quick"
# prepare) does not add throughput, it makes every task 2-4x slower by thrashing.
# The lock is per-ROOT and released automatically when the run exits.
if command -v flock >/dev/null 2>&1; then
  exec 9>>"$ROOT/state/run.lock"
  if ! flock -n 9; then
    if [ "${ALLOW_CONCURRENT:-0}" = "1" ]; then
      runlog "WARN: another run_queue.sh is active; ALLOW_CONCURRENT=1 set, continuing (expect slower roles)"
    else
      cat >&2 <<'LOCKMSG'
run_queue: another run_queue.sh is already active on this repo (state/run.lock).
  One run at a time: a second batch does not add throughput on this machine, it
  makes every role slower. Wait for the current run, or set ALLOW_CONCURRENT=1
  if you really want two batches sharing the CPU.
LOCKMSG
      exit 3
    fi
  fi
fi

# Keep state/ bounded and usable: gzip logs older than the window, and restore any
# per-role artifact that was packed (job ads, keyword files, grounding packs, gate
# receipts) so this run and the agent always see plain files.
# Only files untouched for a week are touched, so an in-flight log is never moved.
python3 "$ROOT/tools/storage.py" --logs --quiet >/dev/null 2>&1 || true
python3 "$ROOT/tools/storage.py" --hydrate-all --quiet >/dev/null 2>&1 || true

# LIGHT runs upload one fixed CV and no letter, so gate that CV once, up front.
# The PASS writes the receipt record_submission.py needs before it will record a
# SUBMITTED row; a CV that fails stops the run before anything is sent.
if [ "$LIGHT" = "1" ]; then
  if [ -z "$FIXED_CV" ] || [ ! -f "$FIXED_CV" ]; then
    echo "LIGHT=1 needs FIXED_CV=<path to the CV to upload>; got '${FIXED_CV}'" >&2
    exit 1
  fi
  if ! python3 "$ROOT/tools/check_documents.py" --cv "$FIXED_CV" --engagement "$ENGAGEMENT" \
       --record > "$LOGS/fixed_cv_gate.out" 2>&1; then
    cat "$LOGS/fixed_cv_gate.out" >&2
    echo "FIXED_CV $FIXED_CV failed the pre-submit gate: fix it or choose another CV, then re-run" >&2
    exit 1
  fi
fi
printf '%s\n' "$QUEUE" > "$ROOT/state/active_queue"
printf '%s\n' "$DONE" > "$ROOT/state/active_done"
printf '%s\n' "$PARALLEL" > "$ROOT/state/active_parallel"

# Resolve the Camoufox server pool. A comma-separated CAMOUFOX_SERVER is used
# verbatim; otherwise, when PARALLEL>1, one server per worker is started on
# consecutive ports. The HTTP server serialises every command behind one browser
# (and one page), so a single shared server makes PARALLEL>1 useless AND unsafe
# (workers would fight over the same page). One browser per worker is the fix.
IFS=',' read -ra SERVERS <<< "$CAMOUFOX_SERVER"
NS=${#SERVERS[@]}
if [ "$NS" -eq 1 ] && [ "${PARALLEL:-1}" -gt 1 ]; then
  for ((i = 1; i < PARALLEL; i++)); do
    SERVERS+=("http://127.0.0.1:$((CAMOUFOX_PORT + i))")
  done
  NS=${#SERVERS[@]}
fi

ensure_server() {
  local url="$1" port="$2"
  curl -s -m 3 "$url/health" >/dev/null 2>&1 && return 0
  runlog "starting camoufox server on port $port ..."
  # The project venv may not have camoufox (it can live in the system/user
  # site-packages), so start the server with an interpreter that can import it.
  local py=""
  for _p in python3 /usr/bin/python3 "$ROOT/.venv/bin/python3"; do
    command -v "$_p" >/dev/null 2>&1 || continue
    "$_p" -c 'import camoufox' >/dev/null 2>&1 && { py="$_p"; break; }
  done
  py="${py:-python3}"
  # A persistent profile per port: a sign-in done once (Google, LinkedIn, an
  # employer portal) survives into later runs instead of every run looking like a
  # new device and triggering another verification. HEADFUL=1 shows the windows,
  # for a run where the human has to sign in by hand.
  local profile="${CAMOUFOX_PROFILE_DIR:-$HOME/.config/job-search/profiles}/work-$port"
  mkdir -p "$profile" 2>/dev/null
  local headful=""
  [ "${HEADFUL:-0}" = "1" ] && headful="--headful"
  setsid nohup "$py" "$ROOT/tools/camoufox_server.py" --port "$port" --profile "$profile" $headful \
    >> "$LOGS/camoufox_server_$port.log" 2>&1 < /dev/null &
  disown
  local _t
  for _t in $(seq 1 30); do
    curl -s -m 3 "$url/health" >/dev/null 2>&1 && return 0
    sleep 1
  done
  return 1
}

# A review run never opens the browser, so it does not need (or wait for) one.
if [ "$REVIEW" != "1" ]; then
  for _u in "${SERVERS[@]}"; do
    ensure_server "$_u" "${_u##*:}" || runlog "WARN: camoufox server $_u did not come up"
  done
fi

browser_help() {
  # One shared browser/flow instruction block for every run mode. It is inlined
  # into the prompt rather than pasted three times, so the `flow` recipe cannot
  # drift between the prepare, submit-prepared and apply paths.
  cat <<BROWSER
  Browser: every command is \`python3 tools/camoufox_browser.py --server $server <cmd>\`; prefix a single command with \`$TIMEOUT_CMD 30\` and a \`flow\` with \`$TIMEOUT_CMD 120\`.
  SPEED - ONE \`flow\` CALL PER FORM PAGE: \`flow '{"steps":[...]}'\` (or \`flow @steps.json\`) runs a whole page in ONE round-trip: nav{url}, fill{selector,value}, type, select{selector,value}, check{selector}, upload{selector,path}, press{key,selector}, click{target}, pick{text,open}, eval{js}, waitfor{selector,timeout}, waittext{text,timeout,regex}, waiturl{url,timeout}, text{max}, snap{match}, sleep{ms}. Add optional:true to a step that may legitimately fail. It stops at the first failed step and returns failed_at + error. Prefer ONE flow covering fill -> upload -> click submit -> waittext for the confirmation -> snap match, then a second flow only if the page moved.
  Waiting: use waitfor / waittext / waiturl instead of wait or sleep - they return the moment the condition holds. Refs renumber after every snap, so re-snap before using refs; prefer CSS selectors with \`fill '<sel>' '<text>'\`. \`snap --match '<regex>'\` returns only the matching refs (their numbers stay valid); \`text [chars]\` returns trimmed page text for a confirmation or an error.
  Many fields without flow: \`fillmap '<json steps>'\` (op: fill|check|select|upload|press) fills them all in one call.
  Custom ATS widgets (Workday, Greenhouse/react-select, Ashby): listbox options are NOT clickable via eval-dispatched events - use \`pick '<option text>' ['<opener selector>']\` (it scrolls virtualised lists and clicks with real input). \`press Enter '<sel>'\` commits type-aheads, \`press Escape\` closes a popup. \`click\` retries with a forced click automatically; add \`--force\` if something is in the way. CSS ids starting with a digit need \`[id="53683"]\`, not \`#53683\`.
  LinkedIn: if a LinkedIn page shows a login wall, checkpoint, App Challenge or SMS code, go to the employer's own ATS or the posting's external apply link first - one attempt on LinkedIn, never a loop. If the employer route needs the LinkedIn session, use the 2FA handoff below.
  CAPTCHA is NOT a human handoff: "verify you are human", hCaptcha/reCAPTCHA, a slider or rotate widget is handled by the captcha rule (the private build solves it). Never ask the human for a CAPTCHA and never use ask_human/open_for_human for one.
  NEEDS THE HUMAN TO SIGN IN (an employer portal or a Google/Microsoft account that wants a password, a LinkedIn "was this you?" app approval, a device check with no code): do NOT just report it and stop, and do NOT use ask_human for a sign-in that needs typing in the page. Run \`python3 tools/open_for_human.py --url "<the exact login URL>" --port ${server##*:} --reason "Sign in: <what>" --detail "$company / $role" --timeout 900\` - it replaces this worker's headless browser with a VISIBLE Camoufox window on the same port and profile, opens the page, and blocks until the human presses Done in the dashboard. Then continue the application in that same browser. Use OPEN_FOR_HUMAN once per sign-in, not per attempt, and never for a CAPTCHA.
  2FA / sign-in checkpoint (LinkedIn "App Challenge" or device approval, an SMS/authenticator code, "verify your device"): a code or an app tap is a HUMAN handoff, not a dead end - do NOT record BLOCKED yet and never try to work around it. READ THE PAGE FIRST and pick the mode: if it says "check your app", "was this you?" or "tap Yes" it is an APPROVAL - \`python3 tools/ask_human.py --mode approve --reason "LinkedIn: approve the sign-in on your phone" --detail "<Company> / <Role>" --timeout 600\` (the dashboard asks the human to tap Yes and press Done; no code exists, so never ask for one). Only if it shows a 6-digit code field use \`--mode code --reason "LinkedIn sign-in: enter the code sent to your phone"\`. It blocks until they answer and prints one JSON line \`{"ok":true,"answer":"482913"}\` (or \`"approved"\`). Then act in the page: \`fill '<code field>' '<answer>'\` + \`press Enter\`, or for an approval re-read the page/\`nav\` it again to let it pass, then carry on with the application. Only if it prints \`"ok":false\` (nobody answered in time) record BLOCKED with "2FA handoff unanswered, page left open". Ask at most once per checkpoint per role. If the checkpoint emails the code instead of texting it, read it with email_verify.py --wait 90 first: no human needed.
BROWSER
}

build_prompt() {
  local company="$1"; role="$2"; url="$3"; cv="$4"; ats="$5"; key="$6"; server="$7"
  local REVIEW_MSG="" OUTCOMES="SUBMITTED|BLOCKED|CLOSED" CAPTCHA_RULE="" REPOST_FLAG=""
  [ -n "${REPOST_NOTE:-}" ] && REPOST_FLAG="--repost"
  if [ "${CAPTCHA_ON:-0}" = "1" ]; then
    CAPTCHA_RULE="If a CAPTCHA / \"verify you are human\" / anti-bot challenge appears: run \`python3 tools/captcha_solver.py --solve --server $server\`. If it reports ok, wait ~3s and submit once if the page has not moved (never submit while the token is empty). If it fails, record \`python3 tools/register.py --set --company \"$company\" --role \"$role\" --status BLOCKED --notes \"captcha: <solver error>\"\` and return STATUS BLOCKED. At most two solver attempts."
  else
    CAPTCHA_RULE="If a CAPTCHA / \"verify you are human\" / anti-bot challenge appears: do NOT solve or evade it. Record \`python3 tools/register.py --set --company \"$company\" --role \"$role\" --status BLOCKED --notes \"captcha: <exact challenge>\"\` and return STATUS BLOCKED."
  fi
  local INTRO="You are applying to ONE job on behalf of the candidate described in config/profile.md. Repo: $ROOT (cwd). Do not touch other jobs."
  if [ "${REVIEW:-0}" = "1" ]; then
    OUTCOMES="PREPARED|BLOCKED|CLOSED"
    INTRO="You are PREPARING documents for ONE job (REVIEW, no submission). Repo: $ROOT (cwd). Do not touch other jobs."
    BROWSER_LINE=""
    REVIEW_MSG="REVIEW MODE (do NOT submit): produce the aligned, grounded, targeted CV and, ONLY when state/letters/$key.need says the advert asks for one, a cover letter (steps 0c-2); run the alignment gate and the pre-submit gate (with --record, so a gate receipt is written) until both print RESULT: PASS; and save every artifact (state/job-descriptions/$key.md, state/ats/$key.txt, state/kb-context/$key.md, state/cv-content/$key.json, documents/applications/${CV_PREFIX}_CV_$key.docx and, only if required, documents/applications/${CV_PREFIX}_Motivation_$key.docx). \`--record-prepared\` writes PREPARED (NOT SUBMITTED) on PASS and includes the document paths in the note. Do not call register.py --set for PREPARED: that would bypass the live-status and repost guard. Do NOT open the browser, do NOT upload, do NOT submit anything. Finish with the STATUS line described at the end, with PREPARED as the outcome."
    REVIEW_MSG="${REVIEW_MSG} The Browser line and steps 4, 4b, 4c and 5 below DO NOT APPLY: ignore them completely. Nothing is uploaded and no form is opened."
  fi
  if [ "${LIGHT:-0}" = "1" ]; then
    cat <<EOF
You are applying to ONE job on behalf of the candidate described in config/profile.md. Repo: $ROOT (cwd). Do not touch other jobs.
Company: $company
Role: $role
Apply URL: $url
CV to upload (FIXED - do NOT generate or edit any CV or cover letter): $FIXED_CV
$(browser_help)

FIRST, before anything else: read config/profile.md and apply it - identity (name, email, phone, location, links), work authorisation, languages, availability, pay/rate, eligibility/exclusions, accuracy rules and the standard diversity/EEO answers. Use those exact values wherever a form asks; never invent or substitute personal data. Treat config/cv.json as the source of truth for the candidate's experience.
This is a LIGHT run: be fast and cheap. Do NOT run GraphRAG, do NOT write a CV or letter, do NOT run alignment/document gates (the runner already gated $FIXED_CV, so recording it as SUBMITTED needs no --force).

Steps:
0. DUPLICATE GUARD: the queue runner already checked the register for this company and role before starting. Do not re-read state/applications.csv or call register.py --show. A repost or an earlier application does NOT block a new one: apply/prepare it as normal and note the repost. Never record CLOSED just because the role looks like a duplicate.
${REPOST_NOTE:-}
0b. ELIGIBILITY GATE (mandatory): apply ONLY if the role is compatible with the eligibility rules in config/profile.md (based-in location, accepted work models, languages, work authorisation, exclusions). If the role is excluded, or requires work authorisation / a language / an on-site location the candidate does not have, record CLOSED with the reason and STOP - do not fill or submit. If the location/work model is unclear or excluded, record CLOSED/BLOCKED per those rules and STOP (no application). Only if eligible, continue.
1. Open the apply URL. If it is a LinkedIn job page, find the employer's own Apply link / real ATS (Greenhouse/Lever/Ashby/Workday/Teamtailor/own site) and apply there; prefer it over LinkedIn Easy Apply.
2. Fill the form with the identity and standard answers from config/profile.md: work authorisation as stated there; salary/pay if asked as stated there; EEO / diversity questions answered truthfully as specified in profile.md - do NOT decline or pick "prefer not to say" unless profile.md says so. Upload $FIXED_CV as the CV. Skip optional cover-letter/portfolio fields.
3. ${CAPTCHA_RULE}
4. Submit, then CONFIRM before recording anything - a submit click alone is NOT proof:
   - Confirm the success/thank-you page (e.g. "application received", "Thanks for applying"); note its EXACT text and URL.
   - EMAIL VERIFICATION (mandatory): some ATS (Teamtailor, join.com, Workday) require a "Complete the application" link before the application counts. Read the candidate's Gmail (the account config/profile.md is set up for), polling instead of sleeping - \`.venv/bin/python tools/email_verify.py --wait 90 --query 'newer_than:2h (from:teamtailor-mail.com OR from:join.com OR "Complete the application" OR "Security code for your application" OR "verify your email" OR "Activate your account")'\` returns as soon as a message with a link or code arrives. Then COMPLETE it: open the verify/activation link in THIS pipeline browser (\`python3 tools/camoufox_browser.py --server $server nav '<LINK>'\`), or type the emailed security code into the code field and resubmit.
5. Record ONLY with real confirmation: \`python3 tools/record_submission.py --company "$company" --role "$role" --ats "$ats" --url "$url" --cv $FIXED_CV --status SUBMITTED --evidence "<the exact thank-you text or the confirmation email you received>"\`. The evidence MUST be real - never "confirmed"/"ok"/a placeholder (the recorder rejects those). If a verification link or code is still pending and you cannot complete it, record \`--status BLOCKED --evidence "submitted but pending email verification: <what>" --force\` instead and STOP. If a CAPTCHA/anti-bot wall persists, record BLOCKED as in step 3. Never fabricate.

Return exactly one line: STATUS <Company> | $role | SUBMITTED|BLOCKED|CLOSED | <reason>
EOF
    return
  fi
  if [ "${PREPARED:-0}" = "1" ]; then
    cat <<EOF
You are SUBMITTING an application whose documents are ALREADY PREPARED on behalf of the candidate in config/profile.md. Repo: $ROOT (cwd). Do not touch other jobs.
Company/tag: $company
Role: $role
ATS: $ats
Apply URL: $url
CV to upload (ALREADY GENERATED - do NOT regenerate): documents/applications/${CV_PREFIX}_CV_$key.docx
$LETTER_LINE
$(browser_help)

SUBMIT-PREPARED RUN: these files were generated, written and gated in an earlier REVIEW pass and are FINAL. Do NOT re-do any preparation. Specifically: do NOT run kb_graphrag.py, ats_keywords.py, cv_target.py, render_motivation/render_cv, and do NOT rewrite, re-render, edit or "improve" the CV or letter. Do NOT run check_alignment.py. Do not call GraphRAG. If the CV is missing, STOP and record BLOCKED with the missing path - never generate a replacement. If only the cover letter is missing because the advert did not ask for one, leave it out unless the form makes it mandatory (step 1b).

FIRST, before anything else: read config/profile.md and apply it - identity (name, email, phone, location, links), work authorisation, languages, availability, pay/rate, eligibility/exclusions, accuracy rules and the standard diversity/EEO answers. Use those exact values wherever a form asks; never invent or substitute personal data.

Steps:
0. DUPLICATE GUARD: the queue runner already checked the register for this company and role before starting. Do not re-read state/applications.csv or call register.py --show. A repost or an earlier application does NOT block a new one: apply/prepare it as normal and note the repost. Never record CLOSED just because the role looks like a duplicate.
${REPOST_NOTE:-}
0b. ELIGIBILITY CHECK (quick): confirm from profile.md that the role's location/work model, languages and authorisation still fit. If it is clearly excluded (or the posting is no longer live and cannot be found), record CLOSED with the reason and STOP. Do not redo any analysis beyond that.
1. PRE-SUBMIT GATE (the only gate to run): \`python3 tools/check_documents.py ${LETTER_GATE}--cv documents/applications/${CV_PREFIX}_CV_$key.docx --company "<Company>" --jd state/job-descriptions/$key.md --ats-keywords state/ats/$key.txt --engagement $ENGAGEMENT --record\` - it must print RESULT: PASS (it re-stamps the receipt for the exact files you upload). If it FAILS, STOP: do not submit; record BLOCKED with the gate's reason.
1b. COVER LETTER FALLBACK (only when the form marks a cover letter as mandatory and no letter was prepared): write a short, grounded letter to state/letters/$key.json with keys headline, title, engagement ("fulltime"), opening and fit, using state/kb-context/$key.md and state/cv-content/$key.json. Use the candidate's voice and only facts the CV/KB support. Render and gate it WITHOUT touching the CV: \`python3 tools/finalise_docs.py --key $key --company "<Company>" --role "$role" --jd state/job-descriptions/$key.md --ats state/ats/$key.txt --engagement $ENGAGEMENT --skip-cv --letter-mode yes\` - it must print RESULT: PASS and write the gate receipt. Then upload documents/applications/${CV_PREFIX}_Motivation_$key.docx, re-run the step 1 gate with \`--letter documents/applications/${CV_PREFIX}_Motivation_$key.docx\`, and add the same \`--letter documents/applications/${CV_PREFIX}_Motivation_$key.docx\` to the step 3 record command. If the letter cannot be generated or gated, record BLOCKED.
2. Apply via the Camoufox browser: fill fields with profile.md values, upload the prepared CV $LETTER_UPLOAD, answer questions honestly, submit. Verify a success/thank-you page.
   Multi-step forms (Workday etc): the footer button is [data-automation-id="pageFooterNextButton"] (Save and Continue). If a save is rejected, read the Error-* text and fix exactly the field it names (usually a custom dropdown - use \`pick\`).
2b. EMAIL VERIFICATION (mandatory): read the candidate's Gmail with a poll instead of a sleep - \`.venv/bin/python tools/email_verify.py --wait 90 --query 'newer_than:2h (from:teamtailor-mail.com OR from:join.com OR "Complete the application" OR "Security code for your application" OR "verify your email" OR "Activate your account")'\` returns as soon as a message with a link or code arrives - and COMPLETE it in THIS browser. Do NOT record SUBMITTED until a real confirmation is seen. If verification remains pending, record BLOCKED.
2c. BLOCKER RECOVERY: re-read the page and retry once; on a login wall use \`python3 tools/accounts.py --get <site-host>\` (the secrets store). If there is no entry, create one with \`python3 tools/accounts.py --for <site-host> --email <the candidate email in config/profile.md>\`: it stores a strong password, and you fill that. Never print or invent a password. If the apply URL is dead, resolve the employer's own ATS. ${CAPTCHA_RULE}
3. On success: \`python3 tools/record_submission.py --company "<Company>" --role "$role" --ats "$ats" --url "$url" --key $key --cv documents/applications/${CV_PREFIX}_CV_$key.docx ${LETTER_RECORD}--status SUBMITTED --evidence "<the exact thank-you text or the confirmation email>"\`. The evidence MUST be real - never "confirmed"/"ok"/a placeholder.

Return exactly one line: STATUS <Company> | $role | SUBMITTED|BLOCKED|CLOSED | <reason> | CV: documents/applications/${CV_PREFIX}_CV_$key.docx | $LETTER_STATUS
EOF
    return
  fi
  cat <<EOF
$INTRO
Company/tag: $company
Role: $role
ATS: $ats
Apply URL: $url
CV to upload: $cv
$(browser_help)

FIRST, before anything else: read config/profile.md and apply it - identity (name, email, phone, location, links), work authorisation, languages, availability, pay/rate, eligibility/exclusions, accuracy rules and the standard diversity/EEO answers. Use those exact values wherever a form asks; never invent or substitute personal data. Use config/cv.json as the source of truth for the candidate's experience, and config/archetypes.json for the CV archetypes described below. Use the real company name you resolve in the gate/record calls.
${REVIEW_MSG:-}
Steps:
0. DUPLICATE GUARD: the queue runner already checked the register for this company and role before starting. Do not re-read state/applications.csv or call register.py --show. A repost or an earlier application does NOT block a new one: apply/prepare it as normal and note the repost. Never record CLOSED just because the role looks like a duplicate.
${REPOST_NOTE:-}
0b. ONLINE ELIGIBILITY GATE (mandatory, before any letter or application):
   - Determine the role's LOCATION and work model (on-site / hybrid / remote) from the posting or a web search.
   - APPLY ONLY IF the role is compatible with the eligibility rules in config/profile.md: based-in location, accepted work models (on-site/hybrid, remote, relocation), work authorisation, and languages.
   - DO NOT APPLY if the role is excluded by profile.md - e.g. on-site in a location the candidate cannot work, needs a visa/work authorisation the candidate does not hold, or requires fluent/professional-level proficiency in a language the candidate does not speak. For those: record CLOSED with the matching reason from profile.md and STOP (no letter, no application).
   - If the location/work model is UNCLEAR, do NOT apply: record BLOCKED with note "location unclear" and STOP.
   - Only if eligible, continue.
   - ELIGIBILITY OVERRIDE (takes precedence over step 0b if set): ${ELIGIBILITY_OVERRIDE:-none}
0c. DETERMINISTIC PREP (one command): \`python3 tools/prepare_role.py --key $key --company "$company" --role "$role"\`. It extracts ATS keywords, builds the GraphRAG context (reused when the JD hash is unchanged), classifies the role, verifies the archetype with check_alignment, and seeds state/cv-content/$key.json from the closest grounded pack. It prints PREP/CONTENT and writes state/briefs/$key.md. If it prints PREP FAIL: HIGH scam signal, record BLOCKED with the signal and STOP - never prepare or submit that role, never download or install software, never join a chat-only interview. If it fails alignment, record CLOSED/BLOCKED with its reason and STOP. If the archetype is clearly wrong, rerun with \`--cv <Archetype>\`; never submit a misaligned CV.
1. READ ONCE: state/briefs/$key.md (full JD + grounded context + paths) and state/cv-content/$key.json. These are the grounding for the CV and letter.
1b. TAILOR THE SEED PACK with the edit tool - do NOT rewrite the whole JSON. Every role, date and fact is already there. Rewrite only: profile (150-180 words, high-level summary, no tool names), tagline, skills (7-9 lines), selected_work (5-6 items), and the role-specific bullet selection/order/rephrasing. Keep EVERY role and ALL key achievements with their metrics and technologies; split compound bullets; add delivery/team bullets where evidenced; weave role terms in naturally - NO fabrication, NO AI-slop, NO keyword stuffing. Content budget 32-38 bullets: 6-8 for the two most recent/relevant roles, 4-6 middle, 2-3 earliest. If the seed pack is missing an evidenced achievement from the brief/KB, add it.
1c. COVER LETTER (only if required): read state/letters/$key.need, written by prepare_role. If it starts with "required:", write state/letters/$key.json with headline, title, engagement "$ENGAGEMENT", opening, fit (optional salutation/recipient), grounded in the brief/KB and config/profile.md. If it starts with "optional:", do NOT write a letter: the advert does not ask for one. Keep employers and dates accurate, past roles in past tense, no embellishment or invented links. NEVER repeat a phrase of four or more words anywhere in the letter (opening + fit): the gate fails on repeated phrases and duplicated logistics (notice, relocation, availability). Do not reuse a sentence or its opening; vary the wording, and say a thing once.
1d. FINALISE (render + measure + gate in ONE command): \`python3 tools/finalise_docs.py --key $key --company "$company" --role "$role" --jd state/job-descriptions/$key.md --ats state/ats/$key.txt --engagement $ENGAGEMENT\` and, in REVIEW mode only, add \`--record-prepared ${REPOST_FLAG}\`. It renders the CV with --require-fill, renders the letter only when the advert requires one, runs the pre-submit gate with --record, and (in REVIEW) records PREPARED only on PASS. If it reports THIN/FILL FAIL or gate FAIL, read the reason, fix the pack/letter and rerun; never bypass or hand-edit the rendered file. Make all edits in one pass; do not re-render after every small change.
4. Apply via the Camoufox browser: fill fields, upload the targeted CV documents/applications/${CV_PREFIX}_CV_$key.docx (ATS-safe) and the prepared letter if one exists, answer questions honestly using the identity and standard answers in config/profile.md (work authorisation etc.), submit. Verify a success/thank-you page.
   If the form has a REQUIRED cover-letter upload and no letter was prepared, write state/letters/$key.json now (same rules), run \`python3 tools/finalise_docs.py --key $key --company "$company" --role "$role" --jd state/job-descriptions/$key.md --ats state/ats/$key.txt --engagement $ENGAGEMENT --letter-mode yes\` and upload the rendered letter. If the field is optional, leave it empty.
   Multi-step forms (Workday etc): the footer button is [data-automation-id="pageFooterNextButton"] (Save and Continue). If a save is rejected, read the Error-* text on the page and fix exactly the field it names (usually a custom dropdown - use \`pick\`). Never leave a required field blank hoping it is optional; optional sections are fine to leave empty.
4b. EMAIL VERIFICATION (mandatory - do not skip): some ATS (Teamtailor, join.com, Workday, etc.) email a "Complete the application" link before the application counts. After submit, read the candidate's Gmail with a poll instead of a sleep (\`.venv/bin/python tools/email_verify.py --wait 90 --query 'newer_than:2h (from:teamtailor-mail.com OR from:join.com OR "Complete the application" OR "Security code for your application" OR "verify your email" OR "Activate your account")'\`) and COMPLETE it: open the verify/activation link in THIS pipeline browser (\`python3 tools/camoufox_browser.py --server $server nav '<LINK>'\`), or enter any emailed security code into the code field and resubmit. Do NOT record SUBMITTED until a real confirmation is seen (final received/thank-you page text or URL, or a confirmation email). If a verification step remains pending, record BLOCKED, not SUBMITTED.
4c. BLOCKER RECOVERY (mandatory - do NOT record BLOCKED until you have actually tried these and can say what you tried). Most "blocked" states have a legitimate workaround:
   - Re-read the page for the EXACT error and retry the action once after a short wait - transient overlays, slow saves and stale sessions are common.
   - Login/session wall (LinkedIn, an ATS account, Google, etc.): sign in using \`python3 tools/accounts.py --get <site-host>\` (the secrets store), or the credentials referenced in config/profile.md. If there is no entry, create one with \`python3 tools/accounts.py --for <site-host> --email <the candidate email in config/profile.md>\` (it stores a strong password). NEVER print or invent credentials. If the site also demands a challenge you cannot solve, that single step is the human step.
   - Gated or dead apply URL (LinkedIn login wall, aggregator redirect, "job not found", "posting has been taken down", moved page): re-resolve the real employer apply URL via web search of the exact title, try the employer's own ATS directly, and try the company careers page.
   - Multi-step form rejected a save: read the Error-* text and fix exactly the field it names (use \`pick\`/\`press\` for custom widgets), then continue.
   - Page navigated away / browser busy / blank page: re-navigate to the apply URL and continue where you left off.
   - Cloudflare / "just a moment" / slow interstitial: wait 10-20s and retry up to 3 times before concluding.
   - Expired ATS session: reload, re-open the apply URL, and re-enter the form.
   - Email verification required: complete it (step 4b).
   ${CAPTCHA_RULE}
5. On success: \`python3 tools/record_submission.py --company "<Company>" --role "$role" --ats "$ats" --url "$url" --key $key --cv documents/applications/${CV_PREFIX}_CV_$key.docx --status SUBMITTED --evidence "<confirmation>"\`. Add \`--letter documents/applications/${CV_PREFIX}_Motivation_$key.docx\` to that command only if the letter exists; otherwise omit it.
If, after step 4c, a genuine blocker remains (an unsolvable CAPTCHA/anti-bot challenge, or a login wall with no stored credentials), record it with the workarounds you tried: \`python3 tools/register.py --set --company "<Company>" --role "$role" --status BLOCKED --notes "blocker: <exact>; tried: <workarounds>"\` and stop. Never fabricate a submission.

Return exactly one line: STATUS <Company> | $role | $OUTCOMES | <reason> | CV: documents/applications/${CV_PREFIX}_CV_$key.docx | letter: <the letter path if one exists, otherwise 'none (not required)'>
EOF
}

is_duplicate() {
  # A repost is information, not a wall. Return the earlier application whose
  # title is the same posting (punctuation and filler may differ), so the prompt
  # can say "you applied before, apply again". Never used to skip a role.
  python3 - "$1" "$2" <<'PYDUP'
import csv, re, sys
company, role = sys.argv[1], sys.argv[2]
stop = {"the", "a", "an", "of", "and", "for", "to", "with"}
def toks(s):
    return {t for t in re.split(r"[^a-z0-9]+", s.lower()) if t and t not in stop}
want = toks(role)
try:
    rows = list(csv.DictReader(open("state/applications.csv")))
except Exception:
    sys.exit(1)
for r in rows:
    if r.get("company", "").strip().lower() != company.strip().lower():
        continue
    if r.get("status") not in ("SUBMITTED", "INTERVIEW", "IN_PROGRESS", "REJECTED"):
        continue
    have = toks(r.get("role", ""))
    if not want or not have or want != have:
        continue
    when = " ".join(x for x in (r.get("status", ""), r.get("date", "")) if x)
    print(f'{r["role"]} ({when})'.strip())
    sys.exit(0)
sys.exit(1)
PYDUP
}

# One structured line per task (state/logs/runs.jsonl), so a run is machine-readable
# instead of scraped from the free-text run_queue.out. Never fatal.
emit_run_json() {  # company role outcome rc reason
  python3 - "$LOGS" "$1" "$2" "$3" "$4" "$5" <<'PYJSON' 2>/dev/null || true
import json, os, sys, time
logs, company, role, outcome, rc, reason = (sys.argv[1:7] + [""] * 6)[:6]
try:
    rc = int(rc)
except (TypeError, ValueError):
    pass
rec = {"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "company": company,
       "role": role, "outcome": outcome or "UNKNOWN", "rc": rc, "reason": reason}
with open(os.path.join(logs, "runs.jsonl"), "a", encoding="utf-8") as fh:
    fh.write(json.dumps(rec) + "\n")
PYJSON
}

run_task() {
  local line="$1" server="$2" company role url cv ats key log rc lock
  # A tab is IFS whitespace, so a plain read collapses an empty URL/CV/ATS and
  # shifts the key into the URL. Split on a non-whitespace separator so every
  # field, including an empty one, stays in its place.
  IFS=$'\x1f' read -r company role url cv ats key <<< "${line//$'\t'/$'\x1f'}"
  [ -z "${company:-}" ] && return 0
  case "$company" in \#*) return 0 ;; esac
  if grep -qxF "$company|$role" "$DONE" 2>/dev/null || { [ -n "${key:-}" ] && grep -qxF "$key" "$DONE" 2>/dev/null; }; then return 0; fi
  if [ -n "${key:-}" ] && python3 -c 'import json,sys
try: d=json.load(open(sys.argv[1]))
except Exception: d={}
sys.exit(0 if isinstance(d,dict) and sys.argv[2] in d else 1)' "${ROOT:-.}/state/shelved.json" "$key"; then
    runlog "SKIP-SHELVED $(date +%H:%M:%S) $company | $role"
    return 0
  fi
  dup="$(is_duplicate "$company" "$role")"
  REPOST_NOTE=""
  if [ -n "$dup" ]; then
    # A repost or a second application is allowed: mark it, never skip it.
    runlog "REPOST $(date +%H:%M:%S) $company | $role (earlier application: $dup; applying again)"
    REPOST_NOTE="REPOST: this role matches an earlier application ($dup). Reapplying is allowed and expected. Do not record CLOSED because it looks like a duplicate. Proceed with the normal task and add the note \"reapplied to a repost of $dup\" when you record it."
  fi
  log="$LOGS/$(echo "$company-$role" | tr ' /|' '___').log"
  # A cover letter exists only when the advert (or an application form) asked for
  # one. Never assume it: most roles are CV only.
  letter_rel="documents/applications/${CV_PREFIX}_Motivation_$key.docx"
  letter_need_file="$ROOT/state/letters/${key}.need"
  letter_ok=0
  if [ -n "${key:-}" ] && [ -f "$ROOT/$letter_rel" ]; then
    # The advert decides. An old rendered letter for a role that no longer asks
    # for one is not uploaded; a forced letter (--letter-mode yes) records
    # "required:" in the need file.
    if [ ! -f "$letter_need_file" ] || ! grep -q '^optional:' "$letter_need_file"; then
      letter_ok=1
    fi
  fi
  if [ "$letter_ok" = "1" ]; then
    LETTER_LINE="Cover letter (ALREADY GENERATED - do NOT regenerate): $letter_rel"
    LETTER_GATE="--letter $letter_rel "
    LETTER_RECORD="--letter $letter_rel "
    LETTER_STATUS="letter: $letter_rel"
    LETTER_UPLOAD="and the prepared letter where a letter field exists"
  else
    LETTER_LINE="Cover letter: NOT PREPARED. The advert did not ask for one. If the form does not require one, skip it. If the form marks a cover letter as mandatory, generate one with step 1b from the existing grounding; never regenerate the CV."
    LETTER_GATE=""
    LETTER_RECORD=""
    LETTER_STATUS="letter: none (not required by the advert; generated only if the form demands it)"
    LETTER_UPLOAD="(no cover letter unless step 1b generated one because the form required it)"
  fi
  runlog "START $(date +%H:%M:%S) $company | $role"
  prompt="$(build_prompt "$company" "$role" "$url" "$cv" "$ats" "$key" "$server")"
  if [ "$REVIEW" = "1" ]; then
    # The apply steps must not reach a review run at all: an agent reading them
    # ran record_submission.py after preparing documents.
    prompt="$(printf '%s\n' "$prompt" | awk '/^4\. Apply via the Camoufox browser/{exit} {print}')"
    prompt="$prompt

REVIEW RUN ENDS HERE. Do NOT open the browser, do NOT upload, do NOT run record_submission.py and do NOT set SUBMITTED. The finalise command (with --record-prepared) has already recorded PREPARED on PASS. Return exactly one line: STATUS $company | $role | PREPARED|BLOCKED|CLOSED | <reason> | CV: documents/applications/${CV_PREFIX}_CV_$key.docx | letter: <the letter path if one exists, otherwise 'none (not required)'>"
  fi
  "$TIMEOUT_CMD" -k 30s "$TASK_TIMEOUT" bash "$ROOT/tools/agent_run.sh" "$prompt" >"$log" 2>&1 </dev/null
  rc=$?
  # The outcome is the third |-separated field of the agent's last STATUS line:
  # "STATUS <Company> | <role> | BLOCKED | <reason> | CV: ...". (Taking the last
  # capitalised word instead picked up letters from the reason or the CV path.)
  outcome="$(grep -aoE 'STATUS .*' "$log" 2>/dev/null | tail -1 | awk -F'|' '{print $3}' | tr -cd 'A-Z_')"
  # Distinguish an APPLICATION failure from an INFRASTRUCTURE failure (the model
  # never really ran). Infra failures must NOT be committed to $DONE or they are
  # lost: the task stays pending for a later run and is re-queued for the retry pass.
  reason=""; hard=0; size=$(wc -c < "$log" 2>/dev/null || echo 0)
  # A STATUS line is the task's own outcome. Earlier transient errors that were
  # retried and then succeeded must not be mistaken for an infrastructure stop.
  if [ -n "$outcome" ]; then
    :
  elif grep -qiE 'rate limit exceeded|budget exceeded|quota exceeded|too many requests|usage limit reached|hit your (usage )?limit|credit balance is too low|rate_limit_error' "$log" 2>/dev/null; then
    reason="model budget/rate limit"; hard=1
  elif grep -qiE 'invalid api key|please run /login|failed to authenticate|oauth (token|session) (has )?expired' "$log" 2>/dev/null; then
    reason="agent not signed in"; hard=1
  elif grep -qiE 'UnknownError|Unexpected server error|AI_APICallError|AI_RetryError|invalid or expired agent session' "$log" 2>/dev/null; then
    reason="model/API error"
  elif ! grep -q 'STATUS' "$log" 2>/dev/null && grep -qE 'API Error: |overloaded_error' "$log" 2>/dev/null; then
    reason="model/API error"
  elif [ "$rc" -eq 124 ] && ! grep -q 'STATUS' "$log" 2>/dev/null; then
    reason="timeout with no model output"
  elif [ "$size" -lt 200 ] && ! grep -q 'STATUS' "$log" 2>/dev/null; then
    reason="empty model output"
  fi
  if [ -n "$reason" ]; then
    # A stall ("timeout with no model output") is not a transient wall: retrying
    # it burns another TASK_TIMEOUT of a worker and stalls in the same place.
    # Leave it pending so the operator can retry it deliberately, alone.
    if [[ "$reason" != *"no model output"* ]]; then
      printf '%s\n' "${key:-$company|$role}" >> "$RETRY_FILE"
    fi
    runlog "INFRA-FAIL $(date +%H:%M:%S) $company | $role ($reason, rc=$rc)"
    if [ "$hard" -eq 1 ]; then
      n=0
      { flock -x 8
        n=$(cat "$TOKENFAIL_FILE" 2>/dev/null); n=${n:-0}; n=$((n + 1))
        printf '%s' "$n" > "$TOKENFAIL_FILE"
      } 8>>"$TOKENFAIL_LOCK"
      runlog "TOKEN-LIMIT $(date +%H:%M:%S) $company | $role (hard failure $n)"
      if [ "$n" -ge "${TOKEN_FAIL_MAX:-3}" ]; then
        : > "$STOP_FILE"
        runlog "ABORT $(date +%H:%M:%S): $reason hit ${n}x - stopping run; top up / sign in to the agent and re-run"
      fi
    fi
  elif [ "$rc" -eq 124 ] || [ "$outcome" = "BLOCKED" ]; then
    # A task that was BLOCKED or timed out is worth one automatic retry (a
    # transient wall, a slow save, or a stale session often clears on a 2nd pass).
    echo "${key:-$company|$role}" >> "$DONE"
    printf '%s\n' "${key:-$company|$role}" >> "$RETRY_FILE"
  else
    echo "${key:-$company|$role}" >> "$DONE"
  fi
  sum_status="${outcome:-}"
  if [ -z "$sum_status" ]; then
    if [ "$rc" -eq 124 ]; then sum_status="TIMEOUT"
    elif [ -n "$reason" ]; then sum_status="INFRA_FAIL"
    else sum_status="FINISHED"; fi
  fi
  printf -- '- %s — %s: %s%s\n' "$company" "$role" "$sum_status" \
    "${reason:+ ($reason)}" >> "$SUMMARY_FILE"
  runlog "$(tail -1 "$log" 2>/dev/null)"
  runlog "DONE  $(date +%H:%M:%S) $company | $role (rc=$rc)"
  lock="$(_role_lock "$line")"
  if [ -n "$lock" ]; then
    { flock -x 7; grep -vxF "$lock" "$HOSTS" > "$HOSTS.tmp" 2>/dev/null; mv -f "$HOSTS.tmp" "$HOSTS"; } 7>>"$LOCK"
  fi
  # The role is finished: its transcript is history, so pack it.
  python3 "$ROOT/tools/storage.py" --pack-log "$log" --quiet >/dev/null 2>&1 || true
  if [ -n "$reason" ]; then
    emit_run_json "$company" "$role" "INFRA_FAIL" "$rc" "$reason"
  elif [ "$rc" -eq 124 ]; then
    emit_run_json "$company" "$role" "TIMEOUT" "$rc" ""
  else
    emit_run_json "$company" "$role" "$outcome" "$rc" ""
  fi
}

export ROOT QUEUE DONE LOGS PARALLEL TASK_TIMEOUT RETRY_LIMIT LIGHT FIXED_CV ELIGIBILITY_OVERRIDE CAMOUFOX_SERVER AGENT MODEL ENGAGEMENT PROFILE CV_PREFIX TIMEOUT_CMD

# Worker pool: $PARALLEL long-lived workers, each atomically claiming the next
# pending role (flock-guarded) and running it to completion.
CLAIMED="$ROOT/state/queue.claimed"
HOSTS="$ROOT/state/queue.hosts"
LOCK="$ROOT/state/queue.lock"
RETRY_FILE="$ROOT/state/queue.retry"
STOP_FILE="$ROOT/state/queue.stop"
PAUSE_FILE="$ROOT/state/queue.pause"
TOKENFAIL_FILE="$ROOT/state/queue.tokenfail"
TOKENFAIL_LOCK="$ROOT/state/queue.tokenfail.lock"
rm -f "$STOP_FILE"
# RESET_CLAIMED=0 lets a second runner instance share the same queue without
# wiping the first instance's in-flight claims (used to scale workers up live).
if [ "${RESET_CLAIMED:-1}" != "0" ]; then
  : > "$CLAIMED"
  : > "$HOSTS"
  : > "$RETRY_FILE"
  : > "$TOKENFAIL_FILE"
fi

# Identity of a queue line for DONE/CLAIMED: the row's own key (field 6) when it
# has one, else the legacy "company|role". Keys survive a company rename and
# cannot be ambiguous when a company name contains "|".
_role_key() {
  local key
  key="$(printf '%s' "$1" | awk -F'\t' '{print $6}')"
  if [ -n "$key" ]; then printf '%s' "$key"; return; fi
  local rest="$1"; rest="${rest#*$'\t'}"; printf '%s|%s' "${1%%$'\t'*}" "${rest%%$'\t'*}"
}
_legacy_key() { local rest="$1"; rest="${rest#*$'\t'}"; printf '%s|%s' "${1%%$'\t'*}" "${rest%%$'\t'*}"; }
# One submission per employer at a time, and all LinkedIn Easy Apply roles
# serialised on the shared LinkedIn account. Different employers can run in
# parallel, which is safe for Ashby/Greenhouse/Teamtailor and per-tenant Workday.
_role_lock() {
  local ats co
  ats="$(printf '%s' "$1" | awk -F'\t' '{print $5}' | tr '[:upper:]' '[:lower:]')"
  case "$ats" in *linkedin*) printf 'linkedin'; return 0 ;; esac
  co="$(printf '%s' "$1" | awk -F'\t' '{print $1}' | tr '[:upper:]' '[:lower:]' | tr -cs 'a-z0-9' '-')"
  printf 'company:%s' "${co:-unknown}"
}
_done_has() { grep -qxF "$1" "$2" 2>/dev/null; }
_line_done() {
  _done_has "$(_role_key "$1")" "$DONE" && return 0
  _done_has "$(_legacy_key "$1")" "$DONE" && return 0
  return 1
}

# Seniority rank of a queue line's role (field 2); higher = more senior. Used so
# the most senior pending role is applied to first (e.g. a Director role before
# an Engineer role at the same company). Set PRIORITISE=0 to keep file order.
# Whole words only, as tools/prioritise_queue.py: punctuation becomes single
# spaces and the title is padded, so "cto" cannot match inside "director",
# "vector" or "contractor".
_seniority() {
  local role
  role=" $(printf '%s' "$1" | awk -F'\t' '{print $2}' | tr '[:upper:]' '[:lower:]' | tr -cs 'a-z0-9' ' ') "
  case "$role" in
    *" chief "*|*" cto "*|*" cio "*|*" ciso "*|*" cdo "*|*" cpo "*|*" svp "*|*" vice president "*|*" vp "*) echo 6 ;;
    *" director "*|*" head of "*) echo 5 ;;
    *" principal "*|*" staff "*) echo 4 ;;
    *" lead "*|*" manager "*) echo 3 ;;
    *" senior "*|*" sr "*) echo 2 ;;
    *) echo 1 ;;
  esac
}

has_pending() {
  local line
  while IFS= read -r line; do
    [ -z "$line" ] && continue
    case "$line" in \#*) continue ;; esac
    _line_done "$line" && continue
    grep -qxF "$(_role_key "$line")" "$CLAIMED" 2>/dev/null && continue
    return 0
  done < "$QUEUE"
  return 1
}

pop_next() {
  local line out="" best=-1 score lock
  {
    flock -x 9
    while IFS= read -r line; do
      [ -z "$line" ] && continue
      case "$line" in \#*) continue ;; esac
      [ -z "${line%%$'\t'*}" ] && continue
      _line_done "$line" && continue
      grep -qxF "$(_role_key "$line")" "$CLAIMED" 2>/dev/null && continue
      lock="$(_role_lock "$line")"
      grep -qxF "$lock" "$HOSTS" 2>/dev/null && continue
      if [ "${PRIORITISE:-1}" = "1" ]; then
        score="$(_seniority "$line")"
        if [ "$score" -gt "$best" ]; then best="$score"; out="$line"; fi
      else
        out="$line"; break
      fi
    done < "$QUEUE"
    if [ -n "$out" ]; then
      printf '%s\n' "$(_role_key "$out")" >> "$CLAIMED"
      printf '%s\n' "$(_role_lock "$out")" >> "$HOSTS"
    fi
  } 9>>"$LOCK"
  printf '%s' "$out"
}

worker() {
  local server="$1" line
  while :; do
    [ -e "$STOP_FILE" ] && break
    while [ -e "$PAUSE_FILE" ] && [ ! -e "$STOP_FILE" ]; do sleep 2; done   # pause: finish nothing new
    [ -e "$STOP_FILE" ] && break
    line="$(pop_next)"
    [ -z "$line" ] && break
    run_task "$line" "$server"
  done
}

run_pool() {
  while [ ! -e "$STOP_FILE" ] && has_pending; do
    while [ -e "$PAUSE_FILE" ] && [ ! -e "$STOP_FILE" ]; do sleep 2; done
    [ -e "$STOP_FILE" ] && break
    for ((i = 0; i < PARALLEL; i++)); do worker "${SERVERS[i % NS]}" & done
    wait
  done
}

run_pool

# Automatic retry passes: a task that was BLOCKED or timed out gets another go
# (transient walls, slow saves and stale sessions often clear on a second pass).
passes=0
while [ ! -e "$STOP_FILE" ] && [ "$passes" -lt "${RETRY_LIMIT:-0}" ] && [ -s "$RETRY_FILE" ]; do
  passes=$((passes + 1))
  runlog "retry pass $passes ($(date +%H:%M:%S)): $(sort -u "$RETRY_FILE" | wc -l) task(s)"
  while IFS= read -r key; do
    [ -z "$key" ] && continue
    grep -vxF "$key" "$DONE" > "$DONE.tmp" 2>/dev/null; mv -f "$DONE.tmp" "$DONE"
    grep -vxF "$key" "$CLAIMED" > "$CLAIMED.tmp" 2>/dev/null; mv -f "$CLAIMED.tmp" "$CLAIMED"
  done < <(sort -u "$RETRY_FILE")
  : > "$RETRY_FILE"
  run_pool
done

if [ -e "$STOP_FILE" ]; then
  runlog "queue stopped early (agent budget/rate limit/sign-in) $(date +%H:%M:%S)"
else
  runlog "queue complete $(date +%H:%M:%S)"
fi

# Register integrity is part of finishing a run: a contradictory register means
# a status lied about what the mailbox says. Report it loudly (do not hide it).
if ! python3 "$ROOT/tools/register.py" --audit > "$LOGS/audit.out" 2>&1; then
  { echo "AUDIT FAILED after this run — inspect and repair before the next one:";
    grep '^FAIL' "$LOGS/audit.out"; } | tee -a "$LOGS/run_queue.out" >&2
fi

# Tell the Agent pane what this run did. A detached runner otherwise just
# disappears when the badge clears, leaving the operator to dig through logs.
if [ -s "$SUMMARY_FILE" ]; then
  python3 "$ROOT/tools/notify_agent.py" --queue "$QUEUE" --summary "$SUMMARY_FILE" \
    --parallel "$PARALLEL" >> "$LOGS/run_queue.out" 2>&1 || true
fi

# Pack the artifacts from earlier runs that this one did not touch.
python3 "$ROOT/tools/storage.py" --state --quiet >/dev/null 2>&1 || true
