#!/usr/bin/env python3
"""Refuse to commit anything private to the public build.

This repository is a separate clone of the public upstream. Private material
lives in the pipeline clone (``state/``, ``kb/sources/``, the stealth browser,
the LinkedIn runner) and must never be copied here by hand.

Two checks run over the staged files:

  paths     files that exist only in the private clone, by name
  terms     literal strings from the operator's private vocabulary: the
            candidate's name, contact details, personal sites and the employers
            in the live register

The terms are read from ``~/.config/job-search/github-private-terms.txt``, which
lives outside both repositories, so the deny-list itself is never committed.
Without that file the path check still runs.

    python3 tools/private_guard.py --staged
    python3 tools/private_guard.py --range origin/main..HEAD
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TERMS = Path(os.environ.get("PRIVATE_TERMS_FILE")
             or Path.home() / ".config" / "job-search" / "github-private-terms.txt")

# Present only in the private clone. See local/MANIFEST.txt there.
DENY_PATHS = (
    "state/",
    "answers/",
    "_archive/",
    "kb/sources/",
    "local/",
    "unhinged/",
    "tools/camoufox_server.py",
    "tools/run_linkedin.sh",
    "tools/gmail_delete.py",
    "tools/gmail_calendar_auth.py",
    "state/pipeline-parallel.md",
    "state/pipeline.md",
)

BINARY = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".pdf", ".zip", ".gz",
          ".woff", ".woff2", ".ttf", ".otf", ".docx", ".xlsx", ".parquet", ".lance")


def git(*args: str) -> str:
    r = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True)
    return r.stdout


def staged_files() -> list[str]:
    out = git("diff", "--cached", "--name-only", "--diff-filter=ACMR")
    return [l for l in out.splitlines() if l.strip()]


def range_files(spec: str) -> list[str]:
    out = git("diff", "--name-only", "--diff-filter=ACMR", spec)
    return [l for l in out.splitlines() if l.strip()]


def content(path: str, index: bool, tip: str = "") -> str:
    try:
        if index:
            return git("show", f":{path}")
        if tip:
            return git("show", f"{tip}:{path}")
        return (ROOT / path).read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""


def load_terms() -> list[str]:
    try:
        lines = TERMS.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    terms = []
    for line in lines:
        t = line.strip()
        if not t or t.startswith("#") or len(t) < 3:
            continue
        terms.append(t)
    return terms


def mask(term: str) -> str:
    if len(term) <= 4:
        return term[:1] + "…"
    return f"{term[:2]}…{term[-2:]} ({len(term)} chars)"


def main() -> int:
    ap = argparse.ArgumentParser(description="Block private material from the public build.")
    ap.add_argument("--staged", action="store_true", help="check the git index (pre-commit)")
    ap.add_argument("--range", default="", help="check a commit range, e.g. origin/main..HEAD")
    args = ap.parse_args()

    spec = args.range or "HEAD~1..HEAD"
    files = staged_files() if args.staged else range_files(spec)
    tip = spec.split("..")[-1].strip() if ".." in spec else "HEAD"
    if not files:
        return 0

    problems: list[str] = []
    for f in files:
        if any(f == p or f.startswith(p) for p in DENY_PATHS):
            problems.append(f"  {f}: lives only in the private clone")

    terms = load_terms()
    if terms:
        low = [(t, t.lower()) for t in terms]
        for f in files:
            if f.lower().endswith(BINARY):
                continue
            body = content(f, index=args.staged, tip=tip)
            if not body:
                continue
            for n, line in enumerate(body.splitlines(), 1):
                lowline = line.lower()
                for term, tlow in low:
                    if tlow in lowline:
                        problems.append(f"  {f}:{n}: contains private term {mask(term)}")
                        break

    if problems:
        print("private_guard: this would publish private material", file=sys.stderr)
        for p in problems[:30]:
            print(p, file=sys.stderr)
        if len(problems) > 30:
            print(f"  … and {len(problems) - 30} more", file=sys.stderr)
        print("\nRemove it, or if it is a false positive, adjust "
              "~/.config/job-search/github-private-terms.txt.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
