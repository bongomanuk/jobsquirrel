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
PARALLEL="${PARALLEL:-5}"
TASK_TIMEOUT="${TASK_TIMEOUT:-1200}"
RETRY_LIMIT="${RETRY_LIMIT:-1}"
LIGHT="${LIGHT:-0}"                 # 1 = cheap run: one fixed CV, no per-role CV/letter
FIXED_CV="${FIXED_CV:-}"            # CV file to upload when LIGHT=1
REVIEW="${REVIEW:-0}"               # 1 = prepare documents only (gate PASS, record PREPARED, do NOT submit)
ELIGIBILITY_OVERRIDE="${ELIGIBILITY_OVERRIDE:-}"
PROFILE="${PROFILE:-$ROOT/config/profile.md}"   # identity / eligibility config
# The coding agent that applies to each role: opencode | claude | any command.
AGENT="$(bash "$ROOT/tools/agent_run.sh" --which)" || exit 1
# opencode: default to a paid, working model. Free/contributor models rate-limit
# ("Rate limit exceeded") and are silently dropped from the run, so never let
# the queue fall back to them. Other agents use their own default model.
# Override with MODEL=... if a different one is needed.
if [ "$AGENT" = "opencode" ]; then
  MODEL="${MODEL:-opencode-go/deepseek-v4.1-flash}"
else
  MODEL="${MODEL:-}"
fi
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
  echo "starting camoufox server on port $port ..." >> "$LOGS/run_queue.out"
  setsid nohup python3 "$ROOT/tools/camoufox_server.py" --port "$port" \
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
    ensure_server "$_u" "${_u##*:}" || echo "WARN: camoufox server $_u did not come up" >> "$LOGS/run_queue.out"
  done
fi

