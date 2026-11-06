#!/usr/bin/env python3
"""Language-agnostic email triage for the reconciliation review queue.

This is a *review booster*, not a classifier that changes status. It looks at
metadata and structure that work across languages:

  - known applicant-tracking-system sender domains,
  - a register company token in the sender domain or display name,
  - an application/requisition id,
  - a meeting link plus a date/time,
  - LinkedIn job alerts,
  - system senders and known bulk/marketing domains.

`gmail_reconcile.py` uses it to surface job-related mail the regex classifier
put in OTHER. A human decides what happens next. It never edits the register and
never touches Gmail.
"""
from __future__ import annotations

import json
import os
import re

ATS_DOMAINS = {
    "teamtailor.com", "teamtailor-mail.com", "greenhouse.io", "greenhouse-mail.io",
    "lever.co", "hire.lever.co", "myworkday.com", "workday.com", "smartrecruiters.com",
    "jobvite.com", "recruitee.com", "workable.com", "pinpoint.email", "join.com",
    "jobylon.com", "msg.jobylon.com", "deel.com", "zerolime.se", "bamboohr.com",
    "personio.com", "personio.de", "hibob.com", "rippling.com", "avature.net",
    "icims.com", "taleo.net", "breezy.hr", "comeet.com", "successfactors.eu",
    "trustcruit.com", "reachmee.com",
}

# Bulk senders that should never become review noise. These are domains, not
# language patterns, so they stay useful across locales.
HARD_MARKETING = {
    "aliexpress.com", "hsbc.com", "hsbc.com.sg", "coinhako.com", "23andme.com",
    "resend.com", "spotify.com", "facebook.com", "instagram.com", "youtube.com",
    "twitter.com", "x.com", "substack.com", "medium.com", "eventbrite.com",
}


# Companies that also send real recruiter mail. A system local part is not job;
# a named person at the domain can still be.
SOFT_MARKETING = {"github.com", "email.github.com", "google.com"}

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOCAL_CONFIG = os.path.join(ROOT, "config", "email-triage.json")


def _load_local():
    try:
        with open(LOCAL_CONFIG, encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


_LOCAL = _load_local()
ATS_DOMAINS |= {str(x).lower() for x in _LOCAL.get("ats_domains", [])}
HARD_MARKETING |= {str(x).lower() for x in _LOCAL.get("hard_marketing", [])}
SOFT_MARKETING |= {str(x).lower() for x in _LOCAL.get("soft_marketing", [])}

SYSTEM_LOCAL = re.compile(
    r"^(?:notifications?|no-?reply|do-?not-?reply|mailer-daemon|postmaster|"
    r"updates?|news|hello|info|marketing|events?|digest|billing|cloudplatform)", re.I)
MEETING = re.compile(
    r"(?:meet\.google\.com|teams\.microsoft\.com|zoom\.us|whereby\.com|"
    r"meet\.jit\.si|chime\.aws)", re.I)
APP_ID = re.compile(
    r"\b(?:JREQ\d+|req(?:uisition)?\s*#?\s*\d{3,}|"
    r"application\s*(?:id|number|ref)\s*[:#]?\s*[A-Z0-9-]{4,})", re.I)
DATE_TIME = re.compile(
    r"\b(?:20\d{2}-\d{2}-\d{2}|\d{1,2}:\d{2}\b|"
    r"\d{1,2}\s+(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+20\d{2})",
    re.I)
VERIFY_SUBJECT = re.compile(r"verif|confirm your|security code|activate", re.I)

_STOP = {"the", "and", "group", "ltd", "ab", "inc", "sweden", "solutions",
         "consulting", "technology", "technologies", "global"}


def plain(text):
    text = re.sub(r"(?is)<(style|script|head)\b[^>]*>.*?</\1>", " ", str(text or ""))
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"&nbsp;?", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def domain(sender):
    m = re.search(r"@([A-Za-z0-9.-]+\.[A-Za-z]{2,})", str(sender or ""))
    return m.group(1).lower().strip(".") if m else ""


def is_ats(host):
    d = str(host or "").lower().strip(".")
    return any(d == a or d.endswith("." + a) for a in ATS_DOMAINS)


def company_tokens(rows):
    out = []
    for r in rows or []:
        for t in re.findall(r"[a-z0-9]{3,}", str(r.get("company") or "").lower()):
            if t not in _STOP and t not in out:
                out.append(t)
    return out


class Triage:
    """Score one message on language-agnostic metadata and structure."""

    def __init__(self, rows=None):
        self.tokens = company_tokens(rows)

    def classify(self, subject, body, sender):
        subject = str(subject or "")
        body = plain(body)
        sender = str(sender or "")
        host = domain(sender)
        name = sender.split("<")[0].lower()
        local = sender.split("<")[-1].strip("<> ").split("@")[0]
        ats = is_ats(host)
        app_id = bool(APP_ID.search(subject) or APP_ID.search(body))
        meeting = bool(MEETING.search(body)) and bool(DATE_TIME.search(body))
        hard = host in HARD_MARKETING or any(host.endswith("." + d) for d in HARD_MARKETING)
        soft = host in SOFT_MARKETING or any(host.endswith("." + d) for d in SOFT_MARKETING)
        system = bool(SYSTEM_LOCAL.match(local))
        token_domain = any(t in host for t in self.tokens)
        # "Name - Company" is a strong recruiter signal; the company name alone
        # is not. A system local part at the company domain is usually a
        # notification, not a recruiter.
        name_company = any(
            re.search(r"[-\u2013\u2014]\s*[^<>]*\b" + re.escape(t) + r"\b", name)
            for t in self.tokens)
        token_hit = (token_domain and not system) or name_company
        linkedin_alert = ("jobalerts-noreply@linkedin.com" in sender.lower()
                          or "linkedin job alerts" in name)

        job, category, why = False, "OTHER", []
        if ats:
            job, category = True, "CONFIRMATION"; why.append("ats")
        if token_hit:
            job = True; why.append("company")
        if app_id:
            job, category = True, "CONFIRMATION"; why.append("app-id")
        if meeting:
            job, category = True, "INTERVIEW"; why.append("meeting")
        if linkedin_alert:
            job, category = True, "OTHER"; why.append("linkedin-alert")
        if (ats or token_hit) and VERIFY_SUBJECT.search(subject):
            category = "VERIFICATION"; why.append("verification")
        if hard and not (ats or app_id or meeting):
            job, category, why = False, "OTHER", ["hard-marketing"]
        if soft and system:
            job, category, why = False, "OTHER", ["system-sender"]

        confidence = "high" if (ats or app_id or meeting) else ("medium" if token_hit else "low")
        return {"job": job, "category": category, "reasons": why,
                "confidence": confidence, "domain": host}


def triage(subject, body, sender, rows=None):
    return Triage(rows).classify(subject, body, sender)
