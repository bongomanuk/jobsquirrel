#!/usr/bin/env python3
"""Canonical application register.

`state/applications.csv` is the single source of truth for outcomes: one row per
(company, role). `state/applications-register.md` is GENERATED from it, so the
register can no longer drift or list the same role under two statuses.
`tools/record_submission.py` upserts here automatically after every submission.

Usage:
  python3 tools/register.py --stats
  python3 tools/register.py --list [--status SUBMITTED]
  python3 tools/register.py --show "<company>"
  python3 tools/register.py --check          # validate; exit 1 on problems
  python3 tools/register.py --render         # write state/applications-register.md
  python3 tools/register.py --set --company <Company> --role "Head of Engineering" \
      --status SUBMITTED --date 2026-10-02 --ats <ATS> --letter <path> --notes "..."
"""
import argparse
import contextlib
import csv
import fcntl
import json
import os
import re
import sys
import tempfile
from datetime import date, datetime

import jd_guard as JD

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CSV_PATH = os.environ.get("APPLICATIONS_CSV", os.path.join(ROOT, "state", "applications.csv"))
MD_PATH = os.environ.get("APPLICATIONS_MD", os.path.join(ROOT, "state", "applications-register.md"))
LOCK_PATH = CSV_PATH + ".lock"
COUNTS_PATH = os.environ.get("APPLICATIONS_COUNTS", os.path.join(ROOT, "state", "counts.md"))
QUEUE_PATH = os.environ.get("QUEUE_TSV", os.path.join(ROOT, "state", "queue.tsv"))
DONE_PATH = os.environ.get("QUEUE_DONE", os.path.join(ROOT, "state", "queue.done"))
SUBMISSIONS_PATH = os.environ.get("SUBMISSIONS_CSV", os.path.join(ROOT, "state", "submissions.csv"))
DRAFTS_DIR = os.environ.get("DRAFTS_DIR", os.path.join(ROOT, "state", "drafts"))
JD_DIR = os.environ.get("JOB_DESCRIPTIONS_DIR", os.path.join(ROOT, "state", "job-descriptions"))
FIELDS = ["date", "company", "role", "ats", "status", "letter", "notes", "employment",
          "action", "key", "apply_url"]
STATUSES = ["QUEUED", "SUBMITTED", "INTERVIEW", "OFFER", "REJECTED", "BLOCKED", "MANUAL",
            "PREPARED", "IN_PROGRESS", "CLOSED"]
# Statuses that count as a live process - an application we have sent and are
# still awaiting an outcome on (not yet rejected/closed, not merely prepared).
PROCESS_STATUSES = ["SUBMITTED", "IN_PROGRESS", "INTERVIEW", "OFFER"]
GROUP_TITLES = {
    "QUEUED": "Queued - waiting to be applied",
    "SUBMITTED": "Submitted - confirmed",
    "INTERVIEW": "Interview in progress",
    "OFFER": "Offer",
    "REJECTED": "Rejected",
    "BLOCKED": "Blocked - needs a manual step (do not auto-retry)",
    "MANUAL": "Manual / login / email",
    "PREPARED": "Prepared - letter ready, not sent",
    "IN_PROGRESS": "In progress",
    "CLOSED": "Closed - do not pursue",
}


def load():
    if not os.path.isfile(CSV_PATH):
        return []
    with open(CSV_PATH, newline="", encoding="utf-8") as fh:
        rows = [{k: (r.get(k) or "") for k in FIELDS} for r in csv.DictReader(fh)]
    for r in rows:
        if not r["key"]:
            r["key"] = make_key(r["company"], r["role"])
    return rows


def _slug(value):
    return re.sub(r"[^a-z0-9]+", "-", str(value or "").lower()).strip("-")


def make_key(company, role):
    """Stable identity for a role: used by the queue, documents and the register.

    The register used to be keyed on the raw (company, role) strings, so a rename
    ('nent' -> 'Nordic Entertainment Group') or a punctuation change silently
    produced a second, unrelated row. The key is derived from the same fields but
    normalised, so it can be compared across artifacts.
    """
    return (_slug(company) + "-" + _slug(role)).strip("-")[:80]


