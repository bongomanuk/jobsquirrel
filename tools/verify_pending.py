#!/usr/bin/env python3
"""Audit ATS email verifications against the application register.

Many ATS (Teamtailor, join.com, Workday, ...) send a "Complete the application"
/ "verify your email" / "Activate your account" message that must be actioned
before an application actually counts. This tool lists recent verification
emails and flags any whose company the register already marks SUBMITTED - i.e.
an application that may have been recorded before the emailed step was done.

Read-only Gmail. `--open` completes a verify/activation link in the pipeline
Camoufox browser (opening the link finalises the application); it never submits
a form and never enters a code for you.

Usage:
  .venv/bin/python tools/verify_pending.py                # report only
  .venv/bin/python tools/verify_pending.py --open         # complete links in the browser
  .venv/bin/python tools/verify_pending.py --days 30
"""
import argparse
import csv
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gmail_readonly as G

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CSV_PATH = os.path.join(ROOT, "state", "applications.csv")

FOOTER = re.compile(r"teamtailor\.com/\?utm|/email-logo|/email-footer|unsubscribe", re.I)
STOP = {"the", "a", "an", "of", "and", "for", "to", "with", "group", "ab", "bank",
        "labs", "team", "recruiting", "hiring"}


def toks(s):
    return {t for t in re.split(r"[^a-z0-9]+", (s or "").lower()) if t and t not in STOP}


def load_submitted():
    out = {}
    if not os.path.isfile(CSV_PATH):
        return out
    for r in csv.DictReader(open(CSV_PATH, newline="", encoding="utf-8")):
        if (r.get("status") or "").upper() == "SUBMITTED":
            out.setdefault(r["company"].strip(), []).append(r["role"].strip())
    return out


def guess_company(sender, link):
    m = re.match(r'\s*"?([^"<]+?)"?\s*<', sender or "")
    name = (m.group(1) if m else "").strip()
    if name and not re.search(r"no-?reply|hiring|recruit|teamtailor|workday|join\.com|jobs", name, re.I):
        return name
    host = re.sub(r"^https?://", "", link or "").split("/")[0]
    return host.split(".")[0].replace("-", " ")


def match_company(submitted, guess):
    gt = toks(guess)
    if not gt:
        return None
    best, bestn = None, 0
    for co in submitted:
        n = len(gt & toks(co))
        if n > bestn:
            best, bestn = co, n
    return best if bestn >= 1 else None


def browser_nav(server, link):
    try:
        r = subprocess.run(
            ["python3", os.path.join(ROOT, "tools", "camoufox_browser.py"),
             "--server", server, "nav", link],
            capture_output=True, text=True, timeout=45)
        return (r.stdout or r.stderr).strip()[:160]
    except Exception as e:
        return f"(could not open: {e})"


def main():
    ap = argparse.ArgumentParser(description="Audit ATS email verifications vs the register.")
    ap.add_argument("--days", type=int, default=14)
    ap.add_argument("--open", action="store_true", help="complete verify/activation links in the pipeline browser")
    ap.add_argument("--server", default=os.environ.get("CAMOUFOX_SERVER", "http://127.0.0.1:9872"))
    ap.add_argument("--query", default="")
    args = ap.parse_args()

    query = args.query or (
        f"newer_than:{args.days}d (from:teamtailor-mail.com OR from:join.com OR "
        '"Complete the application" OR "Security code for your application" OR '
        '"verify your email" OR "Activate your account")')

    service = G.authenticate()
    resp = service.users().messages().list(userId="me", q=query, maxResults=60).execute()
    msgs = resp.get("messages", [])
    submitted = load_submitted()

    rows = []
    for m in msgs:
        msg = service.users().messages().get(userId="me", id=m["id"], format="full").execute()
        headers = {h["name"].lower(): h["value"] for h in msg["payload"].get("headers", [])}
        subject = headers.get("subject", "")
        sender = headers.get("from", "")
        if G.classify(subject, G._decode(msg["payload"])) != "VERIFICATION":
            continue
        links, codes = G.extract(G._decode(msg["payload"]))
        link = next((l for l in links if not FOOTER.search(l)), "")
        guess = guess_company(sender, link)
        co = match_company(submitted, guess)
        rows.append((headers.get("date", ""), guess, co, subject, link, codes[:1]))

    pending = [r for r in rows if r[2]]
    unmapped = [r for r in rows if not r[2]]

    print(f"{len(rows)} verification email(s); {len(pending)} match a SUBMITTED register company.\n")
    print("== SUBMITTED but verification may be pending ==")
    for date, guess, co, subject, link, codes in pending:
        print(f"  {co}  ({guess})  [{date[:16]}]")
        print(f"      {subject[:80]}")
        if link:
            print(f"      LINK {link}")
        if codes:
            print(f"      CODE {codes}")
        if args.open and link:
            print(f"      -> {browser_nav(args.server, link)}")
    if unmapped:
        print("\n== verification emails not matched to a SUBMITTED company ==")
        for date, guess, co, subject, link, codes in unmapped:
            print(f"  ({guess}) [{date[:16]}] {subject[:70]}")
            if link:
                print(f"      LINK {link}")
    print("\nNote: a matched row means the register says SUBMITTED while a verification "
          "mail exists - confirm the application is actually complete, then re-record or "
          "correct its status. This tool never submits a form.")


if __name__ == "__main__":
    main()
