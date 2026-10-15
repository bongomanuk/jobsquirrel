#!/usr/bin/env bash
# Paced runner — SERIALIZED + PACED.
#
#   - ONE application at a time (never parallel)
#   - random human-like pauses between actions (LINKEDIN_DELAY_MIN..MAX seconds)
#   - a daily submission cap (LINKEDIN_CAP), counted from state/submissions.csv
#
# Browser: Camoufox (tools/camoufox_server.py + tools/camoufox_browser.py).
#
# Usage:  bash tools/run_linkedin.sh
# Queue format (TAB-separated): company  role  url  cv  ats  key
set -u
ROOT="${ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
QUEUE="${QUEUE:-$ROOT/state/queue-linkedin.tsv}"
DONE="${DONE:-$ROOT/state/queue-linkedin.done}"
LOGS="$ROOT/state/logs"
CAP="${LINKEDIN_CAP:-8}"
DMIN="${LINKEDIN_DELAY_MIN:-60}"
DMAX="${LINKEDIN_DELAY_MAX:-240}"
PROFILE="${PROFILE:-$ROOT/config/profile.md}"   # identity / eligibility config
CAMOUFOX_SERVER="${CAMOUFOX_SERVER:-http://127.0.0.1:9873}"
CAMOUFOX_PORT="${CAMOUFOX_PORT:-9873}"

# CV/letter filename prefix: env CV_PREFIX, else First_Last from config/profile.md,
# else "CV".
if [ -z "${CV_PREFIX:-}" ] && [ -f "$PROFILE" ]; then
  _pname="$(grep -iE '^[[:space:]]*[-*][[:space:]]*full name[[:space:]]*:' "$PROFILE" | head -n1 | sed 's/^[^:]*:[[:space:]]*//')"
  CV_PREFIX="$(printf '%s' "$_pname" | tr ' ' '_' | tr -cd 'A-Za-z0-9_')"
fi
CV_PREFIX="${CV_PREFIX:-CV}"

mkdir -p "$LOGS"; touch "$QUEUE" "$DONE"
printf '%s\n' "$QUEUE" > "$ROOT/state/active_queue"
printf '%s\n' "$DONE" > "$ROOT/state/active_done"
printf '1\n' > "$ROOT/state/active_parallel"

if ! curl -s -m 3 "$CAMOUFOX_SERVER/health" >/dev/null 2>&1; then
  echo "starting camoufox server on port $CAMOUFOX_PORT ..." >> "$LOGS/linkedin_run.out"
  setsid nohup python3 "$ROOT/tools/camoufox_server.py" --port "$CAMOUFOX_PORT" \
    >> "$LOGS/camoufox_server.log" 2>&1 < /dev/null &
  disown
  for _ in $(seq 1 20); do
    curl -s -m 3 "$CAMOUFOX_SERVER/health" >/dev/null 2>&1 && break
    sleep 1
  done
fi

