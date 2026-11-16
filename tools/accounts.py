#!/usr/bin/env python3
"""Generic per-site account credentials for the pipeline.

Platform-agnostic: keyed by the site's host, so it works for whatever platform an
agent lands on (Workday tenant, SuccessFactors, Ashby, a company's own careers
site, ...). Stored in the central secrets store (tools/secrets_store.py), which
lives outside the repo at ~/.config/job-search/secrets.json (0600).

Usage:
  # ask for credentials for a site; creates a strong password if none exists
  python3 tools/accounts.py --for https://tenant.wd3.myworkdayjobs.com/...
  python3 tools/accounts.py --for jobs.example.com

  python3 tools/accounts.py --add tenant_key              # explicit key
  python3 tools/accounts.py --get tenant.wd3.myworkdayjobs.com
  python3 tools/accounts.py --list
  python3 tools/accounts.py --random
"""
import argparse
import json
import os
import secrets
import string
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import secrets_store as SS  # noqa: E402  central 0600 store, outside the repo
from datetime import date
from urllib.parse import urlparse

PATH = os.environ.get("ACCOUNTS_FILE", os.path.expanduser("~/.config/job-search/accounts.json"))
DEFAULT_EMAIL = os.environ.get("ACCOUNTS_EMAIL", "")
ALPHABET = string.ascii_letters + string.digits + "!@#$%^&*-_=+"


def load():
    """Per-site logins from the central store (legacy file fallback on first run)."""
    data = SS.section("accounts")
    if data:
        return data
    if os.path.isfile(PATH):          # not migrated yet
        try:
            with open(PATH, encoding="utf-8") as fh:
                legacy = json.load(fh)
            if isinstance(legacy, dict):
                return legacy
        except (OSError, ValueError):
            pass
    return {}


def save(data):
    SS.set_section("accounts", data)


def gen_password(n=20):
    while True:
        pw = "".join(secrets.choice(ALPHABET) for _ in range(n))
        if (any(c.islower() for c in pw) and any(c.isupper() for c in pw)
                and any(c.isdigit() for c in pw) and any(c in "!@#$%^&*-_=+" for c in pw)):
            return pw


def key_from(value):
    """Normalise a URL or host into an account key (the host, minus www)."""
    v = value.strip()
    if "/" not in v and "." not in v:
        return v.lower()  # already an explicit key
    if "://" not in v:
        v = "//" + v
    host = urlparse(v).hostname or value
    host = host.lower().strip(".")
    return host[4:] if host.startswith("www.") else host


def ensure(key, email):
    data = load()
    entry = data.get(key)
    created = False
    if not entry:
        entry = {"password": gen_password(),
                 "email": email or DEFAULT_EMAIL,
                 "username": email or DEFAULT_EMAIL,
                 "created": date.today().isoformat()}
        data[key] = entry
        save(data)
        created = True
    return entry, created


def main():
    ap = argparse.ArgumentParser(description="Generic per-site account credentials (outside the repo).")
    ap.add_argument("--for", dest="for_url", metavar="URL",
                    help="get credentials for a site (creates a strong password if new)")
    ap.add_argument("--add", metavar="KEY_OR_URL", help="create/refresh an account entry")
    ap.add_argument("--get", metavar="KEY", help="print an existing entry")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--random", action="store_true")
    ap.add_argument("--email", default="")
    ap.add_argument("--username", default="")
    args = ap.parse_args()

    if args.for_url:
        key = key_from(args.for_url)
        entry, created = ensure(key, args.email)
        print(json.dumps({"key": key, **entry, "created_now": created}, indent=2))
    elif args.add:
        key = key_from(args.add)
        data = load()
        entry = data.get(key, {})
        entry["password"] = entry.get("password") or gen_password()
        entry["email"] = args.email or entry.get("email") or DEFAULT_EMAIL
        entry["username"] = args.username or entry.get("username") or entry["email"]
        entry.setdefault("created", date.today().isoformat())
        data[key] = entry
        save(data)
        print(f"{key}: {entry['username']} / {entry['password']}")
    elif args.get:
        entry = load().get(key_from(args.get))
        if not entry:
            print(f"no account for {args.get!r}", file=sys.stderr)
            sys.exit(1)
        print(json.dumps(entry, indent=2))
    elif args.list:
        for key, entry in sorted(load().items()):
            print(f"{key:<40} {entry.get('username','')}   (created {entry.get('created','?')})")
    elif args.random:
        print(gen_password())
    else:
        ap.print_help()


if __name__ == "__main__":
    main()