build_prompt() {
  local company="$1"; role="$2"; url="$3"; cv="$4"; ats="$5"; key="$6"; server="$7"
  local REVIEW_MSG="" OUTCOMES="SUBMITTED|BLOCKED|CLOSED"
  if [ "${REVIEW:-0}" = "1" ]; then
    OUTCOMES="PREPARED|BLOCKED|CLOSED"
    REVIEW_MSG="REVIEW MODE (do NOT submit): produce the aligned, grounded, targeted CV and cover letter (steps 0c-2), run the alignment gate and the pre-submit gate (with --record, so a gate receipt is written) until both print RESULT: PASS, and save every artifact (state/job-descriptions/$key.md, state/ats/$key.txt, state/kb-context/$key.md, state/cv-content/$key.json, documents/applications/${CV_PREFIX}_CV_$key.docx, documents/applications/${CV_PREFIX}_Motivation_$key.docx). Then record the row as PREPARED (NOT SUBMITTED) with the file paths: \`python3 tools/register.py --set --company \"$company\" --role \"$role\" --status PREPARED --notes \"review: <cv path> | <letter path>\"\`. Do NOT open the browser, do NOT upload, do NOT submit anything. Finish with the STATUS line described at the end, with PREPARED as the outcome."
  fi
  if [ "${LIGHT:-0}" = "1" ]; then
    cat <<EOF
You are applying to ONE job on behalf of the candidate described in config/profile.md. Repo: $ROOT (cwd). Do not touch other jobs.
Company: $company
Role: $role
Apply URL: $url
CV to upload (FIXED - do NOT generate or edit any CV or cover letter): $FIXED_CV
Browser: run every command as \`python3 tools/camoufox_browser.py --server $server <cmd>\` (nav/snap/click/fill/type/select/pick/fillmap/press/check/upload/value/eval/wait). Prefix \`$TIMEOUT_CMD 30\`. Re-snap before using refs; prefer CSS selectors with \`fill '<sel>' '<text>'\`. To cut tokens, BATCH form fields with \`fillmap '<json steps>'\` (steps: [{"selector":"#x","value":"...","op":"fill|check|select|upload|press"}]) instead of one call per field.

FIRST, before anything else: read config/profile.md and apply it - identity (name, email, phone, location, links), work authorisation, languages, availability, pay/rate, eligibility/exclusions, accuracy rules and the standard diversity/EEO answers. Use those exact values wherever a form asks; never invent or substitute personal data. Treat config/cv.json as the source of truth for the candidate's experience.
This is a LIGHT run: be fast and cheap. Do NOT run GraphRAG, do NOT write a CV or letter, do NOT run alignment/document gates (the runner already gated $FIXED_CV, so recording it as SUBMITTED needs no --force).

Steps:
0. DUPLICATE GUARD (mandatory, do this FIRST): run \`python3 tools/register.py --show "$company"\` and read state/applications.csv. If this company already has a row with status SUBMITTED, INTERVIEW or IN_PROGRESS for the SAME role - or a near-identical/renamed variant of it (e.g. "X - Platform Team" vs "X, Platform") - this is a DUPLICATE: record \`python3 tools/register.py --set --company "$company" --role "$role" --status CLOSED --notes "duplicate of existing <status> role: <existing role>"\` and STOP; do NOT open the form or submit. If two titles could plausibly be the same role, treat them as the same and skip.
0b. ELIGIBILITY GATE (mandatory): apply ONLY if the role is compatible with the eligibility rules in config/profile.md (based-in location, accepted work models, languages, work authorisation, exclusions). If the role is excluded, or requires work authorisation / a language / an on-site location the candidate does not have, record CLOSED with the reason and STOP - do not fill or submit. If the location/work model is unclear or excluded, record CLOSED/BLOCKED per those rules and STOP (no application). Only if eligible, continue.
1. Open the apply URL. If it is a LinkedIn job page, find the employer's own Apply link / real ATS (Greenhouse/Lever/Ashby/Workday/Teamtailor/own site) and apply there; prefer it over LinkedIn Easy Apply.
2. Fill the form with the identity and standard answers from config/profile.md: work authorisation as stated there; salary/pay if asked as stated there; EEO / diversity questions answered truthfully as specified in profile.md - do NOT decline or pick "prefer not to say" unless profile.md says so. Upload $FIXED_CV as the CV. Skip optional cover-letter/portfolio fields.
3. If a CAPTCHA / "verify you are human" / anti-bot challenge appears: do NOT evade and do NOT wait for a human. Record it and stop: \`python3 tools/register.py --set --company "$company" --role "$role" --status BLOCKED --notes "captcha: <exact challenge>"\`, then return STATUS BLOCKED.
4. Submit, then CONFIRM before recording anything - a submit click alone is NOT proof:
   - Confirm the success/thank-you page (e.g. "application received", "Thanks for applying"); note its EXACT text and URL.
   - EMAIL VERIFICATION (mandatory): wait ~45s and read the candidate's Gmail (the account config/profile.md is set up for) for an ATS/employer verification message. Some ATS (Teamtailor, join.com, Workday, etc.) require a "Complete the application" link before the application counts. Find it with \`.venv/bin/python tools/email_verify.py --query 'newer_than:2h (from:teamtailor-mail.com OR from:join.com OR "Complete the application" OR "Security code for your application" OR "verify your email" OR "Activate your account")'\` and COMPLETE it: open the verify link in THIS pipeline browser (\`python3 tools/camoufox_browser.py --server $server nav '<LINK>'\`), or type the emailed security code into the code field and resubmit. Also open any account-activation link the employer sends (Workday etc.).
5. Record ONLY with real confirmation: \`python3 tools/record_submission.py --company "$company" --role "$role" --ats "$ats" --url "$url" --cv $FIXED_CV --status SUBMITTED --evidence "<the exact thank-you text or the confirmation email you received>"\`. The evidence MUST be real - never "confirmed"/"ok"/a placeholder (the recorder rejects those). If a verification link or code is still pending and you cannot complete it, record \`--status BLOCKED --evidence "submitted but pending email verification: <what>" --force\` instead and STOP. If a CAPTCHA/anti-bot wall persists, record BLOCKED as in step 3. Never fabricate.

Return exactly one line: STATUS <Company> | $role | SUBMITTED|BLOCKED|CLOSED | <reason>
EOF
    return
  fi
  cat <<EOF
You are applying to ONE job on behalf of the candidate described in config/profile.md. Repo: $ROOT (cwd). Do not touch other jobs.
Company/tag: $company
Role: $role
ATS: $ats
Apply URL: $url
CV to upload: $cv
  Browser: run every command as \`python3 tools/camoufox_browser.py --server $server <cmd>\` (nav/snap/click/fill/type/select/pick/fillmap/press/check/upload/value/eval/wait). Prefix \`$TIMEOUT_CMD 30\`. Refs renumber after every snap - re-snap before using refs; prefer CSS selectors with \`fill '<sel>' '<text>'\`. To cut tokens, BATCH form fields with \`fillmap '<json steps>'\` (steps: [{"selector":"#x","value":"...","op":"fill|check|select|upload|press"}]) instead of one call per field.
  Custom ATS widgets (Workday, Greenhouse/react-select, Ashby): options in a listbox/dropdown are NOT clickable via eval-dispatched events - use \`pick '<option text>' ['<opener selector>']\` (it scrolls virtualised lists and clicks with real input). Use \`press Enter '<sel>'\` to commit type-aheads, \`press Escape\` to close a popup. \`click\` retries with a forced click automatically when an overlay blocks it; add \`--force\` yourself if you already know something is in the way. CSS ids starting with a digit need \`[id="53683"]\`, not \`#53683\`.

FIRST, before anything else: read config/profile.md and apply it - identity (name, email, phone, location, links), work authorisation, languages, availability, pay/rate, eligibility/exclusions, accuracy rules and the standard diversity/EEO answers. Use those exact values wherever a form asks; never invent or substitute personal data. Use config/cv.json as the source of truth for the candidate's experience, and config/archetypes.json for the CV archetypes described below. Use the real company name you resolve in the gate/record calls.
${REVIEW_MSG:-}
Steps:
0. DUPLICATE GUARD (mandatory, do this FIRST): run \`python3 tools/register.py --show "$company"\` and read state/applications.csv. If this company already has a row with status SUBMITTED, INTERVIEW or IN_PROGRESS for the SAME role - or a near-identical/renamed variant of it (e.g. "X - Platform Team" vs "X, Platform") - this is a DUPLICATE: record \`python3 tools/register.py --set --company "$company" --role "$role" --status CLOSED --notes "duplicate of existing <status> role: <existing role>"\` and STOP; do NOT open the form or submit. If two titles could plausibly be the same role, treat them as the same and skip.
0b. ONLINE ELIGIBILITY GATE (mandatory, before any letter or application):
   - Determine the role's LOCATION and work model (on-site / hybrid / remote) from the posting or a web search.
   - APPLY ONLY IF the role is compatible with the eligibility rules in config/profile.md: based-in location, accepted work models (on-site/hybrid, remote, relocation), work authorisation, and languages.
   - DO NOT APPLY if the role is excluded by profile.md - e.g. on-site in a location the candidate cannot work, needs a visa/work authorisation the candidate does not hold, or requires fluent/professional-level proficiency in a language the candidate does not speak. For those: record CLOSED with the matching reason from profile.md and STOP (no letter, no application).
   - If the location/work model is UNCLEAR, do NOT apply: record BLOCKED with note "location unclear" and STOP.
   - Only if eligible, continue.
   - ELIGIBILITY OVERRIDE (takes precedence over step 0b if set): ${ELIGIBILITY_OVERRIDE:-none}
0c. CV ALIGNMENT GATE (mandatory, BEFORE writing the letter): classify the ROLE FAMILY from the JD, then pick the matching archetype from config/archetypes.json (match its tags/title to the role family). Its rendered CV is documents/archetypes/${CV_PREFIX}_CV_<archetype-key>.docx.
   Then run: \`python3 tools/check_alignment.py --cv <chosen-cv> --title "$role" --jd state/job-descriptions/$key.md\`. It MUST print "RESULT: PASS - alignment". If it FAILS, switch to the correct archetype; if NO archetype fits the role, record BLOCKED with note "no aligned CV archetype" and STOP. NEVER submit a misaligned CV. Also treat a FAIL caused by a domain/language misfit (a domain or a programming language/stack the candidate does not use, per config/profile.md) as final: record CLOSED with the gate's reason and STOP. If the JD's primary language or stack is one the candidate does not know, do NOT apply even if the title looks generic. Use the chosen aligned CV in the gate, upload and record steps below.
0d. REUSE PREVIOUS WORK (retries / re-runs - saves GraphRAG + CV/letter generation): if these already exist from an earlier attempt, do NOT rebuild them - reuse them and go straight to the gate (step 3) and the browser apply: state/job-descriptions/$key.md, state/ats/$key.txt, state/kb-context/$key.md, state/cv-content/$key.json, documents/applications/${CV_PREFIX}_CV_$key.docx and documents/applications/${CV_PREFIX}_Motivation_$key.docx. Only regenerate a missing artifact (or one the gate rejects). Never skip the gates themselves.
1. If the Apply URL is a LinkedIn link (login-gated), resolve the real employer and its own apply URL via web search of the exact title; prefer the employer ATS over LinkedIn Easy Apply. Save the JD to state/job-descriptions/$key.md; run \`python3 tools/ats_keywords.py --jd state/job-descriptions/$key.md --out state/ats/$key.txt\`.
1b. KNOWLEDGE-BASE GROUNDING (mandatory): build the grounded context for this role with \`python3 tools/kb_graphrag.py --jd state/job-descriptions/$key.md --out state/kb-context/$key.md\` (GraphRAG local search, ~1 min). state/kb-context/$key.md is the SINGLE SOURCE OF TRUTH for the candidate's achievements, skills, metrics and certifications. Write the letter ONLY from facts present there (plus $cv and config/profile.md). If the context shows a requirement you cannot evidence, do not claim it.
1c. TARGETED CV (mandatory): write state/cv-content/$key.json - a JSON pack grounded ONLY in state/kb-context/$key.md, state/job-descriptions/$key.md, config/cv.json and config/profile.md. Schema: {"key","company","role","role_line","tagline","profile","skills":["Category: items",...],"experience":[{"employer","dates","title","location","bullets":[...],"groups":[{"label":str,"bullets":[...]}]}],"selected_work":[...],"education":[...],"certifications":[...],"languages":[...]}. Rewrite the profile for THIS role. The 'profile' must be a high-level professional summary (role focus, scope, strengths, seniority) - NO implementation details or tool/tech names; those belong in the experience bullets. Select, order and naturally rephrase the strongest, role-relevant bullets (keep employers and dates accurate; past roles stay past tense). Weave the JD's key terms in naturally - NO fabrication, NO AI-slop, NO keyword stuffing. Then render both formats: \`python3 tools/cv_target.py --key $key --content state/cv-content/$key.json\`. Uploads use documents/applications/${CV_PREFIX}_CV_$key.docx (ATS-safe); the .pdf is the human/email version. Include EVERY role and ALL its key achievements with their metrics and technologies, all selected work and all skill categories; use the FULL two pages without exceeding them. Do not drop important specifics. Also: write in your OWN words - never copy phrases from the job description; do not repeat the same phrase or sentence within the letter or CV. GROUNDING RULES: claim only skills/languages present in config/cv.json / config/profile.md; follow the accuracy rules in config/profile.md exactly (never overstate credentials, management scope, employers or product work); distinguish product capabilities from the candidate's personal hands-on work and never present product marketing metrics as personal achievements.
1d. NATURALNESS CHECK (mandatory): re-read the cover letter and the CV as a recruiter would and ask yourself: does this read naturally, like a person wrote it? Fix any stiff, awkward, over-long or repetitive phrasing and any AI-slop; keep every fact and all certifications. If you change anything, re-render the letter/CV and re-run the gate. Only continue once both read naturally and the gate prints RESULT: PASS.
2. Write the letter with a short Python snippet using tools/cv_builder.py (B.OUT="documents/applications"; call B.render_motivation({... "key":"$key", "headline", "title", "engagement":"$ENGAGEMENT", "opening", "fit"})). Ground every claim in state/kb-context/$key.md (GraphRAG context) and config/cv.json / config/profile.md; keep employers and dates accurate and past roles in past tense; no embellishment, no invented links. Save documents/applications/${CV_PREFIX}_Motivation_$key.docx.
3. Gate: \`python3 tools/check_documents.py --letter documents/applications/${CV_PREFIX}_Motivation_$key.docx --cv documents/applications/${CV_PREFIX}_CV_$key.docx --company "<Company>" --jd state/job-descriptions/$key.md --ats-keywords state/ats/$key.txt --engagement $ENGAGEMENT --record\` - must print RESULT: PASS (and write a gate receipt). The gate runs on the EXACT CV and letter you will upload. record_submission.py will refuse to record SUBMITTED without that receipt, so do not skip it.
4. Apply via the Camoufox browser: fill fields, upload the targeted CV documents/applications/${CV_PREFIX}_CV_$key.docx (ATS-safe) and the letter, answer questions honestly using the identity and standard answers in config/profile.md (work authorisation etc.), submit. Verify a success/thank-you page.
   Multi-step forms (Workday etc): the footer button is [data-automation-id="pageFooterNextButton"] (Save and Continue). If a save is rejected, read the Error-* text on the page and fix exactly the field it names (usually a custom dropdown - use \`pick\`). Never leave a required field blank hoping it is optional; optional sections are fine to leave empty.
4b. EMAIL VERIFICATION (mandatory - do not skip): some ATS (Teamtailor, join.com, Workday, etc.) email a "Complete the application" link before the application counts. After submit, wait ~45s, then read the candidate's Gmail (\`.venv/bin/python tools/email_verify.py --query 'newer_than:2h (from:teamtailor-mail.com OR from:join.com OR "Complete the application" OR "Security code for your application" OR "verify your email" OR "Activate your account")'\`) and COMPLETE it: open the verify/activation link in THIS pipeline browser (\`python3 tools/camoufox_browser.py --server $server nav '<LINK>'\`), or enter any emailed security code into the code field and resubmit. Do NOT record SUBMITTED until a real confirmation is seen (final received/thank-you page text or URL, or a confirmation email). If a verification step remains pending, record BLOCKED, not SUBMITTED.
4c. BLOCKER RECOVERY (mandatory - do NOT record BLOCKED until you have actually tried these and can say what you tried). Most "blocked" states have a legitimate workaround:
   - Re-read the page for the EXACT error and retry the action once after a short wait - transient overlays, slow saves and stale sessions are common.
   - Login/session wall (LinkedIn, an ATS account, Google, etc.): sign in using stored credentials from ~/.config/job-search/accounts.json, or the credentials referenced in config/profile.md. NEVER invent credentials. If no credentials are stored for that wall, it is a genuine human step.
   - Gated or dead apply URL (LinkedIn login wall, aggregator redirect, "job not found", "posting has been taken down", moved page): re-resolve the real employer apply URL via web search of the exact title, try the employer's own ATS directly, and try the company careers page.
   - Multi-step form rejected a save: read the Error-* text and fix exactly the field it names (use \`pick\`/\`press\` for custom widgets), then continue.
   - Page navigated away / browser busy / blank page: re-navigate to the apply URL and continue where you left off.
   - Cloudflare / "just a moment" / slow interstitial: wait 10-20s and retry up to 3 times before concluding.
   - Expired ATS session: reload, re-open the apply URL, and re-enter the form.
   - Email verification required: complete it (step 4b).
   A genuine CAPTCHA / "verify you are human" / anti-bot challenge must NOT be solved or evaded - that is a real BLOCKED.
5. On success: \`python3 tools/record_submission.py --company "<Company>" --role "$role" --ats "$ats" --url "$url" --cv documents/applications/${CV_PREFIX}_CV_$key.docx --letter documents/applications/${CV_PREFIX}_Motivation_$key.docx --status SUBMITTED --evidence "<confirmation>"\`.
If, after step 4c, a genuine blocker remains (an unsolvable CAPTCHA/anti-bot challenge, or a login wall with no stored credentials), record it with the workarounds you tried: \`python3 tools/register.py --set --company "<Company>" --role "$role" --status BLOCKED --notes "blocker: <exact>; tried: <workarounds>"\` and stop. Never fabricate a submission.

Return exactly one line: STATUS <Company> | $role | $OUTCOMES | <reason> | CV: documents/applications/${CV_PREFIX}_CV_$key.docx | letter: documents/applications/${CV_PREFIX}_Motivation_$key.docx
EOF
}

is_duplicate() {
  # Conservative guard: skip a queue row whose company already has a live
  # (SUBMITTED/INTERVIEW/IN_PROGRESS) register row for the same or a renamed
  # variant of the role, so we never send a duplicate application.
  python3 - "$1" "$2" <<'PYDUP'
import csv, sys, re
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
    if r.get("status") not in ("SUBMITTED", "INTERVIEW", "IN_PROGRESS"):
        continue
    have = toks(r.get("role", ""))
    if not want or not have:
        continue
    inter = len(want & have)
    if want == have or (inter >= 3 and inter == min(len(want), len(have))):
        print(r["role"])
        sys.exit(0)
sys.exit(1)
PYDUP
}

run_task() {
  local line="$1" server="$2" company role url cv ats key log rc
  IFS=$'\t' read -r company role url cv ats key <<<"$line"
  [ -z "${company:-}" ] && return 0
  case "$company" in \#*) return 0 ;; esac
  if grep -qxF "$company|$role" "$DONE" 2>/dev/null; then return 0; fi
  dup="$(is_duplicate "$company" "$role")"
  if [ -n "$dup" ]; then
    echo "SKIP-DUPLICATE $(date +%H:%M:%S) $company | $role (already $dup)" >> "$LOGS/run_queue.out"
    echo "$company|$role" >> "$DONE"
    return 0
  fi
  log="$LOGS/$(echo "$company-$role" | tr ' /|' '___').log"
  echo "START $(date +%H:%M:%S) $company | $role" >> "$LOGS/run_queue.out"
  "$TIMEOUT_CMD" "$TASK_TIMEOUT" bash "$ROOT/tools/agent_run.sh" \
    "$(build_prompt "$company" "$role" "$url" "$cv" "$ats" "$key" "$server")" >"$log" 2>&1 </dev/null
  rc=$?
  # The outcome is the third |-separated field of the agent's last STATUS line:
  # "STATUS <Company> | <role> | BLOCKED | <reason> | CV: ...". (Taking the last
  # capitalised word instead picked up letters from the reason or the CV path.)
  outcome="$(grep -aoE 'STATUS .*' "$log" 2>/dev/null | tail -1 | awk -F'|' '{print $3}' | tr -cd 'A-Z_')"
  # Distinguish an APPLICATION failure from an INFRASTRUCTURE failure (the model
  # never really ran). Infra failures must NOT be committed to $DONE or they are
  # lost: the task stays pending for a later run and is re-queued for the retry pass.
  reason=""; hard=0; size=$(wc -c < "$log" 2>/dev/null || echo 0)
  if grep -qiE 'rate limit exceeded|budget exceeded|quota exceeded|too many requests|usage limit reached|hit your (usage )?limit|credit balance is too low|rate_limit_error' "$log" 2>/dev/null; then
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
    printf '%s\n' "$company|$role" >> "$RETRY_FILE"
    echo "INFRA-FAIL $(date +%H:%M:%S) $company | $role ($reason, rc=$rc)" >> "$LOGS/run_queue.out"
    if [ "$hard" -eq 1 ]; then
      n=0
      { flock -x 8
        n=$(cat "$TOKENFAIL_FILE" 2>/dev/null); n=${n:-0}; n=$((n + 1))
        printf '%s' "$n" > "$TOKENFAIL_FILE"
      } 8>>"$TOKENFAIL_LOCK"
      echo "TOKEN-LIMIT $(date +%H:%M:%S) $company | $role (hard failure $n)" >> "$LOGS/run_queue.out"
      if [ "$n" -ge "${TOKEN_FAIL_MAX:-3}" ]; then
        : > "$STOP_FILE"
        echo "ABORT $(date +%H:%M:%S): $reason hit ${n}x - stopping run; top up / sign in to the agent and re-run" >> "$LOGS/run_queue.out"
      fi
    fi
  elif [ "$rc" -eq 124 ] || [ "$outcome" = "BLOCKED" ]; then
    # A task that was BLOCKED or timed out is worth one automatic retry (a
    # transient wall, a slow save, or a stale session often clears on a 2nd pass).
    echo "$company|$role" >> "$DONE"
    printf '%s\n' "$company|$role" >> "$RETRY_FILE"
  else
    echo "$company|$role" >> "$DONE"
  fi
  tail -1 "$log" >> "$LOGS/run_queue.out" 2>/dev/null
  echo "DONE  $(date +%H:%M:%S) $company | $role (rc=$rc)" >> "$LOGS/run_queue.out"
}

export ROOT QUEUE DONE LOGS PARALLEL TASK_TIMEOUT RETRY_LIMIT LIGHT FIXED_CV ELIGIBILITY_OVERRIDE CAMOUFOX_SERVER AGENT MODEL ENGAGEMENT PROFILE CV_PREFIX TIMEOUT_CMD

# Worker pool: $PARALLEL long-lived workers, each atomically claiming the next
# pending role (flock-guarded) and running it to completion.
CLAIMED="$ROOT/state/queue.claimed"
LOCK="$ROOT/state/queue.lock"
RETRY_FILE="$ROOT/state/queue.retry"
STOP_FILE="$ROOT/state/queue.stop"
TOKENFAIL_FILE="$ROOT/state/queue.tokenfail"
TOKENFAIL_LOCK="$ROOT/state/queue.tokenfail.lock"
rm -f "$STOP_FILE"
# RESET_CLAIMED=0 lets a second runner instance share the same queue without
# wiping the first instance's in-flight claims (used to scale workers up live).
if [ "${RESET_CLAIMED:-1}" != "0" ]; then
  : > "$CLAIMED"
  : > "$RETRY_FILE"
  : > "$TOKENFAIL_FILE"
fi

_role_key() { local rest="$1"; rest="${rest#*$'\t'}"; printf '%s|%s' "${1%%$'\t'*}" "${rest%%$'\t'*}"; }

# Seniority rank of a queue line's role (field 2); higher = more senior. Used so
# the most senior pending role is applied to first (e.g. a Director role before
# an Engineer role at the same company). Set PRIORITISE=0 to keep file order.
_seniority() {
  local role; role="$(printf '%s' "$1" | awk -F'\t' '{print $2}' | tr '[:upper:]' '[:lower:]')"
  case "$role" in
    *chief*|*cto*|*cio*|*ciso*|*cdo*|*cpo*|*svp*|*"vice president"*|*vp*) echo 6 ;;
    *director*|*"head of"*) echo 5 ;;
    *principal*|*staff*) echo 4 ;;
    *lead*|*manager*) echo 3 ;;
    *senior*|*sr\ *) echo 2 ;;
    *) echo 1 ;;
  esac
}

has_pending() {
  local line
  while IFS= read -r line; do
    [ -z "$line" ] && continue
    case "$line" in \#*) continue ;; esac
    grep -qxF "$(_role_key "$line")" "$DONE" 2>/dev/null && continue
    grep -qxF "$(_role_key "$line")" "$CLAIMED" 2>/dev/null && continue
    return 0
  done < "$QUEUE"
  return 1
}

pop_next() {
  local line out="" best=-1 score
  {
    flock -x 9
    while IFS= read -r line; do
      [ -z "$line" ] && continue
      case "$line" in \#*) continue ;; esac
      [ -z "${line%%$'\t'*}" ] && continue
      grep -qxF "$(_role_key "$line")" "$DONE" 2>/dev/null && continue
      grep -qxF "$(_role_key "$line")" "$CLAIMED" 2>/dev/null && continue
      if [ "${PRIORITISE:-1}" = "1" ]; then
        score="$(_seniority "$line")"
        if [ "$score" -gt "$best" ]; then best="$score"; out="$line"; fi
      else
        out="$line"; break
      fi
    done < "$QUEUE"
    [ -n "$out" ] && printf '%s\n' "$(_role_key "$out")" >> "$CLAIMED"
  } 9>>"$LOCK"
  printf '%s' "$out"
}

worker() {
  local server="$1" line
  while :; do
    [ -e "$STOP_FILE" ] && break
    line="$(pop_next)"
    [ -z "$line" ] && break
    run_task "$line" "$server"
  done
}

run_pool() {
  while [ ! -e "$STOP_FILE" ] && has_pending; do
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
  echo "retry pass $passes ($(date +%H:%M:%S)): $(sort -u "$RETRY_FILE" | wc -l) task(s)" >> "$LOGS/run_queue.out"
  while IFS= read -r key; do
    [ -z "$key" ] && continue
    grep -vxF "$key" "$DONE" > "$DONE.tmp" 2>/dev/null; mv -f "$DONE.tmp" "$DONE"
    grep -vxF "$key" "$CLAIMED" > "$CLAIMED.tmp" 2>/dev/null; mv -f "$CLAIMED.tmp" "$CLAIMED"
  done < <(sort -u "$RETRY_FILE")
  : > "$RETRY_FILE"
  run_pool
done

if [ -e "$STOP_FILE" ]; then
  echo "queue stopped early (agent budget/rate limit/sign-in) $(date +%H:%M:%S)" >> "$LOGS/run_queue.out"
else
  echo "queue complete $(date +%H:%M:%S)" >> "$LOGS/run_queue.out"
fi
