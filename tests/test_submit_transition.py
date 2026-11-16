import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))

import dashboard as D
import approval
import register as REG


def test_submitting_prepared_roles_does_not_reset_them_to_queued(monkeypatch):
    monkeypatch.setattr(D, "_resolve_roles",
                        lambda keys: [{"company": "Acme", "role": "Engineer",
                                       "key": "acme-engineer",
                                       "url": "https://example.test/apply"}])
    monkeypatch.setattr(D, "action_alive", lambda: False)
    monkeypatch.setattr(D, "WQ", None)
    monkeypatch.setattr(D, "_queue_only_roles", lambda rows: ("/tmp/q.tsv", "/tmp/q.done"))
    called = {}
    monkeypatch.setattr(D, "_spawn", lambda *a, **k: called.update(args=a, kwargs=k))
    monkeypatch.setattr(approval, "_record", lambda *a: None)
    wrote = []
    monkeypatch.setattr(REG, "set_row", lambda *a, **k: wrote.append((a, k)))

    out = D.submit_roles(["acme-engineer"], "APPROVE_RUN_QUEUE")
    assert "ok" in out
    assert wrote == [], "a prepared row must stay PREPARED while the submission runs"
    env = called["args"][2]
    assert env["PREPARED"] == "1"
    assert called["kwargs"]["roles"][0]["company"] == "Acme"
