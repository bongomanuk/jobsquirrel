#!/usr/bin/env bash
# MANUAL CAPTCHA queue.
#
# Some ATS (Lever/hCaptcha in particular) reject the token produced inside
# Camoufox, so the automated "solve + auto-submit" path fails with
# "There was an error verifying your application". For those, the reliable path
# is YOUR OWN browser: open the role, solve the challenge, submit. No automation
# touches the site, so the captcha is trusted.
#
# This walks state/queue-captcha.tsv one role at a time, opening each in your
# real browser (xdg-open). Press Enter once you've submitted it (records
# SUBMITTED), 's' to skip, 'q' to quit.
#
# Usage:  bash tools/captcha_manual.sh
set -u
ROOT="${ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
QUEUE="${QUEUE:-$ROOT/state/queue-captcha.tsv}"
DONE="${DONE:-$ROOT/state/queue-captcha.done}"
touch "$QUEUE" "$DONE"

echo "Manual CAPTCHA queue — each role opens in YOUR real browser. Ctrl-C to stop."
while IFS=$'\t' read -r company role url cv letter reason; do
  [ -z "${company:-}" ] && continue
  case "$company" in \#*) continue ;; esac
  grep -qxF "$company|$role" "$DONE" && continue
  echo
  echo "================================================================"
  echo " $company — $role"
  echo " reason  : $reason"
  echo " url     : $url"
  echo " cv      : $cv"
  echo " letter  : $letter"
  echo "================================================================"
  [ -n "$url" ] && xdg-open "$url" >/dev/null 2>&1 &
  printf "  [Enter]=submitted   [s]=skip   [q]=quit : "
  read -r ans || ans="q"
  case "$ans" in
    q|Q) break ;;
    s|S) continue ;;
    *)
      echo "$company|$role" >> "$DONE"
      # Gate the documents (best effort) so the ledger carries a receipt. A
      # genuine human submission in the user's own browser is allowed to bypass
      # enforcement via GATE_ENFORCE=0.
      python3 "$ROOT/tools/check_documents.py" --letter "$letter" ${cv:+--cv "$cv"} \
        --company "$company" --record >/dev/null 2>&1 || true
      GATE_ENFORCE=0 python3 "$ROOT/tools/record_submission.py" \
        --company "$company" --role "$role" --ats "manual" --url "$url" \
        --cv "$cv" --letter "$letter" --status SUBMITTED \
        --evidence "submitted manually in the user's own browser (captcha solved there)" 2>/dev/null \
      || python3 "$ROOT/tools/register.py" --set --company "$company" --role "$role" \
           --status SUBMITTED --notes "submitted manually in own browser (captcha solved there)"
      ;;
  esac
done < "$QUEUE"
echo "manual captcha queue complete $(date +%H:%M:%S)"
