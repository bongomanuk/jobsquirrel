#!/usr/bin/env python3
"""Keep the register's action column honest: only a person waiting for you stays.

The action column is a to-do list, not a wish list. It used to collect our own
follow-up ideas, unanswered leads, expired deadlines and roles that had already
been rejected, which inflated it until the list stopped meaning anything.

Every flag is now proved against the mailbox. The rules, first match wins:

  CLOSED-ROW   status REJECTED/CLOSED: nothing can be owed on a dead role
  SELF         the flag is our own idea ("decide whether to send", "draft ready")
  NO-CONTACT   no mail from that company inside the lookback window
  BALL-OURS    the newest message in the thread is ours
  QUIET        the newest inbound mail is older than --max-age days
  KEEP         someone asked something, and the thread is still recent

A kept flag older than --warn-after days is prefixed "stale Nd: " so its age is
visible rather than buried. A dropped flag becomes a dated note, so the history
survives: the row still says what was asked and when.

    python3 tools/action_audit.py                  # report only
    python3 tools/action_audit.py --apply          # clear the flags that fail
    python3 tools/action_audit.py --apply --max-age 30
"""
import argparse
import os
import re
import sys
from datetime import date, datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import register as R                                       # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROFILE = os.environ.get("PROFILE_MD", os.path.join(ROOT, "config", "profile.md"))

# Our own initiative phrased as a task. Nobody asked, so it is a note, not an action.
SELF_FLAG = re.compile(
    r"^\s*(?:decide whether|consider whether|check whether|review \+ send the draft"
    r"|.*\(draft ready\)\s*$)", re.I)
STALE = re.compile(r"^\s*stale\s+\d+d:\s*", re.I)
EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
DEAD = {"REJECTED", "CLOSED"}


def our_address():
    """The candidate's own address, from config/profile.md, so 'us' is provable."""
    try:
        with open(PROFILE, encoding="utf-8") as fh:
            for line in fh:
                m = re.match(r"\s*-\s*email:\s*(\S+)", line, re.I)
                if m:
                    return m.group(1).strip().lower()
    except OSError:
        pass
    return ""


def strip_stale(action):
    return STALE.sub("", action or "")


def parse_date(value):
    """A timestamp from an RFC-822 header or an ISO string; None when unusable.

    Kept as a datetime even when the source only carries a date, because two
    messages on the same day (a question at 14:51 answered at 15:15) must not
    look simultaneous. Display always drops back to the day.
    """
    if not value:
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day)
    text = str(value).strip()
    try:
        return datetime.fromisoformat(text[:19]).replace(tzinfo=None)
    except ValueError:
        pass
    try:
        from email.utils import parsedate_to_datetime
        return parsedate_to_datetime(text).replace(tzinfo=None)
    except (TypeError, ValueError):
        return None


def _as_dt(value):
    if not value:
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day)
    return None


def decide(status, action, last_in, last_out, today, max_age=21, warn_after=7):
    """(keep, reason, prefix) for one flagged row. Pure: no mail, no clock."""
    act = strip_stale(action)
    status = (status or "").upper()
    if status in DEAD:
        return False, "the role is closed", ""
    if SELF_FLAG.match(act):
        return False, "our own follow-up, nobody asked", ""
    if not last_in:
        return False, "no mail from them in the window", ""
    li, lo = _as_dt(last_in), _as_dt(last_out)
    if lo and li and lo > li:
        return False, "the last message in the thread was ours", ""
    now = _as_dt(today) or datetime.combine(today, datetime.min.time())
    age = (now - li).days
    if age > max_age:
        return False, f"quiet for {age} days", ""
    return True, "", f"stale {age}d: " if age > warn_after else ""


def contacts(row):
    """Addresses we already correspond with on this role, taken from its notes."""
    me = our_address()
    blob = " ".join([row.get("notes") or "", row.get("action") or ""])
    out = []
    for raw in EMAIL.findall(blob):
        a = raw.strip(".,;:()<>[]").lower()
        if not a or a == me or a in out:
            continue
        out.append(a)
    return out[:6]


def msg_ids(row):
    """Gmail message ids quoted in the row's notes, for leads with no address."""
    return re.findall(r"\b[0-9a-f]{16}\b", row.get("notes") or "")[:4]


