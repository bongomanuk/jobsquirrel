"""Employment-contract terms must be blocked or redacted from the graph."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))
import sensitive as S  # noqa: E402


def test_contract_and_legal_titles_are_blocked():
    for title in ("COURT", "COURT ORDER", "ENGLISH COURTS",
                  "LAWS OF ENGLAND AND WALES", "CLAUSE 2.3",
                  "PERSONAL SERVICE COMPANY (PSC)", "AGENCY WORKER",
                  "EMPLOYER", "NOTICE PERIOD"):
        assert S.blocked_title(title), title


def test_ordinary_skill_is_not_blocked():
    assert not S.blocked_title("SOFTWARE ENGINEERING")
    assert not S.blocked_title("KAFKA")
    assert not S.blocked_title("IDENTITY AND ACCESS MANAGEMENT")


def test_legal_sentences_are_redacted():
    text = ("The English Courts have sole jurisdiction over these Terms.\n"
            "Built and ran the identity platform.")
    cleaned = S.redact(text)
    assert "Built and ran the identity platform." in cleaned
    assert "English Courts" not in cleaned
    assert "jurisdiction" not in cleaned


def test_employment_dispute_is_sensitive():
    assert S.sensitive("A legal dispute about the employment contract")
    assert S.sensitive("The court may require disclosure")
    assert not S.sensitive("Led the platform engineering team")


def test_personal_identifiers_are_sensitive_and_redacted():
    assert S.sensitive("Email me at someone@example.com")
    assert S.sensitive("Swedish ID No. 19781023-1352")
    text = ("Built the platform. "
            "Haud Systems AB employment documentation identifies him by Swedish ID No. "
            "19781023-1352 and email someone@example.com. "
            "He is resident in Huddinge, Sweden. "
            "Led the team.")
    cleaned = S.redact(text)
    assert "Built the platform." in cleaned
    assert "Led the team." in cleaned
    assert "19781023-1352" not in cleaned
    assert "someone@example.com" not in cleaned
    assert "Huddinge" not in cleaned


def test_identity_document_and_private_terms_are_sensitive():
    assert S.sensitive("Swedish identity card and residence on record")
    assert S.sensitive("Full UK amateur radio licence; Swedish identity card")
