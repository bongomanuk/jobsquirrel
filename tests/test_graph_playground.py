"""The knowledge-graph playground builds a brief and a traversal timeline."""
import glob
import json
import os
import subprocess

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = os.path.join(ROOT, ".venv-graphrag", "bin", "python")
TOOL = os.path.join(ROOT, "tools", "graph_explore.py")


def test_playground_returns_steps_and_a_document():
    jds = sorted(glob.glob(os.path.join(ROOT, "state", "job-descriptions", "*.md")))
    if not jds or not os.path.exists(PY) or not os.path.exists(
            os.path.join(ROOT, "kb", "graphrag", "output", "entities.parquet")):
        pytest.skip("no saved job spec or GraphRAG index in this checkout")
    key = os.path.basename(jds[0])[:-3]
    r = subprocess.run([PY, TOOL, "playground", key, "1"],
                       cwd=ROOT, capture_output=True, text=True, timeout=120)
    data = json.loads((r.stdout or "").strip() or "{}")
    assert not data.get("error"), data
    assert data["steps"]
    assert data["steps"][0]["kind"] == "read"
    assert all("query" in s for s in data["steps"])
    # the recursive query is animated before anything is written
    assert any(s["kind"] == "query" for s in data["steps"])
    assert any(s["query"].startswith("MATCH requirement") for s in data["steps"])
    assert any(s["query"].startswith("EXPAND hop") for s in data["steps"])
    assert any(s["kind"] == "write" for s in data["steps"])
    assert all(s.get("explain") for s in data["steps"])
    assert any(s.get("write") for s in data["steps"])
    assert any(s.get("trace") for s in data["steps"])
    assert data["job"]["lines"] and data["job"]["found"]
    assert isinstance(data["job"]["hops"], int)
    assert not any("[object Object]" in json.dumps(s) for s in data["steps"])
    assert data["doc"]["blocks"]
    assert any("summary" in b["heading"].lower() or "experience" in b["heading"].lower()
               for b in data["doc"]["blocks"])
    assert data["doc"]["name"]
    assert data["doc"]["contact"]
    assert data["graph"]["nodes"]
    assert all("label" in s for s in data["steps"])

    letter = subprocess.run([PY, TOOL, "playground", key, "1", "letter"],
                            cwd=ROOT, capture_output=True, text=True, timeout=120)
    ldata = json.loads((letter.stdout or "").strip() or "{}")
    assert not ldata.get("error"), ldata
    assert ldata["doc"]["title"] == "Cover letter"
    assert ldata["doc"]["prologue"] == ["Dear Hiring Team,"]
    assert all(b["type"] == "letter" and not b["heading"] for b in ldata["doc"]["blocks"])
    assert any(s["kind"] == "query" for s in ldata["steps"])


def test_playground_drawer_works_in_both_views():
    html = open(os.path.join(ROOT, "tools", "web", "index.html"), encoding="utf-8").read()
    app = open(os.path.join(ROOT, "tools", "web", "app.js"), encoding="utf-8").read()
    css = open(os.path.join(ROOT, "tools", "web", "app.css"), encoding="utf-8").read()
    assert 'id="kg-play-drawer"' in html
    assert 'id="kg-play-open"' in html
    assert 'id="kg-play-grip"' in html
    assert 'id="kg-side-grip"' in html
    assert "KGMODE === 'universe'" in app
    assert "window.__uni.setPlayback" in app
    assert "kgPlayFilter" in app
    assert "kg-play-q" in app
    assert "kg-play-spec" in app
    assert "kgPlaySpecFocus" in app
    assert "kg-play-pane" in css
    assert "var(--kg-play-w" in css
    assert "kg-play-drawer" in css
