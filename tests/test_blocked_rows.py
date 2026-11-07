"""Blocked rows: a gate refusal is its own sub-state, and bare queue keys are not rows."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))

import dashboard as D  # noqa: E402


def test_a_gate_refusal_gets_the_gate_substate():
    key, label, hint = D._substate(
        "BLOCKED",
        "pre-submit gate FAIL (check_documents.py RESULT: FAIL): CV canonical-fact violations")
    assert key == "gate"
    assert "gate" in label.lower()


def test_a_captcha_block_is_still_captcha():
    key, label, _ = D._substate("BLOCKED", "blocked by a CAPTCHA on the employer site")
    assert key == "captcha"


def test_a_bare_retry_key_is_not_a_queue_row(tmp_path):
    q = tmp_path / "queue.retry"
    q.write_text("li_monterro_chief_technology_officer_kaisa\n"
                 "Acme\tEngineer\thttps://x/\tcv.docx\tAshby\tacme-engineer\n", encoding="utf-8")
    rows = D._queue_rows(str(q))
    assert len(rows) == 1
    assert rows[0]["company"] == "Acme" and rows[0]["role"] == "Engineer"
