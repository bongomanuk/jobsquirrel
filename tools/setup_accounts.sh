#!/usr/bin/env bash
# Show the setup status of the accounts/credentials the pipeline can use, and
# what to run next for each. Safe to run any time.
#
#   bash tools/setup_accounts.sh            # status + next steps
#   bash tools/setup_accounts.sh --check    # same (alias)
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PY="${PYTHON:-python3}"
CONFIG_DIR="$HOME/.config/job-search"
if [ -f "$ROOT/tools/google_config.py" ]; then
  eval "$("$PY" "$ROOT/tools/google_config.py" --paths 2>/dev/null)" || true
fi
CFG="${GMAIL_CONFIG_DIR:-$CONFIG_DIR}"
CREDS="${CREDENTIALS:-$CFG/credentials.json}"
TOKENP="${TOKEN:-$CFG/token.json}"

echo "Account / credential status"
echo "  config dir: $CFG"
if "$PY" "$ROOT/tools/secrets_store.py" --check >/dev/null 2>&1; then
  STORE="$("$PY" - "$ROOT" <<'EOF'
import sys
sys.path.insert(0, sys.argv[1] + "/tools")
import secrets_store as S
print(S.path())
EOF
)"
  echo "  OK    Secrets store ($STORE)"
else
  echo "  TODO  Secrets store needs attention: python3 tools/secrets_store.py --check"
fi
echo

ok()   { echo "  OK    $1"; }
todo() { echo "  TODO  $1"; echo "        -> $2"; }

# 1. Camoufox
if "$PY" -c "import camoufox" >/dev/null 2>&1; then
  ok "Camoufox installed"
else
  todo "Camoufox browser not installed" "pip install 'camoufox[geoip]' && python3 -m camoufox fetch"
fi

# 2. Google OAuth credentials + token (paths from config/google.json)
if [ -f "$ROOT/config/google.json" ]; then ok "Google config (config/google.json)"; else
  echo "  --    No config/google.json (defaults apply); copy config/google.example.json or use Settings -> Accounts"
fi
if [ -f "$CREDS" ]; then ok "Google OAuth client ($CREDS)"; else
  todo "Google OAuth client missing" "Settings -> Accounts (paste client id/secret), or docs/ACCOUNT-SETUP.md §2 -> $CREDS"
fi
if [ -f "$TOKENP" ]; then
  ok "Google token ($TOKENP)"
  scopes="$("$PY" - "$TOKENP" <<'EOF' 2>/dev/null
import json,sys
try: print(" ".join(json.load(open(sys.argv[1])).get("scopes",[])))
except Exception: pass
EOF
)"
  echo "        scopes: ${scopes:-unknown}"
  case "$scopes" in
    *gmail.send*) ok "  send scope present (mail sending possible, still needs your approval)";;
    *) echo "        (read-only; run: python3 tools/gmail_readonly.py --auth to add gmail.send)";;
  esac
  case "$scopes" in
    *calendar.events*|*calendar.readonly*) ok "  calendar scope present";;
    *) echo "        (no calendar; run: python3 tools/gmail_calendar_auth.py for interview events)";;
  esac
else
  todo "Gmail token missing (not authorised yet)" "python3 tools/gmail_readonly.py --auth"
fi
if [ -f "$ROOT/config/email.json" ]; then ok "Email config (config/email.json)"; else
  echo "  --    No config/email.json (defaults apply); copy config/email.example.json"
fi
if [ -f "$ROOT/config/calendar.json" ]; then ok "Calendar config (config/calendar.json)"; else
  echo "  --    No config/calendar.json (defaults apply); copy config/calendar.example.json"
fi

# 3. LinkedIn persistent profile
if [ -d "$CFG/linkedin-profile" ]; then
  ok "LinkedIn profile dir present ($CFG/linkedin-profile) — log in once via camoufox --headful"
else
  todo "LinkedIn profile not set up (optional)" "docs/ACCOUNT-SETUP.md §4 (start camoufox :9869 --headful and log in)"
fi

# 4. Per-site credentials
n="$("$PY" - "$ROOT" <<'EOF' 2>/dev/null
import sys
sys.path.insert(0, sys.argv[1] + "/tools")
try:
    import secrets_store as S
    print(len(S.section("accounts")))
except Exception:
    print(0)
EOF
)"
if [ "${n:-0}" -gt 0 ]; then
  ok "Per-site credentials ($n host(s) in the secrets store)"
else
  echo "  --    No per-site credentials yet (fine) — created on demand:"
  echo "        python3 tools/accounts.py --for <url>"
fi

# 5. Agent/GraphRAG LLM key
if [ -n "${GRAPHRAG_API_KEY:-}${OPENAI_API_KEY:-}${ANTHROPIC_API_KEY:-}${OPENCODE_API_KEY:-}" ]; then
  ok "An LLM API key is present in the environment"
else
  echo "  --    No LLM key detected in this shell (the agent host may provide it elsewhere)."
  echo "        GraphRAG keys live in the secrets store (mirrored to kb/graphrag/.env)."
fi

echo
echo "Full walkthrough: docs/ACCOUNT-SETUP.md"
echo "Knowledge base:   bash tools/setup_kb.sh --check"
