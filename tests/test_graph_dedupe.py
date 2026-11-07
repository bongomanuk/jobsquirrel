"""Graph dedupe helpers: legal/office variants collapse, symbols do not."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))

import graph_dedupe as G  # noqa: E402


def test_office_and_legal_variants_share_a_base():
    assert G.base_org("ANAPLAN UK LTD") == "anaplan"
    assert G.base_org("ANAPLAN SINGAPORE PTE LTD") == "anaplan"
    assert G.base_org("ANAPLAN APAC HQ") == "anaplan"
    assert G.base_org("HAUD AB") == "haud"


def test_symbolic_titles_are_never_merged():
    assert G.symbolic("C++") and G.symbolic("C#") and G.symbolic("Spring/Camel")
    assert G.base_org("C++") == ""


def test_normalisation_keeps_tech_symbols_apart():
    assert G.norm("C++") != G.norm("C#")
    assert G.norm("C#") != G.norm("C")
