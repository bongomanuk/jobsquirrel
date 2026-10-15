#!/usr/bin/env bash
# Build the optional knowledge base (GraphRAG) from your own documents.
#
#   bash tools/setup_kb.sh --check     # explain + check prerequisites
#   bash tools/setup_kb.sh             # configure, stage sources, start embeddings, index
#   bash tools/setup_kb.sh --no-index  # do everything except the (slow) indexing step
#
# What this is: a private GraphRAG index over kb/sources/. For each job the
# pipeline retrieves the most relevant, CITED facts from it, and the CVs/letters
# are written only from those facts (plus config/cv.json). It's optional: without
# it, grounding falls back to config/cv.json.
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
KB="$ROOT/kb"
GR="$KB/graphrag"
HELP_CMD="python3 tools/kb_graphrag.py --check"

explain() {
  cat <<'EOF'
The knowledge base (GraphRAG)
-----------------------------
This is how targeted documents are generated, so it is required — not optional.
We build a graph of the people, projects, skills, metrics and certifications in
YOUR documents (every CV, project notes, a brag doc, talks, reviews) and, for
each job, retrieve the most relevant, cited facts from it. The CVs and letters are
written only from those facts, so they stay accurate. Feed it as much as you can:
the more you add, the better every application. Any format works — this converts
PDF/DOCX/DOC/ODT/HTML/email/Markdown to text for you. Everything runs locally.
EOF
}

find_graphrag() {
  if [ -n "${GRAPHRAG_BIN:-}" ] && [ -x "${GRAPHRAG_BIN}" ]; then echo "$GRAPHRAG_BIN"; return; fi
  if [ -x "$ROOT/.venv-graphrag/bin/graphrag" ]; then echo "$ROOT/.venv-graphrag/bin/graphrag"; return; fi
  if command -v graphrag >/dev/null 2>&1; then echo "graphrag"; return; fi
  echo ""
}

check() {
  explain
  echo
  local ok=1
  [ -d "$GR/prompts" ] && echo "  OK   prompts present" || { echo "  MISS kb/graphrag/prompts"; ok=0; }
  if [ -f "$GR/settings.yaml" ]; then echo "  OK   settings.yaml present"; else echo "  TODO settings.yaml (copy from settings.example.yaml)"; ok=0; fi
  if [ -f "$GR/.env" ]; then echo "  OK   .env present"; else echo "  TODO .env (copy from .env.example)"; ok=0; fi
  local gr; gr="$(find_graphrag)"
  [ -n "$gr" ] && echo "  OK   graphrag CLI: $gr" || { echo "  MISS graphrag CLI (pip install graphrag, or set GRAPHRAG_BIN)"; ok=0; }
  bash "$ROOT/tools/embeddings.sh" >/dev/null 2>&1 && echo "  OK   embeddings backend" || echo "  TODO embeddings backend (bash tools/embeddings.sh)"
  echo
  echo "sources: $(ls "$KB/sources" 2>/dev/null | grep -v '^\.' | wc -l | tr -d ' ') file(s) in kb/sources/"
  [ -f "$GR/output/entities.parquet" ] && echo "index:   built" || echo "index:   not built yet (run: bash tools/setup_kb.sh)"
  echo
  echo "after indexing, verify with: $HELP_CMD"
  return 0
}

if [ "${1:-}" = "--check" ]; then check; exit 0; fi

explain
echo
mkdir -p "$GR/input" "$KB/sources"

# 1. config
if [ ! -f "$GR/settings.yaml" ] && [ -f "$GR/settings.example.yaml" ]; then
  cp "$GR/settings.example.yaml" "$GR/settings.yaml"; echo "wrote kb/graphrag/settings.yaml (edit models/keys if needed)"
fi
if [ ! -f "$GR/.env" ] && [ -f "$GR/.env.example" ]; then
  cp "$GR/.env.example" "$GR/.env"; echo "wrote kb/graphrag/.env (edit GRAPHRAG_* values)"
fi

# 2. stage + ingest sources (any format -> text/GraphRAG-native)
if [ -f "$ROOT/tools/kb_ingest.py" ]; then
  python3 "$ROOT/tools/kb_ingest.py" --sources "$KB/sources" --out "$GR/input" || {
    echo "ingest failed; falling back to copying .txt/.md only"
    for f in "$KB"/sources/*.txt "$KB"/sources/*.md; do [ -e "$f" ] && cp "$f" "$GR/input/"; done
  }
else
  for f in "$KB"/sources/*.txt "$KB"/sources/*.md; do [ -e "$f" ] || continue; cp "$f" "$GR/input/"; done
fi
n=$(ls "$GR/input" 2>/dev/null | grep -v '^\.' | wc -l | tr -d ' ')
if [ "$n" -eq 0 ]; then
  echo "NOTE: no documents ingested. Add your CVs/notes (any format) to kb/sources/ and re-run."
fi

# 3. embeddings backend (auto-selects CUDA / Metal / Vulkan / CPU)
bash "$ROOT/tools/embeddings.sh" || true

# 4. index
gr="$(find_graphrag)"
if [ -z "$gr" ]; then
  echo "graphrag CLI not found. Install it (pip install graphrag) or set GRAPHRAG_BIN, then run:"
  echo "  graphrag index --root kb/graphrag"
  exit 0
fi
if [ "${1:-}" = "--no-index" ]; then
  echo "ready. To build the index (can take many minutes):"
  echo "  $gr index --root kb/graphrag"
  exit 0
fi
echo "indexing (this can take many minutes and uses the LLM)..."
"$gr" index --root kb/graphrag && echo "index complete." || echo "indexing failed — see kb/graphrag/logs/. Re-run to resume (completed steps are cached)."
echo "verify with: $HELP_CMD"
