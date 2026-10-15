#!/usr/bin/env python3
"""Build the human-assist queue from the register's BLOCKED rows.

Only roles whose blocker is a HUMAN step (CAPTCHA / bot-check / Ashby "possible
spam" re-submit / rate-limit reset) are included. Each row carries the apply URL
and the prepared CV/letter paths, so a human can finish it in seconds.

Writes state/queue-human.tsv (tab-separated):
  company  role  url  cv  letter  reason

Usage: python3 tools/build_human_queue.py
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import register as R

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
APPS = os.path.join(ROOT, "documents", "applications")

HUMAN = re.compile(r"captcha|recaptcha|hcaptcha|datadome|turnstile|possible spam|"
                   r"flagged as possible spam|re-flagged|429|rate.?limit|"
                   r"90 day|three applications|two-factor|checkpoint", re.I)


def reason_of(note):
    n = note.lower()
    if any(k in n for k in ("captcha", "recaptcha", "hcaptcha", "datadome", "turnstile")):
        return "CAPTCHA"
    if "spam" in n or "re-flagged" in n:
        return "Ashby anti-spam re-check"
    if "429" in n or "rate" in n or "90 day" in n or "three applications" in n:
        return "rate-limit / cap reset"
    return "human step"


def load_queue():
    """(company, role, url, cv) from the queues that still hold the apply URL."""
    m = {}
    for fn in ("state/queue.tsv", "state/queue-linkedin.tsv"):
        p = os.path.join(ROOT, fn)
        if not os.path.exists(p):
            continue
        for line in open(p):
            if not line.strip() or line.startswith("#"):
                continue
            f = line.rstrip("\n").split("\t")
            if len(f) < 6:
                continue
            m[(f[0].strip().lower(), f[1].strip().lower())] = (f[2], f[3])
    return m


def find_letter(company, role):
    slug = re.sub(r"[^a-z0-9]+", "_", f"{company}_{role}".lower())[:40]
    base = re.sub(r"[^a-z0-9]", "", company.lower())[:12]
    for fn in os.listdir(APPS) if os.path.isdir(APPS) else []:
        low = fn.lower()
        if low.endswith(".docx") and ("motivation" in low) and (base and base in low):
            return os.path.join("documents", "applications", fn)
    return ""


def main():
    import argparse
    ap = argparse.ArgumentParser(description="Build the human-assist queue from BLOCKED rows.")
    ap.add_argument("--only", default="",
                    help="keep only rows whose reason matches this substring (e.g. 'captcha')")
    args = ap.parse_args()
    q = load_queue()
    rows = []
    for r in R.load():
        if r["status"] != "BLOCKED":
            continue
        note = r["notes"]
        if not HUMAN.search(note):
            continue
        key = (r["company"].strip().lower(), r["role"].strip().lower())
        url, cv = q.get(key, ("", ""))
        if not url:
            m = re.search(r"https?://[^\s)]+", note)
            url = m.group(0) if m else ""
        out = os.path.join(ROOT, "state", "queue-human.tsv")
        rows.append((r["company"], r["role"], url, cv, find_letter(r["company"], r["role"]), reason_of(note)))

    # also route not-done QUEUE rows whose ATS flags automation (Ashby / LinkedIn) to manual
    def dset(path):
        return {l.strip() for l in open(os.path.join(ROOT, path))} if os.path.exists(os.path.join(ROOT, path)) else set()
    for fn, dpath in (("state/queue.tsv", "state/queue.done"), ("state/queue-linkedin.tsv", "state/queue-linkedin.done")):
        p = os.path.join(ROOT, fn)
        if not os.path.exists(p):
            continue
        done = dset(dpath)
        for line in open(p):
            if not line.strip() or line.startswith("#"):
                continue
            f = (line.rstrip("\n").split("\t") + [""] * 6)[:6]
            co, role, url, cv, ats = f[0], f[1], f[2], f[3], f[4]
            if not co or f"{co}|{role}" in done:
                continue
            if not re.search(r"ashby|linkedin", ats, re.I):
                continue
            reason = "Ashby anti-spam re-check" if "ashby" in ats.lower() else "LinkedIn Easy Apply"
            rows.append((co, role, url, cv, find_letter(co, role), reason))

    # dedupe by company|role
    seen = set()
    final = []
    for row in rows:
        k = f"{row[0]}|{row[1]}"
        if k in seen:
            continue
        seen.add(k)
        final.append(row)
    if args.only:
        final = [r for r in final if args.only.lower() in r[5].lower()]
    with open(os.path.join(ROOT, "state", "queue-human.tsv"), "w") as f:
        f.write("# human-assist queue — roles blocked only by a HUMAN step (CAPTCHA / Ashby re-check / cap reset)\n")
        f.write("# company\trole\turl\tcv\tletter\treason\n")
        for co, role, url, cv, letter, reason in final:
            f.write(f"{co}\t{role}\t{url}\t{cv}\t{letter}\t{reason}\n")
    print(f"human-assist queue: {len(final)} roles -> state/queue-human.tsv")
    from collections import Counter
    print("by reason:", dict(Counter(r[5] for r in final)))


if __name__ == "__main__":
    main()
