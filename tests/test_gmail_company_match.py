"""Company matching must not turn a word in a job title into an employer."""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))

import gmail_reconcile as G  # noqa: E402

ROWS = [
    {"company": "Customer First AB", "role": "DevOps Team Lead", "status": "SUBMITTED"},
    {"company": "Spotify", "role": "Senior Backend Engineer - Subscriptions",
     "status": "SUBMITTED"},
]


def test_job_title_word_does_not_resolve_a_company():
    got = G.match_company(
        "Your application – (Senior) Software Engineer (Customer Identity) (m/f/d) "
        "Riverty Hiring Team",
        ROWS, body="", sender="Riverty Hiring Team <notifications@smartrecruiters.com>")
    assert got != "Customer First AB", got


def test_full_company_name_still_matches():
    got = G.match_company("Customer First AB — DevOps Team Lead", ROWS,
                          body="", sender="careers@customerfirst.se")
    assert got == "Customer First AB", got
