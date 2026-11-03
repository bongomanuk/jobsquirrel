"""Present-tense claims are checked per clause, not per whole sentence.

A profile sentence can mention a past employer and then a present-day fact about
today ("... at Telia's R&D division, and I run two AI products"). That is not a
claim about the past employer, so it must not fail the gate.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))

import facts as F

FACTS = {"past_terms": ["Telia", "Anaplan"], "current_terms": [], "past_employers": [],
         "current_employers": [], "employers": [], "certifications": [], "languages": []}
CORPUS = "telia anaplan"


def _errors(text):
    return F.check_text(text, FACTS, CORPUS)[0]


def test_past_employer_then_current_practice_is_allowed():
    assert not _errors(
        "I owned enterprise architecture at Telia's R&D division, platform architecture "
        "at Anaplan through its scale-up to $11B, and I run two AI products of my own.")


def test_present_tense_at_a_past_employer_still_fails():
    assert _errors("At Telia I currently lead the engineering organisation.")


def test_present_tense_at_a_past_employer_after_and_still_fails():
    assert _errors("I am leading the platform team at Anaplan.")


def test_leading_place_phrase_stays_with_its_clause():
    assert _errors("At Anaplan, I am leading the platform team.")


def test_past_tense_and_a_separate_present_fact_is_allowed():
    assert not _errors("I was Head of Engineering at Telia and I now run two products.")
