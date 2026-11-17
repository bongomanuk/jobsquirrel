#!/usr/bin/env python3
"""Surface and record EXTERNAL active processes from Gmail (recruiter leads,
contracts) into the canonical register, so the register is the single source of
truth for every live process, pipeline or not.

Scans recent mail from people/agencies (not ATS auto-responders) that look like
direct opportunities, drops anything whose company is already in the register,
and (with --apply) adds the rest as MANUAL leads. A recruiter email is not a job
advert: the message is saved as a lead brief under state/job-descriptions/ and
the row stays MANUAL until a real spec exists.

Usage:
  .venv/bin/python tools/email_opportunities.py                 # dry run (list)
  .venv/bin/python tools/email_opportunities.py --apply
  .venv/bin/python tools/email_opportunities.py --days 45
"""
from __future__ import annotations

import argparse
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gmail_readonly as G
import gmail_reconcile as R
import identity as ID
import register as REG
import scam_check

ATS = re.compile(r"no-?reply|noreply|donotreply|jobs-noreply|job alert|newsletter|"
                 r"linkedin|teamtailor-mail|greenhouse|ashbyhq|lever\.co|myworkday|"
                 r"successfactors|workable|smartrecruiters|jobylon|deel", re.I)
OPP = re.compile(r"contract|freelance|consultant|assignment|right to represent|"
                 r"role|position|opportunity|available for|we are looking for|"
                 r"team delivery|day rate|hourly rate", re.I)
NEG = re.compile(r"unfortunately|not moving forward|unable to offer|decided to "
                 r"move forward with other|we have received your application|"
                 r"thank you for applying|thanks for applying", re.I)
# Words that appear in a sender's display name but identify nobody. They must not
# be used to decide that a lead is "already in the register".
GENERIC = {"recruiter", "recruiting", "recruitment", "talent", "search", "hiring",
           "agency", "executive", "consultant", "consulting", "staffing", "careers",
           "team", "people", "roles", "role", "jobs", "mail", "gmail", "outlook"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--query", default="")
    args = ap.parse_args()

    q = args.query or (f"newer_than:{args.days}d (\"contract role\" OR \"contract position\" OR "
                       "\"Right to Represent\" OR \"we are looking for\" OR assignment OR freelance OR "
                       "consultant OR \"available for\" OR \"role that fits\" OR \"team delivery\")")
    svc = G.authenticate()
    rows = REG.load()
    known = {r["company"].strip().lower() for r in rows}
    # Dedupe on the Gmail message id recorded in a row's notes: the sender's
    # display name is not the company (a lead is filed under the firm), so the
    # name alone let an already-recorded lead come back as a new one.
    known_ids = set()
    for r in rows:
        known_ids.update(re.findall(r"\b1[0-9a-f]{15}\b", r.get("notes", "") or ""))
    me = ID.parse()
    own_email = (me.get("email") or "").lower()
    own_name = (me.get("full name") or "").lower()
    seen, found = set(), []
    for m in R.list_ids(svc, q, max_results=50):
        msg = R.fetch_full(svc, m["id"]); time.sleep(0.06)
        h = {x["name"].lower(): x["value"] for x in msg["payload"].get("headers", [])}
        frm = h.get("from", ""); subj = h.get("subject", ""); date = h.get("date", "")
        if ATS.search(frm):
            continue
        # Never treat the candidate's own mail as an inbound opportunity.
        if own_email and own_email in frm.lower():
            continue
        if own_name and R.sender_display(frm).strip().lower() == own_name:
            continue
        if m["id"] in known_ids:
            continue
        who = R.sender_display(frm)
        if who.lower() in seen:
            continue
        body = G._decode(msg["payload"])
        txt = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", G.html.unescape(body))).strip()
        if not OPP.search(subj + " " + txt[:400]) or NEG.search(subj + " " + txt[:200]):
            continue
        seen.add(who.lower())
        # already tracked? (sender name, or sender email domain, appears in a register company)
        # Generic job-market words are not identities: without this, a sender display
        # name like "David George Recruiter" matched the "James Worden (recruiter)"
        # row and the lead was silently dropped.
        toks = {t for t in re.findall(r"[a-z0-9]+", who.lower())
                if len(t) > 3 and t not in GENERIC}
        em = re.search(r"@([a-z0-9.-]+)", frm.lower())
        if em:
            toks.add(em.group(1).split(".")[0])
        toks -= GENERIC
        if any(any(t in c for t in toks) for c in known):
            continue
        url = ""
        mu = re.search(r"https?://[^\s\"'<>()\]]+", G.html.unescape(body))
        if mu:
            url = mu.group(0)[:140]
        found.append({"company": who, "role": subj[:120] or "(role in email)",
                      "date": date[:31], "url": url, "note": txt[:180],
                      "id": m["id"], "sender": frm, "subject": subj, "body": txt})

    if not found:
        print("no new external opportunities")
        return 0
    print(f"{len(found)} external opportunity/lead(s) not in the register:\n")
    for f in found:
        print(f"[{f['date']}] {f['company']}\n   {f['role']}\n   {f['note']}\n")
    if args.apply:
        os.makedirs(REG.JD_DIR, exist_ok=True)
        for f in found:
            key = REG.make_key(f["company"], f["role"])
            brief = (
                f"# {f['company']}: {f['role']}\n"
                f"Source: Gmail message {f['id']} from {f['sender']}\n"
                f"Received: {f['date']}\n"
                "Spec status: lead brief, no job advert supplied\n"
                "---\n"
                f"{f['body']}\n"
            )
            with open(os.path.join(REG.JD_DIR, f"{key}.md"), "w", encoding="utf-8") as fh:
                fh.write(brief)
            scan = scam_check.scan(brief, f["company"], f["sender"], subject=f["subject"])
            scam_check.save(key, scan)
            REG.upsert(f["company"], f["role"], "MANUAL",
                       day=time.strftime("%Y-%m-%d"), ats="Agency",
                       notes=(f"external (Gmail) lead {f['id']}: {f['subject']}: "
                              f"no advert supplied; lead brief saved to "
                              f"state/job-descriptions/{key}.md; reply to request the "
                              f"full spec before preparing documents. "
                              + (f"SCAM {scan['level'].upper()}: " + scam_check.summary(scan) + " "
                                 if scan["level"] != "clear" else "")
                              + f"{f['note']}"))
        print(f"recorded {len(found)} external lead(s) as MANUAL (no spec yet)")
    else:
        print("(dry run: re-run with --apply to record these)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
