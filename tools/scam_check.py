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
    "avature.net", "icims.com", "taleo.net", "breezy.hr", "comeet.com",
    "greenhouse-mail.io", "msg.jobylon.com", "hire.lever.co", "successfactors.eu",
}

LEVELS = {"clear": 0, "low": 1, "medium": 2, "high": 3}

_DANGEROUS_EXT = (".exe", ".scr", ".msi", ".dmg", ".pkg", ".bat", ".cmd", ".ps1",
                  ".vbs", ".js", ".jse", ".wsf", ".hta", ".lnk", ".iso", ".img",
                  ".jar", ".apk", ".app", ".run", ".bin")
_ARCHIVE_EXT = (".zip", ".rar", ".7z", ".tar", ".gz", ".tgz")
_SHORTENERS = {"bit.ly", "tinyurl.com", "t.co", "goo.gl", "ow.ly", "is.gd",
               "buff.ly", "rebrand.ly", "cutt.ly", "shorturl.at", "rb.gy",
               "tiny.cc", "lnkd.in", "trib.al"}
_FILE_HOSTS = {"mega.nz", "drive.google.com", "dropbox.com", "we.tl",
               "transfer.sh", "file.io", "gofile.io", "sendspace.com"}
_URL_RE = re.compile(r"https?://[^\s\"'<>()]+", re.I)


def links_in(text):
    """Every URL in a body, so the caller can pass them to scan()."""
    return _URL_RE.findall(str(text or ""))


def _host(url):
    m = re.match(r"https?://([^/:\s?#]+)", str(url or ""), re.I)
    return m.group(1).lower().strip(".") if m else ""


def _ip_host(host):
    return bool(re.fullmatch(r"\d{1,3}(?:\.\d{1,3}){3}", host or ""))


def _dangerous_file(path):
    p = str(path or "").lower().split("?", 1)[0].split("#", 1)[0]
    return p.endswith(_DANGEROUS_EXT)


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


def _is_ats(domain):
    d = str(domain or "").lower().strip(".")
    return any(d == a or d.endswith("." + a) for a in ATS_DOMAINS)


def _email_domain(sender):
    m = re.search(r"@([A-Za-z0-9.-]+\.[A-Za-z]{2,})", str(sender or ""))
    return m.group(1).lower().strip(".") if m else ""


def _system_sender(sender):
    local = (re.match(r"[^@\s<]+", str(sender or "").split("<")[-1].strip("<> ")) or [""])[0]
    return any(x in local.lower() for x in ("mailer-daemon", "no-reply", "noreply",
                                             "do-not-reply", "donotreply", "postmaster"))


def scan(text, company="", sender="", reply_to="", subject="", links=None,
         attachments=None, company_domain=""):
    """Return {level, signals, rule} for an advert or a message.

    Sender checks compare the From domain with the named company and with the
    Reply-To; link and attachment checks catch installers, shorteners, IP hosts
    and wallet-drainer URLs that the body text alone would miss.
    """
    body = _clean(text)
    found, seen = [], set()

    def add(key, level, why, advice, match):
        if key in seen:
            return
        seen.add(key)
        found.append({"key": key, "level": level, "why": why,
                      "advice": advice, "match": str(match)[:160]})

    for sig in SIGNALS:
        for m in re.finditer(sig["re"], body, re.I):
            if _warning_context(body, m.start(), m.end()):
                continue
            add(sig["key"], sig["level"], sig["why"], sig["advice"], m.group(0))
            break

    domain = _email_domain(sender)
    system = _system_sender(sender)
    expected = (company_domain or "").lower().strip().strip(".")
    if expected.startswith("www."):
        expected = expected[4:]
    if domain and not system:
        if domain in FREE_MAIL:
            add("free-mail-sender", "medium",
                "The message comes from a free mailbox, not a company domain.",
                "Verify the recruiter through the employer's own website before "
                "replying or sharing anything.", domain)
        elif expected and domain != expected and not domain.endswith("." + expected):
            if not _is_ats(domain):
                root = expected.split(".")[0]
                lookalike = bool(root and len(root) >= 4 and root in domain)
                # A lookalike is suspicious; a completely different domain is
                # usually an agency or a job board, so it is only a note.
                add("lookalike-domain" if lookalike else "sender-domain-mismatch",
                    "medium" if lookalike else "low",
                    ("The sender's domain looks like the company's but is not it."
                     if lookalike else
                     "The sender's domain is not the company's apply domain."),
                    "Check the company's real domain and the recruiter's name on the "
                    "employer's site.", f"{domain} (expected {expected})")
    if reply_to and domain:
        rd = _email_domain(reply_to)
        if rd and rd != domain and (rd in FREE_MAIL or _ip_host(rd) or rd.startswith("xn--")):
            add("reply-to-mismatch", "medium",
                "Replies go to a different, unverified address than the sender.",
                "Reply only to the address you can verify on the employer's site.",
                f"{domain} -> {rd}")

    for u in list(links or []) + links_in(text):
        host, path = _host(u), str(u).lower()
        if _dangerous_file(path) or re.search(r"(anydesk|teamviewer|rustdesk|ultraviewer)", path):
            add("software-download-link", "high",
                "The message links to an installer or a remote-access tool.",
                "Never download or install it. Delete the message and report it.",
                u)
        if _ip_host(host):
            add("ip-address-link", "high",
                "A raw IP address instead of a company domain is a common phishing host.",
                "Do not open the link; verify the sender through the company site.", u)
        if host in _SHORTENERS:
            add("shortened-link", "low",
                "A shortened link hides its real destination.",
                "Expand or ignore it; never enter credentials after a shortened link.", u)
        if host.startswith("xn--"):
            add("punycode-link", "medium",
                "A punycode host can imitate a real company domain.",
                "Check the real domain spelling before opening anything.", u)
        if (not re.search(r"\.(?:png|jpe?g|gif|svg|webp|css|js)(?:\?|$)", path)
                and re.search(r"(connect|claim|airdrop|mint|seed|validate|sync|restore)", path)
                and re.search(r"(wallet|crypto|web3|nft)", path)):
            add("wallet-link", "high",
                "The link is about connecting or claiming a wallet.",
                "Never connect a wallet or share a seed phrase for a job.", u)
        if host in _FILE_HOSTS and re.search(r"\.(exe|scr|msi|dmg|pkg|zip|rar|7z|iso|lnk)(?:\?|$)", path):
            add("file-host-download", "high",
                "A file host is being used to deliver an installer or archive.",
                "Do not download it; legitimate employers do not send installers.", u)

    for a in (attachments or []):
        al = str(a).lower()
        if _dangerous_file(al) or re.search(r"(anydesk|teamviewer|rustdesk|ultraviewer)", al):
            add("dangerous-attachment", "high",
                "The message carries an executable, installer or remote-access tool.",
                "Do not open it. Delete the message and report it.", a)
        elif al.endswith(_ARCHIVE_EXT):
            add("archive-attachment", "medium",
                "A password-protected or compressed archive can hide an installer.",
                "Do not open it unless you can verify the sender and the contents.", a)

    level = "clear"
    for f in found:
        if LEVELS[f["level"]] > LEVELS[level]:
            level = f["level"]
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
