import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))

import dashboard as D
import approval


def test_prepare_and_submit_requires_the_approval_token(monkeypatch):
    monkeypatch.setattr(D, "_resolve_roles",
                        lambda keys: [{"company": "Acme", "role": "Engineer", "key": "acme-engineer", "url": "https://example.test/apply"}])
    monkeypatch.setattr(D, "action_alive", lambda: False)
    monkeypatch.setattr(D, "WQ", None)
    monkeypatch.setattr(D, "_queue_only_roles", lambda rows: ("/tmp/q.tsv", "/tmp/q.done"))
    called = {}
    monkeypatch.setattr(D, "_spawn", lambda *a, **k: called.update(args=a, kwargs=k))
    monkeypatch.setattr(approval, "_record", lambda *a: None)

    refused = D.prepare_submit_roles(["acme-engineer"], "")
    assert "error" in refused
    assert not called

    out = D.prepare_submit_roles(["acme-engineer"], "APPROVE_RUN_QUEUE")
    assert "ok" in out
    env = called["args"][2]
    assert env["PARALLEL"] == "1"
    assert "PREPARED" not in env and "REVIEW" not in env
    assert called["kwargs"]["roles"][0]["company"] == "Acme"


def test_the_context_menu_offers_prepare_and_submit():
    with open(os.path.join(ROOT, "tools", "web", "app.js"), encoding="utf-8") as fh:
        app = fh.read()
    assert "prepareSubmit: async" in app
    assert "Prepare and submit (${submitRows.length})" in app
    assert "label: 'Prepare and submit'" in app
    assert "App.prepareSubmit([${JSON.stringify(r.key)}])" in app
    assert "Prepare and submit (applies again)" in app


def test_prepare_and_submit_refuses_a_role_without_an_apply_url(monkeypatch):
    monkeypatch.setattr(D, "_resolve_roles",
                        lambda keys: [{"company": "Toptal", "role": "Talent network",
                                       "key": "toptal-talent-network", "url": ""}])
    monkeypatch.setattr(D, "action_alive", lambda: False)
    monkeypatch.setattr(D, "WQ", None)
    called = {}
    monkeypatch.setattr(D, "_spawn", lambda *a, **k: called.update(args=a, kwargs=k))
    out = D.prepare_submit_roles(["toptal-talent-network"], "APPROVE_RUN_QUEUE")
    assert "no apply URL" in out["error"]
    assert not called


def test_the_menu_hides_prepare_and_submit_without_a_url():
    with open(os.path.join(ROOT, "tools", "web", "app.js"), encoding="utf-8") as fh:
        app = fh.read()
    assert "submitRows = activeRows.filter(x => !!x.url)" in app
    assert "active && r.url" in app


def test_resolve_roles_falls_back_to_the_register_apply_url(monkeypatch):
    monkeypatch.setattr(D, "_queue_rows", lambda path: [])
    monkeypatch.setattr(D, "_rows", lambda path: [{
        "company": "Acme", "role": "Software Engineer",
        "apply_url": "https://example.test/apply",
    }])
    monkeypatch.setattr(D, "_key_maps", lambda: ({("acme", "software engineer"): "acme-key"}, {}))
    monkeypatch.setattr(D, "_queue_fields", lambda co, role: ("", "", "", ""))
    rows = D._resolve_roles(["acme-key"])
    assert rows[0]["url"] == "https://example.test/apply"