@contextlib.contextmanager
def locked():
    """Exclusive cross-process lock so parallel agents cannot interleave a
    read-modify-write of the register (or clobber each other's writes)."""
    os.makedirs(os.path.dirname(LOCK_PATH), exist_ok=True)
    with open(LOCK_PATH, "w") as lf:
        fcntl.flock(lf, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lf, fcntl.LOCK_UN)


def save(rows):
    os.makedirs(os.path.dirname(CSV_PATH), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(CSV_PATH), prefix=".applications.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=FIELDS)
            w.writeheader()
            for r in rows:
                w.writerow({k: r.get(k, "") for k in FIELDS})
        os.replace(tmp, CSV_PATH)  # atomic swap
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def _key(company, role):
    return (company.strip().lower(), role.strip().lower())


def find_row(company, role):
    """The single register row for this exact company+role, or None."""
    k = ((company or "").strip().lower(), (role or "").strip().lower())
    for r in load():
        if (r["company"].strip().lower(), r["role"].strip().lower()) == k:
            return r
    return None


PROFILE_ROLE = re.compile(
    r"talent network|consultant profile|consultant network|consultant hub|"
    r"aggregator of konsultuppdrag|intro meeting|"
    r"independent consultant network|consultant feed",
    re.I)


def profile_role(role):
    """A network/profile row has no job advert by nature, so it is exempt from
    the 'every live role has a job spec' rule."""
    return bool(PROFILE_ROLE.search(role or ""))


def jd_path(company, role, key=""):
    """Find the saved job description for a role, tolerating key-style drift.

    Lookup order: the exact key, the key with hyphens/underscores swapped, the
    generated company-role key, then an exact company-slug file (e.g.
    redpine.md for a role keyed redpine-senior-knowledge-graph-engineer).
    """
    def variants(k):
        k = (k or "").strip()
        if not k:
            return []
        return list(dict.fromkeys([k, k.replace("_", "-"), k.replace("-", "_")]))

    folder = JD_DIR
    for cand in variants(key) + variants(make_key(company, role)):
        for ext in (".md", ".md.gz"):
            p = os.path.join(folder, cand + ext)
            if os.path.isfile(p):
                return p
    slug = _slug(company or "")
    if slug:
        for ext in (".md", ".md.gz"):
            p = os.path.join(folder, slug + ext)
            if os.path.isfile(p):
                return p
    return ""


LIVE_JD_STATUSES = ("PREPARED", "SUBMITTED", "INTERVIEW", "IN_PROGRESS")


def _jd_guard(company, role, status):
    """A live role must have a real advert, not just a recruiter email.

    This closes the hole that let email_opportunities.py record a lead as
    PREPARED with no spec: every transition into a live state now has to point
    at a substantive saved job description. Network/profile rows are exempt
    because they have no advert by nature.
    """
    st = (status or "").upper()
    if st not in LIVE_JD_STATUSES or profile_role(role):
        return
    existing = find_row(company, role)
    if existing and (existing.get("status") or "").upper() == st:
        # Re-affirming a status is not a new claim; legacy rows keep working.
        return
    path = jd_path(company, role)
    if path and JD.has_spec_at(path):
        return
    raise ValueError(
        f"refusing {st} without a saved job spec: save the advert to "
        f"state/job-descriptions/<key>.md first (python3 tools/jd_guard.py "
        f"--fetch --key <key> --url <url>), then set {st}. A recruiter email "
        f"or a lead brief does not count.")


def provenance(company, role):
    """The submissions.csv row proving this application was sent, or None."""
    k = ((company or "").strip().lower(), (role or "").strip().lower())
    try:
        with open(SUBMISSIONS_PATH, newline="", encoding="utf-8") as fh:
            for s in csv.DictReader(fh):
                if ((s.get("company", "").strip().lower(),
                     s.get("role", "").strip().lower()) == k
                        and (s.get("status") or "").upper() == "SUBMITTED"):
                    return s
    except OSError:
        return None
    return None


def _submitted_guard(company, role, status, note=""):
    """SUBMITTED must be backed by a provenance row.

    The only exemption is a row that ALREADY carries the pre-ledger annotation
    "provenance not recorded" (written by --record-provenance-gaps), so the
    annotation cannot be used as a shortcut on a new claim.
    """
    if (status or "").upper() != "SUBMITTED":
        return
    if provenance(company, role):
        return
    existing = find_row(company, role)
    if existing and "provenance not recorded" in (existing.get("notes") or "").lower():
        return
    raise ValueError(
        "refusing SUBMITTED without a submissions.csv provenance row: send it "
        "through record_submission.py first (or annotate 'provenance not "
        "recorded' for a pre-ledger row)")


def upsert(company, role, status, day="", ats="", letter="", notes="", employment="", action=None,
           key="", apply_url=""):
    """Insert or update the single row for (company, role). Returns the row."""
    _submitted_guard(company, role, status, notes)
    _jd_guard(company, role, status)
    with locked():
        rows = load()
        k = _key(company, role)
        for r in rows:
            if _key(r["company"], r["role"]) == k:
                r["status"] = status
                if day:
                    r["date"] = day
                if ats:
                    r["ats"] = ats
                if letter:
                    r["letter"] = letter
                if notes:
                    r["notes"] = notes
                if employment:
                    r["employment"] = employment
                if action is not None:
                    r["action"] = action.strip()
                if key:
                    r["key"] = key
                if apply_url:
                    r["apply_url"] = apply_url
                save(rows)
                render(silent=True)
                return r
        r = {"date": day or date.today().isoformat(), "company": company, "role": role,
             "ats": ats, "status": status, "letter": letter, "notes": notes,
             "employment": employment, "action": (action or "").strip(),
             "key": key or make_key(company, role), "apply_url": apply_url}
        rows.append(r)
        save(rows)
        render(silent=True)
        return r


def delete(company, role):
    """Remove a row (company+role). Returns how many were removed."""
    with locked():
        rows = load()
        k = _key(company, role)
        kept = [r for r in rows if _key(r["company"], r["role"]) != k]
        removed = len(rows) - len(kept)
        if removed:
            save(kept)
            render(silent=True)
        return removed


def set_row(company, role, status="", note="", employment=None, action=None):
    """Update exactly one row (company+role): status, note, type and/or follow-up flag.

    `action=None` leaves the flag alone; `action=""` clears it.
    """
    _submitted_guard(company, role, status, note)
    _jd_guard(company, role, status)
    with locked():
        rows = load()
        k = _key(company, role)
        n = 0
        for r in rows:
            if _key(r["company"], r["role"]) == k:
                if status:
                    r["status"] = status
                if note:
                    r["notes"] = (r["notes"] + " | " if r["notes"] else "") + note
                if employment is not None:
                    r["employment"] = employment.strip()
                if action is not None:
                    r["action"] = action.strip()
                n += 1
        if n:
            save(rows)
            render(silent=True)
        return n


def log_outbound(company, role, to, subject, message_id="", when="", action=None):
    """Record an email we sent on the role: dated note + Gmail message id.

    Idempotent: a message id already present in the row's notes is not added
    again, so reconcile can safely re-scan the Sent folder. `action=None` leaves
    the follow-up flag alone; `action=""` clears it.
    """
    mid = (message_id or "").strip()
    note = f"{when or date.today().isoformat()}: email sent to {to or '(unknown recipient)'}"
    if subject:
        note += f" — {subject.strip()[:140]}"
    if mid:
        note += f" (message id {mid})"
    with locked():
        rows = load()
        k = _key(company, role)
        for r in rows:
            if _key(r["company"], r["role"]) == k:
                if mid and mid in r["notes"]:
                    return False
                r["notes"] = (r["notes"] + " | " if r["notes"] else "") + note
                if action is not None:
                    r["action"] = action.strip()
                save(rows)
                render(silent=True)
                return True
    return False


def add_note(needle, text, status=""):
    """Append a note on every row matching needle.

    A status is only applied when the needle identifies exactly ONE row. A
    company-only hint can match several roles, and flipping all of them is how
    an interview invitation for one role was once recorded against another.
    """
    needle = (needle or "").lower()
    if not needle:
        return 0
    with locked():
        rows = load()
        matched = [r for r in rows
                   if needle in r["company"].lower() or needle in r["role"].lower()]
        for r in matched:
            r["notes"] = (r["notes"] + " | " if r["notes"] else "") + text
        if status and len(matched) == 1:
            matched[0]["status"] = status
        if matched:
            save(rows)
            render(silent=True)
        return len(matched)


def stats(write=True):
    rows = load()
    counts = {s: 0 for s in STATUSES}
    for r in rows:
        counts[r["status"] if r["status"] in counts else "CLOSED"] += 1
    lines = [f"total: {len(rows)}"]
    for s in STATUSES:
        if counts[s]:
            lines.append(f"  {s:<12} {counts[s]}")
    in_process = sum(counts[s] for s in PROCESS_STATUSES)
    breakdown = " + ".join(f"{s} {counts[s]}" for s in PROCESS_STATUSES)
    lines.append(f"  {'-' * 17}")
    lines.append(f"  IN PROCESS   {in_process}  ({breakdown})")
    actions = sum(1 for r in rows if (r.get("action") or "").strip())
    if actions:
        lines.append(f"  ACTION       {actions}  (needs a reply / follow-up)")
    body = "\n".join(lines)
    print(body)
    if write:
        # counts.md is written by the same command that prints the counts, so it
        # cannot drift from the register. The reconcile loop used to be the only
        # writer, so a reconcile that did not finish left it stale (it reported
        # 855 rows while the register held 931).
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        out = (f"# Application counts\n\n_Updated: {ts} - source: register.py --stats_\n\n"
               f"```\n{body}\n```\n")
        tmp = COUNTS_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(out)
        os.replace(tmp, COUNTS_PATH)
    return rows


def listing(status=""):
    rows = load()
    if status:
        rows = [r for r in rows if r["status"].upper() == status.upper()]
    rows.sort(key=lambda r: (STATUSES.index(r["status"]) if r["status"] in STATUSES else 99,
                             r["company"].lower(), r["role"].lower()))
    for r in rows:
        print(f"{r['status']:<11} {r['date']:<10} {r['company']:<28} {r['role']}")
    print(f"({len(rows)} rows)")


def show(needle):
    needle = needle.lower()
    hits = [r for r in load() if needle in r["company"].lower() or needle in r["role"].lower()]
    for r in hits:
        print(f"{r['status']:<11} {r['date']:<10} {r['company']} — {r['role']}")
        if r["letter"]:
            print(f"            letter: {r['letter']}")
        if r["action"]:
            print(f"            ACTION: {r['action']}")
        if r["notes"]:
            print(f"            notes:  {r['notes']}")
    print(f"({len(hits)} matches)")


def check():
    rows = load()
    problems = []
    seen = {}
    for i, r in enumerate(rows, start=2):
        if not r["company"].strip() or not r["role"].strip():
            problems.append(f"row {i}: missing company or role")
        if r["status"] not in STATUSES:
            problems.append(f"row {i}: invalid status {r['status']!r} (allowed: {', '.join(STATUSES)})")
        k = _key(r["company"], r["role"])
        if k in seen:
            problems.append(f"row {i}: duplicate of row {seen[k]} -> {r['company']} / {r['role']}")
        else:
            seen[k] = i
    for p in problems:
        print("FAIL", p)
    print(f"{len(rows)} rows, {len(problems)} problems")
    return 1 if problems else 0


def _read_queue():
    rows = []
    try:
        with open(QUEUE_PATH, encoding="utf-8") as fh:
            for line in fh:
                if not line.strip() or line.startswith("#"):
                    continue
                parts = line.rstrip("\n").split("\t")
                while len(parts) < 6:
                    parts.append("")
                rows.append({"company": parts[0].strip(), "role": parts[1].strip(),
                             "url": parts[2].strip(), "key": parts[5].strip()})
    except OSError:
        pass
    return rows


def backfill():
    """Fill `key` / `apply_url` from the queue, then from the row itself."""
    q = _read_queue()
    exact = {(x["company"].lower(), x["role"].lower()): x for x in q}
    loose = {make_key(x["company"], x["role"]): x for x in q}
    with locked():
        rows = load()
        filled_key = filled_url = 0
        seen = {}
        for r in rows:
            ref = exact.get((r["company"].strip().lower(), r["role"].strip().lower()))
            if ref is None:
                ref = loose.get(make_key(r["company"], r["role"]))
            if ref:
                if ref["key"] and r.get("key") != ref["key"]:
                    r["key"] = ref["key"]
                    filled_key += 1
                if ref["url"] and not r.get("apply_url"):
                    r["apply_url"] = ref["url"]
                    filled_url += 1
            if not r.get("key"):
                r["key"] = make_key(r["company"], r["role"])
                filled_key += 1
            base = r["key"]
            n = 2
            while r["key"] in seen:
                r["key"] = f"{base}-{n}"
                n += 1
            seen[r["key"]] = True
        save(rows)
        render(silent=True)
    print(f"backfill: {filled_key} key(s), {filled_url} apply_url(s) set; {len(rows)} rows")


def audit():
    """Report every place where 'what was handled' is uncertain. Read-only."""
    rows = load()
    problems = []
    seen_pairs, seen_keys = {}, {}
    for i, r in enumerate(rows, start=2):
        p = make_key(r["company"], r["role"])
        if p in seen_pairs:
            problems.append(f"duplicate row {i} of row {seen_pairs[p]}: {r['company']} / {r['role']}")
        else:
            seen_pairs[p] = i
        if r["key"] in seen_keys and r["key"]:
            problems.append(f"duplicate key {r['key']!r} on rows {seen_keys[r['key']]} and {i}")
        seen_keys[r["key"]] = i

    reg_pairs = {_key(r["company"], r["role"]) for r in rows}
    reg_keys = {r["key"] for r in rows if r["key"]}
    by_role = {}
    for r in rows:
        by_role.setdefault(_slug(r["role"]), set()).add(r["key"])

    q = _read_queue()
    qinfo = {x["key"]: (x["company"], x["role"]) for x in q}
    q_keys = {}
    for x in q:
        q_keys[x["key"]] = q_keys.get(x["key"], 0) + 1
    for k, n in q_keys.items():
        if n > 1:
            problems.append(f"queue key {k!r} appears {n} times")
    pending = [x for x in q if x["key"] not in reg_keys
               and make_key(x["company"], x["role"]) not in reg_keys
               and _key(x["company"], x["role"]) not in reg_pairs]

    try:
        with open(DONE_PATH, encoding="utf-8") as fh:
            done = [l.strip() for l in fh if l.strip()]
    except OSError:
        done = []

    done_key = {}
    for x in q:
        done_key[f"{x['company']}|{x['role']}"] = x["key"]
        done_key[f"{x['company']}|{x['role']}".lower()] = x["key"]

    def done_known(d):
        if d in reg_keys:
            return True
        info = qinfo.get(d)
        if info:
            co, ro = info
            if _key(co, ro) in reg_pairs or make_key(co, ro) in reg_keys:
                return True
            same = by_role.get(_slug(ro))
            if same and len(same) == 1:
                return True
        return False

    for d in done:
        if "|" in d:
            mapped = done_key.get(d) or done_key.get(d.lower())
            if mapped and (mapped in reg_keys or done_known(mapped)):
                continue
            a, b = d.split("|", 1)
            if done_known(d) or _key(a, b) in reg_pairs or make_key(a, b) in reg_keys:
                continue
            same = by_role.get(_slug(b))
            if same and len(same) == 1:
                continue
            problems.append(f"queue.done entry not in register: {d}")
        elif not done_known(d):
            problems.append(f"queue.done key not in register: {d}")

    prov = set()
    try:
        with open(SUBMISSIONS_PATH, newline="", encoding="utf-8") as fh:
            for s in csv.DictReader(fh):
                prov.add((s.get("company", "").strip().lower(), s.get("role", "").strip().lower()))
    except OSError:
        pass
    for r in rows:
        if r["status"] == "SUBMITTED" and (r["company"].strip().lower(), r["role"].strip().lower()) not in prov:
            if "provenance not recorded" in (r.get("notes") or ""):
                continue
            problems.append(f"SUBMITTED without provenance: {r['company']} / {r['role']}")

    # --- evidence checks (audit v2): catch a status that contradicts the mail ---
    def _draft_meta(path):
        try:
            with open(path, encoding="utf-8") as fh:
                head = fh.read(4000).split("---", 1)[0]
        except OSError:
            return {}
        meta = {}
        for line in head.splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                meta[k.strip().lower()] = v.strip()
        return meta

    def _row_for(company, role):
        k = ((company or "").strip().lower(), (role or "").strip().lower())
        for r in rows:
            if (r["company"].strip().lower(), r["role"].strip().lower()) == k:
                return r
        return None

    # A draft that was sent with attachments is an application, so the row
    # cannot still be PREPARED.
    sent_file = os.path.join(DRAFTS_DIR, "sent.json")
    try:
        with open(sent_file, encoding="utf-8") as fh:
            sent_drafts = json.load(fh)
    except (OSError, ValueError):
        sent_drafts = {}
    for path in sent_drafts:
        meta = _draft_meta(path)
        if not meta or not meta.get("attachment"):
            continue
        row = _row_for(meta.get("company", ""), meta.get("role", ""))
        if row and row["status"] == "PREPARED":
            problems.append(
                f"PREPARED but an application email with attachments was sent: "
                f"{row['company']} / {row['role']} ({os.path.basename(path)})")

    # Backstop for older notes (draft files may have been removed).
    for r in rows:
        if r["status"] != "PREPARED":
            continue
        n = (r.get("notes") or "").lower()
        if "email sent" in n and ("attach" in n or " cv" in n or "letter" in n):
            problems.append(f"PREPARED but the notes record a sent application email: "
                            f"{r['company']} / {r['role']}")

    # An INTERVIEW row must name the invitation that produced it.
    for r in rows:
        if r["status"] != "INTERVIEW":
            continue
        n = (r.get("notes") or "").lower()
        if any(k in n for k in ("gmail: interview", "interview", "invited",
                                "invitation", "booked", "scheduled", "held",
                                "first call", "video call", "first chat")):
            continue
        problems.append(f"INTERVIEW without an invitation in the notes: "
                        f"{r['company']} / {r['role']}")

    # Every live role must have its advert saved; a profile/network row has none
    # by nature, and historical rows may carry the pre-guard annotation.
    for r in rows:
        if r["status"] not in ("QUEUED", "PREPARED", "SUBMITTED", "INTERVIEW", "IN_PROGRESS"):
            continue
        saved = jd_path(r["company"], r["role"], r["key"])
        if profile_role(r["role"]) or (saved and JD.has_spec_at(saved)):
            continue
        if "jd not recorded" in (r.get("notes") or "").lower():
            continue
        problems.append(f"live role without a saved job description: "
                        f"{r['company']} / {r['role']}")

    # A finished queue row that is really the same role as a register row must
    # not exist under a second identity (the stale-alias / phantom-row bug).
    def _token(name):
        t = re.sub(r"\bstarting at\b.*$", "", (name or "").lower())
        t = re.sub(r"[^a-z0-9 ]+", " ", t)
        words = [w for w in t.split() if w not in ("the", "ab", "inc", "ltd", "group")]
        return words[0] if words else ""

    done_set = set(done)
    reg_identities = {(r["role"].strip().lower(), _token(r["company"])) for r in rows}
    for x in q:
        if x["key"] in reg_keys or _key(x["company"], x["role"]) in reg_pairs:
            continue
        finished = (x["key"] in done_set
                    or f"{x['company']}|{x['role']}" in done_set)
        if finished and (x["role"].strip().lower(), _token(x["company"])) in reg_identities:
            problems.append(
                f"queue alias of a register row (finished twice): "
                f"{x['company']} / {x['role']} (key {x['key']})")

    try:
        with open(COUNTS_PATH, encoding="utf-8") as fh:
            m = re.search(r"total:\s*(\d+)", fh.read())
        if m and int(m.group(1)) != len(rows):
            problems.append(f"counts.md stale: says {m.group(1)}, register has {len(rows)}")
    except OSError:
        problems.append("counts.md missing")

    for p in problems:
        print("FAIL", p)
    print(f"{len(rows)} register rows, {len(q)} queue rows ({len(pending)} pending), "
          f"{len(done)} done entries, {len(problems)} problem(s)")
    return 1 if problems else 0


def dedupe(dry=False):
    """Merge rows that are the same role twice (normally a duplicate-guard row)."""
    admin = re.compile(r"duplicate of existing|skipped .*duplicate", re.I)
    rank = {st: i for i, st in enumerate(
        ["OFFER", "INTERVIEW", "REJECTED", "SUBMITTED", "IN_PROGRESS", "PREPARED",
         "MANUAL", "BLOCKED", "CLOSED"])}
    with locked():
        rows = load()
        groups = {}
        for r in rows:
            groups.setdefault(make_key(r["company"], r["role"]), []).append(r)
        merged, out = 0, []
        for group in groups.values():
            if len(group) == 1:
                out.append(group[0])
                continue
            real = [r for r in group if not admin.search(r.get("notes") or "")]
            pool = real or group
            pool.sort(key=lambda r: (r["date"], -rank.get(r["status"], 99)), reverse=True)
            keep = pool[0]
            dropped = [r for r in group if r is not keep]
            note = "audit: merged duplicate row(s) " + ", ".join(
                f"{r['status']} ({r['date']})" for r in dropped)
            keep["notes"] = (keep["notes"] + " | " if keep["notes"] else "") + note
            for r in dropped:
                if r.get("letter") and not keep.get("letter"):
                    keep["letter"] = r["letter"]
                if r.get("apply_url") and not keep.get("apply_url"):
                    keep["apply_url"] = r["apply_url"]
            out.append(keep)
            merged += len(dropped)
            print(f"merge {len(dropped)} row(s) into {keep['status']}: {keep['company']} / {keep['role']}")
        if merged and not dry:
            save(out)
            render(silent=True)
    print(f"dedupe: {merged} row(s) merged" + (" (dry run)" if dry else ""))
    return merged


def backfill_done():
    """Record queue.done entries that have no register row as MANUAL.

    queue.done means a runner handled the role; without a register row the
    outcome was never recorded. MANUAL + an explicit action makes the uncertainty
    visible and countable instead of silently lost.
    """
    rows = load()
    pairs = {_key(r["company"], r["role"]) for r in rows}
    keys = {r["key"] for r in rows if r["key"]}
    by_role = {}
    for r in rows:
        by_role.setdefault(_slug(r["role"]), set()).add(r["key"])
    q = _read_queue()
    qinfo = {x["key"]: (x["company"], x["role"]) for x in q}
    qpairs = {f"{x['company']}|{x['role']}": (x["company"], x["role"]) for x in q}
    try:
        with open(DONE_PATH, encoding="utf-8") as fh:
            done = [l.strip() for l in fh if l.strip()]
    except OSError:
        done = []
    created = 0
    for d in done:
        if "|" in d:
            company, role = qpairs.get(d, (None, None))
            if not company:
                company, role = (x.strip() for x in d.split("|", 1))
        else:
            company, role = qinfo.get(d, ("", ""))
            if not company:
                continue
        if _key(company, role) in pairs or make_key(company, role) in keys:
            continue
        same = by_role.get(_slug(role))
        if same and len(same) == 1:
            continue
        upsert(company, role, "MANUAL",
               notes=f"audit {date.today().isoformat()}: queue.done entry with no register record; outcome unknown",
               action="verify outcome: queue.done has no register record (check Gmail)")
        keys.add(make_key(company, role))
        pairs.add(_key(company, role))
        created += 1
    print(f"backfill-done: {created} MANUAL row(s) created")
    return created


def record_provenance_gaps():
    """Annotate SUBMITTED rows that have no state/submissions.csv entry."""
    rows = load()
    prov = set()
    try:
        with open(SUBMISSIONS_PATH, newline="", encoding="utf-8") as fh:
            for s in csv.DictReader(fh):
                prov.add((s.get("company", "").strip().lower(), s.get("role", "").strip().lower()))
    except OSError:
        pass
    marked = 0
    for r in rows:
        if r["status"] != "SUBMITTED":
            continue
        if (r["company"].strip().lower(), r["role"].strip().lower()) in prov:
            continue
        if "provenance not recorded" in (r.get("notes") or ""):
            continue
        set_row(r["company"], r["role"],
                note=f"{date.today().isoformat()} audit: provenance not recorded (applied before submissions.csv logging)")
        marked += 1
    print(f"record-provenance-gaps: {marked} row(s) annotated")
    return marked


def render(silent=False):
    rows = load()
    lines = [
        "# Applications register - single source of truth",
        "",
        "GENERATED FILE. Do not edit by hand. Edit `state/applications.csv` (or run",
        "`tools/register.py --set ...`); `tools/record_submission.py` upserts it on every",
        "submission. Regenerate with `python3 tools/register.py --render`.",
        "",
        "Statuses: SUBMITTED | BLOCKED | MANUAL | PREPARED | IN_PROGRESS | CLOSED.",
        "Documents sent are recorded in `state/submissions.csv`.",
        "",
    ]
    for status in STATUSES:
        group = [r for r in rows if r["status"] == status]
        if not group:
            continue
        group.sort(key=lambda r: (r["date"], r["company"].lower(), r["role"].lower()))
        lines.append(f"## {GROUP_TITLES[status]} ({len(group)})")
        lines.append("")
        lines.append("| Date | Company | Role | Type | ATS | Action | Notes |")
        lines.append("|---|---|---|---|---|---|---|")
        for r in group:
            note = r["notes"]
            if r["letter"]:
                note = (note + " " if note else "") + f"letter: `{r['letter']}`"
            action = (r.get("action") or "").replace("|", "·")
            note = note.replace("|", "·").replace("\n", " ")
            lines.append(f"| {r['date']} | {r['company']} | {r['role']} | {r.get('employment','')} | {r['ats']} | {action} | {note} |")
        lines.append("")
    with open(MD_PATH, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))
    if not silent:
        print(f"wrote {os.path.relpath(MD_PATH, ROOT)} ({len(rows)} rows)")


