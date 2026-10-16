"""run_queue.sh end to end with a stub agent, and agent_run.sh's command lines.

The queue runs in a throwaway ROOT (tools/ symlinked in), in REVIEW mode so no
browser is started, with AGENT pointing at a stub that records each call.
"""
import os
import stat
import subprocess

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

STUB = """#!/bin/sh
company=$(printf '%s\\n' "$1" | sed -n 's/^Company[^:]*: //p' | head -n1)
role=$(printf '%s\\n' "$1" | sed -n 's/^Role: //p' | head -n1)
printf '%s|%s\\n' "$company" "$role" >> "$CALLS"
printf '%s\\n' "$1" > "$PROMPTS/$company.txt"
case "$role" in
  Slow*) sleep 30 ;;
  Blocked*) echo "STATUS $company | $role | BLOCKED | hCaptcha on Workday | CV: documents/applications/Jane_Doe_CV_k.docx | letter: documents/applications/Jane_Doe_Motivation_k.docx"
            exit 0 ;;
esac
echo "STATUS $company | $role | PREPARED | stub"
"""


def _exe(path, text):
    path.write_text(text)
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


def _sandbox(tmp_path, rows):
    root = tmp_path / "root"
    (root / "state").mkdir(parents=True)
    os.symlink(os.path.join(ROOT, "tools"), root / "tools")
    (root / "state" / "queue.tsv").write_text(
        "".join("\t".join(r) + "\n" for r in rows))
    (tmp_path / "prompts").mkdir()
    env = dict(os.environ, ROOT=str(root), REVIEW="1", RETRY_LIMIT="0",
               AGENT=str(_exe(tmp_path / "stub-agent", STUB)),
               CALLS=str(tmp_path / "calls"), PROMPTS=str(tmp_path / "prompts"))
    env.pop("VIRTUAL_ENV", None)
    return root, env


