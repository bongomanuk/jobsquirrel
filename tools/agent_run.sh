#!/usr/bin/env bash
# Run one headless agent task with whichever coding-agent CLI is configured, so
# the runners are not tied to one vendor.
#
#   bash tools/agent_run.sh "<prompt>"   # run the task (output on stdout/stderr)
#   bash tools/agent_run.sh --which      # print the agent that would be used
#
# Env:
#   AGENT   opencode | claude | any other command, run as: $AGENT "<prompt>"
#           (default: opencode if installed, else claude)
#   MODEL   model id passed as --model (empty = the agent's own default)
#
# Claude Code only. A headless run cannot stop and ask you to approve a tool, so
# it may use only the tools allowed here and everything else is refused. This is
# a guardrail against stray commands, not a sandbox (python3 can do anything).
#   CLAUDE_ALLOWED_TOOLS    replace the default allowlist (space-separated rules)
#   CLAUDE_PERMISSION_MODE  default dontAsk; bypassPermissions allows every tool
#   CLAUDE_ARGS             extra flags, e.g. "--max-turns 80 --no-session-persistence"
set -u

# Agent + model defaults come from the dashboard config (Settings -> AI & agent).
# Environment variables still win, so a runner/CI can override either one.
AGENT_CFG_FILE="${AGENT_CFG:-$HOME/.config/job-search/agent.json}"
if [ -f "$AGENT_CFG_FILE" ]; then
  eval "$(python3 - "$AGENT_CFG_FILE" <<'PY' 2>/dev/null
import json, re, shlex, sys
try:
    d = json.load(open(sys.argv[1]))
except Exception:
    d = {}
agent = str(d.get("agent") or "").strip()
model = str(d.get("model") or "").strip()
models = d.get("models") if isinstance(d.get("models"), dict) else {}
if agent and not model:
    model = str(models.get(agent) or "").strip()
if agent:
    print("CFG_AGENT=" + shlex.quote(agent))
if model:
    print("CFG_MODEL=" + shlex.quote(model))
env = d.get("env") if isinstance(d.get("env"), dict) else {}
for k, v in env.items():
    k = re.sub(r"[^A-Za-z0-9_]", "", str(k))[:80]
    if not k or k in ("AGENT", "MODEL") or v is None or str(v) == "":
        continue
    print(f'if [ -z "${{{k}:-}}" ]; then export {k}={shlex.quote(str(v))}; fi')
PY
)"
fi
# A stray AGENT=1 (or similar) must not shadow a configured agent.
if [ -n "${AGENT:-}" ] && [ "${AGENT}" != "openrouter" ] && [ "${AGENT}" != "llamacpp" ] &&    ! command -v "${AGENT%% *}" >/dev/null 2>&1 && [ -n "${CFG_AGENT:-}" ]; then
  AGENT="$CFG_AGENT"
fi
[ -n "${AGENT:-}" ] || AGENT="${CFG_AGENT:-}"
[ -n "${MODEL:-}" ] || MODEL="${CFG_MODEL:-}"
export MODEL

resolve_agent() {
  # openrouter/llamacpp are virtual agents: OpenCode is the local tool runner,
  # while the provider supplies the model. They have no binary of their own.
  case "${AGENT:-}" in openrouter|local|llamacpp) printf '%s' "$AGENT"; return 0 ;; esac
  if [ -n "${AGENT:-}" ]; then
    if command -v "${AGENT%% *}" >/dev/null 2>&1; then printf '%s' "$AGENT"; return 0; fi
    # AGENT is set but not a real command (e.g. a stray AGENT=1 / AGENT=true in the
    # environment) — warn and fall through to auto-detect instead of failing the run.
    echo "agent_run: AGENT='$AGENT' is not installed or on PATH — falling back to auto-detect" >&2
  fi
  local a
  for a in opencode claude; do
    command -v "$a" >/dev/null 2>&1 && { printf '%s' "$a"; return 0; }
  done
  echo "agent_run: no coding-agent CLI found; install opencode or Claude Code, or set AGENT=<command>" >&2
  return 1
}

agent="$(resolve_agent)" || exit 127
if [ "${1:-}" = "--which" ]; then
  printf '%s\n' "$agent"
  exit 0
