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
from datetime import date
from email.utils import parsedate_to_datetime

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
REVIEW_FILE = os.path.join(STATE, "gmail-review.json")
REVIEW_ACK_FILE = os.path.join(STATE, "gmail-review-ack.json")
REVIEW_CFG_FILE = os.path.join(os.path.dirname(STATE), "config", "gmail-review.json")


def review_enabled():
    try:
        with open(REVIEW_CFG_FILE, encoding="utf-8") as fh:
            return bool(json.load(fh).get("enabled", True))
    except (OSError, ValueError):
        return True


def auto_model_enabled():
    try:
        with open(REVIEW_CFG_FILE, encoding="utf-8") as fh:
            d = json.load(fh)
        return (bool(d.get("enabled", True)) and bool(d.get("use_model", True))
                and bool(d.get("auto_model", False)))
    except (OSError, ValueError):
        return False


def _review_ack_ids():
    try:
        with open(REVIEW_ACK_FILE, encoding="utf-8") as fh:
            return {str(x) for x in json.load(fh)}
    except (OSError, ValueError):
        return set()


def save_review(entries, seen_ids):
    """Persist the human-review queue, preserving old unresolved items.

    Mail in the current scan is replaced by the current decision; older mail
    stays until the operator marks it Done. A disabled review queue writes
    nothing.
    """
    if not review_enabled():
        return
    old = {}
    try:
        with open(REVIEW_FILE, encoding="utf-8") as fh:
            for e in json.load(fh):
                if isinstance(e, dict) and e.get("id"):
                    old[e["id"]] = e
    except (OSError, ValueError):
        pass
    for mid in seen_ids:
        old.pop(mid, None)
    for e in entries:
        if e.get("id"):
            old[e["id"]] = e
    ack = _review_ack_ids()
    out = sorted((e for mid, e in old.items() if mid not in ack),
                 key=lambda e: str(e.get("date", "")), reverse=True)
    os.makedirs(STATE, exist_ok=True)
    with open(REVIEW_FILE, "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=2, ensure_ascii=False)


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


def list_ids(service, query, max_results=3000, page_size=500, attempts=6):
    """List EVERY matching message, following nextPageToken (no silent 300 cap)."""
    found, token = [], None
    while len(found) < max_results:
        for i in range(attempts):
            try:
                params = {"userId": "me", "q": query,
                          "maxResults": min(page_size, max_results - len(found))}
                if token:
                    params["pageToken"] = token
                resp = service.users().messages().list(**params).execute()
                break
            except Exception as exc:
                msg = str(exc)
                if "Quota exceeded" in msg or "rateLimitExceeded" in msg or "403" in msg:
                    print(f"  (gmail quota; waiting {15*(i+1)}s)")
                    time.sleep(15 * (i + 1))
                    continue
                raise
        else:
            raise RuntimeError("Gmail quota exceeded listing messages")
        found.extend(resp.get("messages", []))
        token = resp.get("nextPageToken")
        if not token:
            break
    return found[:max_results]

# Sweep the whole recent mailbox, not just known ATS domains: recruiters write
# from ordinary addresses (e.g. example.com for Acme Corp) and a narrow
# allow-list silently missed their mail. The two halves are OR-ed:
#   - every recent message (14 days) outside promotions/social/forums, so a
#     brand-new recruiter email is inspected regardless of sender/subject;
#   - the known ATS senders + the `applications` label for 180 days, so older
#     confirmations/rejections still land.
# Pagination means no silent 300-message cap; the message cache keeps later runs fast.
DEFAULT_QUERY = os.environ.get(
    "GMAIL_RECONCILE_QUERY",
    "(newer_than:14d -in:sent -in:spam -in:trash "
    "-category:promotions -category:social -category:forums) OR "
    "(newer_than:180d (from:ashbyhq.com OR from:teamtailor.com OR from:teamtailor-mail.com OR "
    "from:greenhouse.io OR from:greenhouse-mail.io OR from:lever.co OR from:hire.lever.co OR "
    "from:myworkday.com OR from:successfactors.eu OR from:workable.com OR from:pinpoint.email OR "
    "from:join.com OR from:zerolime.se OR from:deel.com OR from:jobylon.com OR from:msg.jobylon.com OR label:applications))")

# Outbound mail: what WE sent (follow-ups, replies). Notes only - never a status.
OUTBOUND_QUERY = os.environ.get(
    "GMAIL_OUTBOUND_QUERY",
    "in:sent newer_than:14d -in:spam -in:trash")

COMMON = {"group", "labs", "health", "studios", "studio", "recruiting", "recruitment",
          "hiring", "team", "the", "ab", "inc", "ltd", "technologies", "technology"}
# Generic words excluded from word-level matching.
GENERIC_WORD = {"sound", "international", "solutions", "systems", "digital", "media",
                "data", "tech", "global", "nordic", "partners", "partner", "software",
                "services", "service", "and", "of", "the", "company", "security", "cyber",
                "cloud", "platform", "architect", "devops", "consultant", "consulting",
                "engineer", "engineering", "manager",
                "director", "lead", "senior", "analyst", "specialist", "operations",
                "network", "it", "ai", "ml"}
# ATS vendor names: never treat these as the employer.
ATS_VENDORS = {"ashby", "ashbyhq", "teamtailor", "greenhouse", "lever", "hire",
               "workday", "myworkday", "successfactors", "join", "pinpoint", "workable",
               "zerolime", "deel", "recruitee", "jobvite", "smartrecruiters", "noreply",
               "no", "reply", "system", "danaher"}


def sender_display(sender):
    m = re.match(r'\s*"?([^"<]*?)"?\s*<', sender)
    return (m.group(1) if m else sender).strip()


def sender_domain(sender):
    """First label of the sender's email domain, e.g. 'acme' from
    'Acme <interview@jobs.acme.com>'."""
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


# Sender/display names that differ from the register's company name. Kept in
# config/recruiter-aliases.json (private, optional) so real employer/agency names
# never end up in the code or the public mirror.
ALIAS_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                          "config", "recruiter-aliases.json")


