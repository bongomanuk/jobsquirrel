#!/usr/bin/env python3
"""Record exactly which documents were uploaded for one application.

This is the provenance ledger. It appends one row to state/submissions.csv with
the exact file paths and their sha256, and (unless --inferred) copies the files
into documents/submitted/<date>_<company>_<role>/ so the exact bytes are kept.

Why: the tracker records a CV *archetype name*, not the file that was actually
uploaded, and letters were sometimes only referenced as a draft file. That means
"what did we send to <company>?" was unanswerable. This fixes it.

Usage:
  python3 tools/record_submission.py \
    --company <Company> --role "Senior Engineer" --ats <ATS> \
    --url https://jobs.example.com/<company>/<id> \
    --cv documents/archetypes/YOUR_CV.docx \
    --letter documents/applications/Motivation_<Company>_<Role>.docx \
    --status SUBMITTED --evidence 'Confirmed "Success"'

Backfill an old row (no snapshot, marked inferred):
  python3 tools/record_submission.py ... --inferred

Query:
  python3 tools/record_submission.py --show <Company>
"""
import argparse
import csv
import hashlib
import os
import shutil
import sys
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LEDGER = os.environ.get("SUBMISSIONS_CSV", os.path.join(ROOT, "state", "submissions.csv"))
SNAPSHOT_DIR = os.environ.get("SUBMISSIONS_DIR", os.path.join(ROOT, "documents", "submitted"))

FIELDS = [
    "date", "company", "role", "ats", "apply_url", "status", "confidence",
    "cv_file", "cv_sha256", "letter_file", "letter_sha256",
    "evidence", "snapshot_dir", "recorded_at",
]


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def slugify(text):
    out = []
    for ch in text.lower():
        if ch.isalnum():
            out.append(ch)
        elif out and out[-1] != "-":
            out.append("-")
    return "".join(out).strip("-")[:80]


def resolve(path):
    if not path:
        return ""
    return path if os.path.isabs(path) else os.path.join(ROOT, path)


def rel(path):
    if path and path.startswith(ROOT + os.sep):
        return os.path.relpath(path, ROOT)
    return path


def show(needle):
    if not os.path.isfile(LEDGER):
        print("no ledger yet:", rel(LEDGER))
        return
    needle = needle.lower()
    with open(LEDGER, newline="") as fh:
        rows = list(csv.DictReader(fh))
    hits = [r for r in rows if needle in r["company"].lower() or needle in r["role"].lower()]
    if not hits:
        print("no submissions match", repr(needle))
        return
    for r in hits:
        print(f"{r['date']}  {r['company']} — {r['role']}  [{r['status']}, {r['confidence']}]")
        print(f"    CV:     {r['cv_file'] or '(none)'}  {r['cv_sha256'][:12]}")
        print(f"    letter: {r['letter_file'] or '(none)'}  {r['letter_sha256'][:12]}")
        if r["snapshot_dir"]:
            print(f"    snapshot: {r['snapshot_dir']}")
        if r["evidence"]:
            print(f"    evidence: {r['evidence']}")


def verify(needle):
    """Check that the live files and the snapshots still match the recorded hashes."""
    if not os.path.isfile(LEDGER):
        print("no ledger yet:", rel(LEDGER))
        return 1
    needle = needle.lower()
    with open(LEDGER, newline="") as fh:
        rows = list(csv.DictReader(fh))
    hits = [r for r in rows if needle in r["company"].lower() or needle in r["role"].lower()]
    if not hits:
        print("no submissions match", repr(needle))
        return 1
    bad = 0
    for r in hits:
        print(f"{r['date']}  {r['company']} — {r['role']}")
        for kind in ("cv", "letter"):
            recorded = r[f"{kind}_sha256"]
            if not recorded:
                print(f"    {kind}: (not recorded)")
                continue
            live_path = resolve(r[f"{kind}_file"])
            live = sha256(live_path) if os.path.isfile(live_path) else None
            snap_path = os.path.join(ROOT, r["snapshot_dir"], kind + ".docx") if r["snapshot_dir"] else ""
            snap = sha256(snap_path) if snap_path and os.path.isfile(snap_path) else None
            live_ok = "match" if live == recorded else ("DRIFT" if live else "missing")
            snap_ok = "match" if snap == recorded else ("DRIFT" if snap else "none")
            if live != recorded and snap != recorded:
                bad += 1
            print(f"    {kind}: live={live_ok} snapshot={snap_ok} recorded={recorded[:12]}")
    return 0 if bad == 0 else 1