def main():
    ap = argparse.ArgumentParser(description="Canonical application register.")
    ap.add_argument("--stats", action="store_true")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--status", default="")
    ap.add_argument("--show", default="")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--audit", action="store_true", help="report every uncertain/unrecorded role (read-only)")
    ap.add_argument("--backfill", action="store_true", help="fill key/apply_url from the queue")
    ap.add_argument("--dedupe", action="store_true", help="merge duplicate (company, role) rows")
    ap.add_argument("--backfill-done", action="store_true",
                    help="record queue.done entries missing from the register as MANUAL")
    ap.add_argument("--record-provenance-gaps", action="store_true",
                    help="annotate SUBMITTED rows that have no submissions.csv entry")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--render", action="store_true")
    ap.add_argument("--set", action="store_true")
    ap.add_argument("--delete", action="store_true")
    ap.add_argument("--company", default="")
    ap.add_argument("--role", default="")
    ap.add_argument("--date", default="")
    ap.add_argument("--ats", default="")
    ap.add_argument("--letter", default="")
    ap.add_argument("--notes", default="")
    ap.add_argument("--employment", default="",
                    help="engagement type: full-time | part-time | contract | consultant | freelance | internship | temporary")
    ap.add_argument("--action", default=None,
                    help="follow-up needed (e.g. 'reply to the recruiter about the interview'); empty string clears it")
    args = ap.parse_args()

    # --company/--role/--notes only mean something with --set or --delete. Without
    # them, `--company X --status BLOCKED` used to fall through to the listing
    # and record nothing, silently, so refuse instead.
    if (args.company or args.role or args.notes or args.action) and not (args.set or args.delete):
        ap.error("--company/--role/--notes/--action need --set (to record a row) or --delete")

    if args.delete:
        if not args.company or not args.role:
            ap.error("--delete requires --company and --role")
        n = delete(args.company, args.role)
        print(f"deleted {n} row(s): {args.company} — {args.role}")
    elif args.set:
        if not args.company or not args.role or not args.status:
            ap.error("--set requires --company, --role and --status")
        try:
            row = upsert(args.company, args.role, args.status.upper(), args.date, args.ats,
                         args.letter, args.notes, args.employment, args.action)
        except ValueError as exc:
            print(f"refused: {exc}", file=sys.stderr)
            sys.exit(1)
        print(f"set {row['status']}: {row['company']} — {row['role']}")
    elif args.stats:
        stats()
    elif args.list or args.status:
        listing(args.status)
    elif args.show:
        show(args.show)
    elif args.check:
        sys.exit(check())
    elif args.audit:
        sys.exit(audit())
    elif args.backfill:
        backfill()
    elif args.dedupe:
        dedupe(dry=args.dry_run)
    elif args.backfill_done:
        backfill_done()
    elif args.record_provenance_gaps:
        record_provenance_gaps()
    elif args.render:
        render()
    else:
        ap.print_help()


if __name__ == "__main__":
    main()
