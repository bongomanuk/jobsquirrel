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
import json, os, re, shlex, sys
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
legacy = d.get("env") if isinstance(d.get("env"), dict) else {}
# Secrets live in the central store; agent.json keeps only the agent/model choice.
sec_file = os.path.expanduser(os.environ.get(
    "JOBSQUIRREL_SECRETS", "~/.config/job-search/secrets.json"))
try:
    with open(sec_file, encoding="utf-8") as fh:
        stored = (json.load(fh).get("sections") or {}).get("agent") or {}
except Exception:
    stored = {}
env = {**(legacy if isinstance(legacy, dict) else {}), **(stored if isinstance(stored, dict) else {})}
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
    # Tolerate the classic stray shell values (AGENT=1 / true / yes / on), which
    # mean "nothing specified". Any other missing command is a configuration
    # error and must fail loudly: silently switching agents mid-pipeline hides it.
    case "$AGENT" in
      1|true|TRUE|yes|YES|on|ON) : ;;
      *) echo "agent_run: AGENT='$AGENT' is not installed or on PATH; fix Settings -> AI & agent or install it" >&2
         return 1 ;;
    esac
  fi
  local a
  for a in opencode claude; do
    command -v "$a" >/dev/null 2>&1 && { printf '%s' "$a"; return 0; }
  done
  echo "agent_run: no coding-agent CLI found; install opencode or Claude Code, or set AGENT=<command>" >&2
  return 1
}

# Transient provider failures (HTTP 420 / 429 / 5xx, rate limits, quota) are
# worth retrying: they abort before or during a call, and the pipeline's own
# duplicate guards make a re-run safe. Anything else (auth, bad request) is not
# retried, and the failure is returned unchanged.
#
# Env: AGENT_RETRY (default 4), AGENT_RETRY_BASE seconds (default 20; doubles).
fatal_transient() {
  local f="$1"
  grep -qiE '(APIError|ProviderError|Error|status|code|HTTP)[^\n]{0,24}\b(420|429|500|502|503|504)\b|enhance your calm|too many requests|rate.?limit|overloaded|quota exceeded' "$f" \
    || { grep -q '"type":"error"' "$f" && grep -qiE '\b(420|429)\b|rate.?limit|quota' "$f"; }
}

# Did the agent already act? A shell tool line (`$ ...`) or a JSON tool_use
# event means a retry could repeat side effects, so it is not automatic.
partial_work() {
  grep -qE '"type":"tool_use"|^\$ ' "$1"
}

run_agent() {
  local -a cmd=("$@")
  local out rc attempt=1 wait cont=0 a has_s=0
  local tries="${AGENT_RETRY:-4}" base="${AGENT_RETRY_BASE:-20}"

  # Pin a session for opencode so a retry continues the same conversation
  # instead of starting over and repeating tool calls. This is what makes a
  # mid-task 420 safe to retry.
  if [ "${cmd[0]:-}" = "opencode" ] && [ "${cmd[1]:-}" = "run" ]; then
    for a in "${cmd[@]}"; do
      case "$a" in -s|--session) has_s=1 ;; esac
    done
    if [ "$has_s" = 0 ]; then
      cmd=(opencode run -s "ses_retry_$(date +%s)_$RANDOM" "${cmd[@]:2}")
    fi
    cont=1
  fi

  out="$(mktemp "${TMPDIR:-/tmp}/agent-run.XXXXXX")" || return 1
  while :; do
    "${cmd[@]}" 2>&1 | tee "$out"
    rc=${PIPESTATUS[0]}
    if [ "$rc" -eq 0 ]; then
      rm -f "$out"; return 0
    fi
    if [ "$tries" -le 0 ] || [ "$attempt" -ge "$tries" ] || ! fatal_transient "$out"; then
      rm -f "$out"; return "$rc"
    fi
    # Without a resumable session, only retry when the agent has not acted yet.
    if [ "$cont" = 0 ] && partial_work "$out"; then
      echo "agent_run: transient provider error after tool use; not retrying automatically (partial work)" >&2
      rm -f "$out"; return "$rc"
    fi
    wait=$(( base * (1 << (attempt - 1)) ))
    wait=$(( wait + RANDOM % 10 ))
    echo "agent_run: transient provider error (attempt $attempt/$tries); retrying in ${wait}s" >&2
    sleep "$wait"
    attempt=$(( attempt + 1 ))
  done
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
    run_agent opencode run --model "local/$m" "${fmt[@]}" "$prompt"
    exit $?
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
    run_agent opencode run --model "$m" "${fmt[@]}" "$prompt"
    exit $?
    ;;
  opencode)
    fmt=()
    [ "${AGENT_JSON:-}" = "1" ] && fmt+=(--format json)
    [ -n "${AGENT_SESSION:-}" ] && fmt+=(-s "$AGENT_SESSION")
    if [ -n "${MODEL:-}" ]; then
      run_agent opencode run --model "$MODEL" "${fmt[@]}" "$prompt"
      exit $?
    fi
    run_agent opencode run "${fmt[@]}" "$prompt"
    exit $?
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
    run_agent claude -p "$prompt" "${args[@]}" ${CLAUDE_ARGS:-}
    exit $?
    ;;
  *)
    # shellcheck disable=SC2086  # AGENT may carry its own flags, e.g. "mycli run --fast"
    run_agent $agent "$prompt"
    exit $?
    ;;
esac
