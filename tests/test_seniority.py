"""Seniority grading: word boundaries matter, and rank order is stable."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))

import dashboard as D  # noqa: E402


def grade(title):
    return D.seniority_of(title)[0]


def test_director_is_not_c_level():
    # "director" contains the letters "cto"; a substring match graded it C-level.
    assert grade("Engineering Director") == "director"
    assert grade("Director of Engineering") == "director"
    assert grade("Head of Platform") == "director"


def test_manager_beats_senior():
    assert grade("Senior Manager, Product Analytics") == "manager"
    assert grade("Data Engineering Manager") == "manager"


def test_individual_contributor_ladder():
    assert grade("Senior Data Engineer") == "senior"
    assert grade("Staff ML Engineer") == "staff"
    assert grade("Principal Architect") == "principal"
    assert grade("Platform Engineering Lead") == "lead"
    assert grade("Analytics Engineer") == "mid"
    assert grade("Junior Developer") == "junior"
    assert grade("Software Engineering Intern") == "intern"


def test_executive_ladder():
    assert grade("VP of R&D") == "vp"
    assert grade("Co-Founder/CTO") == "c-level"
    assert grade("Chief Technology Officer") == "c-level"


def test_jd_fallback_when_title_is_generic():
    assert grade("Engineer") == "mid"
    key, label, rank = D.seniority_of("Engineer", "You will report to the CTO.")
    assert key == "lead" and rank == 6
