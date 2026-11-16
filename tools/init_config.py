#!/usr/bin/env python3
"""Scaffold and check the pipeline configuration.

`config/` holds the only three files a human must fill in:
  profile.md      identity, eligibility, accuracy rules, EEO, pay
  cv.json         the CV as structured data
  archetypes.json role-family CV templates

Usage:
  python3 tools/init_config.py            # create config/*.md/json from the templates (no overwrite)
  python3 tools/init_config.py --check    # report which files exist and whether they are still placeholders
  python3 tools/init_config.py --explain  # print what each config file is for
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CFG = os.path.join(ROOT, "config")

FILES = {
    "profile.md": "profile.example.md",
    "cv.json": "cv.example.json",
    "archetypes.json": "archetypes.example.json",
}

# Written when missing, but never required: sensible defaults apply without them.
OPTIONAL = {
    "google.json": "google.example.json",
    "email.json": "email.example.json",
    "calendar.json": "calendar.example.json",
    "recruiter-aliases.json": "recruiter-aliases.example.json",
}

PLACEHOLDER_STRINGS = (
    "your name", "you@example.com", "+00 000 000 000",
    "https://linkedin.com/in/you", "https://yoursite.com", "your_",
    "your city", "your country",
    "most recent employer", "earlier employer", "example employer",
)


def _looks_placeholder(path: str) -> list[str]:
    """Return reasons the file still looks like a template (empty = looks filled in)."""
    reasons: list[str] = []
    low = ""
    try:
        low = open(path, encoding="utf-8").read().lower()
    except OSError:
        return ["unreadable"]
    for token in PLACEHOLDER_STRINGS:
        if token in low:
            reasons.append(f"contains placeholder '{token}'")
            break
    if path.endswith("cv.json"):
        try:
            data = json.load(open(path, encoding="utf-8"))
            if not data.get("experience"):
                reasons.append("cv.json has no experience entries")
        except Exception as exc:
            reasons.append(f"cv.json not valid JSON: {exc}")
    if path.endswith("archetypes.json"):
        try:
            data = json.load(open(path, encoding="utf-8"))
            if not isinstance(data, list) or not data:
                reasons.append("archetypes.json is empty")
        except Exception as exc:
            reasons.append(f"archetypes.json not valid JSON: {exc}")
    return reasons


def check() -> int:
    ok = True
    print("config check:")
    for name, example in FILES.items():
        path = os.path.join(CFG, name)
        if not os.path.exists(path):
            print(f"  MISSING   config/{name}   (run without --check to scaffold, then edit)")
            ok = False
            continue
        reasons = _looks_placeholder(path)
        if reasons:
            print(f"  PLACEHOLDER config/{name}  -> {reasons[0]}")
            ok = False
        else:
            print(f"  OK        config/{name}")
    if ok:
        print("\nconfig looks ready.")
    else:
        print("\nconfig not ready yet — have the agent run BOOTSTRAP.md (interview the user).")
    return 0 if ok else 1


def scaffold() -> int:
    os.makedirs(CFG, exist_ok=True)
    for name, example in {**FILES, **OPTIONAL}.items():
        dst = os.path.join(CFG, name)
        src = os.path.join(CFG, example)
        if os.path.exists(dst):
            print(f"  keep  config/{name} (already exists)")
            continue
        if not os.path.exists(src):
            print(f"  WARN  template {example} not found; skipped config/{name}", file=sys.stderr)
            continue
        shutil.copyfile(src, dst)
        print(f"  wrote config/{name} (from {example})")
    print("\nNext: edit config/profile.md, config/cv.json, config/archetypes.json "
          "(see BOOTSTRAP.md), then: python3 tools/build_archetypes.py\n"
          "Optional: config/google.json, config/email.json, config/calendar.json "
          "(defaults are fine; edit them in the dashboard Settings).")
    return 0


def explain() -> int:
    print(
        "config/profile.md      Your identity, work authorisation, languages, "
        "availability, pay, ELIGIBILITY rules (where you can work / what you accept) "
        "and ACCURACY rules (what must never be overstated), plus optional EEO answers.\n"
        "config/cv.json         Your CV as structured data: experience (with quantified "
        "bullets), projects, skills, education, certifications, languages, sidebar. "
        "This is the ground truth the gate checks every claim against.\n"
        "config/archetypes.json Your role-family CV templates: a headline, summary, "
        "skills and tags per family. One 2-page CV + base letter is built per entry, "
        "and the alignment gate maps each job to a family.\n"
        "config/google.json     (optional) Where your Google OAuth client lives and, if you "
        "paste a client id/secret, lets the pipeline write credentials.json for you. "
        "Editable in the dashboard under Settings -> Accounts.\n"
        "config/email.json      (optional) Sender signature, attachment folder, size cap.\n"
        "config/calendar.json   (optional) Timezone, default meeting length, working hours."
    )
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Scaffold/check the pipeline config.")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--explain", action="store_true")
    args = ap.parse_args()
    if args.explain:
        return explain()
    if args.check:
        return check()
    return scaffold()


if __name__ == "__main__":
    sys.exit(main())
