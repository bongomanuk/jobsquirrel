#!/usr/bin/env bash
# Show the setup status of the accounts/credentials the pipeline can use, and
# what to run next for each. Safe to run any time.
#
#   bash tools/setup_accounts.sh            # status + next steps
#   bash tools/setup_accounts.sh --check    # same (alias)
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CFG="${GMAIL_CONFIG_DIR:-$HOME/.config/job-search}"
ACCOUNTS="${ACCOUNTS_FILE:-$CFG/accounts.json}"
PY="${PYTHON:-python3}"

echo "Account / credential status"
echo "  config dir: $CFG"
echo

ok()   { echo "  OK    $1"; }
todo() { echo "  TODO  $1"; echo "        -> $2"; }

# 1. Camoufox
if "$PY" -c "import camoufox" >/dev/null 2>&1; then
  ok "Camoufox installed"
else
  todo "Camoufox browser not installed" "pip install 'camoufox[geoip]' && python3 -m camoufox fetch"
fi

# 2. Gmail OAuth credentials + token
if [ -f "$CFG/credentials.json" ]; then ok "Gmail OAuth client (credentials.json)"; else
  todo "Gmail OAuth client missing" "docs/ACCOUNT-SETUP.md §2 (Google Cloud -> Desktop OAuth client) -> save to $CFG/credentials.json"
fi
if [ -f "$CFG/token.json" ]; then
  ok "Gmail token (token.json)"
  scopes="$("$PY" - "$CFG/token.json" <<'EOF' 2>/dev/null
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

# 3. LinkedIn persistent profile
if [ -d "$CFG/linkedin-profile" ]; then
  ok "LinkedIn profile dir present ($CFG/linkedin-profile) — log in once via camoufox --headful"
else
  todo "LinkedIn profile not set up (optional)" "docs/ACCOUNT-SETUP.md §4 (start camoufox :9869 --headful and log in)"
fi

# 4. Per-site credentials
if [ -f "$ACCOUNTS" ]; then
  n="$("$PY" - "$ACCOUNTS" <<'EOF' 2>/dev/null
import json,sys
try:
    d=json.load(open(sys.argv[1])); print(len(d) if isinstance(d,dict) else 0)
except Exception: print(0)
EOF
)"
  ok "Per-site credentials ($n host(s) in $ACCOUNTS)"
else
  echo "  --    No per-site credentials yet (fine) — created on demand:"
  echo "        python3 tools/accounts.py --for <url>"
fi

# 5. Agent/GraphRAG LLM key
if [ -n "${GRAPHRAG_API_KEY:-}${OPENAI_API_KEY:-}${ANTHROPIC_API_KEY:-}${OPENCODE_API_KEY:-}" ]; then
  ok "An LLM API key is present in the environment"
else
  echo "  --    No LLM key detected in this shell (the agent host may provide it elsewhere)."
  echo "        GraphRAG uses kb/graphrag/.env (GRAPHRAG_API_KEY, GRAPHRAG_API_BASE, GRAPHRAG_LLM_MODEL)."
fi

echo
echo "Full walkthrough: docs/ACCOUNT-SETUP.md"
echo "Knowledge base:   bash tools/setup_kb.sh --check"