def query_for(row, lookback, extra=()):
    """Gmail query for this role: the addresses we know, else the company word."""
    addrs = list(dict.fromkeys(list(contacts(row)) + list(extra)))[:8]
    if addrs:
        inner = " OR ".join(addrs)
        return f"newer_than:{lookback}d (from:({inner}) OR to:({inner}))"
    try:
        import gmail_reconcile as GR
        terms = sorted(GR.terms(row.get("company") or ""), key=len, reverse=True)
    except Exception:
        terms = []
    word = terms[0] if terms else (row.get("company") or "").strip()
    return f'newer_than:{lookback}d "{word}"' if word else f"newer_than:{lookback}d"


def _headers(msg):
    return {h["name"].lower(): h["value"] for h in msg["payload"].get("headers", [])}


def thread(service, row, lookback, extra=()):
    """(last_inbound, last_outbound) timestamps for this role, from the mailbox."""
    import gmail_reconcile as GR
    me = our_address()
    last_in = last_out = None
    seen = set()

    def note(when, frm):
        nonlocal last_in, last_out
        if not when:
            return
        if me and me in (frm or "").lower():
            if not last_out or when > last_out:
                last_out = when
        elif not last_in or when > last_in:
            last_in = when

    ids = GR.list_ids(service, query_for(row, lookback, extra), max_results=40)
    picks = [m["id"] for m in ids[:40]] + msg_ids(row)
    for mid in picks:
        if mid in seen:
            continue
        seen.add(mid)
        try:
            h = _headers(GR.fetch_full(service, mid))
        except Exception:
            continue
        note(parse_date(h.get("date")), h.get("from"))
    return last_in, last_out


def audit(service, rows, apply=False, max_age=21, warn_after=7, lookback=180,
          quiet=False, only=""):
    """Check every flagged row, optionally clearing the flags that fail."""
    today = date.today()
    flagged = [r for r in rows if (r.get("action") or "").strip()]
    if only:
        flagged = [r for r in flagged if only.lower() in (r.get("key") or "").lower()
                   or only.lower() in (r.get("company") or "").lower()]
    kept, dropped = [], []
    for row in flagged:
        action = row["action"]
        # A dead row needs no mailbox: the decision is already made.
        if (row.get("status") or "").upper() in DEAD:
            keep, reason, prefix, li, lo = False, "the role is closed", "", None, None
        else:
            li, lo = thread(service, row, lookback)
            keep, reason, prefix = decide(row.get("status"), action, li, lo, today,
                                          max_age=max_age, warn_after=warn_after)
        if keep:
            wanted = prefix + strip_stale(action)
            if wanted != action and apply:
                R.set_row(row["company"], row["role"], action=wanted)
            kept.append((row, li, reason or "asked, recent", wanted))
        else:
            dropped.append((row, reason, li, lo))
    if not quiet:
        print(f"\nACTION AUDIT  {len(flagged)} flagged · {len(kept)} real · {len(dropped)} to clear\n")
        for row, li, why, wanted in kept:
            age = (today - li.date()).days if li else 0
            print(f"  KEEP  {(row.get('company') or '')[:22]:<22} {(row.get('role') or '')[:34]:<34} "
                  f"{('asked ' + li.date().isoformat()) if li else why} ({age}d)")
        for row, why, li, lo in dropped:
            print(f"  CLEAR {(row.get('company') or '')[:22]:<22} {(row.get('role') or '')[:34]:<34} {why}"
                  f"{' · last inbound ' + li.date().isoformat() if li else ''}")
        if dropped and not apply:
            print("\n(dry run - re-run with --apply to clear these)")
    if apply:
        for row, why, li, lo in dropped:
            note = (f"{today.isoformat()}: action flag removed ({why}); "
                    f"last inbound {li.date().isoformat() if li else 'none'}, "
                    f"last outbound {lo.date().isoformat() if lo else 'none'}")
            R.set_row(row["company"], row["role"], note=note, action="")
        if not quiet:
            print(f"\ncleared {len(dropped)} flag(s); register regenerated")
    return {"flagged": len(flagged), "kept": len(kept), "cleared": len(dropped)}


def main():
    ap = argparse.ArgumentParser(description="An action must be a person waiting for a reply.")
    ap.add_argument("--apply", action="store_true", help="clear the flags that fail the check")
    ap.add_argument("--max-age", type=int, default=21, help="days before a silent thread is dropped")
    ap.add_argument("--warn-after", type=int, default=7, help="days before a kept flag is marked stale")
    ap.add_argument("--lookback", type=int, default=180, help="how far back to read the mailbox")
    ap.add_argument("--key", default="", help="only this key or company")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    import gmail_readonly as G
    service = G.authenticate()
    audit(service, R.load(), apply=args.apply, max_age=args.max_age,
          warn_after=args.warn_after, lookback=args.lookback,
          quiet=args.quiet, only=args.key)


if __name__ == "__main__":
    main()
