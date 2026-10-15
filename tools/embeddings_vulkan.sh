#!/usr/bin/env bash
# Start the GraphRAG embeddings backend: llama.cpp with the Vulkan backend,
# running nomic-embed-text on a Vulkan-capable GPU, exposed as an OpenAI-compatible
# /v1/embeddings endpoint. Idempotent: starts it only if it is not already up.
set -u
HOME_DIR="${HOME}"
SRV="${LLAMA_SERVER:-$HOME_DIR/.local/llama.cpp/llama-b11498/llama-server}"
MODEL="${EMBED_MODEL:-$HOME_DIR/.local/llama.cpp/models/nomic-embed.gguf}"
PORT="${EMBED_PORT:-11435}"
LOG="${EMBED_LOG:-/tmp/llama-server.log}"

if curl -s -m 2 "http://127.0.0.1:$PORT/health" >/dev/null 2>&1; then
  echo "embeddings already up on :$PORT"; exit 0
fi
if [ ! -x "$SRV" ]; then echo "llama-server not found at $SRV" >&2; exit 1; fi

setsid nohup "$SRV" -m "$MODEL" --embeddings --host 127.0.0.1 --port "$PORT" \
  --device Vulkan0 -ngl 99 -c 2048 -b 2048 -ub 2048 >>"$LOG" 2>&1 </dev/null &
disown
for _ in $(seq 1 30); do
  curl -s -m 2 "http://127.0.0.1:$PORT/health" >/dev/null 2>&1 && { echo "embeddings up on :$PORT (Vulkan)"; exit 0; }
  sleep 1
done
echo "failed to start embeddings backend (see $LOG)" >&2; exit 1
