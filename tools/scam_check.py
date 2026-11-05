#!/usr/bin/env python3
"""Recruitment-scam signals for job adverts and recruiter mail.

A small, explainable rule set. It never decides for you: it names the signal, the
level and what to do, and the document pipeline refuses to prepare a role that
trips a HIGH signal unless you override it.

The hard rule, always shown with a warning:

    Never download or install software, join a chat-only interview, share a
    wallet/seed phrase/private key, pay a fee, or move money during a recruitment
    process. Legitimate employers interview over their own video link and never
    need remote-access tools.

Usage:
  python3 tools/scam_check.py --text "..."
  python3 tools/scam_check.py --jd state/job-descriptions/<key>.md [--company X]
  python3 tools/scam_check.py --email <file> [--sender "Name <a@b.com>"]
  python3 tools/scam_check.py --jd ... --json
Exit: 0 clear/low, 1 medium, 2 high (so it can be used as a gate).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCAM_DIR = ROOT / "state" / "scam"

HARD_RULE = (
    "Never download or install software, join a chat-only interview, share a "
    "wallet, seed phrase or private key, pay a fee, or move money during a "
    "recruitment process. A real employer interviews over its own video link and "
    "never needs remote-access tools."
)

# Specific phrases, not single words: "crypto" and "download" are ordinary in a
# security or engineering advert, so they only count in a scam context.
_REMOTE = (r"(?:anydesk|teamviewer|ultraviewer|rustdesk|quick\s*assist|"
           r"remote\s+(?:access|desktop)|screen[- ]?shar(?:e|ing)\s+(?:app|tool|software))")

SIGNALS = [
    {
        "key": "remote-access-software",
        "level": "high",
        "re": rf"(?:download|install|run|open|use)\b.{{0,70}}\b{_REMOTE}\b"
              rf"|\b{_REMOTE}\b.{{0,60}}\b(?:download|install|interview|meeting|call)\b",
        "why": "Remote-access tools are the standard way an 'interview' takes over "
               "your machine, browser session and wallet.",
        "advice": "Never install AnyDesk, TeamViewer, RustDesk or any remote-access "
                  "tool. Decline and report the message.",
    },
    {
        "key": "crypto-wallet",
        "level": "high",
        "re": r"\b(?:seed phrase|recovery phrase|private key|metamask|trust wallet|"
              r"crypto wallet|bitcoin wallet|usdt|binance wallet)\b"
              r"|\b(?:install|download|open)\b.{0,50}\b(?:crypto|wallet|trading)\s+"
              r"(?:app|software|platform)\b",
        "why": "A wallet, seed phrase or trading app is never part of a hiring "
               "process; this is the crypto-stealing pattern.",
        "advice": "Never share a wallet, seed phrase or private key, and never "
                  "install a 'trading' or 'payment' app for an employer.",
    },
    {
        "key": "pay-to-work",
        "level": "high",
        "re": r"\b(?:you (?:must|will|need to) (?:pay|send|transfer)|pay (?:a|the) "
              r"(?:fee|deposit)|payment of (?:a |the )?(?:fee|deposit))\b"
              r"|\b(?:training|certification|background check|equipment|onboarding|"
              r"registration|visa|uniform)\s+(?:fee|cost|deposit)\b"
              r"|\b(?:fee|deposit|payment)\s+(?:for|to (?:start|begin|secure))\s+"
              r"(?:training|certification|equipment|onboarding|a background check)\b"
              r"|\b(?:gift card|wire transfer|western union|moneygram)\b",
        "why": "Legitimate employers do not ask a candidate to pay for training, "
               "equipment, checks or onboarding.",
        "advice": "Do not pay, transfer or buy gift cards. Record the role as "
                  "BLOCKED and escalate.",
    },
    {
        "key": "fake-check",
        "level": "high",
        "re": r"\b(?:we(?:'ll| will)? (?:send|mail) you a (?:check|cheque)|"
              r"cash the (?:check|cheque)|buy (?:your own )?(?:equipment|supplies)"
              r".{0,70}reimburse|reimburse you for (?:equipment|supplies))\b",
        "why": "The overpayment/equipment-cheque scam uses a fake cheque and asks "
               "you to send part of it back.",
        "advice": "Never cash a cheque or forward money for an employer.",
    },
    {
        "key": "chat-only-interview",
        "level": "high",
        "re": r"\b(?:interview|hiring|recruit\w*)\b.{0,90}\b(?:telegram|whatsapp|"
              r"signal|google hangouts|text[- ]only|chat[- ]only)\b"
              r"|\b(?:telegram|whatsapp)\b.{0,70}\b(?:interview|hiring)\b",
        "why": "Chat-only 'interviews' on Telegram/WhatsApp are a common way to "
               "avoid a traceable company video call.",
        "advice": "Ask for a video interview on the company's own platform. Do not "
                  "continue on a chat app.",
    },
    {
        "key": "no-experience-high-pay",
        "level": "high",
        "re": r"\b(?:no experience (?:needed|required)|earn|make)\b.{0,50}"
              r"\b(?:\$|€|£|usd|eur)\s?\d{2,}[,.]?\d*\s*(?:per|/|a)\s*(?:day|week)\b"
              r"|\b(?:data entry|package forwarding|reshipping)\b.{0,50}"
              r"\b(?:pay|earn|\$|€|£)\b",
        "why": "Unrealistic pay for no experience is the hook for a money-mule or "
               "advance-fee scam.",
        "advice": "Treat it as a scam until the employer is verified independently.",
    },
    {
        "key": "bank-or-id-early",
        "level": "medium",
        "re": r"\b(?:send|provide|share|give|submit|upload|enter)\b.{0,40}"
              r"\b(?:your )?(?:bank account|routing number|sort code|iban|ssn|"
              r"social security|national insurance|passport (?:copy|number)|"
              r"driver'?s licen[cs]e (?:copy|number))\b",
        "why": "Identity and bank details belong after a signed offer, not in an "
               "advert or an early message.",
        "advice": "Do not send ID or bank details until you have a signed contract "
                  "with a verified employer.",
    },
    {
        "key": "urgency",
        "level": "low",
        "re": r"\b(?:urgent|immediately|within 24 hours|act now|today only|"
              r"limited (?:slots|positions)|immediate start)\b",
        "why": "Pressure to act before you can verify the employer is a scam tactic.",
        "advice": "Slow down. Verify the company and the recruiter independently "
                  "before replying.",
    },
]

# Free mailboxes are common for small agencies, so this is a warning, not a block.
FREE_MAIL = {
    "gmail.com", "googlemail.com", "outlook.com", "hotmail.com", "live.com",
    "msn.com", "yahoo.com", "yahoo.co.uk", "aol.com", "icloud.com", "me.com",
    "proton.me", "protonmail.com", "gmx.com", "gmx.de", "mail.com", "yandex.com",
}
# Applicant-tracking and job-board domains are expected senders.
ATS_DOMAINS = {
    "teamtailor.com", "teamtailor-mail.com", "ashbyhq.com", "greenhouse.io",
    "lever.co", "myworkday.com", "workday.com", "smartrecruiters.com",
    "jobvite.com", "recruitee.com", "workable.com", "pinpoint.email", "join.com",
    "deel.com", "zerolime.se", "linkedin.com", "indeed.com", "bamboohr.com",
    "personio.com", "personio.de", "hibob.com", "rippling.com",
}

LEVELS = {"clear": 0, "low": 1, "medium": 2, "high": 3}


def _clean(text):
    text = re.sub(r"(?is)<(style|script|head)\b[^>]*>.*?</\1>", " ", str(text or ""))
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", text)).strip()


_WARNING_WORDS = ("fraudulent", "fraud", "beware", "do not pay", "never pay",
                  "we have been made aware", "fake job offer", "fake offers",
                  "phishing", "protect yourself", "scam alert",
                  "scams may involve", "fake job")


def _warning_context(body, start, end):
    """True when the match is inside the advert's own anti-fraud warning.

    A legitimate advert often says "scammers may ask for payment for equipment".
    That sentence is a warning, not a signal, so it must not trip the gate.
    """
    left = max(body.rfind(". ", 0, start), body.rfind("\n", 0, start)) + 1
    right_candidates = [x for x in (body.find(". ", end), body.find("\n", end)) if x != -1]
    right = min(right_candidates) if right_candidates else len(body)
    sentence = body[left:right].lower()
    return any(w in sentence for w in _WARNING_WORDS)


def _email_domain(sender):
    m = re.search(r"@([A-Za-z0-9.-]+\.[A-Za-z]{2,})", str(sender or ""))
    return m.group(1).lower().strip(".") if m else ""


def scan(text, company="", sender=""):
    """Return {level, signals, rule} for a job advert or a message."""
    body = _clean(text)
    low = body.lower()
    found = []
    for sig in SIGNALS:
        for m in re.finditer(sig["re"], body, re.I):
            if _warning_context(body, m.start(), m.end()):
                continue
            found.append({"key": sig["key"], "level": sig["level"],
                          "why": sig["why"], "advice": sig["advice"],
                          "match": m.group(0)[:160]})
            break
    domain = _email_domain(sender)
    local = (re.match(r"[^@\s<]+", str(sender or "").split("<")[-1].strip("<> ")) or [""])[0]
    system = any(x in local.lower() for x in ("mailer-daemon", "no-reply", "noreply",
                                              "do-not-reply", "donotreply", "postmaster"))
    if domain and not system:
        if domain in FREE_MAIL:
            found.append({
                "key": "free-mail-sender", "level": "medium",
                "why": "The message comes from a free mailbox, not a company domain.",
                "advice": "Verify the recruiter through the employer's own website "
                          "before replying or sharing anything.",
                "match": domain,
            })
        elif (company and domain not in ATS_DOMAINS
              and not any(part in domain for part in re.findall(r"[a-z0-9]{4,}", company.lower()))):
            found.append({
                "key": "sender-domain-mismatch", "level": "medium",
                "why": "The sender's domain does not look like the named company.",
                "advice": "Check the company's real domain and the recruiter's name "
                          "on the employer's site.",
                "match": domain,
            })
    level = "clear"
    for f in found:
        if LEVELS[f["level"]] > LEVELS[level]:
            level = f["level"]
    # A single weak phrase is a note, not a warning.
    if level == "clear" and any(f["level"] == "low" for f in found):
        level = "low"
    return {"level": level, "signals": found, "rule": HARD_RULE}


def save(key, result):
    """Persist a scan beside the per-role artifacts (state/scam/<key>.json)."""
    key = re.sub(r"[^A-Za-z0-9._-]", "-", str(key or "")).strip("-.")
    if not key:
        return ""
    SCAM_DIR.mkdir(parents=True, exist_ok=True)
    path = SCAM_DIR / f"{key}.json"
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(result, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    return str(path)


def load(key):
    key = re.sub(r"[^A-Za-z0-9._-]", "-", str(key or "")).strip("-.")
    if not key:
        return None
    path = SCAM_DIR / f"{key}.json"
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def summary(result):
    """One line for a log or a dashboard tooltip."""
    if not result or result.get("level") in (None, "", "clear"):
        return "no scam signals"
    keys = ", ".join(s["key"] for s in result.get("signals", [])[:4])
    return f"{result['level'].upper()} — {keys}"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--text", default="")
    ap.add_argument("--jd", default="")
    ap.add_argument("--email", default="")
    ap.add_argument("--company", default="")
    ap.add_argument("--sender", default="")
    ap.add_argument("--key", default="", help="save the scan to state/scam/<key>.json")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    if args.jd:
        text = Path(args.jd).read_text(encoding="utf-8", errors="ignore")
    elif args.email:
        text = Path(args.email).read_text(encoding="utf-8", errors="ignore")
    else:
        text = args.text
    if not text:
        ap.error("give --text, --jd or --email")
    result = scan(text, args.company, args.sender)
    if args.key:
        save(args.key, result)
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print(f"SCAM: {result['level'].upper()}")
        for s in result["signals"]:
            print(f"  [{s['level'].upper()}] {s['key']}: {s['why']}")
            print(f"      match: {s['match']}")
            print(f"      do: {s['advice']}")
        print(f"\nRULE: {result['rule']}")
    return 0 if LEVELS[result["level"]] == 0 else (2 if result["level"] == "high" else 1)


if __name__ == "__main__":
    sys.exit(main())
