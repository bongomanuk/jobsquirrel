"""A reconcile reports what it actually proposed or changed.

The Activity pane used to show only the final counts line ("3 proposed"),
which told the user that something happened but not what. The overview now
carries the register changes and the UI renders them.
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))

import dashboard as D  # noqa: E402

APP = os.path.join(ROOT, "tools", "web", "app.js")


def _lines(mode="applied"):
    return [
        "== proposed register changes ==",
        "  Acme       Engineer         SUBMITTED  -> REJECTED  [REJECTION]",
        "  Beta Corp  Engineering Lead SUBMITTED  -> INTERVIEW [INTERVIEW]",
        "",
        "applied 2 change(s); register regenerated" if mode == "applied" else "(dry run)",
        "",
        f"== summary ({'applied' if mode == 'applied' else 'dry run'}): 10 inspected · "
        "2 proposed · 0 outbound · 0 verification · 0 unmatched · 0 ambiguous ==",
    ]


def test_applied_reconcile_names_the_changes(tmp_path, monkeypatch):
    monkeypatch.setattr(D, "STATE", str(tmp_path))
    out = D.action_overview("action=reconcile_apply", _lines("applied"), False)
    text = "\n".join(out)
    assert "new this run (applied): 2 proposed" in text
    assert "changed: Acme Engineer SUBMITTED -> REJECTED [REJECTION]" in text
    assert "changed: Beta Corp Engineering Lead SUBMITTED -> INTERVIEW [INTERVIEW]" in text


def test_dry_run_calls_them_proposals(tmp_path, monkeypatch):
    monkeypatch.setattr(D, "STATE", str(tmp_path))
    out = D.action_overview("reconcile", _lines("dry run"), False)
    text = "\n".join(out)
    assert "new this run (dry run): 2 proposed" in text
    assert "proposed: Acme Engineer SUBMITTED -> REJECTED [REJECTION]" in text


def test_the_agent_console_gets_the_outcome_and_activity_stays_live():
    with open(APP, encoding="utf-8") as fh:
        app = fh.read()
    # The durable action card (with the reconcile overview) lives in the chat.
    assert "Where we are" in app
    assert "ov = a.overview || []" in app
    # A finished background task carries its final prose answer in the chat.
    assert "d.summary && d.summary !== d.result" in app
    assert "full log" in app.lower() or "Full log" in app
    # Activity no longer renders a finished action summary.
    assert "else if (a.name && a.finished)" not in app
    assert "Nothing running." in app


def test_the_reconcile_log_still_prints_the_changes(tmp_path, monkeypatch):
    # The CLI must keep its own summary for hand-run reconciles.
    import gmail_reconcile as GR
    assert "== proposed register changes ==" in open(GR.__file__, encoding="utf-8").read()
    assert 'f"\\n== summary ({mode})' in open(GR.__file__, encoding="utf-8").read()
