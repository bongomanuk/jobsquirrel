"""Settings → About: full health checks plus this instance's details."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))

import dashboard as D  # noqa: E402


def test_health_full_reports_checks_and_instance(monkeypatch):
    monkeypatch.setattr(D, "health", lambda force=False: {
        "v": "PASS",
        "detail": "all ok",
        "checks": [{"name": "python", "status": "pass", "detail": "3.14"}],
        "register": {"summary": "32 register rows, 0 problem(s)", "problems": 0},
    })
    monkeypatch.setattr(D, "graph_query", lambda *a: {
        "index": True, "entities": 492, "relationships": 982,
        "communities": 8, "documents": 8, "runtime_s": 842,
    })
    monkeypatch.setattr(D, "_rows", lambda path: [{}, {}, {}])
    monkeypatch.setattr(D, "_count", lambda path: 7)
    monkeypatch.setattr(D, "_file_count", lambda path: 0)
    monkeypatch.setattr(D, "current_version", lambda: "9.9.9")

    d = D.health_full()

    assert d["status"] == "PASS"
    assert d["checks"][0]["name"] == "python"
    assert d["register"]["problems"] == 0
    inst = d["instance"]
    assert inst["version"] == "9.9.9"
    assert inst["register_rows"] == 3
    assert inst["submissions"] == 7
    assert inst["queue_rows"] == 7
    assert inst["graph"]["entities"] == 492
    assert inst["paths"]["state"] == "state"
    assert inst["python"]
    assert inst["platform"]


def test_health_full_survives_a_missing_graph(monkeypatch):
    monkeypatch.setattr(D, "health", lambda force=False: {
        "v": "PASS", "detail": "all ok", "checks": [], "register": {},
    })
    monkeypatch.setattr(D, "graph_query", lambda *a: {"error": "no index"})
    monkeypatch.setattr(D, "_rows", lambda path: [])
    monkeypatch.setattr(D, "_count", lambda path: 0)
    monkeypatch.setattr(D, "_file_count", lambda path: 0)

    d = D.health_full()

    assert d["instance"]["graph"] == {"error": "no index"}
