"""run_linkedin.sh, human_assist.sh and captcha_manual.sh with stub commands, and
watch_queue's live-task detection (/proc on Linux, ps on macOS).

Each runner runs in a throwaway ROOT (tools/ symlinked in) with AGENT pointing
at a stub that records each call. Stub curl, open and xdg-open on PATH make the
browser server look healthy and record what would open in the user's browser,
so no real browser is started or opened.
"""
import importlib.util
import os
import platform
import shutil
import stat
import subprocess
import time

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

STUB = """#!/bin/sh
company=$(printf '%s\\n' "$1" | sed -n 's/^Company[^:]*: //p' | head -n1)
role=$(printf '%s\\n' "$1" | sed -n 's/^Role: //p' | head -n1)
printf '%s\\n' "$1" > "$PROMPTS/$company.txt"
cat > "$PROMPTS/$company.stdin"
printf '%s|%s\\n' "$company" "$role" >> "$CALLS"
while [ -n "${HOLD:-}" ] && [ ! -e "$HOLD" ]; do sleep 0.1; done
echo "STATUS $company | $role | SUBMITTED | stub"
"""


def _exe(path, text):
    path.write_text(text)
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


def _sandbox(tmp_path, queue, rows):
    root = tmp_path / "root"
    (root / "state").mkdir(parents=True)
    os.symlink(os.path.join(ROOT, "tools"), root / "tools")
    (root / "state" / queue).write_text("".join("\t".join(r) + "\n" for r in rows))
    (tmp_path / "prompts").mkdir()
    bindir = tmp_path / "bin"
    bindir.mkdir()
    _exe(bindir / "curl", "#!/bin/sh\nexit 0\n")
    _exe(bindir / "notify-send", "#!/bin/sh\nexit 0\n")
    for opener in ("open", "xdg-open"):
        _exe(bindir / opener, f'#!/bin/sh\nprintf "{opener} %s\\n" "$1" >> "$OPENED"\n')
    env = dict(os.environ, ROOT=str(root), PATH=f"{bindir}:{os.environ['PATH']}",
               AGENT=str(_exe(tmp_path / "stub-agent", STUB)),
               CALLS=str(tmp_path / "calls"), PROMPTS=str(tmp_path / "prompts"),
               OPENED=str(tmp_path / "opened"))
    for k in ("VIRTUAL_ENV", "MODEL", "HOLD", "CAMOUFOX_SERVER", "HUMAN_SERVER"):
        env.pop(k, None)
    return root, env


def _timeout_cmd(root, env):
    """What the runner tells the agent to prefix browser commands with."""
    if shutil.which("timeout", path=env["PATH"]):
        return "timeout"
    return f"{root}/tools/compat/timeout"


def _script(name):
    return os.path.join(ROOT, "tools", name)