build_prompt() {
  local company="$1" role="$2" url="$3" cv="$4" ats="$5" key="$6"
  cat <<EOF
You are applying to ONE job on behalf of the candidate described in config/profile.md. Repo: $ROOT (cwd). Do not touch other jobs.
Company: $company
Role: $role
Apply URL: $url
CV to upload: $cv
  Browser: run every command as \`python3 tools/camoufox_browser.py --server $CAMOUFOX_SERVER <cmd>\` (nav/snap/click/fill/select/check/upload/value/eval/wait). Prefix \`timeout 30\`. Refs renumber after every snap; prefer CSS selectors with \`fill '<sel>' '<text>'\`.
BEHAVE LIKE A CAREFUL HUMAN: one action at a time, normal navigation, short natural pauses - do not click in rapid bursts.

FIRST, before anything else: read config/profile.md and apply it - identity (name, email, phone, location, links), work authorisation, languages, availability, pay/rate, eligibility/exclusions, accuracy rules and the standard diversity/EEO answers. Use those exact values wherever a form asks; never invent or substitute personal data. Use config/cv.json as the source of truth for the candidate's experience, and config/archetypes.json for the CV archetypes below.

Steps:
0. ELIGIBILITY gate: apply only if the role is compatible with the eligibility rules in config/profile.md (based-in location, accepted work models, languages, work authorisation, exclusions). Record CLOSED if the role is on-site in a location the candidate cannot work or requires work authorisation they lack; record CLOSED for a language requirement the candidate does not meet. If unclear, record BLOCKED and STOP.
0b. CV ALIGNMENT gate: classify the role family and choose the matching archetype from config/archetypes.json (match its tags/title); its rendered CV is documents/archetypes/${CV_PREFIX}_CV_<archetype-key>.docx. Run \`python3 tools/check_alignment.py --cv $cv --jd state/job-descriptions/$key.md\` (save the JD there first) - it MUST PASS; if it fails, switch archetype or record BLOCKED "no aligned CV archetype" and STOP.
1. Open the job page, read the description, save it to state/job-descriptions/$key.md. Prefer the EMPLOYER'S OWN ATS: if the posting links to (or resolves to) an external apply URL (Greenhouse/Lever/Workday/Teamtailor/SmartRecruiters/own site), apply there instead of the in-page form.
1b. KNOWLEDGE-BASE GROUNDING (mandatory): run \`python3 tools/kb_graphrag.py --jd state/job-descriptions/$key.md --out state/kb-context/$key.md\` (GraphRAG local search). Write the letter ONLY from facts in state/kb-context/$key.md plus config/cv.json and config/profile.md; do not claim anything not evidenced there.
1c. TARGETED CV (mandatory): write state/cv-content/$key.json - a JSON pack grounded ONLY in state/kb-context/$key.md, state/job-descriptions/$key.md, config/cv.json and config/profile.md (schema: key,company,role,role_line,tagline,profile,skills,experience[{employer,dates,title,location,bullets}],selected_work,education,certifications,languages). Rewrite the profile for this role; The 'profile' must be a high-level professional summary (role focus, scope, strengths, seniority) - NO implementation details or tool/tech names; those belong in the experience bullets. Select, order and naturally rephrase the strongest role-relevant bullets (employers/dates accurate; past roles past tense); weave JD terms in naturally - NO fabrication, NO AI-slop, NO keyword stuffing. Render: \`python3 tools/cv_target.py --key $key --content state/cv-content/$key.json\`. Upload documents/applications/${CV_PREFIX}_CV_$key.docx (ATS-safe); the .pdf is the human version. Include EVERY role and ALL its key achievements with their metrics and technologies, all selected work and all skill categories; use the FULL two pages without exceeding them. Do not drop important specifics. Also: write in your OWN words - never copy phrases from the job description; do not repeat the same phrase or sentence within the letter or CV. GROUNDING RULES: claim only skills/languages present in config/cv.json / config/profile.md; follow the accuracy rules in config/profile.md exactly (never overstate credentials, management scope, employers or product work); distinguish product capabilities from the candidate's personal hands-on work and never present product marketing metrics as personal achievements.
1d. NATURALNESS CHECK (mandatory): re-read the cover letter and the CV as a recruiter would and ask yourself: does this read naturally, like a person wrote it? Fix any stiff, awkward, over-long or repetitive phrasing and any AI-slop; keep every fact and all certifications. If you change anything, re-render the letter/CV and re-run the gate. Only continue once both read naturally and the gate prints RESULT: PASS.
2. Prepare the letter (tools/cv_builder.py; grounded in state/kb-context/$key.md; key $key) and gate it: \`python3 tools/check_documents.py --letter documents/applications/${CV_PREFIX}_Motivation_$key.docx --cv $cv --company "$company" --jd state/job-descriptions/$key.md\` (must PASS).
3. Complete the application form, attach the targeted CV documents/applications/${CV_PREFIX}_CV_$key.docx, and paste the letter text into any message/cover-letter field. Fill the form using the identity and standard answers in config/profile.md.
4. Submit and verify the confirmation. If a CAPTCHA / "verify you are human" / checkpoint appears: STOP, do NOT evade, record BLOCKED with note "CAPTCHA/checkpoint" and stop.
4b. EMAIL VERIFICATION (mandatory): if the employer's ATS emails a "Complete the application" link or a security code, wait ~45s, read the candidate's Gmail (\`.venv/bin/python tools/email_verify.py --query 'from:teamtailor-mail.com OR "Complete the application" OR "Security code" newer_than:1h'\`) and complete it (open the verify link, or enter the code and resubmit) before recording SUBMITTED.
5. Record: \`python3 tools/record_submission.py --company "$company" --role "$role" --ats "$ats" --url "$url" --cv documents/applications/${CV_PREFIX}_CV_$key.docx --letter documents/applications/${CV_PREFIX}_Motivation_$key.docx --status SUBMITTED --evidence "<exact confirmation text or URL>"\`.

Return exactly one line: STATUS <Company> | $role | SUBMITTED|BLOCKED|CLOSED | <reason>
EOF
}

run_task() {
  local line="$1" company role url cv ats key log rc
  IFS=$'\t' read -r company role url cv ats key <<<"$line"
  [ -z "${company:-}" ] && return 0
  case "$company" in \#*) return 0 ;; esac
  grep -qxF "$company|$role" "$DONE" 2>/dev/null && return 0
  log="$LOGS/$(echo "$company-$role" | tr ' /|' '___').log"
  echo "START $(date +%H:%M:%S) $company | $role" >> "$LOGS/linkedin_run.out"
  timeout 1200 opencode run "$(build_prompt "$company" "$role" "$url" "$cv" "$ats" "$key")" >"$log" 2>&1
  rc=$?
  echo "$company|$role" >> "$DONE"
  tail -1 "$log" >> "$LOGS/linkedin_run.out" 2>/dev/null
  echo "DONE  $(date +%H:%M:%S) $company | $role (rc=$rc)" >> "$LOGS/linkedin_run.out"
}

sent_today() { awk -F, -v d="$(date +%F)" 'tolower($4) ~ /linkedin/ && $1==d' "$ROOT/state/submissions.csv" 2>/dev/null | wc -l; }

next_pending() {
  local line
  while IFS= read -r line; do
    [ -z "$line" ] && continue
    case "$line" in \#*) continue ;; esac
    k="$(printf '%s' "$line" | cut -f1,2 | tr '\t' '|')"
    grep -qxF "$k" "$DONE" 2>/dev/null && continue
    printf '%s\n' "$line"; return 0
  done < "$QUEUE"
  return 1
}

export ROOT QUEUE DONE LOGS CAMOUFOX_SERVER PROFILE CV_PREFIX

echo "paced runner: serialized, delay ${DMIN}-${DMAX}s, daily cap $CAP, browser $CAMOUFOX_SERVER" | tee -a "$LOGS/linkedin_run.out"
while line="$(next_pending)"; do
  [ -z "$line" ] && break
  s=$(sent_today)
  if [ "$s" -ge "$CAP" ]; then echo "daily cap reached ($s/$CAP) - stopping for today" | tee -a "$LOGS/linkedin_run.out"; break; fi
  run_task "$line"
  s=$(sent_today)
  [ "$s" -ge "$CAP" ] && { echo "cap reached ($s/$CAP)" | tee -a "$LOGS/linkedin_run.out"; break; }
  d=$(( DMIN + RANDOM % (DMAX - DMIN + 1) ))
  echo "pause ${d}s before next (human-like)" | tee -a "$LOGS/linkedin_run.out"
  sleep "$d"
done
echo "paced queue complete $(date +%H:%M:%S)" | tee -a "$LOGS/linkedin_run.out"
