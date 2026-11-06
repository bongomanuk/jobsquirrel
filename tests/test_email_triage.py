"""Language-agnostic email triage: metadata and structure, not per-language regex."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))
import email_triage as ET  # noqa: E402


def _triage(sender, subject, body, company):
    r = ET.triage(subject, body, sender, [{"company": company}])
    return r["job"], r["category"]


def test_ats_confirmation_is_job_without_language_patterns():
    job, cat = _triage("Acme <no-reply@acme.teamtailor-mail.com>",
                       "Vi har tagit emot din ansökan!", "Tack för din ansökan.", "Acme")
    assert job and cat == "CONFIRMATION"


def test_marketing_domain_is_not_job():
    job, _ = _triage("AliExpress <x@newarrival.aliexpress.com>",
                     "Deals", "Shop now", "AliExpress")
    assert not job


def test_github_ci_is_not_job():
    job, _ = _triage("build-bot <notifications@github.com>",
                     "[repo] Run failed: CI", "workflow run", "GitHub")
    assert not job


def test_meeting_link_and_date_is_interview():
    job, cat = _triage("Acme <hr@acme.com>", "Interview",
                       "Join https://meet.google.com/abc on 2026-11-12 at 10:00", "Acme")
    assert job and cat == "INTERVIEW"


def test_company_token_in_sender_is_job():
    job, _ = _triage("Jane Doe - Acme <jane.doe@acme.se>",
                     "Vi har tagit emot din ansökan!", "Tack.", "Acme")
    assert job


def test_application_id_is_confirmation():
    job, cat = _triage("Acme <hr@acme.com>", "Application", "Your req 12345 is received.", "Acme")
    assert job and cat == "CONFIRMATION"
