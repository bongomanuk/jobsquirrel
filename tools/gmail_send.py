#!/usr/bin/env python3
"""Send email via Gmail using the pipeline's OAuth token.

Requires the gmail.send scope (see tools/gmail_readonly.py SCOPES). If the token
only has gmail.readonly, re-consent once:

  .venv/bin/python tools/gmail_readonly.py --auth

Usage:
  .venv/bin/python tools/gmail_send.py --to a@b.com --subject "Hi" --body-file state/draft.txt
  .venv/bin/python tools/gmail_send.py --to a@b.com --subject "Hi" --body "..." --dry-run
"""
import argparse
import base64
import os
import sys
from email.mime.text import MIMEText

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gmail_readonly as G


def main():
    ap = argparse.ArgumentParser(description="Send a plain-text email via Gmail.")
    ap.add_argument("--to", required=True)
    ap.add_argument("--subject", required=True)
    ap.add_argument("--body", default="")
    ap.add_argument("--body-file", default="")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    body = args.body
    if args.body_file:
        with open(args.body_file, encoding="utf-8") as fh:
            body = fh.read()
    if not body.strip():
        print("empty body", file=sys.stderr)
        sys.exit(2)

    msg = MIMEText(body, "plain", "utf-8")
    msg["To"] = args.to
    msg["Subject"] = args.subject
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()

    if args.dry_run:
        print(f"DRY RUN -> {args.to} | {args.subject}")
        print(body)
        return

    # Sending email is risky and irreversible: require explicit human approval
    # (interactive y/N, or APPROVE_SEND_EMAIL=1 for this one command).
    import approval
    if not approval.approved(f"sending email to {args.to} (subject: {args.subject!r})", "SEND-EMAIL"):
        print("refused: sending email needs explicit approval "
              "(answer y at the prompt, or set APPROVE_SEND_EMAIL=1 for this command).", file=sys.stderr)
        sys.exit(4)

    svc = G.authenticate()
    sent = svc.users().messages().send(userId="me", body={"raw": raw}).execute()
    print("sent", sent.get("id"))


if __name__ == "__main__":
    main()