fi
if [ $# -ne 1 ]; then
  echo "usage: bash tools/agent_run.sh \"<prompt>\" | --which" >&2
  exit 64
fi
prompt="$1"

case "$agent" in
  local|llamacpp)
    command -v opencode >/dev/null 2>&1 || {
      echo "agent_run: local LLM needs opencode as the tool runner on PATH" >&2; exit 127; }
    [ -n "${MODEL:-}" ] || { echo "agent_run: local LLM needs a model (Settings -> AI & agent)" >&2; exit 64; }
    LOCAL_LLM_BASE_URL="${LOCAL_LLM_BASE_URL:-${LLAMACPP_BASE_URL:-http://127.0.0.1:8080/v1}}"
    LOCAL_LLM_API_KEY="${LOCAL_LLM_API_KEY:-sk-local}"
    export LOCAL_LLM_BASE_URL LOCAL_LLM_API_KEY
    m="${MODEL#local/}"; m="${m#llamacpp/}"
    OPENCODE_CONFIG_CONTENT="$(python3 -c 'import json,sys; base,key,model=sys.argv[1],sys.argv[2],sys.argv[3]; print(json.dumps({"permission":{"external_directory":{"*":"deny"},"task":"allow"},"provider":{"local":{"npm":"@ai-sdk/openai-compatible","name":"Local LLM","options":{"baseURL":base,"apiKey":key},"models":{model:{"name":model+" (local)","limit":{"context":131072,"output":8192}}}}}}))' "$LOCAL_LLM_BASE_URL" "$LOCAL_LLM_API_KEY" "$m")"
    export OPENCODE_CONFIG_CONTENT
    fmt=()
    [ "${AGENT_JSON:-}" = "1" ] && fmt+=(--format json)
    [ -n "${AGENT_SESSION:-}" ] && fmt+=(-s "$AGENT_SESSION")
    exec opencode run --model "local/$m" "${fmt[@]}" "$prompt"
    ;;
  openrouter)
    command -v opencode >/dev/null 2>&1 || {
      echo "agent_run: openrouter needs opencode as the local tool runner on PATH" >&2; exit 127; }
    [ -n "${MODEL:-}" ] || { echo "agent_run: openrouter needs a model (Settings -> AI & agent)" >&2; exit 64; }
    m="$MODEL"
    case "$m" in openrouter/*) ;; *) m="openrouter/$m" ;; esac
    fmt=()
    [ "${AGENT_JSON:-}" = "1" ] && fmt+=(--format json)
    [ -n "${AGENT_SESSION:-}" ] && fmt+=(-s "$AGENT_SESSION")
    exec opencode run --model "$m" "${fmt[@]}" "$prompt"
    ;;
  opencode)
    fmt=()
    [ "${AGENT_JSON:-}" = "1" ] && fmt+=(--format json)
    [ -n "${AGENT_SESSION:-}" ] && fmt+=(-s "$AGENT_SESSION")
    if [ -n "${MODEL:-}" ]; then
      exec opencode run --model "$MODEL" "${fmt[@]}" "$prompt"
    fi
    exec opencode run "${fmt[@]}" "$prompt"
    ;;
  claude)
    # What a queue task needs: read/write files in the repo, search the web for
    # the employer's own apply page, and run the pipeline's Python tools (some
    # wrapped in timeout, as the prompt asks).
    tmo="${TIMEOUT_CMD:-timeout}"
    allowed="${CLAUDE_ALLOWED_TOOLS:-Read Write Edit Glob Grep WebSearch WebFetch Bash(python3 *) Bash(.venv/bin/python *) Bash(timeout *) Bash(sleep *)}"
    # On macOS the portable timeout is used; allow its exact path too. A path
    # containing a space cannot go in --allowedTools (space-separated rules), so
    # leave it out rather than emit a rule that never matches.
    if [ "$tmo" != "timeout" ] && [ "$tmo" = "${tmo% *}" ]; then
      allowed="$allowed Bash($tmo *)"
    fi
    args=(--permission-mode "${CLAUDE_PERMISSION_MODE:-dontAsk}" --allowedTools "$allowed"
          --strict-mcp-config)   # no MCP servers: none are needed, and it keeps mail/social tools out of reach
    [ -n "${MODEL:-}" ] && args+=(--model "$MODEL")
    # Structured event stream for the dashboard chat (opencode --format json equivalent).
    [ "${AGENT_JSON:-}" = "1" ] && args+=(--output-format stream-json --verbose)
    # Continue a pinned dashboard-chat session when one is supplied.
    [ -n "${AGENT_SESSION:-}" ] && args+=(--resume "$AGENT_SESSION")
    # The prompt goes straight after -p: --allowedTools takes a variable number
    # of values and would otherwise swallow it.
    # shellcheck disable=SC2086  # CLAUDE_ARGS is a list of flags
    exec claude -p "$prompt" "${args[@]}" ${CLAUDE_ARGS:-}
    ;;
  *)
    # shellcheck disable=SC2086  # AGENT may carry its own flags, e.g. "mycli run --fast"
    exec $agent "$prompt"
    ;;
esac
