#!/usr/bin/env python3
"""Ensure a role has a saved job description before it enters the work queue.

  python3 tools/jd_guard.py --queue                 # report queue rows without a spec
  python3 tools/jd_guard.py --require --key <key>  # exit 2 if the spec is missing
  python3 tools/jd_guard.py --fetch --key <key> --url <url> [--company ...] [--role ...] [--server ...]
"""

import argparse
import html
import json
import os
import re
import subprocess
import sys
import urllib.request
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JD_DIR = ROOT / "state" / "job-descriptions"
QUEUE = ROOT / "state" / "queue.tsv"
MIN_CHARS = 300
UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")


def jd_path(key):
    return JD_DIR / f"{key}.md"


def clean(key):
    key = re.sub(r"[^A-Za-z0-9._-]", "-", str(key or "")).strip("-.")
    return key[:160]


def has_jd(key):
    p = jd_path(clean(key))
    try:
        return p.stat().st_size >= 200
    except OSError:
        return False


def text_from_html(raw):
    raw = re.sub(r"(?is)<(style|script|head)\b[^>]*>.*?</\1>", " ", raw)
    raw = re.sub(r"(?is)<br\s*/?>|</p>|</li>|</h[1-6]>", "\n", raw)
    text = html.unescape(re.sub(r"<[^>]+>", " ", raw))
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n\n", text)
    return text.strip()


def _looks_closed(text):
    low = (text or "").lower()
    return any(x in low for x in (
        "authwall", "sign in to view", "join now to see", "linkedin.com/login",
        "please sign in", "log in to continue"))


def fetch_http(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "en"})
    with urllib.request.urlopen(req, timeout=25) as r:
        raw = r.read(4_000_000).decode("utf-8", "ignore")
    text = text_from_html(raw)
    if len(text) < MIN_CHARS or _looks_closed(text):
        raise ValueError("page has no usable job description (login wall or empty)")
    return text


def fetch_browser(url, server):
    cmd = [sys.executable, str(ROOT / "tools" / "camoufox_browser.py"),
           "--server", server.rstrip("/"), "nav", url]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=90)
    if r.returncode:
        raise ValueError((r.stdout + r.stderr).strip()[:300] or "browser navigation failed")
    cmd = [sys.executable, str(ROOT / "tools" / "camoufox_browser.py"),
           "--server", server.rstrip("/"), "eval", "document.body.innerText"]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    try:
        out = json.loads(r.stdout)
    except ValueError:
        raise ValueError("browser returned no readable text")
    text = str(out.get("result") or "").strip()
    if not out.get("ok") or len(text) < MIN_CHARS or _looks_closed(text):
        raise ValueError("browser page has no usable job description")
    return text


def write_jd(key, company, role, url, text):
    key = clean(key)
    if not key:
        raise ValueError("empty key")
    JD_DIR.mkdir(parents=True, exist_ok=True)
    body = (
        f"# {company or 'Unknown company'} — {role or 'Unknown role'}\n"
        f"Source: {url}\n"
        f"Fetched: {date.today().isoformat()}\n"
        "---\n"
        f"{text.strip()}\n"
    )
    jd_path(key).write_text(body, encoding="utf-8")
    return jd_path(key)


def queue_missing():
    missing = []
    try:
        lines = QUEUE.read_text(encoding="utf-8").splitlines()
    except OSError:
        return missing
    for line in lines:
        if not line.strip() or line.startswith("#"):
            continue
        p = line.split("\t")
        if len(p) < 6 or not p[5].strip():
            continue
        if not has_jd(p[5]):
            missing.append((p[0], p[1], p[5]))
    return missing


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--queue", action="store_true", help="report queue rows without a job spec")
    ap.add_argument("--require", action="store_true", help="exit 2 when the spec is missing")
    ap.add_argument("--fetch", action="store_true", help="fetch and save a job spec")
    ap.add_argument("--key", default="")
    ap.add_argument("--url", default="")
    ap.add_argument("--company", default="")
    ap.add_argument("--role", default="")
    ap.add_argument("--server", default=os.environ.get("CAMOUFOX_SERVER", ""),
                    help="optional Camoufox server for login-gated pages")
    args = ap.parse_args()

    if args.queue:
        missing = queue_missing()
        print(f"{len(missing)} queue row(s) without a job description")
        for co, role, key in missing[:60]:
            print(f"  {co} | {role} | {key}")
        if len(missing) > 60:
            print(f"  … {len(missing) - 60} more")
        return 1 if missing else 0

    if args.require:
        if has_jd(args.key):
            print(f"RESULT: PASS - job description exists for {clean(args.key)}")
            return 0
        print(f"RESULT: FAIL - no job description for {clean(args.key)}", file=sys.stderr)
        return 2

    if args.fetch:
        if not args.key or not args.url:
            print("--fetch needs --key and --url", file=sys.stderr)
            return 2
        try:
            text, via = "", ""
            if args.server:
                try:
                    text, via = fetch_browser(args.url, args.server), "browser"
                except Exception as e:
                    print(f"browser fetch failed: {e}", file=sys.stderr)
            if not text:
                text, via = fetch_http(args.url), "http"
            path = write_jd(args.key, args.company, args.role, args.url, text)
            print(f"RESULT: PASS - saved {path} ({via}, {len(text)} chars)")
            return 0
        except Exception as e:
            print(f"RESULT: FAIL - could not fetch a job description: {e}", file=sys.stderr)
            return 2

    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
