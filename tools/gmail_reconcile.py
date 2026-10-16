#!/usr/bin/env python3
"""Reconcile state/applications.csv against your Gmail (read-only).

Reads application mail, classifies it, matches each message to a register row by
company/role, and proposes status changes:
  confirmation -> SUBMITTED (only if not already further along / missing)
  interview    -> INTERVIEW
  rejection    -> REJECTED
  verification -> note only (link surfaced for you to act on)

Dry-run by default; add --apply to write changes. Never clicks links.
Verification links you have already handled are silenced with
  .venv/bin/python tools/gmail_reconcile.py --ack "<url substring>"
(recorded in state/gmail_reconcile_ack.txt).

Run with the venv python:
  .venv/bin/python tools/gmail_reconcile.py
  .venv/bin/python tools/gmail_reconcile.py --apply
"""
import argparse
import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import register as R
import gmail_readonly as G

STATE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "state")
ACK_FILE = os.path.join(STATE, "gmail_reconcile_ack.txt")
# Message bodies are immutable, so cache the decoded mail keyed by id. Only new
# ids are fetched from Gmail on later runs, which avoids re-downloading the whole
# window every time (quota-safe, fast, no repeated token spend). Derived, so it
# lives outside the register and can be deleted at any time.
CACHE_FILE = os.path.join(STATE, "gmail_cache.json")


def fetch_full(service, mid, attempts=5):
    """messages.get with backoff for the Gmail per-minute read quota."""
    for i in range(attempts):
        try:
            return service.users().messages().get(userId="me", id=mid, format="full").execute()
        except Exception as exc:
            msg = str(exc)
            if "Quota exceeded" in msg or "rateLimitExceeded" in msg or "403" in msg:
                time.sleep(8 * (i + 1))
                continue
            raise
    raise RuntimeError(f"Gmail quota exceeded fetching {mid}")


def list_ids(service, query, max_results=300, attempts=6):
    for i in range(attempts):
        try:
            resp = service.users().messages().list(userId="me", q=query, maxResults=max_results).execute()
            return resp.get("messages", [])
        except Exception as exc:
            msg = str(exc)
            if "Quota exceeded" in msg or "rateLimitExceeded" in msg or "403" in msg:
                print(f"  (gmail quota; waiting {15*(i+1)}s)")
                time.sleep(15 * (i + 1))
                continue
            raise
    raise RuntimeError("Gmail quota exceeded listing messages")

DEFAULT_QUERY = os.environ.get(
    "GMAIL_RECONCILE_QUERY",
    'newer_than:180d (from:ashbyhq.com OR from:teamtailor.com OR from:teamtailor-mail.com OR '
    'from:greenhouse.io OR from:greenhouse-mail.io OR from:lever.co OR from:hire.lever.co OR '
    'from:myworkday.com OR from:successfactors.eu OR from:workable.com OR from:pinpoint.email OR '
    'from:join.com OR from:deel.com OR from:jobylon.com OR label:applications OR '
    '(interview OR "next steps" OR "next step" OR "first chat" OR "intro call" OR "phone screen" OR '
    '"screening" OR unfortunately OR "not moving forward" OR "move forward with" OR "other candidates" OR '
    '"application update" OR "application status" OR "not able to offer" OR "decided to" OR offer OR rejection))')

COMMON = {"group", "labs", "health", "studios", "studio", "recruiting", "recruitment",
          "hiring", "team", "the", "ab", "inc", "ltd", "technologies", "technology"}
# Generic words excluded from word-level matching.
GENERIC_WORD = {"sound", "international", "solutions", "systems", "digital", "media",
                "data", "tech", "global", "nordic", "partners", "partner", "software",
                "services", "service", "and", "of", "the", "company"}