def _load_aliases():
    try:
        with open(ALIAS_FILE, encoding="utf-8") as fh:
            data = json.load(fh)
        return {str(k).lower(): str(v).strip() for k, v in data.items() if str(k).strip() and v}
    except (OSError, ValueError):
        return {}


SENDER_ALIASES = _load_aliases()

# Job-board alerts, newsletters and marketing mail can mention a registered
# company in the body; they are not application correspondence. Drop them before
# matching so they cannot create fake "reply needed" rows or steal a role.
BULK_SUBJECT = re.compile(r"jobalerts?|job alerts?|newsletter|weekly insights|digest|"
                          r"unsubscribe|promotions?|%\s*off|up to \d+%", re.I)
BULK_SENDER = re.compile(r"jobalerts?|job alerts?|linkedin.*(alert|notification)|"
                         r"newsletter|marketing|digest", re.I)


def _bulk_mail(sender, subject, body):
    disp = sender_display(sender)
    if BULK_SENDER.search(disp) or BULK_SENDER.search(sender) or BULK_SUBJECT.search(subject):
        return True
    b = (body or "").lower()
    return "view job:" in b or "manage alerts" in b

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
    (more exact) company name. This stops a parent/subsidiary pair, or two
    near-identical names, from flipping between runs on set-iteration order.
    """
    low = text.lower()
    dom = sender_domain(sender)
    names = {r["company"] for r in rows}
    # A deliberately curated sender/subject alias beats a generic company word
    # ("security", "stockholm", "software", …) from the subject/body.
    for key, co in sorted(SENDER_ALIASES.items(), key=lambda kv: -len(kv[0])):
        if co in names and key in low:
            return co
    if body:
        blow = body.lower()
        for key, co in sorted(SENDER_ALIASES.items(), key=lambda kv: -len(kv[0])):
            if co in names and key in blow and _in_prose(blow, key):
                return co
    best_key, best_co = None, ""
    for co in {r["company"] for r in rows}:
        for t in terms(co):
            if t in low:
                # A whole-word hit beats a bare substring hit, whatever the
                # length: "Thanks for Considering Cisco" must not match the
                # company "Consid" (consid-ering). Only fall back to the
                # substring match when nothing matches cleanly.
                wm = 1 if _word_match(t, low) else 0
                dm = 1 if (dom and dom in re.sub(r"[^a-z0-9]", "", co.lower())) else 0
                key = (wm, len(t), dm, -len(co), co)
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
    if body:
        blow = body.lower()
        for key, co in SENDER_ALIASES.items():
            if key in blow and co in {r["company"] for r in rows} and _in_prose(blow, key):
                return co
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
    # Compare on a punctuation-free skeleton as well as the raw text: an email
    # names a role as "Research Engineer, Web Crawlers" while the register row
    # says "Research Engineer - Web Crawlers", so a raw substring test misses it
    # and the row ends up picked arbitrarily among the company's other roles.
    low_skel = re.sub(r"[^a-z0-9]+", "", low)
    best, best_key = None, None
    tie = False
    for r in cand:
        name = re.sub(r"\s+", " ", r["role"].lower()).strip()
        full = len(name) if name and name in low else 0
        skel = re.sub(r"[^a-z0-9]+", "", name)
        if not full and len(skel) >= 8 and skel in low_skel:
            full = len(skel)
        word = 0
        matched = 0
        for t in terms(r["role"]):
            if _word_match(t, low):
                matched += 1
                word = max(word, len(t))
        key = (full, word, matched)
        if best_key is None or key > best_key:
            best, best_key, tie = r, key, False
        elif key == best_key:
            # Equally good match for a different role: genuinely ambiguous.
            # Do not guess - the caller reports it for review instead.
            tie = True
    if best_key is not None and (best_key[0] or best_key[1]) and not tie:
        return best
    return None


def follow_up(category, sender, subject):
    """A short, human follow-up line for statuses that usually need a reply."""
    if category == "INTERVIEW":
        who = sender_display(sender) or "the recruiter"
        return f"Reply to {who} — {subject[:90]}"
    return None


def propose(current, category):
    if category == "REJECTION":
        return current if current == "OFFER" else "REJECTED"
    if category == "INTERVIEW":
        # Never reopen a row the candidate or an operator closed by hand
        # (CLOSED = do not pursue) and never overwrite a row that is waiting on
        # a human step (BLOCKED/MANUAL). Those are human decisions; a replayed
        # invitation email must not undo them.
        if current in ("OFFER", "REJECTED"):
            return current
        if current in ("CLOSED", "BLOCKED", "MANUAL"):
            return ""
        return "INTERVIEW"
    if category == "CONFIRMATION":
        # Only upgrade a prepared role. IN_PROGRESS means it is already further
        # along (assessment/interview stage); a generic confirmation must never
        # move it backwards. MANUAL/BLOCKED are left for a human too.
        return "SUBMITTED" if current == "PREPARED" else ""
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
    """Return (date, sender, subject, body) for a message, fetching it once and
    caching the decoded body. Returns the cache dict too so callers can prune."""
    hit = cache.get(mid)
    if hit is None:
        msg = fetch_full(service, mid)
        headers = {h["name"].lower(): h["value"] for h in msg["payload"].get("headers", [])}
        hit = {"date": headers.get("date", ""), "from": headers.get("from", ""),
               "subject": headers.get("subject", ""), "body": G._decode(msg["payload"])}
        cache[mid] = hit
        time.sleep(0.05)
        return hit, True
    return hit, False


def _msg_date(header):
    try:
        return parsedate_to_datetime(header).date().isoformat()
    except (TypeError, ValueError):
        return date.today().isoformat()


def scan_outbound(service, rows, max_results=1000):
    """Sent mail from the last 14 days, matched to register rows.

    Outbound mail can only add a note (with the Gmail message id); it must never
    change status - our own email is not an outcome. Skipped when the id is
    already in the row's notes, so repeated runs are idempotent.
    """
    found, ambiguous = [], []
    for m in list_ids(service, OUTBOUND_QUERY, max_results=max_results):
        msg = fetch_full(service, m["id"])
        headers = {h["name"].lower(): h["value"] for h in msg["payload"].get("headers", [])}
        to = ", ".join(x for x in (headers.get("to", ""), headers.get("cc", "")) if x)
        subject = headers.get("subject", "")
        # Outbound matching is deliberately conservative: recipient + subject
        # only, never the body (our own prose mentions many companies).
        company = match_company(f"{subject} {sender_display(to)}", rows, sender=to)
        row = match_row(company, subject, rows)
        if not row:
            if company:
                ambiguous.append((subject, company, to))
            continue
        mid = m["id"]
        if mid in row["notes"]:
            continue
        found.append((_msg_date(headers.get("date", "")), row["company"], row["role"],
                      sender_display(to) or to, subject, mid))
        time.sleep(0.05)
    return found, ambiguous


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="write changes (default: dry run)")
    ap.add_argument("--query", default=DEFAULT_QUERY)
    ap.add_argument("--max", type=int, default=3000, help="hard cap on messages inspected")
    ap.add_argument("--ack", help="substring of a verification link to mark as already handled")
    ap.add_argument("--no-cache", action="store_true", help="ignore the message cache and re-fetch everything")
    args = ap.parse_args()

    if args.ack:
        add_ack(args.ack)
        print(f"acked {args.ack[:80]} -> {ACK_FILE}")

    rows = R.load()
    service = G.authenticate()
    messages = list_ids(service, args.query, max_results=args.max)
    print(f"{len(messages)} messages inspected (window: {args.query[:80]})\n")
    acks = load_acks()
    cache = {} if args.no_cache else load_cache()

    changes, unmatched, verifications, ambiguous, replies = [], [], [], [], []
    review = []
    fetched = 0
    for idx, m in enumerate(messages, 1):
        if idx % 100 == 0:
            print(f"  inspected {idx}/{len(messages)} …", flush=True)
        hit, was_fetched = cached_message(service, m["id"], cache)
        fetched += was_fetched
        date, sender, subject, body = hit["date"], hit["from"], hit["subject"], hit["body"]
        category = G.classify(subject, body)
        # plain, truncated body text so generic ATS senders still resolve to a
        # company - drop <style>/<script> first so inline CSS (fonts.googleapis.com
        # etc.) cannot be mistaken for prose mentioning a company
        clean = re.sub(r"(?is)<(style|script|head)\b[^>]*>.*?</\1>", " ", body)
        plain = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", clean))[:4000]
        if _bulk_mail(sender, subject, plain):
            continue
        company = match_company(f"{subject} {sender_display(sender)}", rows, body=plain, sender=sender)
        row = match_row(company, " ".join([subject, plain]), rows)
        if category == "VERIFICATION":
            links, codes = G.extract(body)
            verifications.append((date, company or sender_display(sender), subject, links, codes))
            review.append({"id": m["id"], "date": date, "category": category,
                           "company": company, "role": row["role"] if row else "",
                           "sender": sender_display(sender), "subject": subject,
                           "reason": "verification link or code; handle manually",
                           "links": links, "codes": codes})
        amb = False
        # An invite/rejection for a company with several applications whose
        # subject names none of the roles is NOT guessed: it is reported under
        # "role ambiguous" for manual review. Guessing the most recent row made
        # past runs rejected the wrong role (see the notes on ambiguous matches).
        if category == "OTHER":
            if row:
                replies.append((date, row, sender_display(sender), subject))
                reason = "reply may need a human"
                rco, rrole = row["company"], row["role"]
            elif company:
                ambiguous.append((date, "REPLY?", company, subject))
                reason = "company matched but role ambiguous"
                rco, rrole = company, ""
            else:
                reason = "could not classify or match this email"
                rco, rrole = "", ""
            review.append({"id": m["id"], "date": date, "category": "OTHER",
                           "company": rco, "role": rrole, "sender": sender_display(sender),
                           "subject": subject, "reason": reason, "links": [], "codes": []})
            continue
        if not row:
            (ambiguous if company else unmatched).append((date, category, company or sender, subject))
            review.append({"id": m["id"], "date": date, "category": category,
                           "company": company, "role": "", "sender": sender_display(sender),
                           "subject": subject,
                           "reason": ("company matched but role ambiguous" if company
                                      else "no company match in the register"),
                           "links": [], "codes": []})
            continue
        proposed = propose(row["status"], category)
        if proposed and proposed != row["status"]:
            changes.append((row, proposed, category, date, subject, amb, sender))
        elif category in ("OTHER", "INTERVIEW"):
            # No status change, but a personal/interview reply still needs a
            # human: an invitation or "are you still interested?" is not a
            # status transition on a row that is already INTERVIEW.
            replies.append((date, row, sender_display(sender), subject))
            review.append({"id": m["id"], "date": date, "category": category,
                           "company": row["company"], "role": row["role"],
                           "sender": sender_display(sender), "subject": subject,
                           "reason": "reply may need a human", "links": [], "codes": []})

    outbound, outbound_ambiguous = scan_outbound(service, rows)

    # keep the cache bounded to the current window and persist it
    live = {m["id"] for m in messages}
    cache = {k: v for k, v in cache.items() if k in live}
    save_cache(cache)
    # Optional, bounded model pass: only mail that is new since the previous
    # review file (never the existing backlog), suggestions only, no status.
    if auto_model_enabled() and os.path.exists(REVIEW_FILE):
        try:
            with open(REVIEW_FILE, encoding="utf-8") as fh:
                old_ids = {str(e.get("id")) for e in json.load(fh) if isinstance(e, dict)}
        except (OSError, ValueError):
            old_ids = set()
        ack_ids = _review_ack_ids()
        new_items = [e for e in review
                     if str(e.get("id")) not in old_ids and str(e.get("id")) not in ack_ids]
        if new_items:
            try:
                import gmail_review_model as GRM
                print(f"auto model review: {len(new_items)} new item(s)", flush=True)
                for item in new_items:
                    res = GRM.ask(item)
                    if res.get("suggestion"):
                        item["suggestion"] = res["suggestion"]
                        item["model"] = res.get("model", "")
                        print(f"  suggested: {item.get('company') or item.get('sender','')} — {item.get('subject','')[:60]}", flush=True)
                    else:
                        print(f"  skipped: {res.get('error','no suggestion')[:120]}", flush=True)
            except Exception as e:
                print(f"auto model review skipped: {str(e)[:160]}", flush=True)
    save_review(review, live)
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

    print("== outbound email to record (notes only) ==")
    if not outbound:
        print("  (none)")
    for odate, company, role, to, subject, mid in outbound:
        print(f"  {odate}  {company:<24} {role[:38]:<38} -> {to[:40]}  [{subject[:50]}]")
    if outbound_ambiguous:
        print("\n== outbound company matched but role ambiguous (not recorded) ==")
        for subject, company, to in outbound_ambiguous:
            print(f"  {company:<24} -> {to[:40]}  {subject[:60]}")

    if replies:
        print("\n== replies that may need a human (no status change) ==")
        for date, row, sender, subject in replies:
            print(f"  {date[:16]}  {row['company']:<24} {row['role'][:34]:<34} "
                  f"{sender[:28]:<28} {subject[:60]}")

    print("\n== proposed register changes ==")
    if not changes:
        print("  (none)")
    for row, proposed, category, date, subject, amb, _sender in changes:
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

    if args.apply and outbound:
        for odate, company, role, to, subject, mid in outbound:
            R.log_outbound(company, role, to, subject, mid, when=odate)
        print(f"\nrecorded {len(outbound)} outbound email(s) in the register")

    if args.apply and changes:
        for row, proposed, category, date, subject, amb, sender in changes:
            note = f"gmail: {category} {date}" + (" (role ambiguous - best guess)" if amb else "")
            action = follow_up(category, sender, subject) if proposed == "INTERVIEW" else None
            if proposed in ("REJECTED", "CLOSED"):
                action = ""                      # nothing to do on a dead application
            R.set_row(row["company"], row["role"], status=proposed, note=note, action=action)
        print(f"\napplied {len(changes)} change(s); register regenerated")
    elif changes:
        print("\n(dry run - re-run with --apply to write these)")

    mode = "applied" if args.apply else "dry run"
    print(f"\n== summary ({mode}): {len(messages)} inspected · {len(changes)} proposed · "
          f"{len(outbound)} outbound · {len(verifications)} verification · "
          f"{len(unmatched)} unmatched · {len(ambiguous)} ambiguous ==")


if __name__ == "__main__":
    main()
