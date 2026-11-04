#!/usr/bin/env python3
"""Sensitive employment-contract terms that must not shape the job-search graph.

The knowledge graph should contain evidence of work, skills and outcomes, not
the legal machinery of an employment contract (garden leave, pay in lieu of
notice, probation, grievances, exact salary/bonus, etc.). These terms are
personal and can read negatively in a job-search context.

Two lists:
  TITLE_TERMS   - an entity whose title matches is removed
  REDACT_TERMS  - sentences containing these are removed from surviving text
"""
from __future__ import annotations

import os
import re

# Drop the entity if its title contains one of these phrases.
TITLE_TERMS = [
    "garden leave", "pay in lieu of notice", "lieu of notice", "notice period",
    "probation", "probationary", "disciplinary", "grievance",
    "restrictive covenant", "restrictive covenants", "non-compete",
    "non-solicitation", "non-solicit", "severance", "redundancy",
    "termination", "employment agreement", "employment contract",
    "employee handbook", "pension scheme", "pension", "salary", "bonus",
    "annual leave", "holiday entitlement", "sick leave", "medical certificate",
    "payroll", "deductions", "key information document", "assignment confirmation",
    "uppsägningstid", "uppsagningstid", "opt out", "opt-out", "rehire period",
    "privacy notice", "alternative agreement", "these terms", "wfs terms",
    "contract for services", "employment business", "employment agency",
    "working hours", "sickness compensation", "tax authority", "hr department",
    "specified services", "work finding services", "recruitment services",
    # legal / terms-and-conditions machinery
    "court", "court order", "english courts", "tribunal", "jurisdiction",
    "severability", "laws of england", "laws of england and wales",
    "governing law", "legal costs", "legal fees", "legal agent",
    "legal dispute", "employment dispute", "clause", "work-finding",
    "agency worker", "personal service company", "psc contractor",
    # personal identifiers and contract provenance
    "swedish id", "personal identity number", "personnummer", "date of birth",
    "employment documentation", "indefinite period", "contract terms",
    "company policies", "resident in", "home address", "personal email",
    "swedish identity", "identity card", "residence on record",
]

# Extra exact/generic titles produced by contract documents.
GENERIC_TITLES = {
    "COMPANY", "EMPLOYEE", "AGENT", "SUPPLIER", "CUSTOMER", "LINE MANAGER",
    "DIRECT MANAGER", "ASSIGNMENT", "TERMS", "EMPLOYMENT AGREEMENT",
    "EMPLOYMENT CONTRACT", "EMPLOYEE HANDBOOK", "KEY INFORMATION DOCUMENT",
    "NOTICE PERIOD", "PAY IN LIEU OF NOTICE", "GARDEN LEAVE",
    "SERVICES", "SPECIFIED SERVICES", "WORK FINDING SERVICES", "RECRUITMENT SERVICES",
    "ALTERNATIVE AGREEMENT", "THESE TERMS", "WFS TERMS", "AGREEMENT",
    "CONTRACT FOR SERVICES", "PRIVACY NOTICE", "NOTICE OF OPT OUT", "REHIRE PERIOD",
    "EMPLOYMENT BUSINESS", "HR DEPARTMENT", "CLIENT", "TAX AUTHORITY",
    "EXTERNAL CONTRACTOR", "REGISTERED CONTRACTOR",
    "NORMAL WEEKLY WORKING HOURS OF 40 HOURS",
    "SICKNESS COMPENSATION FROM FIFTEENTH DAY",
    "UPDATED VERSION OF THESE TERMS",
    "CONDUCT OF EMPLOYMENT AGENCIES AND EMPLOYMENT BUSINESSES REGULATIONS 2003",
    "EMPLOYMENT AGENCY STANDARDS (EAS) INSPECTORATE",
    "ADDRESSEE", "WORKER", "HIRER", "END USER",
    "COURT", "COURT ORDER", "ENGLISH COURTS", "LAWS OF ENGLAND AND WALES",
    "WORK SERVICES", "CLAUSE 2.3", "LEGAL AGENT", "AUTHORISED OFFICER",
    "AUTHORISED PERSON", "REGULATORY BODY", "AGENCY WORKER", "CANDIDATE",
    "PSC CONTRACTOR", "PERSONAL SERVICE COMPANY", "PERSONAL SERVICE COMPANY (PSC)",
    "HYPOTHETICAL ASSIGNMENT", "EMPLOYER", "EMPLOYEE", "REPRESENTATIVE",
    "THIRD PARTY", "RELATIVE", "REFEREE", "DIRECTORS", "OFFICERS", "AGENTS",
    "OMBUD", "KÄRANDE", "SVARANDE", "VD", "MONTHLY", "PAY", "FEES",
}

