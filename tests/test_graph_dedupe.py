"""Duplicate entities: same person twice, an employer and its legal entities.

The rule that matters: merge into the node the graph actually uses (most
connections), never into an abbreviation that merely normalises the same.
"""
import os
import sys

import pandas as pd
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))

import graph_dedupe as D  # noqa: E402


def frame(rows):
    return pd.DataFrame([{"title": t, "type": ty, "degree": d, "frequency": f}
                         for t, ty, d, f in rows])


def test_one_person_two_names_merges_into_the_full_name():
    ents = frame([("PETER HOLLAS", "PERSON", 108, 14),
                  ("PETER LIAM HOLLAS", "PERSON", 711, 15)])
    merge = D.build_map(ents)
    assert merge.get("PETER HOLLAS") == "PETER LIAM HOLLAS"


def test_two_different_people_are_not_merged():
    ents = frame([("ANNA SMITH", "PERSON", 10, 2), ("PETER SMITH", "PERSON", 9, 2)])
    assert D.build_map(ents) == {}


def test_an_employer_merges_into_its_busiest_node_not_its_abbreviation():
    ents = frame([("HAUD", "ORGANIZATION", 26, 2), ("HAUD AB", "ORGANIZATION", 82, 12)])
    assert D.build_map(ents).get("HAUD") == "HAUD AB"


def test_symbolic_names_are_never_merged():
    ents = frame([("C", "TECHNOLOGY", 40, 9), ("C++", "TECHNOLOGY", 22, 5),
                  ("C#", "TECHNOLOGY", 18, 4)])
    assert D.build_map(ents) == {}


def test_cycles_collapse_to_one_survivor():
    rank = {"A": (1, 1, 1), "B": (9, 1, 1), "C": (5, 1, 1)}
    out = D._break_cycles({"A": "B", "B": "C", "C": "A"}, rank)
    assert len({v for k, v in out.items()}) == 1
    assert out.get("A") == "B"


def test_a_duplicate_title_filed_under_two_types_is_merged():
    ents = frame([("CALLER FRAUD DETECTION PIPELINE", "PROJECT", 6, 3),
                  ("CALLER-FRAUD DETECTION PIPELINE", "TECHNOLOGY", 13, 6)])
    assert D.build_map(ents).get("CALLER FRAUD DETECTION PIPELINE") == "CALLER-FRAUD DETECTION PIPELINE"
