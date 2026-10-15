#!/usr/bin/env python3
"""Find and act on an ATS email-verification link or code (read-only Gmail).

Reads the newest matching verification email, prints the verification link and any
code, and can open the link in the browser (user's real browser via xdg-open,
falling back to the Camoufox pipeline browser) so the account/application is
finalised. It never submits a form.

Run with the project venv:
  .venv/bin/python tools/email_verify.py --query 'from:join.com verify'
  .venv/bin/python tools/email_verify.py --query 'from:successfactors.eu' --open
"""
import argparse
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gmail_readonly as G


def messages(query, max_results=5):
    service = G.authenticate()
    resp = service.users().messages().list(userId="me", q=query, maxResults=max_results).execute()
    out = []
    for m in resp.get("messages", []):
        msg = service.users().messages().get(userId="me", id=m["id"], format="full").execute()
        headers = {h["name"].lower(): h["value"] for h in msg["payload"].get("headers", [])}
        out.append((headers.get("date", ""), headers.get("subject", ""), G._decode(msg["payload"])))
    out.sort(key=lambda x: x[0])
    return out


def open_link(link):
    # Prefer the user's real browser so the click is visible and uses their session.
    try:
        subprocess.Popen(["xdg-open", link], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print("  opened in your browser")
        return
    except FileNotFoundError:
        pass
    try:
        r = subprocess.run(["python3", "tools/camoufox_browser.py", "--server",
                            os.environ.get("CAMOUFOX_SERVER", "http://127.0.0.1:9872"),
                            "nav", link],
                           capture_output=True, text=True, timeout=45)
        print("  camoufox:", (r.stdout or r.stderr).strip()[:200])
    except Exception:
        print("  open manually:\n   ", link)


def main():
    ap = argparse.ArgumentParser(description="ATS/site email verification helper (read-only Gmail).")
    ap.add_argument("--query", default="", help="Gmail query, e.g. 'from:join.com verify'")
    ap.add_argument("--domain", default="", help="site domain (any platform), e.g. myworkdayjobs.com")
    ap.add_argument("--days", type=int, default=14, help="look back this many days (with --domain)")
    ap.add_argument("--latest", type=int, default=1, help="how many of the newest messages to show")
    ap.add_argument("--open", action="store_true", help="open the newest link in the browser")
    args = ap.parse_args()

    query = args.query
    if not query and args.domain:
        query = (f"newer_than:{args.days}d from:{args.domain} "
                 f"(verify OR verification OR confirm OR confirmation OR activate "
                 f'OR "verification code" OR "confirm your email")')
    if not query:
        ap.error("provide --query or --domain")

    msgs = messages(query, max_results=15)
    if not msgs:
        print(f"no matching messages for: {query}")
        sys.exit(1)
    # Prefer the newest message that actually contains a link or a code.
    with_links = [m for m in msgs if any(G.extract(m[2]))]
    chosen = (with_links or msgs)[-args.latest:]
    if not with_links:
        print("(no link/code found in recent matches; showing newest)\n")
    for date, subject, body in chosen:
        links, codes = G.extract(body)
        print(f"{date}  {subject}")
        for l in links[:3]:
            print("  LINK", l)
        for c in codes[:3]:
            print("  CODE", c)
        if args.open and links:
            open_link(links[0])
    print("\nEnter the code in the form yourself; this tool never submits.")


if __name__ == "__main__":
    main()
