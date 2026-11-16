#!/usr/bin/env bash
# Deprecated name. The embeddings backend now auto-selects the hardware (CUDA /
# Metal / Vulkan / CPU). This wrapper forwards to tools/embeddings.sh so existing
# references keep working. Prefer:  bash tools/embeddings.sh
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
exec bash "$ROOT/tools/embeddings.sh" "$@"
