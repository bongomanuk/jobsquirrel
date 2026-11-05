"""Queue aliases must not appear as a second role on the dashboard.

A LinkedIn alert title ("Neko Health starting at $405K/year") or a short form
("neko") can differ from the register's employer name after a rename. The grid
merges the alias into the register row using the title plus the employer token.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))

import dashboard as D


def test_company_token_ignores_alert_suffix_and_case():
    assert D._company_token("Neko Health starting at $405K/year") == "neko"
    assert D._company_token("Neko Health") == "neko"
    assert D._company_token("neko") == "neko"
    assert D._company_token("Spotify AB") == "spotify"


def test_company_token_keeps_different_employers_apart():
    assert D._company_token("King") != D._company_token("Kingfisher")
    assert D._company_token("") == ""


def test_alias_matches_register_role():
    reg = {("data science pod lead", D._company_token("Neko Health"))}
    alias = ("Data Science Pod Lead", "neko")
    assert (alias[0].lower(), D._company_token(alias[1])) in reg


def test_ats_key_resolves_short_employer_and_source_prefix(tmp_path, monkeypatch):
    ats = tmp_path / "ats"
    ats.mkdir()
    (ats / "li_seb_engineering_manager_tech_its_distribution_investments_seb_.txt").write_text("banking\n")
    (ats / "seb_team_mgr_cib_credit_ai.txt").write_text("credit\n")
    monkeypatch.setattr(D, "STATE", str(tmp_path))
    key = "seb-engineering-manager-tech-its-distribution-investments-seb-solna"
    got = D._ats_key_for(
        "SEB",
        "Engineering Manager – Tech ITS Distribution & Investments | SEB, Solna",
        key,
    )
    assert got == "li_seb_engineering_manager_tech_its_distribution_investments_seb_"


def test_ats_key_ignores_company_suffix(tmp_path, monkeypatch):
    ats = tmp_path / "ats"
    ats.mkdir()
    (ats / "publicis_senior_ai_and_data_engineer.txt").write_text("llm\n")
    monkeypatch.setattr(D, "STATE", str(tmp_path))
    key = "publicis-groupe-senior-ai-and-data-engineer"
    assert D._ats_key_for("Publicis Groupe", "Senior AI and Data Engineer", key) == \
        "publicis_senior_ai_and_data_engineer"


def test_ats_key_uses_company_level_ad_when_role_is_in_the_ad(tmp_path, monkeypatch):
    (tmp_path / "ats").mkdir()
    (tmp_path / "job-descriptions").mkdir()
    (tmp_path / "ats" / "solita.txt").write_text("llm\n")
    (tmp_path / "job-descriptions" / "solita.md").write_text("# AI Lead Developer - Solita\n")
    monkeypatch.setattr(D, "STATE", str(tmp_path))
    assert D._ats_key_for("Solita", "AI Lead Developer", "solita-ai-lead-developer") == "solita"
