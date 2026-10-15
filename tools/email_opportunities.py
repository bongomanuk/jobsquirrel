#!/usr/bin/env python3
"""Surface and record EXTERNAL active processes from Gmail (recruiter leads,
contracts) into the canonical register — so the register is the single source of
truth for every live process, pipeline or not.

Scans recent mail from people/agencies (not ATS auto-responders) that look like
direct opportunities, drops anything whose company is already in the register,
and (with --apply) adds the rest as PREPARED rows.

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
import register as REG

ATS = re.compile(r"no-?reply|noreply|donotreply|jobs-noreply|job alert|newsletter|"
                 r"linkedin|teamtailor-mail|greenhouse|ashbyhq|lever\.co|myworkday|"
                 r"successfactors|workable|smartrecruiters|jobylon|deel", re.I)
OPP = re.compile(r"contract|freelance|consultant|assignment|right to represent|"
                 r"role|position|opportunity|available for|we are looking for|"
                 r"team delivery|day rate|hourly rate", re.I)
NEG = re.compile(r"unfortunately|not moving forward|unable to offer|decided to "
                 r"move forward with other|we have received your application|"
                 r"thank you for applying|thanks for applying", re.I)


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
    seen, found = set(), []
    for m in R.list_ids(svc, q, max_results=50):
        msg = R.fetch_full(svc, m["id"]); time.sleep(0.06)
        h = {x["name"].lower(): x["value"] for x in msg["payload"].get("headers", [])}
        frm = h.get("from", ""); subj = h.get("subject", ""); date = h.get("date", "")
        if ATS.search(frm):
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
        toks = {t for t in re.findall(r"[a-z0-9]+", who.lower()) if len(t) > 3}
        em = re.search(r"@([a-z0-9.-]+)", frm.lower())
        if em:
            toks.add(em.group(1).split(".")[0])
        if any(any(t in c for t in toks) for c in known):
            continue
        url = ""
        mu = re.search(r"https?://[^\s\"'<>()\]]+", G.html.unescape(body))
        if mu:
            url = mu.group(0)[:140]
        found.append({"company": who, "role": subj[:120] or "(role in email)",
                      "date": date[:31], "url": url, "note": txt[:180]})

    if not found:
        print("no new external opportunities")
        return 0
    print(f"{len(found)} external opportunity/lead(s) not in the register:\n")
    for f in found:
        print(f"[{f['date']}] {f['company']}\n   {f['role']}\n   {f['note']}\n")
    if args.apply:
        for f in found:
            REG.upsert(f["company"], f["role"], "PREPARED",
                       day=time.strftime("%Y-%m-%d"), ats="Agency",
                       notes=f"external (Gmail): {f['note']}")
        print(f"recorded {len(found)} row(s) as PREPARED")
    else:
        print("(dry run — re-run with --apply to record these)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
