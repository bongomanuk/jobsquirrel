import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))

import dashboard as D
import approval


def test_prepare_and_submit_requires_the_approval_token(monkeypatch):
    monkeypatch.setattr(D, "_resolve_roles",
                        lambda keys: [{"company": "Acme", "role": "Engineer", "key": "acme-engineer"}])
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
    assert "Prepare and submit (${activeRows.length})" in app
    assert "label: 'Prepare and submit'" in app
    assert "App.prepareSubmit([${JSON.stringify(r.key)}])" in app
    assert "Prepare and submit (applies again)" in app
