#!/usr/bin/env python3
"""Print the standard identity answers for filling any signup/application form.

Reads config/profile.md (falling back to config/profile.example.md) — the single
source of truth for identity, eligibility and standard answers — and emits the
fields an agent needs, so any platform's form is filled consistently. No
third-party deps.

  python3 tools/identity.py            # human-readable
  python3 tools/identity.py --json     # machine-readable (for agents)
"""
import argparse
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_DIR = os.path.join(ROOT, "config")


def config_path(name, ext):
    """config/<name>.<ext> if present, else config/<name>.example.<ext>."""
    for fn in (f"{name}.{ext}", f"{name}.example.{ext}"):
        p = os.path.join(CONFIG_DIR, fn)
        if os.path.isfile(p):
            return p
    return ""


def parse():
    """Parse the "- key: value" lines of the profile into a dict."""
    data = {}
    path = config_path("profile", "md")
    if not path:
        return data
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line.startswith("- ") and ":" in line:
                key, value = line[2:].split(":", 1)
                value = value.strip()
                if value:
                    data[key.strip().lower()] = value
    return data


def main():
    ap = argparse.ArgumentParser(description="Standard identity answers for forms.")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    data = parse()
    if args.json:
        print(json.dumps(data, indent=2))
    else:
        for key in sorted(data):
            print(f"{key}: {data[key]}")


if __name__ == "__main__":
    main()
