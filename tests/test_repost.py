import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))

import dashboard as D


def test_a_repost_is_the_same_title_ignoring_punctuation():
    assert D._same_role("Principal Consultant - Data & AI Strategy",
                        "Principal Consultant, Data & AI Strategy")
    assert D._same_role("Senior Solutions Engineer | Sweden | Remote",
                        "Senior Solutions Engineer (Sweden, Remote)")
    assert D._same_role("Lead AI Automation Engineer", "Lead AI & Automation Engineer")


def test_a_different_title_is_not_a_repost():
    assert not D._same_role("AI Engineer", "Senior AI Engineer")
    assert not D._same_role("Staff Engineer", "Senior Staff Machine Learning Engineer")
    assert not D._same_role("AI Engineer - QuantumBlack", "Senior AI Engineer - QuantumBlack")


def test_the_queue_runner_never_skips_a_repost():
    with open(os.path.join(ROOT, "tools", "run_queue.sh"), encoding="utf-8") as fh:
        sh = fh.read()
    assert "SKIP-DUPLICATE" not in sh
    assert "REPOST $(date" in sh
    assert "Do not record CLOSED because it looks like a duplicate" in sh
