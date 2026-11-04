"""`runner_active()` must see a run for THIS repo and nothing else.

The dashboard shows a "running" badge and, when it clears, announces that a run
finished. Before this was scoped, any `run_queue.sh` anywhere (the test suite
starts them in throwaway sandboxes) flipped that badge — so an open dashboard
kept announcing finished runs while the code was being worked on.
"""
import os
import subprocess
import sys
import time

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))

import watch_queue as WQ  # noqa: E402

pytestmark = pytest.mark.skipif(not os.path.isdir("/proc"), reason="needs /proc (Linux)")


def _fake_run(env_root, cwd, queue=""):
    """A process whose command line looks like a queue runner."""
    env = dict(os.environ)
    env.pop("ROOT", None)
    if env_root:
        env["ROOT"] = str(env_root)
    if queue:
        env["QUEUE"] = queue
    proc = subprocess.Popen(["bash", "-c", "exec -a run_queue.sh sleep 10"],
                            cwd=str(cwd), env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    deadline = time.time() + 3
    while time.time() < deadline:
        try:
            with open(f"/proc/{proc.pid}/cmdline", "rb") as fh:
                if b"run_queue.sh" in fh.read():
                    return proc
        except OSError:
            pass
        time.sleep(0.02)
    proc.kill()
    pytest.fail("the fake runner never showed up in /proc")


def test_a_run_for_this_repo_counts():
    proc = _fake_run(ROOT, ROOT)
    try:
        assert WQ.runner_active() is True
    finally:
        proc.kill()


def test_a_run_started_from_the_repo_counts_even_without_root_env():
    """A hand-run `bash tools/run_queue.sh` has no ROOT= but works in the repo."""
    proc = _fake_run("", ROOT)
    try:
        assert WQ.runner_active() is True
    finally:
        proc.kill()


def test_a_run_in_a_throwaway_root_does_not_count(tmp_path):
    """The test suite runs the real script against a sandbox ROOT= — ignore it."""
    proc = _fake_run(tmp_path, ROOT)
    try:
        assert WQ.runner_active() is False
    finally:
        proc.kill()


def test_a_run_from_another_directory_does_not_count(tmp_path):
    proc = _fake_run("", tmp_path)
    try:
        assert WQ.runner_active() is False
    finally:
        proc.kill()


def test_watch_queue_itself_is_never_a_run(tmp_path):
    env = dict(os.environ, ROOT=ROOT)
    proc = subprocess.Popen(["bash", "-c", "exec -a watch_queue.py sleep 10"],
                            cwd=ROOT, env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        time.sleep(0.2)
        assert WQ.runner_active() is False
    finally:
        proc.kill()


def test_a_bench_queue_does_not_count(tmp_path):
    """A /tmp/bench queue is a local benchmark, not a job-search run."""
    proc = _fake_run(ROOT, ROOT, queue=str(tmp_path / "bench-queue.tsv"))
    try:
        assert WQ.runner_active() is False
        assert f"Fake Co|Fake Role" not in WQ.live_tasks()
    finally:
        proc.kill()
