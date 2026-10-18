#!/usr/bin/env bash
# Incremental knowledge-graph update: ingest new/changed kb/sources into the GraphRAG
# input folder, run `graphrag update` (only the delta), then promote the updated index
# into kb/graphrag/output so queries see it. Much faster than a full re-index.
#
#   bash tools/kb_update.sh
set -u
ROOT="${ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
cd "$ROOT" || exit 1
GR="$ROOT/kb/graphrag"

gr() {
  if [ -x "$ROOT/.venv-graphrag/bin/graphrag" ]; then echo "$ROOT/.venv-graphrag/bin/graphrag"; return; fi
  if [ -n "${GRAPHRAG_BIN:-}" ] && [ -x "$GRAPHRAG_BIN" ]; then echo "$GRAPHRAG_BIN"; return; fi
  command -v graphrag || true
}
G="$(gr)"
[ -n "$G" ] || { echo "no graphrag CLI found (set GRAPHRAG_BIN or run tools/install.sh)" >&2; exit 1; }
[ -f "$GR/settings.yaml" ] || { echo "missing kb/graphrag/settings.yaml" >&2; exit 1; }
[ -f "$GR/output/entities.parquet" ] || { echo "no existing index — run a full build first (tools/setup_kb.sh)" >&2; exit 1; }

echo "== ingest kb/sources -> kb/graphrag/input =="
python3 "$ROOT/tools/kb_ingest.py" --sources "$ROOT/kb/sources" --out "$GR/input" \
  || { echo "ingest failed" >&2; exit 1; }

echo "== graphrag update (incremental; only new/changed docs) =="
"$G" update --root "$GR" || { echo "graphrag update failed" >&2; exit 1; }

# Promote the updated index so queries use it.
if [ -f "$GR/update_output/entities.parquet" ]; then
  echo "== promoting update_output -> output =="
  rm -rf "$GR/output"
  mv "$GR/update_output" "$GR/output"
fi
echo "knowledge graph updated $(date +%H:%M:%S)"
