"""Recruitment-scam signals: the patterns must fire on scams and stay quiet on ads."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))
import scam_check as S  # noqa: E402


def _keys(text, **kw):
    return {s["key"] for s in S.scan(text, **kw)["signals"]}


def test_a_normal_advert_is_clear():
    text = ("We are hiring a Senior Backend Engineer to build Python services on AWS. "
            "You will meet the team on Google Meet. Salary 90000 EUR/year.")
    assert S.scan(text)["level"] == "clear"


def test_remote_access_tool_is_high():
    r = S.scan("Download AnyDesk and install it before your interview so we can guide you.")
    assert r["level"] == "high"
    assert "remote-access-software" in {s["key"] for s in r["signals"]}


def test_wallet_and_seed_phrase_is_high():
    r = S.scan("Install Trust Wallet and share your seed phrase with the hiring manager.")
    assert r["level"] == "high"
    assert "crypto-wallet" in {s["key"] for s in r["signals"]}


def test_pay_for_training_is_high():
    r = S.scan("There is a one-time training fee of 250 EUR, refundable after onboarding.")
    assert r["level"] == "high"
    assert "pay-to-work" in {s["key"] for s in r["signals"]}


def test_chat_only_interview_is_high():
    r = S.scan("The interview will be on Telegram. Message our hiring manager there.")
    assert r["level"] == "high"
    assert "chat-only-interview" in {s["key"] for s in r["signals"]}


def test_equipment_cheque_is_high():
    r = S.scan("We will send you a check to buy your own equipment, then you reimburse the balance.")
    assert r["level"] == "high"
    assert "fake-check" in {s["key"] for s in r["signals"]}


def test_urgency_is_a_low_note_not_a_block():
    r = S.scan("Urgent: immediate start, limited positions, reply within 24 hours.")
    assert r["level"] == "low"
    assert "urgency" in {s["key"] for s in r["signals"]}


def test_a_free_mailbox_sender_is_flagged():
    r = S.scan("Hello, I am the recruiter from Acme Ltd.",
               company="Acme Ltd", sender="Recruiter <recruiter@gmail.com>")
    assert "free-mail-sender" in {s["key"] for s in r["signals"]}


def test_an_ats_sender_is_not_flagged():
    r = S.scan("Your application was received.", company="Acme Ltd",
               sender="Acme <no-reply@acme.teamtailor-mail.com>")
    assert "free-mail-sender" not in {s["key"] for s in r["signals"]}
    assert "sender-domain-mismatch" not in {s["key"] for s in r["signals"]}


def test_crypto_in_a_security_advert_does_not_fire():
    # "crypto" alone is ordinary in a security role; only the wallet pattern counts.
    assert "crypto-wallet" not in _keys("Experience with cryptography and TLS is required.")


def test_save_and_load_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(S, "SCAM_DIR", tmp_path)
    r = S.scan("Download TeamViewer before the call.")
    S.save("acme-engineer", r)
    assert S.load("acme-engineer")["level"] == "high"
    assert S.summary(S.load("acme-engineer")).startswith("HIGH")


def test_reply_to_mismatch_is_flagged():
    r = S.scan("Hello", sender="HR <hr@acme.com>", reply_to="HR <hr@gmail.com>")
    assert "reply-to-mismatch" in {s["key"] for s in r["signals"]}


def test_dangerous_attachment_is_high():
    r = S.scan("Please install this before the call.", attachments=["AnyDesk.exe"])
    assert r["level"] == "high"
    assert "dangerous-attachment" in {s["key"] for s in r["signals"]}


def test_archive_attachment_is_medium():
    r = S.scan("See attached.", attachments=["documents.zip"])
    assert r["level"] == "medium"
    assert "archive-attachment" in {s["key"] for s in r["signals"]}


def test_installer_link_is_high():
    r = S.scan("Setup: https://example.com/teamviewer-setup.exe")
    assert r["level"] == "high"
    assert "software-download-link" in {s["key"] for s in r["signals"]}


def test_shortened_and_ip_links():
    assert "shortened-link" in _keys("Open https://bit.ly/abc")
    r = S.scan("Open http://192.0.2.10/login")
    assert "ip-address-link" in {s["key"] for s in r["signals"]}


def test_punycode_and_wallet_links():
    assert "punycode-link" in _keys("Open https://xn--acme-9ja.com/login")
    r = S.scan("Open https://acme.example/connect-wallet")
    assert "wallet-link" in {s["key"] for s in r["signals"]}


def test_a_lookalike_domain_is_flagged_against_the_apply_domain():
    r = S.scan("Hello", sender="Acme HR <hr@acme-careers.com>",
               company="Acme", company_domain="acme.com")
    assert "lookalike-domain" in {s["key"] for s in r["signals"]}


def test_the_real_company_domain_is_not_flagged():
    r = S.scan("Hello", sender="Acme HR <hr@acme.com>",
               company="Acme", company_domain="acme.com")
    assert "sender-domain-mismatch" not in {s["key"] for s in r["signals"]}
    assert "lookalike-domain" not in {s["key"] for s in r["signals"]}


def test_a_careers_subdomain_of_the_company_is_not_flagged():
    r = S.scan("Hello", sender="Acme HR <hr@careers.acme.com>",
               company="Acme", company_domain="careers.acme.com")
    assert "sender-domain-mismatch" not in {s["key"] for s in r["signals"]}
