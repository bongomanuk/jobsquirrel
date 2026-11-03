#!/usr/bin/env python3
"""Where the Google OAuth client + token live (Gmail and Calendar share one token).

Paths are configurable in `config/google.json`:

    {
      "config_dir": "~/.config/job-search",   # where credentials/token live
      "credentials": "credentials.json",      # absolute, or relative to config_dir
      "token": "token.json",                  # absolute, or relative to config_dir
      "client_id": "",                        # legacy (now in the secrets store)
      "client_secret": ""
    }

The client id/secret and the serialized credentials/token files are kept in the
central secrets store (tools/secrets_store.py). The two JSON files remain as
0600 caches because Google's libraries read them directly; `hydrate()` recreates
them from the store when missing, and `capture()` writes changes back.

Environment overrides still win (handy for CI or a second account):
GMAIL_CONFIG_DIR, GMAIL_CREDENTIALS, GMAIL_TOKEN, JOBSQUIRREL_SECRETS.

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

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import secrets_store as SS  # noqa: E402  central 0600 store, outside the repo

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG = os.environ.get("JOBSQUIRREL_GOOGLE_CONFIG", os.path.join(ROOT, "config", "google.json"))
DEFAULTS = {
    "config_dir": "~/.config/job-search",
    "credentials": "credentials.json",
    "token": "token.json",
    "client_id": "",
    "client_secret": "",
}
KEYS = ("config_dir", "credentials", "token")


def _read_config() -> dict:
    cfg = dict(DEFAULTS)
    try:
        with open(CONFIG, encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, dict):
            cfg.update({k: data.get(k, cfg[k]) for k in DEFAULTS})
    except FileNotFoundError:
        pass
    except (OSError, ValueError) as exc:
        print(f"warning: ignoring {CONFIG}: {exc}", file=sys.stderr)
    return cfg


def _stored_client(sec: dict) -> tuple[str, str]:
    """The client id/secret, either stored directly or inside credentials.json."""
    payload = sec.get("credentials")
    inner = {}
    if isinstance(payload, dict):
        inner = payload.get("installed") or payload.get("web") or {}
    return (str(sec.get("client_id") or inner.get("client_id") or ""),
            str(sec.get("client_secret") or inner.get("client_secret") or ""))


def load() -> dict:
    """Paths from config/google.json, secrets from the store (legacy falls back)."""
    cfg = _read_config()
    sec = SS.section("google")
    cid, secret = _stored_client(sec)
    cfg["client_id"] = cid or str(cfg.get("client_id") or "")
    cfg["client_secret"] = secret or str(cfg.get("client_secret") or "")
    return cfg


def save(values: dict) -> dict:
    """Save non-secret paths; client ids go to the secrets store, never the repo."""
    cfg = _read_config()
    for key in KEYS:
        if values.get(key) is not None:
            cfg[key] = values[key]
    if values.get("client_id") is not None:
        SS.put("google", "client_id", str(values["client_id"]).strip())
    if values.get("client_secret") is not None:
        SS.put("google", "client_secret", str(values["client_secret"]).strip())
    # Keep the legacy fields out of the tracked file.
    cfg["client_id"] = ""
    cfg["client_secret"] = ""
    os.makedirs(os.path.dirname(CONFIG), exist_ok=True)
    with open(CONFIG, "w", encoding="utf-8") as fh:
        json.dump(cfg, fh, indent=2)
        fh.write("\n")
    return load()


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


def _write_json(path: str, payload: dict) -> None:
    os.makedirs(os.path.dirname(path) or ".", mode=0o700, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)
        fh.write("\n")
    os.chmod(path, 0o600)


def _client_payload(client_id: str, client_secret: str) -> dict:
    return {"installed": {
        "client_id": client_id,
        "client_secret": client_secret,
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
        "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
        "redirect_uris": ["http://localhost"],
    }}


def hydrate() -> dict:
    """Materialize credentials.json / token.json from the store when missing."""
    sec = SS.section("google")
    _, credentials_path, token_path = paths()
    made = []
    payload = sec.get("credentials")
    if not isinstance(payload, dict):
        cid, secret = sec.get("client_id"), sec.get("client_secret")
        payload = _client_payload(str(cid), str(secret)) if cid and secret else None
    if payload and not os.path.exists(credentials_path):
        _write_json(credentials_path, payload)
        made.append(credentials_path)
    token = sec.get("token")
    if isinstance(token, dict) and not os.path.exists(token_path):
        _write_json(token_path, token)
        made.append(token_path)
    for p in (credentials_path, token_path):
        if os.path.isfile(p):
            try:
                os.chmod(p, 0o600)
            except OSError:
                pass
    return {"made": made, "credentials": credentials_path, "token": token_path,
            "store": SS.path()}


def capture(token_modify: str = "") -> dict:
    """Copy the current credentials/token files back into the store."""
    _, credentials_path, token_path = paths()
    saved = []
    for key, p in (("credentials", credentials_path), ("token", token_path)):
        try:
            with open(p, encoding="utf-8") as fh:
                data = json.load(fh)
            if isinstance(data, dict):
                SS.put("google", key, data)
                saved.append(key)
        except (OSError, ValueError):
            pass
    if token_modify:
        try:
            with open(token_modify, encoding="utf-8") as fh:
                data = json.load(fh)
            if isinstance(data, dict):
                SS.put("google", "token_modify", data)
                saved.append("token_modify")
        except (OSError, ValueError):
            pass
    for p in (credentials_path, token_path):
        if os.path.isfile(p):
            try:
                os.chmod(p, 0o600)
            except OSError:
                pass
    return {"saved": saved, "store": SS.path()}


def write_credentials(client_id: str = "", client_secret: str = "", override: bool = False) -> str | None:
    """Write credentials.json for a Desktop/installed-app OAuth client."""
    cfg = load()
    client_id = (client_id or cfg.get("client_id") or "").strip()
    client_secret = (client_secret or cfg.get("client_secret") or "").strip()
    _, credentials_path, _ = paths()
    if not client_id or not client_secret:
        return None
    SS.put("google", "client_id", client_id)
    SS.put("google", "client_secret", client_secret)
    payload = _client_payload(client_id, client_secret)
    SS.put("google", "credentials", payload)
    if os.path.exists(credentials_path) and not override:
        return None
    _write_json(credentials_path, payload)
    return credentials_path


def status() -> dict:
    cfg = load()
    config_dir, credentials, token = paths()
    sec = SS.section("google")
    cid, secret = _stored_client(sec)
    out = {
        "config_file": CONFIG,
        "config_dir": config_dir,
        "credentials": credentials,
        "token": token,
        "credentials_exists": os.path.isfile(credentials),
        "token_exists": os.path.isfile(token),
        "has_client_secret": bool(cid and secret),
        "client_id": cid or cfg.get("client_id", ""),
        "in_store": bool(sec.get("credentials") or sec.get("token")),
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
    ap.add_argument("--hydrate", action="store_true", help="recreate missing files from the secrets store")
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
    if args.hydrate:
        out = hydrate()
        print(f"store: {out['store']}")
        print(f"recreated: {', '.join(out['made']) or 'nothing missing'}")
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
    print(f"client id + secret: {'stored' if st['has_client_secret'] else 'not stored'}")
    print(f"secrets store:      {SS.path()}")
    if st["account"]:
        print(f"account:            {st['account']}")
    if st["scopes"]:
        print("scopes:             " + " ".join(st["scopes"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