def main():
    ap = argparse.ArgumentParser(description="Record the exact documents uploaded for an application.")
    ap.add_argument("--company")
    ap.add_argument("--role", default="")
    ap.add_argument("--ats", default="")
    ap.add_argument("--url", default="")
    ap.add_argument("--cv", default="", help="path to the CV docx actually uploaded")
    ap.add_argument("--letter", default="", help="path to the cover letter docx uploaded (empty if pasted inline or none)")
    ap.add_argument("--status", default="", help="SUBMITTED | BLOCKED | LOGIN | CLOSED | ...")
    ap.add_argument("--evidence", default="", help="confirmation text/URL proving the submission")
    ap.add_argument("--date", default="", help="YYYY-MM-DD (defaults to today)")
    ap.add_argument("--inferred", action="store_true", help="backfilled row: do not snapshot; mark confidence=inferred")
    ap.add_argument("--force", action="store_true",
                    help="record SUBMITTED even with placeholder/empty evidence (not recommended)")
    ap.add_argument("--show", metavar="COMPANY", help="print recorded submissions matching COMPANY and exit")
    ap.add_argument("--verify", metavar="COMPANY", help="check live files/snapshots against recorded hashes and exit")
    args = ap.parse_args()

    if args.show:
        show(args.show)
        return
    if args.verify:
        sys.exit(verify(args.verify))
    if not args.company or not args.status:
        ap.error("--company and --status are required (or use --show/--verify)")

    # Never let an application be marked SUBMITTED on a placeholder: the whole
    # point is that a SUBMITTED row carries the confirmation that proves it.
    PLACEHOLDERS = {"", "confirmed", "confirm", "ok", "okay", "yes", "y", "done",
                    "submitted", "n/a", "na", "none", "true", "success", "successful",
                    "application submitted", "thank you", "thanks"}
    if args.status.upper() == "SUBMITTED" and not args.force:
        ev = (args.evidence or "").strip().lower()
        if ev in PLACEHOLDERS or len(ev) < 8:
            print("ERROR: refusing to record SUBMITTED without real confirmation evidence.", file=sys.stderr)
            print("       --evidence must be the exact thank-you text/URL or the confirmation email.", file=sys.stderr)
            print("       For 'submitted but awaiting email verification' use --status BLOCKED instead.", file=sys.stderr)
            print("       (override only if you truly have confirmation: --force)", file=sys.stderr)
            sys.exit(2)

    date = args.date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    recorded_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    cv = resolve(args.cv)
    letter = resolve(args.letter)
    cv_hash = sha256(cv) if cv and os.path.isfile(cv) else ""
    letter_hash = sha256(letter) if letter and os.path.isfile(letter) else ""

    snapshot = ""
    confidence = "inferred" if args.inferred else "verified"
    if not args.inferred and (cv or letter):
        name = f"{date}_{slugify(args.company)}_{slugify(args.role)}"
        dest = os.path.join(SNAPSHOT_DIR, name)
        os.makedirs(dest, exist_ok=True)
        if cv:
            shutil.copy2(cv, os.path.join(dest, "cv.docx"))
        if letter:
            shutil.copy2(letter, os.path.join(dest, "letter.docx"))
        snapshot = rel(dest)
    elif not args.inferred and not cv and not letter:
        print("warning: no --cv/--letter given; recording paths only", file=sys.stderr)

    row = {
        "date": date,
        "company": args.company,
        "role": args.role,
        "ats": args.ats,
        "apply_url": args.url,
        "status": args.status,
        "confidence": confidence,
        "cv_file": rel(cv),
        "cv_sha256": cv_hash,
        "letter_file": rel(letter),
        "letter_sha256": letter_hash,
        "evidence": args.evidence,
        "snapshot_dir": snapshot,
        "recorded_at": recorded_at,
    }

    os.makedirs(os.path.dirname(LEDGER), exist_ok=True)
    new = (not os.path.isfile(LEDGER)) or os.path.getsize(LEDGER) == 0
    with open(LEDGER, "a", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=FIELDS)
        if new:
            writer.writeheader()
        writer.writerow(row)

    # Keep the canonical register in sync (one row per company+role).
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import register as REG
        REG.upsert(args.company, args.role or "-", args.status.upper(), date,
                   args.ats, row["letter_file"], args.evidence)
    except Exception as exc:  # never fail the record because of the register
        print(f"warning: could not update register: {exc}", file=sys.stderr)

    print(f"recorded {args.company} / {args.role or '-'} [{args.status}, {confidence}]")
    print(f"  cv:     {row['cv_file'] or '(none)'}  {cv_hash[:12]}")
    print(f"  letter: {row['letter_file'] or '(none)'}  {letter_hash[:12]}")
    if snapshot:
        print(f"  snapshot: {snapshot}")


if __name__ == "__main__":
    main()
