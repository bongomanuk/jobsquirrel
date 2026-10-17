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

resolve_agent() {
  if [ -n "${AGENT:-}" ]; then
    command -v "${AGENT%% *}" >/dev/null 2>&1 && { printf '%s' "$AGENT"; return 0; }
    echo "agent_run: AGENT=$AGENT, but '${AGENT%% *}' is not installed or not on PATH" >&2
    return 1
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
  opencode)
    fmt=()
    [ "${AGENT_JSON:-}" = "1" ] && fmt+=(--format json)
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
