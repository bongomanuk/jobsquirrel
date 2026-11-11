"""The `flow` command: a whole form page in one browser round-trip.

These tests drive a real Camoufox server (never Chromium) against a local
file:// fixture, so they exercise the same dispatch path an application uses:
nav, waitfor, fill, select, upload, click, waittext, snap --match and text.

If Camoufox is not installed the module is skipped rather than failed: the
pipeline's unit tests must pass on a machine that has not run tools/install.sh.
"""
import json
import os
import socket
import subprocess
import sys
import time
import urllib.request

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SERVER = os.path.join(ROOT, "tools", "camoufox_server.py")
CLI = os.path.join(ROOT, "tools", "camoufox_browser.py")

pytest.importorskip("camoufox")

FIXTURE = """<!doctype html><html><head><meta charset="utf-8"><title>Apply</title></head>
<body>
  <h1>Senior Manager</h1>
  <form onsubmit="return false">
    <input id="name" name="name">
    <select id="country"><option value="">-</option><option value="se">Sweden</option></select>
    <input id="cv" type="file">
    <button id="go" type="button"
      onclick="document.getElementById('out').innerText='Thank you for applying'">Submit</button>
    <button id="late" type="button">Never mind</button>
  </form>
  <div id="out"></div>
</body></html>
"""


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture(scope="module")
def server():
    port = _free_port()
    url = f"http://127.0.0.1:{port}"
    proc = subprocess.Popen([sys.executable, SERVER, "--port", str(port)],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(120):
            try:
                with urllib.request.urlopen(f"{url}/health", timeout=2) as r:
                    if r.status == 200:
                        break
            except Exception:
                time.sleep(1)
        else:
            pytest.skip("camoufox server did not start")
        yield url
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except Exception:
            proc.kill()


@pytest.fixture()
def page(tmp_path):
    p = tmp_path / "apply.html"
    p.write_text(FIXTURE, encoding="utf-8")
    return p.as_uri()


def _run(server, *args, timeout=180):
    r = subprocess.run([sys.executable, CLI, "--server", server, *args],
                       capture_output=True, text=True, timeout=timeout)
    assert r.stdout.strip(), r.stderr
    return json.loads(r.stdout)


def _flow(server, steps, **extra):
    spec = json.dumps({"steps": steps, **extra})
    return _run(server, "flow", spec)


def test_flow_fills_submits_and_confirms_in_one_call(server, page, tmp_path):
    cv = tmp_path / "cv.docx"
    cv.write_bytes(b"not a real docx")
    out = _flow(server, [
        {"op": "nav", "url": page},
        {"op": "waitfor", "selector": "#name"},
        {"op": "fill", "selector": "#name", "value": "Peter Hollas"},
        {"op": "select", "selector": "#country", "value": "se"},
        {"op": "upload", "selector": "#cv", "path": str(cv)},
        {"op": "click", "target": "#go"},
        {"op": "waittext", "text": "thank you", "timeout": 5000},
        {"op": "snap", "match": "never mind"},
    ], text=True, text_max=300)

    assert out["ok"] is True, out
    assert out["step_count"] == 8
    assert all(s["ok"] for s in out["steps"]), out["steps"]
    # The confirmation is read in the same call: no second turn needed.
    assert "Thank you for applying" in out["text"]
    # values landed
    assert _run(server, "value", "#name")["value"] == "Peter Hollas"
    assert _run(server, "eval", "document.getElementById('cv').files[0].name")["result"] == "cv.docx"
    # snap --match narrowed the refs but kept their real indices
    snap = out["steps"][-1]
    assert [r["text"] for r in snap["refs"]] == ["Never mind"]
    assert snap["refs_total"] >= 3
    assert snap["refs"][0]["ref"] >= 2


def test_flow_stops_at_the_first_failing_step(server, page):
    out = _flow(server, [
        {"op": "nav", "url": page},
        {"op": "click", "target": "#does-not-exist"},
        {"op": "fill", "selector": "#name", "value": "should not happen"},
    ])
    assert out["ok"] is False
    assert out["failed_at"] == 1
    assert out["failed_op"] == "click"
    assert len(out["steps"]) == 2              # the third step never ran
    assert _run(server, "value", "#name")["value"] == ""


def test_flow_optional_step_does_not_abort(server, page):
    out = _flow(server, [
        {"op": "nav", "url": page},
        {"op": "click", "target": "#missing", "optional": True},
        {"op": "fill", "selector": "#name", "value": "continued"},
    ])
    assert out["ok"] is True, out
    assert out["steps"][1]["ok"] is False
    assert _run(server, "value", "#name")["value"] == "continued"


def test_waittext_times_out_with_a_hint(server, page):
    t0 = time.time()
    res = _run(server, "nav", page)
    assert res["ok"] is True
    out = _run(server, "waittext", "no such confirmation", "600")
    assert out["ok"] is False
    assert "not seen in 600ms" in out["error"]
    assert out["text"]                      # what the page actually said
    assert time.time() - t0 < 30            # it returns, it does not hang
    # A wait that holds costs only as long as the condition takes.
    out = _run(server, "waittext", "Senior Manager", "5000")
    assert out["ok"] is True and out["waited_ms"] < 5000


def test_waitfor_and_text_commands(server, page):
    out = _run(server, "nav", page)
    assert out["ok"] is True
    assert _run(server, "waitfor", "#go", "3000")["ok"] is True
    # an empty container is attached but not visible: both states are available
    assert _run(server, "waitfor", "#out", "3000", "attached")["ok"] is True
    assert _run(server, "waitfor", "#out", "400")["ok"] is False
    bad = _run(server, "waitfor", "#nothing-here", "500")
    assert bad["ok"] is False and "not seen in 500ms" in bad["error"]
    txt = _run(server, "text", "120")
    assert txt["ok"] is True and "Senior Manager" in txt["text"]


def test_flow_reads_steps_from_a_file(server, page, tmp_path):
    spec = tmp_path / "steps.json"
    spec.write_text(json.dumps({"steps": [{"op": "nav", "url": page},
                                          {"op": "snap", "match": "Submit"}]}))
    out = _run(server, "flow", f"@{spec}")
    assert out["ok"] is True, out
    assert [r["text"] for r in out["steps"][-1]["refs"]] == ["Submit"]
