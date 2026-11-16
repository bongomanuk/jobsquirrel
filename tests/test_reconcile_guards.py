"""Reconciliation must not invent a stage from an old or premature email."""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))

import gmail_reconcile as G  # noqa: E402


def test_an_invitation_cannot_promote_a_role_that_was_never_sent():
    for status in ("PREPARED", "QUEUED", "DRAFTING"):
        assert G.propose(status, "INTERVIEW") == "", status


def test_an_invitation_still_promotes_a_submitted_role():
    assert G.propose("SUBMITTED", "INTERVIEW") == "INTERVIEW"
    assert G.propose("IN_PROGRESS", "INTERVIEW") == "INTERVIEW"
    assert G.propose("INTERVIEW", "INTERVIEW") != ""


def test_a_closed_or_blocked_row_is_never_reopened_by_mail():
    for status in ("CLOSED", "BLOCKED", "MANUAL"):
        assert G.propose(status, "INTERVIEW") == ""
    assert G.propose("OFFER", "REJECTION") == "OFFER"


def test_an_email_older_than_the_row_is_ignored():
    row = {"date": "2026-11-11"}
    assert G.predates_row("2026-11-05", row) is True
    assert G.predates_row("2026-11-11", row) is False
    assert G.predates_row("2026-11-12", row) is False
    assert G.predates_row("2026-11-05", {}) is False      # no date, no guess
