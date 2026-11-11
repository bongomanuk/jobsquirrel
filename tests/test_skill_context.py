"""ATS keywords and missing-skill labels must describe skills, not page chrome."""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))

import ats_keywords as A  # noqa: E402
import skill_context as S  # noqa: E402

JD = """# Acme AB — Head of Data
Source: https://example.test/job
Fetched: 2026-11-11
---
Head of Data
Acme AB  Stockholm

You will lead our data platform with Python, dbt and LLMOps.
Our other open positions
Senior Engineer | BCG Platinion
Head of VMO | GOT YOUR BACK
Salary SEK 90000
"""


def test_ats_extract_skips_header_codes_and_related_jobs():
    kws = A.extract(JD)
    joined = " ".join(kws)
    assert "Python" in kws and "dbt" in kws
    for noise in ("BCG", "GOT", "VMO", "SEK", "Head of VMO"):
        assert noise not in joined, (noise, kws)
    assert len(kws) == len({k.lower() for k in kws})


def test_missing_skill_context_explains_and_filters():
    cleaned = A.clean_jd(JD)
    assert S._deterministic("LLMOps", cleaned, JD)["label"].startswith("LLM Operations")
    assert S._deterministic("SEK", cleaned, JD)["kind"] == "not-a-skill"
    assert S._deterministic("UMKACN", cleaned, JD)["kind"] == "not-a-skill"
    assert S._deterministic("BCG", cleaned, JD)["kind"] == "not-a-skill"
