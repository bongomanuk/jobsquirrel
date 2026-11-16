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


def test_coverage_ignores_page_chrome(monkeypatch, tmp_path):
    """A row at 100% has no missing skills, and junk never lowers coverage."""
    import dashboard as D

    jd_dir = tmp_path / "job-descriptions"
    jd_dir.mkdir()
    (jd_dir / "acme.md").write_text(
        "# Acme AB — Engineer\n---\nA Python role. Salary SEK 100000.\n", encoding="utf-8")
    monkeypatch.setattr(D, "STATE", str(tmp_path))
    monkeypatch.setattr(S, "STATE", str(tmp_path))
    monkeypatch.setattr(S, "_MEM", None)
    monkeypatch.setattr(S, "_JD_MEM", {})

    cov, missing, detail = D._coverage_with_gaps("acme", ["Python", "SEK", "BCG"], "python")
    assert cov == 100, (cov, missing, detail)
    assert {d["term"] for d in detail if d["kind"] == "not-a-skill"} == {"SEK", "BCG"}
    assert [d["term"] for d in detail if d["kind"] != "not-a-skill"] == []


def test_parenthetical_label_is_the_noun_phrase_not_the_sentence():
    jd = ("# Acme — Engineer\n---\nWork together with the Acme Product Public Key "
          "Infrastructure (EPPKI). The role has responsibility for the Internal "
          "Development Platform (IDP).\n")
    cleaned = A.clean_jd(jd)
    assert S._deterministic("EPPKI", cleaned, jd)["label"] == \
        "Acme Product Public Key Infrastructure (EPPKI)"
    assert S._deterministic("IDP", cleaned, jd)["label"] == \
        "Internal Development Platform (IDP)"