# ATS vendor names: never treat these as the employer.
ATS_VENDORS = {"ashby", "ashbyhq", "teamtailor", "greenhouse", "lever", "hire",
               "workday", "myworkday", "successfactors", "join", "pinpoint", "workable",
               "zerolime", "deel", "recruitee", "jobvite", "smartrecruiters", "noreply",
               "no", "reply", "system"}


def sender_display(sender):
    m = re.match(r'\s*"?([^"<]*?)"?\s*<', sender)
    return (m.group(1) if m else sender).strip()


def sender_domain(sender):
    """First label of the sender's email domain, e.g. 'acme' from
    'Acme Corp <interview@jobs.acme.example>'."""
    m = re.search(r"@([A-Za-z0-9.-]+)", sender or "")
    return m.group(1).lower().split(".")[0] if m else ""


def terms(value):
    """Distinctive match terms: phrase, spaceless form, and individual words."""
    out = []
    for part in re.split(r"[/()|,]", value):
        part = part.strip().lower()
        if not part:
            continue
        if len(part) >= 3 and part not in COMMON and part not in ATS_VENDORS:
            out.append(part)
        compact = re.sub(r"[^a-z0-9]", "", part)
        if len(compact) >= 4 and compact not in COMMON and compact not in ATS_VENDORS and compact != part:
            out.append(compact)
        for word in re.split(r"\s+", part):
            if len(word) >= 4 and word not in COMMON and word not in GENERIC_WORD and word not in ATS_VENDORS:
                out.append(word)
    return list(dict.fromkeys(out))


# Sender/display names that differ from the register's company name.
# Fill in your own mappings, e.g. {"ats-sender-label": "Register Company Name"}.
SENDER_ALIASES = {}

# Single-word company terms that are also ordinary hiring-email vocabulary.
BODY_WORD_STOP = {"recruiter", "recruiters", "recruiting", "future", "candidate",
                  "candidates", "application", "applications", "interview"}


def _body_terms_ok(term, company):
    """Safe to match this term against a message body.

    Bodies are full of role and process words, so a bare fragment of a company
    name is only usable when it is unambiguous: a multi-word chunk of the name,
    the compacted full name, or a short single-word company name itself.
    """
    if " " in term:
        return True
    if term == re.sub(r"[^a-z0-9]", "", company.lower()):
        return True
    words = [w for w in re.split(r"\s+", re.sub(r"[()|,]", " ", company.lower())) if w]
    if len(words) == 1 and len(term) >= 5 and term not in BODY_WORD_STOP:
        return True
    return False


def _in_prose(body, term):
    """True when at least one occurrence of term sits in prose, not in a URL or
    markup leftover. Without this, 'google' inside fonts.googleapis.com in an
    email's inline CSS resolves the sender to Google."""
    for m in re.finditer(re.escape(term), body):
        pre = body[max(0, m.start() - 1):m.start()]
        if pre in ("", " ", "\t", "\n", "(", '"', "'", "<", ",", ";", ":"):
            return True
    return False


def match_company(text, rows, body="", sender=""):
    """Return the register company that matches the subject/sender, falling back
    to a conservative match against the body text, then known sender aliases.

    Matching is deterministic: the longest matching term wins; ties are broken in
    favour of a company whose name matches the sender's domain, then the shorter
    (more exact) company name. This stops 'Acme' vs 'a parent/subsidiary pair' and
    'Alpha Ltd' vs 'Beta Ltd' from flipping between runs on set-iteration order.
    """
    low = text.lower()
    dom = sender_domain(sender)
    best_key, best_co = None, ""
    for co in {r["company"] for r in rows}:
        for t in terms(co):
            if t in low:
                dm = 1 if (dom and dom in re.sub(r"[^a-z0-9]", "", co.lower())) else 0
                key = (len(t), dm, -len(co), co)
                if best_key is None or key > best_key:
                    best_key, best_co = key, co
    if best_co:
        return best_co
    if body:
        best_key, best_co = None, ""
        for co in {r["company"] for r in rows}:
            for t in terms(co):
                if t in body and _body_terms_ok(t, co) and _in_prose(body, t):
                    key = (len(t), -len(co), co)
                    if best_key is None or key > best_key:
                        best_key, best_co = key, co
        if best_co:
            return best_co
    for key, co in SENDER_ALIASES.items():
        if key in low and co in {r["company"] for r in rows}:
            return co
    return ""


