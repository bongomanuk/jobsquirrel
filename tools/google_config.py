#!/usr/bin/env python3
"""Where the Google OAuth client + token live (Gmail and Calendar share one token).

Everything is configurable, so a new user never has to match a hard-coded path.
Settings live in `config/google.json`:

    {
      "config_dir": "~/.config/job-search",   # where credentials/token live
      "credentials": "credentials.json",      # absolute, or relative to config_dir
      "token": "token.json",                  # absolute, or relative to config_dir
      "client_id": "",                        # optional: build credentials.json for you
      "client_secret": ""
    }

Environment overrides still win (handy for CI or a second account):
GMAIL_CONFIG_DIR, GMAIL_CREDENTIALS, GMAIL_TOKEN.

Usage:
  python3 tools/google_config.py --status             # paths, what exists, scopes
  python3 tools/google_config.py --paths              # shell-friendly paths
  python3 tools/google_config.py --write-credentials  # from client_id/client_secret
"""
from __future__ import annotations

import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG = os.environ.get("JOBSQUIRREL_GOOGLE_CONFIG", os.path.join(ROOT, "config", "google.json"))
DEFAULTS = {
    "config_dir": "~/.config/job-search",
    "credentials": "credentials.json",
    "token": "token.json",
    "client_id": "",
    "client_secret": "",
}
KEYS = tuple(DEFAULTS)


def load() -> dict:
    cfg = dict(DEFAULTS)
    try:
        with open(CONFIG, encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, dict):
            cfg.update({k: data.get(k, cfg[k]) for k in KEYS})
    except FileNotFoundError:
        pass
    except (OSError, ValueError) as exc:
        print(f"warning: ignoring {CONFIG}: {exc}", file=sys.stderr)
    return cfg


def save(values: dict) -> dict:
    cfg = load()
    cfg.update({k: (values.get(k) if values.get(k) is not None else cfg[k]) for k in KEYS})
    os.makedirs(os.path.dirname(CONFIG), exist_ok=True)
    with open(CONFIG, "w", encoding="utf-8") as fh:
        json.dump(cfg, fh, indent=2)
        fh.write("\n")
    return cfg


def paths() -> tuple[str, str, str]:
    """(config_dir, credentials, token), honouring env overrides."""
    cfg = load()
    config_dir = os.path.expanduser(os.environ.get("GMAIL_CONFIG_DIR") or cfg["config_dir"])
    credentials = os.environ.get("GMAIL_CREDENTIALS") or cfg["credentials"]
    token = os.environ.get("GMAIL_TOKEN") or cfg["token"]
    if not os.path.isabs(credentials):
        credentials = os.path.join(config_dir, credentials)
    if not os.path.isabs(token):
        token = os.path.join(config_dir, token)
    return config_dir, os.path.expanduser(credentials), os.path.expanduser(token)


def write_credentials(client_id: str = "", client_secret: str = "", override: bool = False) -> str | None:
    """Write credentials.json for a Desktop/installed-app OAuth client.

    Returns the path, or None when there is nothing to write (no client id, or the
    file already exists and override is False).
    """
    cfg = load()
    client_id = (client_id or cfg.get("client_id") or "").strip()
    client_secret = (client_secret or cfg.get("client_secret") or "").strip()
    _, credentials_path, _ = paths()
    if not client_id or not client_secret:
        return None
    if os.path.exists(credentials_path) and not override:
        return None
    payload = {"installed": {
        "client_id": client_id,
        "client_secret": client_secret,
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
        "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
        "redirect_uris": ["http://localhost"],
    }}
    os.makedirs(os.path.dirname(credentials_path), exist_ok=True)
    with open(credentials_path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)
        fh.write("\n")
    os.chmod(credentials_path, 0o600)
    return credentials_path


def status() -> dict:
    cfg = load()
    config_dir, credentials, token = paths()
    out = {
        "config_file": CONFIG,
        "config_dir": config_dir,
        "credentials": credentials,
        "token": token,
        "credentials_exists": os.path.isfile(credentials),
        "token_exists": os.path.isfile(token),
        "has_client_secret": bool(cfg.get("client_id") and cfg.get("client_secret")),
        "client_id": cfg.get("client_id", ""),
        "account": "",
        "scopes": [],
    }
    try:
        with open(token, encoding="utf-8") as fh:
            data = json.load(fh)
        out["scopes"] = data.get("scopes", [])
        out["account"] = data.get("account", "")
    except (OSError, ValueError):
        pass
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Inspect/write the Google OAuth config.")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--paths", action="store_true")
    ap.add_argument("--write-credentials", action="store_true")
    ap.add_argument("--client-id", default="")
    ap.add_argument("--client-secret", default="")
    ap.add_argument("--force", action="store_true", help="overwrite an existing credentials.json")
    args = ap.parse_args()

    if args.paths:
        config_dir, credentials, token = paths()
        print(f"CONFIG_DIR={config_dir}")
        print(f"CREDENTIALS={credentials}")
        print(f"TOKEN={token}")
        return 0
    if args.write_credentials:
        path = write_credentials(args.client_id, args.client_secret, args.force)
        print(f"wrote {path}" if path else "nothing to write (need client_id + client_secret, or file exists)")
        return 0
    st = status()
    print(f"config file:        {st['config_file']}")
    print(f"config dir:         {st['config_dir']}")
    print(f"credentials.json:   {'OK' if st['credentials_exists'] else 'missing'}  ({st['credentials']})")
    print(f"token.json:         {'OK' if st['token_exists'] else 'missing'}  ({st['token']})")
    print(f"client id + secret: {'stored in config' if st['has_client_secret'] else 'not stored'}")
    if st["account"]:
        print(f"account:            {st['account']}")
    if st["scopes"]:
        print("scopes:             " + " ".join(st["scopes"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