def test_linkedin_runs_each_role_through_the_agent(tmp_path):
    rows = [("Co0", "Engineer", "https://example.test/0", "cv.docx", "linkedin", "k0"),
            ("Co1", "Manager", "https://example.test/1", "cv.docx", "linkedin", "k1")]
    root, env = _sandbox(tmp_path, "queue-linkedin.tsv", rows)
    env.update(LINKEDIN_DELAY_MIN="0", LINKEDIN_DELAY_MAX="0")

    r = subprocess.run(["bash", _script("run_linkedin.sh")], env=env, input="not for the agent\n",
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    assert "command not found" not in r.stderr, r.stderr
    assert f"agent {env['AGENT']}" in r.stdout

    assert (tmp_path / "calls").read_text().splitlines() == ["Co0|Engineer", "Co1|Manager"]
    done = (root / "state" / "queue-linkedin.done").read_text().splitlines()
    assert done == ["Co0|Engineer", "Co1|Manager"]
    out = (root / "state" / "logs" / "linkedin_run.out").read_text()
    assert "STATUS Co1 | Manager | SUBMITTED | stub" in out
    assert "paced queue complete" in out

    assert (tmp_path / "prompts" / "Co0.stdin").read_text() == "", "the agent's stdin must be /dev/null"
    prompt = (tmp_path / "prompts" / "Co0.txt").read_text()
    assert f"Prefix `{_timeout_cmd(root, env)} 30`" in prompt


def test_human_assist_prefills_each_role_through_the_agent(tmp_path):
    rows = [("Co0", "Engineer", "https://example.test/0", "cv.docx", "letter.docx", "captcha"),
            ("Co1", "Manager", "", "cv.docx", "letter.docx", "captcha")]
    root, env = _sandbox(tmp_path, "queue-human.tsv", rows)

    r = subprocess.run(["bash", _script("human_assist.sh")], env=env,
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    assert "command not found" not in r.stderr, r.stderr
    assert "starting headful camoufox" not in r.stdout

    # The loop reads the queue on stdin; an agent that inherited it would swallow Co1.
    assert (tmp_path / "calls").read_text().splitlines() == ["Co0|Engineer", "Co1|Manager"]
    assert (tmp_path / "prompts" / "Co0.stdin").read_text() == ""
    assert "STATUS Co0 | Engineer | SUBMITTED | stub" in r.stdout
    assert "STATUS Co0 | Engineer" in (root / "state" / "logs" / "Co0-Engineer.human.log").read_text()
    prompt = (tmp_path / "prompts" / "Co0.txt").read_text()
    assert f"Prefix `{_timeout_cmd(root, env)} 30`" in prompt


@pytest.mark.parametrize("script, args, queue", [
    ("captcha_manual.sh", [], "queue-captcha.tsv"),
    ("human_assist.sh", ["--manual"], "queue-human.tsv"),
])
def test_manual_mode_opens_the_users_own_browser(tmp_path, script, args, queue):
    rows = [("Co0", "Engineer", "https://example.test/0", "cv.docx", "letter.docx", "captcha")]
    root, env = _sandbox(tmp_path, queue, rows)
    env["AGENT"] = "no-such-agent-xyz"  # manual mode runs no agent, so needs none

    r = subprocess.run(["bash", _script(script), *args], env=env,
                       capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr

    opened = tmp_path / "opened"
    deadline = time.monotonic() + 5  # the opener runs in the background
    while not opened.exists() and time.monotonic() < deadline:
        time.sleep(0.1)
    opener = "open" if platform.system() == "Darwin" else "xdg-open"
    assert opened.read_text() == f"{opener} https://example.test/0\n"
    assert not (tmp_path / "calls").exists()


def _watch_queue(monkeypatch, root):
    pytest.importorskip("rich")
    spec = importlib.util.spec_from_file_location("watch_queue", _script("watch_queue.py"))
    wq = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(wq)
    monkeypatch.setattr(wq, "ROOT", str(root))
    return wq


def test_watcher_marks_a_running_task_live(tmp_path, monkeypatch):
    # A real run: /proc on Linux, ps on macOS.
    rows = [("Acme Ltd", "Staff Engineer", "https://example.test/0", "cv.docx", "linkedin", "k0")]
    root, env = _sandbox(tmp_path, "queue-linkedin.tsv", rows)
    env.update(HOLD=str(tmp_path / "release"), LINKEDIN_DELAY_MIN="0", LINKEDIN_DELAY_MAX="0")
    wq = _watch_queue(monkeypatch, root)

    p = subprocess.Popen(["bash", _script("run_linkedin.sh")], env=env,
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        deadline = time.monotonic() + 20
        while not (tmp_path / "calls").exists() and time.monotonic() < deadline:
            time.sleep(0.1)
        assert (tmp_path / "calls").exists(), "the stub agent never started"
        assert wq.live_tasks() == {"Acme Ltd|Staff Engineer"}
    finally:
        (tmp_path / "release").touch()
        p.wait(timeout=30)
    assert wq.live_tasks() == set()


def test_watcher_reads_ps_where_there_is_no_proc(tmp_path, monkeypatch):
    root = tmp_path / "root"
    wq = _watch_queue(monkeypatch, root)
    monkeypatch.setattr(wq, "HAVE_PROC", False)
    listing = tmp_path / "ps.txt"
    bindir = tmp_path / "bin"
    bindir.mkdir()
    _exe(bindir / "ps", f'#!/bin/sh\ncat "{listing}"\n')
    monkeypatch.setenv("PATH", f"{bindir}:{os.environ['PATH']}")

    # As macOS `ps -axww -o pid=,command=` prints it: a newline inside an
    # argument is \012 and a tab \011. Our own process is skipped.
    queue_task = (f"  201 timeout 1200 bash {root}/tools/agent_run.sh You are applying. Repo: {root}"
                  r" (cwd).\012Company/tag: Acme Ltd\012Role: Staff Engineer\012ATS:\011greenhouse")
    human_task = (f"  202 claude -p You are helping. Repo: {root} (cwd).\\012Company: Beta AG"
                  r"\012Role: Lead\012Blocker (a human must act): captcha")
    lines = [f"{os.getpid()} python3 {root}/tools/run_queue.sh claude Company: Self\\012Role: Me",
             r"  203 /usr/bin/other Company: Elsewhere\012Role: Not ours"]
    listing.write_text("\n".join(lines) + "\n")
    assert wq.live_tasks() == set()
    assert not wq.runner_active()

    lines += [f"  200 bash {root}/tools/run_queue.sh", queue_task, human_task]
    listing.write_text("\n".join(lines) + "\n")
    assert wq.live_tasks() == {"Acme Ltd|Staff Engineer", "Beta AG|Lead"}
    assert wq.runner_active()
