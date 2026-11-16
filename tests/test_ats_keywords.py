"""Decision-science terms must be extracted, not silently omitted from Fit."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))

import ats_keywords as A


def test_decision_science_terms_are_extracted():
    jd = ("We need causal inference, personalization, experimentation, "
          "decision automation, decisioning, live game analytics and simulation.")
    terms = {t.lower() for t in A.extract(jd)}
    for want in ("causal inference", "personalization", "experimentation",
                 "decision automation", "decisioning", "live game", "simulation"):
        assert want in terms, want
