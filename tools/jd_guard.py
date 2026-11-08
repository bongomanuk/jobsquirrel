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

sys.path.insert(0, str(Path(__file__).resolve().parent))
import stateio
import scam_check

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


LEAD_MARKERS = ("spec status: lead brief", "no advert supplied",
                "no job advert supplied")


def _head(path, limit=2000):
    try:
        if path.endswith(stateio.SUFFIX):
            return stateio.read_text(path)[:limit]
        with open(path, encoding="utf-8", errors="ignore") as fh:
            return fh.read(limit)
    except OSError:
        return ""


def is_lead_brief(path):
    """A saved recruiter email is a lead, not a job advert.

    Lead briefs are stored under state/job-descriptions/ so the source is kept,
    but they must never satisfy the "every role has a spec" gate.
    """
    text = _head(path).lower()
    return any(marker in text for marker in LEAD_MARKERS)


def has_spec_at(path):
    """True when this exact file is a substantive job advert (not a lead note)."""
    if not path:
        return False
    if path.endswith(stateio.SUFFIX):
        text = stateio.read_text(path)
        return len(text) >= 200 and not is_lead_brief(path)
    try:
        if os.stat(path).st_size < 200:
            return False
    except OSError:
        return False
    if _looks_shell(_head(path)):
        return False
    return not is_lead_brief(path)


def has_jd(key):
    found = stateio.resolve(str(jd_path(clean(key))))
    if not found:
        return False
    return has_spec_at(found)


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


def _looks_shell(text):
    """A LinkedIn page shell with no advert body is not a job description."""
    low = (text or "").lower()
    if "linkedin corporation" not in low or "select language" not in low:
        return False
    return not any(x in low for x in (
        "about the job", "job description", "responsibilities", "qualifications",
        "what you will do", "om jobbet", "arbetsuppgifter", "kvalifikationer"))


def fetch_http(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "en"})
    with urllib.request.urlopen(req, timeout=25) as r:
        raw = r.read(4_000_000).decode("utf-8", "ignore")
    text = text_from_html(raw)
    if len(text) < MIN_CHARS or _looks_closed(text) or _looks_shell(text):
        raise ValueError("page has no usable job description (login wall or empty)")
    return text


def fetch_browser(url, server):
    base = [sys.executable, str(ROOT / "tools" / "camoufox_browser.py"),
            "--server", server.rstrip("/")]
    r = subprocess.run(base + ["nav", url], capture_output=True, text=True, timeout=90)
    if r.returncode:
        raise ValueError((r.stdout + r.stderr).strip()[:300] or "browser navigation failed")
    # LinkedIn and several ATSs render the advert after the first paint. Give
    # the page a moment, then take the description element rather than the
    # navigation/footer shell.
    subprocess.run(base + ["wait", "3500"], capture_output=True, text=True, timeout=30)
    js = r"""(() => {
      const sels = ['.jobs-description-content__text', '.jobs-box__html-content',
        '[data-testid="job-description"]', '[class*="jobs-description"]',
        '[class*="job-description"]', 'article'];
      for (const s of sels) {
        const e = document.querySelector(s);
        if (e && (e.innerText || '').trim().length > 300) return e.innerText;
      }
      return document.body.innerText;
    })()"""
    r = subprocess.run(base + ["eval", js], capture_output=True, text=True, timeout=60)
    try:
        out = json.loads(r.stdout)
    except ValueError:
        raise ValueError("browser returned no readable text")
    text = str(out.get("result") or "").strip()
    if not out.get("ok") or len(text) < MIN_CHARS or _looks_closed(text) or _looks_shell(text):
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
    stateio.write(str(jd_path(key)), body.encode("utf-8"))
    scan = scam_check.scan(body, company or "", "")
    scam_check.save(key, scan)
    if scan["level"] in ("high", "medium"):
        print(f"SCAM {scan['level'].upper()} — {scam_check.summary(scan)}", file=sys.stderr)
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
        found = stateio.resolve(str(jd_path(clean(args.key))))
        if found and is_lead_brief(found):
            print(f"RESULT: FAIL - {clean(args.key)} is a recruiter lead brief, not a "
                  f"job advert; save the full spec before preparing documents",
                  file=sys.stderr)
        else:
            print(f"RESULT: FAIL - no job description for {clean(args.key)}",
                  file=sys.stderr)
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
