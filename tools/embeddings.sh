#!/usr/bin/env bash
# Start the GraphRAG embeddings backend.
#
# Runs a local llama.cpp `llama-server` serving an embedding model
# (nomic-embed-text by default) as an OpenAI-compatible /v1/embeddings endpoint
# that GraphRAG uses. It auto-selects the best available acceleration:
#
#   EMBED_BACKEND=auto|metal|cuda|vulkan|cpu     (default: auto)
#     auto  -> metal on macOS; cuda if nvidia-smi is present;
#              else vulkan; else cpu.
#
# Idempotent: does nothing if the endpoint is already up. Run with --check to
# report what it found (server, model, backend, endpoint) without starting.
#
# Config (env):
#   LLAMA_SERVER    path to llama-server, or a dir containing it
#   EMBED_MODEL     path to the embedding .gguf (default: nomic-embed-text)
#   EMBED_PORT      port (default 11435)
#   EMBED_BACKEND   force a backend (auto|metal|cuda|vulkan|cpu)
#   EMBED_NGL       layers to offload to the GPU (default 99 = all)
#   EMBED_LOG       log file (default /tmp/llama-server.log)
#
# Note on builds: llama.cpp must be compiled with the backend you select.
#   Apple:    brew install llama.cpp                (Metal is built in)
#   NVIDIA:   a CUDA build   (-DGGML_CUDA=ON), or a prebuilt CUDA release
#   AMD/Intel: a Vulkan build (-DGGML_VULKAN=ON), or a prebuilt Vulkan release
#   CPU only: any build works.
# See docs/KNOWLEDGE-BASE.md ("Embeddings backend and acceleration").
#
# Usage: bash tools/embeddings.sh [--check]
set -u

PORT="${EMBED_PORT:-11435}"
LOG="${EMBED_LOG:-/tmp/llama-server.log}"
MODEL="${EMBED_MODEL:-$HOME/.local/llama.cpp/models/nomic-embed.gguf}"
NGL="${EMBED_NGL:-99}"
CHECK=0
[ "${1:-}" = "--check" ] && CHECK=1

up() { curl -s -m 2 "http://127.0.0.1:$PORT/health" >/dev/null 2>&1; }
say() { printf '%s\n' "$*"; }

find_server() {
  if [ -n "${LLAMA_SERVER:-}" ]; then
    if [ -x "${LLAMA_SERVER}" ]; then echo "${LLAMA_SERVER}"; return; fi
    if [ -x "${LLAMA_SERVER}/llama-server" ]; then echo "${LLAMA_SERVER}/llama-server"; return; fi
  fi
  if command -v llama-server >/dev/null 2>&1; then command -v llama-server; return; fi
  local c
  for c in \
    "$HOME/.local/llama.cpp"/*/llama-server \
    /opt/homebrew/bin/llama-server \
    /usr/local/bin/llama-server; do
    [ -x "$c" ] && { echo "$c"; return; }
  done
  echo ""
}

detect_backend() {
  if [ -n "${EMBED_BACKEND:-}" ] && [ "${EMBED_BACKEND}" != "auto" ]; then
    echo "${EMBED_BACKEND}"; return
  fi
  if [ "$(uname -s)" = "Darwin" ]; then echo "metal"; return; fi
  if command -v nvidia-smi >/dev/null 2>&1; then echo "cuda"; return; fi
  if command -v vulkaninfo >/dev/null 2>&1 || ls /usr/share/vulkan/icd.d/*.json >/dev/null 2>&1; then
    echo "vulkan"; return
  fi
  echo "cpu"
}

SERVER="$(find_server)"
BACKEND="$(detect_backend)"

if [ "$CHECK" = "1" ]; then
  say "embeddings backend check"
  say "  server:   ${SERVER:-MISSING (set LLAMA_SERVER or install llama.cpp)}"
  say "  model:    $MODEL $([ -f "$MODEL" ] && echo '(present)' || echo '(MISSING)')"
  say "  backend:  $BACKEND  (override with EMBED_BACKEND=metal|cuda|vulkan|cpu)"
  if up; then say "  endpoint: UP on :$PORT"; else say "  endpoint: down (run: bash tools/embeddings.sh)"; fi
  [ -n "$SERVER" ] && [ -f "$MODEL" ] && exit 0 || exit 1
fi

if up; then say "embeddings already up on :$PORT"; exit 0; fi
if [ -z "$SERVER" ]; then
  say "llama-server not found. Install llama.cpp, or set LLAMA_SERVER." >&2
  say "  macOS:  brew install llama.cpp" >&2
  say "  other:  https://github.com/ggml-org/llama.cpp (build with -DGGML_CUDA=ON for NVIDIA or -DGGML_VULKAN=ON for AMD/Intel)" >&2
  exit 1
fi
if [ ! -f "$MODEL" ]; then
  say "embedding model not found at $MODEL" >&2
  say "  get one, e.g.:  curl -L -o '$MODEL' https://huggingface.co/nomic-ai/nomic-embed-text-v1.5-GGUF/resolve/main/nomic-embed-text-v1.5.Q8_0.gguf" >&2
  say "  or set EMBED_MODEL to an existing .gguf" >&2
  exit 1
fi

case "$BACKEND" in
  metal)  FLAGS=(-ngl "$NGL") ;;
  cuda)   FLAGS=(-ngl "$NGL") ;;
  vulkan) FLAGS=(--device Vulkan0 -ngl "$NGL") ;;
  cpu)    FLAGS=(-ngl 0) ;;
  *)      say "unknown EMBED_BACKEND '$BACKEND' (use metal|cuda|vulkan|cpu)" >&2; exit 1 ;;
esac

say "starting embeddings on :$PORT (backend=$BACKEND)..."
setsid nohup "$SERVER" -m "$MODEL" --embeddings --host 127.0.0.1 --port "$PORT" \
  "${FLAGS[@]}" -c 2048 -b 2048 -ub 2048 >>"$LOG" 2>&1 </dev/null &
disown
for _ in $(seq 1 30); do
  up && { say "embeddings up on :$PORT (backend=$BACKEND)"; exit 0; }
  sleep 1
done
say "failed to start embeddings backend (backend=$BACKEND); see $LOG" >&2
say "  if the build lacks $BACKEND, try EMBED_BACKEND=cpu" >&2
exit 1