def _word_match(term, text):
    """Whole-word (not substring) presence of term in text. Stops a term like
    'consultant' matching the body word 'consultants' and stealing a role."""
    return re.search(r"(?<![a-z0-9])" + re.escape(term) + r"(?![a-z0-9])", text) is not None


def match_row(company, subject, rows):
    """The register row for a company. If the company has several roles and the
    subject names none of them, return None (ambiguous - do not guess).

    Roles are scored by (full-name match length, longest whole-word term match)
    so the most specific role wins: an email naming 'Senior Analytics Engineer
    (Multiple Domains)' picks that row rather than its 'Senior Analytics
    Engineer' prefix, and 'Tech Lead' is not stolen by a role whose word
    'consultant' happens to appear as 'consultants' in the prose."""
    if not company:
        return None
    cand = [r for r in rows if r["company"] == company]
    if not cand:
        return None
    if len(cand) == 1:
        return cand[0]
    low = re.sub(r"\s+", " ", subject.lower())
    best, best_key = None, None
    for r in cand:
        name = re.sub(r"\s+", " ", r["role"].lower()).strip()
        full = len(name) if name and name in low else 0
        word = 0
        for t in terms(r["role"]):
            if _word_match(t, low):
                word = max(word, len(t))
        key = (full, word)
        if best is None or key > best_key:
            best, best_key = r, key
    if best_key and (best_key[0] or best_key[1]):
        return best
    return None


def propose(current, category):
    if category == "REJECTION":
        return current if current == "OFFER" else "REJECTED"
    if category == "INTERVIEW":
        return current if current in ("OFFER", "REJECTED") else "INTERVIEW"
    if category == "CONFIRMATION":
        # Only upgrade a role we had not recorded as submitted. MANUAL/BLOCKED are
        # left for a human (a single confirmation may not cover a grouped row).
        return "SUBMITTED" if current in ("PREPARED", "IN_PROGRESS") else ""
    return ""


def load_acks():
    if not os.path.exists(ACK_FILE):
        return []
    with open(ACK_FILE) as f:
        return [ln.strip() for ln in f if ln.strip() and not ln.startswith("#")]


def add_ack(pattern):
    with open(ACK_FILE, "a") as f:
        f.write(pattern + "\n")


def load_cache():
    if not os.path.exists(CACHE_FILE):
        return {}
    try:
        with open(CACHE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (ValueError, OSError):
        return {}


def save_cache(cache):
    tmp = CACHE_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cache, f)
    os.replace(tmp, CACHE_FILE)


