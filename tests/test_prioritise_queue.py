import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))

import prioritise_queue as P  # noqa: E402

# Shared with tests/test_run_queue.py, which checks run_queue.sh ranks the same.
TITLES = [
    ("Junior Contractor - QA", 1),            # "cto" inside "contractor"
    ("Software Engineer, Public Sector", 1),  # "cto" inside "sector"
    ("Director of Engineering", 5),           # "cto" inside "director"
    ("VP Engineering", 6),
    ("Senior Engineer", 2),
    ("Engineer (Vector Search)", 1),          # "cto" inside "vector"
    ("Co-founder & CTO", 6),
    ("Head of Platform", 5),
    ("Staff Engineer", 4),
    ("Engineering Manager", 3),
    ("Engineering Leadership Programme", 1),  # "lead" inside "leadership"
    ("Sr. Data Engineer", 2),
]


@pytest.mark.parametrize("title, rank", TITLES)
def test_seniority_matches_whole_words(title, rank):
    assert P.seniority(title) == rank