def test_queue_runs_each_role_once_in_parallel(tmp_path):
    rows = [(f"Co{i}", f"Engineer {i}", f"https://example.test/{i}", "cv.docx", "ats", f"k{i}")
            for i in range(6)]
    rows.append(("CoSlow", "Slow Role", "https://example.test/slow", "cv.docx", "ats", "kslow"))
    root, env = _sandbox(tmp_path, rows)
    env.update(PARALLEL="3", TASK_TIMEOUT="2")

    r = subprocess.run(["bash", os.path.join(ROOT, "tools", "run_queue.sh")],
                       env=env, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    assert "command not found" not in r.stderr, r.stderr

    calls = (tmp_path / "calls").read_text().splitlines()
    want = sorted(f"{c}|{role}" for c, role, *_ in rows)
    assert sorted(calls) == want, "every role must be claimed exactly once"

    done = (root / "state" / "queue.done").read_text().splitlines()
    assert sorted(done) == sorted(k for k in want if not k.startswith("CoSlow"))

    out = (root / "state" / "logs" / "run_queue.out").read_text()
    assert "INFRA-FAIL" in out and "CoSlow | Slow Role (timeout with no model output" in out
    assert "queue complete" in out

    prompt = (tmp_path / "prompts" / "Co0.txt").read_text()
    assert "REVIEW MODE (do NOT submit)" in prompt
    assert "timeout 30" in prompt
    # Review runs end on the same STATUS line the runner parses, not a PREPARED line.
    assert "STATUS <Company> | Engineer 0 | PREPARED|BLOCKED|CLOSED |" in prompt
    assert "Return exactly one line: PREPARED" not in prompt


def test_blocked_roles_get_one_retry(tmp_path):
    rows = [("CoB", "Blocked Role", "u1", "cv", "ats", "kb"),
            ("CoOk", "Engineer", "u2", "cv", "ats", "kok")]
    root, env = _sandbox(tmp_path, rows)
    env.update(PARALLEL="1", RETRY_LIMIT="1")
    r = subprocess.run(["bash", os.path.join(ROOT, "tools", "run_queue.sh")],
                       env=env, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    calls = (tmp_path / "calls").read_text().splitlines()
    assert calls.count("CoB|Blocked Role") == 2, calls
    assert calls.count("CoOk|Engineer") == 1, calls
    assert "retry pass 1" in (root / "state" / "logs" / "run_queue.out").read_text()


def test_queue_aborts_when_the_agent_is_not_signed_in(tmp_path):
    rows = [(f"Co{i}", "Eng", "u", "cv", "ats", f"k{i}") for i in range(5)]
    root, env = _sandbox(tmp_path, rows)
    # Claude Code's exact message when its sign-in has lapsed.
    env["AGENT"] = str(_exe(tmp_path / "signed-out-agent", "#!/bin/sh\necho 'Failed to "
                            "authenticate: OAuth session expired and could not be refreshed'\nexit 1\n"))
    env["PARALLEL"] = "1"
    r = subprocess.run(["bash", os.path.join(ROOT, "tools", "run_queue.sh")],
                       env=env, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    out = (root / "state" / "logs" / "run_queue.out").read_text()
    assert "ABORT" in out and "agent not signed in hit 3x" in out
    assert out.count("START") == 3, "the run must stop after 3 sign-in failures"
    assert not (root / "state" / "queue.done").read_text().strip(), "failed roles stay pending"


def test_queue_stops_when_no_agent_is_installed(tmp_path):
    root, env = _sandbox(tmp_path, [("Co", "Eng", "u", "cv", "ats", "k")])
    env["AGENT"] = "no-such-agent-xyz"
    r = subprocess.run(["bash", os.path.join(ROOT, "tools", "run_queue.sh")],
                       env=env, capture_output=True, text=True, timeout=30)
    assert r.returncode != 0
    assert "no-such-agent-xyz" in r.stderr
    assert not (tmp_path / "calls").exists()


def _argv_of(tmp_path, agent, **extra):
    """Run agent_run.sh against a fake `agent` binary that prints its argv."""
    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)
    _exe(bindir / agent, '#!/bin/sh\nfor a in "$@"; do printf "%s\\n" "$a"; done\n')
    env = dict(os.environ, PATH=f"{bindir}:{os.environ['PATH']}", AGENT=agent, **extra)
    for k in ("MODEL", "CLAUDE_ALLOWED_TOOLS", "CLAUDE_PERMISSION_MODE", "CLAUDE_ARGS"):
        if k not in extra:
            env.pop(k, None)
    r = subprocess.run(["bash", os.path.join(ROOT, "tools", "agent_run.sh"), "do the thing"],
                       env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return r.stdout.splitlines()


def test_agent_run_claude_is_headless_with_an_allowlist(tmp_path):
    argv = _argv_of(tmp_path, "claude", MODEL="sonnet")
    assert argv[:2] == ["-p", "do the thing"]  # prompt before the variadic --allowedTools
    assert argv[argv.index("--permission-mode") + 1] == "dontAsk"
    allowed = argv[argv.index("--allowedTools") + 1]
    assert "Bash(python3 *)" in allowed and "WebSearch" in allowed
    assert "--strict-mcp-config" in argv
    assert argv[argv.index("--model") + 1] == "sonnet"


def test_agent_run_claude_overrides(tmp_path):
    argv = _argv_of(tmp_path, "claude", CLAUDE_PERMISSION_MODE="bypassPermissions",
                    CLAUDE_ALLOWED_TOOLS="Read", CLAUDE_ARGS="--max-turns 5")
    assert argv[argv.index("--permission-mode") + 1] == "bypassPermissions"
    assert argv[argv.index("--allowedTools") + 1] == "Read"
    assert argv[-2:] == ["--max-turns", "5"]
    assert "--model" not in argv


def test_agent_run_opencode(tmp_path):
    assert _argv_of(tmp_path, "opencode", MODEL="m") == ["run", "--model", "m", "do the thing"]
    assert _argv_of(tmp_path, "opencode") == ["run", "do the thing"]