def cached_message(service, mid, cache):
    """Return (decoded message dict, was_fetched). Message bodies are immutable,
    so they are fetched once and reused; only new ids hit the Gmail API."""
    hit = cache.get(mid)
    if hit is None:
        msg = fetch_full(service, mid)
        headers = {h["name"].lower(): h["value"] for h in msg["payload"].get("headers", [])}
        hit = {"date": headers.get("date", ""), "from": headers.get("from", ""),
               "subject": headers.get("subject", ""), "body": G._decode(msg["payload"])}
        cache[mid] = hit
        time.sleep(0.2)
        return hit, True
    return hit, False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="write changes (default: dry run)")
    ap.add_argument("--query", default=DEFAULT_QUERY)
    ap.add_argument("--ack", help="substring of a verification link to mark as already handled")
    ap.add_argument("--no-cache", action="store_true", help="ignore the message cache and re-fetch everything")
    args = ap.parse_args()

    if args.ack:
        add_ack(args.ack)
        print(f"acked {args.ack[:80]} -> {ACK_FILE}")

    rows = R.load()
    service = G.authenticate()
    messages = list_ids(service, args.query)
    print(f"{len(messages)} application messages over the query\n")
    acks = load_acks()
    cache = {} if args.no_cache else load_cache()

    changes, unmatched, verifications, ambiguous = [], [], [], []
    fetched = 0
    for m in messages:
        hit, was_fetched = cached_message(service, m["id"], cache)
        fetched += was_fetched
        subject, sender, date, body = hit["subject"], hit["from"], hit["date"], hit["body"]
        category = G.classify(subject, body)
        # plain, truncated body text so generic ATS senders still resolve to a
        # company - drop <style>/<script> first so inline CSS (fonts.googleapis.com
        # etc.) cannot be mistaken for prose mentioning a company
        clean = re.sub(r"(?is)<(style|script|head)\b[^>]*>.*?</\1>", " ", body)
        plain = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", clean))[:4000]
        company = match_company(f"{subject} {sender_display(sender)}", rows, body=plain, sender=sender)
        row = match_row(company, " ".join([subject, plain]), rows)
        if category == "VERIFICATION":
            links, codes = G.extract(body)
            verifications.append((date, company or sender_display(sender), subject, links, codes))
        amb = False
        # An invite/rejection for a company with several applications whose
        # subject names none of the roles is NOT guessed: it is reported under
        # "role ambiguous" for manual review. Guessing the most recent row made
        # past runs reject the wrong role.
        if not row:
            if category != "OTHER":
                (ambiguous if company else unmatched).append((date, category, company or sender, subject))
            continue
        proposed = propose(row["status"], category)
        if proposed and proposed != row["status"]:
            changes.append((row, proposed, category, date, subject, amb))

    # keep the cache bounded to the current window and persist it
    live = {m["id"] for m in messages}
    cache = {k: v for k, v in cache.items() if k in live}
    save_cache(cache)
    print(f"({fetched} fetched, {len(messages) - fetched} from cache)\n")

    # de-duplicate (the same mail can match twice) keeping the first
    seen_keys, uniq = set(), []
    for c in changes:
        k = (c[0]["company"], c[0]["role"], c[1])
        if k in seen_keys:
            continue
        seen_keys.add(k)
        uniq.append(c)
    changes = uniq

    # drop verification links the user has already acted on (see --ack)
    if acks:
        verifications = [
            e for e in verifications
            if not any(any(a in link for a in acks) for link in e[3])
        ]

    print("== proposed register changes ==")
    if not changes:
        print("  (none)")
    for row, proposed, category, date, subject, amb in changes:
        flag = "  (role ambiguous - best guess)" if amb else ""
        print(f"  {row['company']:<24} {row['role'][:38]:<38} {row['status']:<10} -> {proposed:<10} [{category}]{flag}")

    if verifications:
        print("\n== verification links/codes (handle manually) ==")
        for date, who, subject, links, codes in verifications:
            print(f"  {who}: {subject[:60]}")
            for l in links:
                print(f"     LINK {l[:120]}")
            for c in codes:
                print(f"     CODE {c}")

    if unmatched:
        print("\n== mail not matched to a register row ==")
        for date, category, sender, subject in unmatched:
            print(f"  [{category}] {sender[:40]:<40} {subject[:60]}")

    if ambiguous:
        print("\n== company matched but role ambiguous (review manually) ==")
        for date, category, company, subject in ambiguous:
            print(f"  [{category}] {company:<24} {subject[:60]}")

    if args.apply and changes:
        for row, proposed, category, date, subject, amb in changes:
            note = f"gmail: {category} {date}" + (" (role ambiguous - best guess)" if amb else "")
            R.set_row(row["company"], row["role"], status=proposed, note=note)
        print(f"\napplied {len(changes)} change(s); register regenerated")
    elif changes:
        print("\n(dry run - re-run with --apply to write these)")


if __name__ == "__main__":
    main()
