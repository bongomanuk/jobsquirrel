"""Orphan attachment counts links and places members in a community."""
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))
import graph_attach_orphans as G  # noqa: E402


def test_degrees_counts_relationships_and_overlay_links():
    rels = pd.DataFrame({"source": ["A", "B"], "target": ["B", "C"]})
    deg = G.degrees(rels, [{"source": "C", "target": "D"}])
    assert deg["A"] == 1
    assert deg["B"] == 2
    assert deg["C"] == 2
    assert deg["D"] == 1


def test_norm_collapses_case_and_punctuation():
    assert G._norm("Customer-Facing  Representation") == "customer facing representation"


def test_assign_communities_uses_target_community():
    ents = pd.DataFrame({
        "id": ["id-alex", "id-skill", "id-acme"],
        "title": ["ALEX", "SKILL", "ACME"],
    })
    comms = pd.DataFrame({
        "community": [0], "level": [0], "size": [1],
        "entity_ids": [["id-acme"]],
    })
    reports = pd.DataFrame({"community": [0], "size": [1]})
    n, updated = G.assign_communities(
        {"SKILL": [{"target": "ACME"}]}, ents, comms, reports)
    assert n == 1
    assert "id-skill" in list(updated.iloc[0]["entity_ids"])
    assert int(updated.iloc[0]["size"]) == 2
