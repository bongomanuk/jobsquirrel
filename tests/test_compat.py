"""The tools/compat stand-ins for flock/setsid/timeout (macOS has none of them).

They are run by path, so these tests exercise them even where the real
commands exist.
"""
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COMPAT = os.path.join(ROOT, "tools", "compat")
TIMEOUT = os.path.join(COMPAT, "timeout")
FLOCK = os.path.join(COMPAT, "flock")
SETSID = os.path.join(COMPAT, "setsid")


def test_timeout_passes_status_through():
    assert subprocess.run([TIMEOUT, "5", "true"]).returncode == 0
    assert subprocess.run([TIMEOUT, "5", "sh", "-c", "exit 3"]).returncode == 3


def test_timeout_expires_with_124_and_kills_children(tmp_path):
    marker = tmp_path / "survived"
    start = time.monotonic()
    # The grandchild would write the marker after 2s if it outlived the timeout.
    r = subprocess.run([TIMEOUT, "1", "sh", "-c", f"(sleep 2; touch {marker}) & wait"])
    assert r.returncode == 124
    assert time.monotonic() - start < 1.9
    time.sleep(1.5)
    assert not marker.exists(), "grandchild outlived the timeout"


def test_timeout_missing_command():
    assert subprocess.run([TIMEOUT, "1", "no-such-command-xyz"],
                          capture_output=True).returncode == 127


def test_flock_fd_form_is_mutually_exclusive(tmp_path):
    # Two writers each do 100 read-increment-write cycles on one counter. Without
    # a working lock the cycles interleave and updates are lost.
    counter, lock = tmp_path / "n", tmp_path / "lock"
    counter.write_text("0")
    script = (f'for i in $(seq 1 100); do {{ "{FLOCK}" -x 9; '
              f'n=$(cat "{counter}"); echo $((n + 1)) > "{counter}"; }} 9>>"{lock}"; done')
    procs = [subprocess.Popen(["bash", "-c", script]) for _ in range(2)]
    assert all(p.wait() == 0 for p in procs)
    assert counter.read_text().strip() == "200"


def test_flock_nonblocking_fails_while_held(tmp_path):
    lock = tmp_path / "lock"
    holder = subprocess.Popen(["bash", "-c", f'{{ "{FLOCK}" -x 9; sleep 2; }} 9>>"{lock}"'])
    time.sleep(0.5)
    r = subprocess.run(["bash", "-c", f'{{ "{FLOCK}" -n 9; }} 9>>"{lock}"'])
    holder.wait()
    assert r.returncode == 1


def test_setsid_starts_a_new_session():
    code = "import os, sys; sys.exit(0 if os.getsid(0) == os.getpid() else 1)"
    assert subprocess.run([SETSID, "-w", sys.executable, "-c", code]).returncode == 0