# Remove sentences/lines that carry these terms from surviving descriptions
# and reports. Kept narrower than TITLE_TERMS so ordinary words such as
# "company" are not redacted.
REDACT_TERMS = [
    "garden leave", "pay in lieu of notice", "lieu of notice", "notice period",
    "probation", "probationary", "disciplinary", "grievance",
    "restrictive covenant", "restrictive covenants", "non-compete",
    "non-solicitation", "non-solicit", "severance", "redundancy",
    "termination", "employment agreement", "employment contract",
    "employee handbook", "pension scheme", "pension", "salary", "bonus",
    "annual leave", "holiday entitlement", "sick leave", "medical certificate",
    "payroll", "deductions", "key information document", "assignment confirmation",
    "uppsägningstid", "uppsagningstid", "opt out", "opt-out", "rehire period",
    "privacy notice", "employment agency", "working hours", "sickness compensation",
    "tax authority",
    # legal / terms-and-conditions machinery
    "court", "court order", "english courts", "tribunal", "jurisdiction",
    "severability", "laws of england", "laws of england and wales",
    "governing law", "legal costs", "legal fees", "legal agent",
    "legal dispute", "employment dispute", "clause", "work-finding",
    "agency worker", "personal service company", "psc contractor",
    # personal identifiers and contract provenance
    "swedish id", "personal identity number", "personnummer", "date of birth",
    "employment documentation", "indefinite period", "contract terms",
    "company policies", "resident in", "home address", "personal email",
    "swedish identity", "identity card", "residence on record",
]

def _private_redactions():
    """Private terms (a locality, a former surname) kept out of public code."""
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "kb", "graphrag", "private-redactions.txt")
    try:
        with open(path, encoding="utf-8") as fh:
            return [ln.strip() for ln in fh
                    if ln.strip() and not ln.lstrip().startswith("#")]
    except OSError:
        return []


REDACT_TERMS = REDACT_TERMS + [t for t in _private_redactions() if t not in REDACT_TERMS]

_TITLE_RE = re.compile("|".join(r"\b" + re.escape(t) + r"\b" for t in TITLE_TERMS), re.I)
_REDACT_RE = re.compile("|".join(r"\b" + re.escape(t) + r"\b" for t in REDACT_TERMS), re.I)
_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_ID_RE = re.compile(r"\b(?:19|20)\d{6}[-+]\d{4}\b|\b\d{6}[-+]\d{4}\b")


def blocked_title(title: str) -> bool:
    t = str(title or "").strip()
    if t.upper() in GENERIC_TITLES:
        return True
    return bool(_TITLE_RE.search(t))


def pii(text: str) -> bool:
    """Email addresses and Swedish personal identity numbers."""
    value = str(text or "")
    return bool(_EMAIL_RE.search(value) or _ID_RE.search(value))


def sensitive(text: str) -> bool:
    return bool(_REDACT_RE.search(str(text or ""))) or pii(text)


def redact(text: str) -> str:
    """Remove lines and sentences that contain a sensitive term."""
    out = []
    for line in str(text or "").splitlines():
        if not line.strip():
            out.append(line)
            continue
        if _REDACT_RE.search(line) or pii(line):
            keep = [s for s in re.split(r"(?<=[.!?])\s+", line)
                    if not _REDACT_RE.search(s) and not pii(s)]
            if keep:
                out.append(" ".join(keep).strip())
            continue
        out.append(line)
    return "\n".join(out).strip()
