"""The ontology: typed relations and per-role class weights.

GraphRAG emits typed entities but untyped edges. The ontology turns the edges
into a vocabulary the selection layer can reason about, and gives each kind of
role its own weighting of the graph.
"""
import os
import sys

import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))

import ontology as ONT  # noqa: E402
import graph_relations as GR  # noqa: E402


def test_a_person_and_a_role_is_a_held_role():
    assert ONT.relation_for("PERSON", "ROLE") == "HELD_ROLE"
    assert ONT.relation_for("ROLE", "PERSON") == "HELD_ROLE"


def test_an_organisation_and_a_technology_is_uses():
    assert ONT.relation_for("ORGANIZATION", "TECHNOLOGY") == "USES"
    assert ONT.relation_for("PROJECT", "PLATFORM") == "USES"


def test_siblings_stay_generic():
    assert ONT.relation_for("TECHNOLOGY", "TECHNOLOGY") == "RELATED_TO"
    assert ONT.relation_for("SKILL", "SKILL") == "RELATED_TO"


def test_aliases_are_resolved_before_classifying():
    # COMPANY is an alias for ORGANIZATION, TOOL for TECHNOLOGY
    assert ONT.relation_for("COMPANY", "TOOL") == "USES"


def test_weights_follow_the_kind_of_role():
    assert ONT.weights_for("Head of Engineering")[0] == "leadership"
    assert ONT.weights_for("Senior AI Engineer, LLM agents")[0] == "ai"
    assert ONT.weights_for("Cyber Security Architect")[0] == "security"
    assert ONT.weights_for("Data Scientist")[0] == "data"
    prof, w = ONT.weights_for("Head of Engineering")
    assert w["ROLE"] > w["TECHNOLOGY"], "leadership leans on roles, not tools"
    prof, w = ONT.weights_for("Senior AI Engineer")
    assert w["TECHNOLOGY"] > w["ROLE"], "an AI CV leans on technology"


def test_every_class_has_a_weight():
    _, w = ONT.weights_for("Head of Engineering")
    for cls in ("ROLE", "ORGANIZATION", "TEAM", "PROJECT", "SKILL", "TECHNOLOGY"):
        assert ONT.weight_of(w, cls) > 0


def test_edges_are_classified_from_their_endpoints():
    ents = pd.DataFrame({"title": ["PETER HOLLAS", "HAUD AB", "PYTHON", "SMS FRAUD"],
                         "type": ["PERSON", "ORGANIZATION", "TECHNOLOGY", "PROJECT"]})
    rels = pd.DataFrame({
        "id": [1, 2, 3], "source": ["PETER HOLLAS", "HAUD AB", "SMS FRAUD"],
        "target": ["HAUD AB", "PYTHON", "PYTHON"], "description": ["worked there", "", ""],
        "weight": [1.0, 1.0, 1.0]})
    out = GR.classify(ents, rels)
    assert list(out["relation_type"]) == ["AT_ORGANIZATION", "USES", "USES"]


def test_the_shipped_ontology_has_a_profile_for_each_family():
    data = ONT.load()
    profiles = data.get("profiles") or {}
    for name in ("leadership", "ai", "data", "security", "architecture"):
        assert name in profiles, name
