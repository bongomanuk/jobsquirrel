#!/usr/bin/env bash
# Install everything the pipeline needs, into a local virtualenv. Idempotent.
# Nothing is bundled with the repo; this fetches it:
#   - Python deps (python-docx, google auth/api, camoufox, graphrag)
#   - the Camoufox browser (a one-off download)
#   - a check for LibreOffice (renders the styled PDF)
#
#   bash tools/install.sh            # install (creates ./​.venv)
#   bash tools/install.sh --check    # report what is present/missing, install nothing
#   VENV=/path/to/venv bash tools/install.sh
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

CHECK=0
[ "${1:-}" = "--check" ] && CHECK=1

say()  { printf '%s\n' "$*"; }
have() { command -v "$1" >/dev/null 2>&1; }

say "Jobsquirrel installer"
say "  repo: $ROOT"

# ---- python ----
PY="${PYTHON:-python3}"
have "$PY" || { say "ERROR: python3 not found on PATH"; exit 1; }
say "  python: $PY ($("$PY" -c 'import sys;print("%d.%d"%sys.version_info[:2])'))"

# Prefer an already-active venv; else create ./​.venv
if [ -n "${VIRTUAL_ENV:-}" ] && [ -x "${VIRTUAL_ENV}/bin/pip" ]; then
  VENV="$VIRTUAL_ENV"
elif [ -x "$ROOT/.venv/bin/python" ]; then
  VENV="$ROOT/.venv"
else
  VENV="${VENV:-$ROOT/.venv}"
fi
VPY="$VENV/bin/python"; VPIP="$VENV/bin/pip"

if [ ! -x "$VPY" ]; then
  if [ "$CHECK" = "1" ]; then
    say "  MISS: virtualenv ($VENV) — run without --check to create it"
  else
    say "  creating virtualenv: $VENV"
    "$PY" -m venv "$VENV" || { say "ERROR: could not create venv (install python3-venv?)"; exit 1; }
  fi
fi

# ---- python deps ----
if [ -x "$VPIP" ]; then
  if [ "$CHECK" = "1" ]; then
    "$VPY" -c "import docx"            >/dev/null 2>&1 && say "  OK    python-docx"        || say "  MISS  python-docx"
    "$VPY" -c "import googleapiclient" >/dev/null 2>&1 && say "  OK    google-api-client"   || say "  MISS  google-api-client"
    "$VPY" -c "import camoufox"        >/dev/null 2>&1 && say "  OK    camoufox (pip)"      || say "  MISS  camoufox (pip)"
    "$VPY" -c "import graphrag"        >/dev/null 2>&1 && say "  OK    graphrag"             || say "  MISS  graphrag (required for document generation)"
  else
    say "  upgrading pip and installing dependencies (this can take a while)..."
    "$VPIP" install -q --upgrade pip >/dev/null 2>&1 || true
    if "$VPIP" install -q -r requirements.txt; then
      say "  OK    python deps installed"
    else
      say "  WARN  some dependencies failed — see the output above"
    fi
    # graphrag (required for the knowledge base); install separately so we can report it
    "$VPY" -c "import graphrag" >/dev/null 2>&1 || {
      say "  installing graphrag (required for the knowledge base)..."
      "$VPIP" install -q graphrag || say "  WARN  graphrag install failed (KB will be unavailable until it is installed)"
    }
  fi
fi

# ---- camoufox browser ----
if [ "$CHECK" = "0" ] && [ -x "$VPY" ]; then
  say "  fetching the Camoufox browser (one-off download)..."
  "$VPY" -m camoufox fetch >/dev/null 2>&1 && say "  OK    camoufox browser fetched" \
    || say "  WARN  camoufox fetch failed — retry: $VPY -m camoufox fetch"
fi

# ---- libreoffice (system) ----
if have soffice; then
  say "  OK    LibreOffice (soffice) present"
else
  say "  MISS  LibreOffice (renders the styled PDF). Install one of:"
  say "          Debian/Ubuntu: sudo apt-get install -y libreoffice"
  say "          Fedora/RHEL:   sudo dnf install -y libreoffice"
  say "          macOS:         brew install --cask libreoffice"
  say "          Windows:       winget install TheDocumentFoundation.LibreOffice"
fi

# ---- embeddings backend for GraphRAG (required for targeted documents) ----
say "  note  GraphRAG embeddings (required for the knowledge base): point"
say "        kb/graphrag/.env at a hosted embeddings API, or run the local server"
say "        (bash tools/embeddings.sh, needs llama.cpp; auto-selects CUDA/Metal/Vulkan/CPU)."

say ""
say "done. Next steps:"
say "  1) configure:  python3 tools/init_config.py   (or let your AI agent run BOOTSTRAP.md)"
say "  2) archetypes: $VPY tools/build_archetypes.py"
say "  3) knowledge base (required): bash tools/setup_kb.sh --check"
say "  4) accounts (browser/Gmail/…):  bash tools/setup_accounts.sh --check"
