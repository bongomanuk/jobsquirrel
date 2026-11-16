#!/usr/bin/env python3
"""One-time human-confirmation receipts for sending a saved email draft.

The dashboard issues a receipt only after the operator approves the exact draft
in the UI. `gmail_send.py` requires a valid, unexpired receipt that matches the
draft's path and SHA-256, then consumes it. An agent cannot get an email out by
setting `APPROVE_SEND_EMAIL=1`: that environment variable is no longer honoured
for email, and a draft must exist first.

Receipts live in `state/send-receipts/<sha256>.json` and are removed on use.
"""
from __future__ import annotations

import hashlib
import json
import os
import secrets
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIR = os.path.join(ROOT, "state", "send-receipts")
TTL_SECONDS = 30 * 60


def draft_sha256(path: str) -> str:
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def _path_for(sha: str) -> str:
    return os.path.join(DIR, sha + ".json")


def issue(draft_path: str, by: str = "dashboard", ttl: int = TTL_SECONDS) -> dict:
    """Record that a human approved this exact draft. Returns the receipt."""
    draft_path = os.path.abspath(draft_path)
    sha = draft_sha256(draft_path)
    rec = {"path": draft_path, "sha256": sha, "by": by,
           "created": int(time.time()), "expires": int(time.time()) + int(ttl),
           "nonce": secrets.token_hex(8)}
    os.makedirs(DIR, exist_ok=True)
    with open(_path_for(sha), "w", encoding="utf-8") as fh:
        json.dump(rec, fh)
    return rec


def valid(draft_path: str) -> dict | None:
    """The unexpired receipt for this draft, or None (content must match)."""
    try:
        draft_path = os.path.abspath(draft_path)
        sha = draft_sha256(draft_path)
        with open(_path_for(sha), encoding="utf-8") as fh:
            rec = json.load(fh)
    except (OSError, ValueError):
        return None
    if rec.get("path") != draft_path or rec.get("sha256") != sha:
        return None
    if int(rec.get("expires") or 0) < int(time.time()):
        consume(draft_path)
        return None
    return rec


def consume(draft_path: str) -> None:
    try:
        os.remove(_path_for(draft_sha256(draft_path)))
    except OSError:
        pass
