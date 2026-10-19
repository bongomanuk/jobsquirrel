#!/usr/bin/env python3
"""Send email via Gmail using the pipeline's OAuth token.

Requires the gmail.send scope (see tools/gmail_readonly.py SCOPES). If the token
only has gmail.readonly, re-consent once:

  .venv/bin/python tools/gmail_readonly.py --auth

Usage:
  .venv/bin/python tools/gmail_send.py --to a@b.com --subject "Hi" --body-file state/draft.txt
  .venv/bin/python tools/gmail_send.py --to a@b.com --subject "Hi" --body "..." \
      --attach documents/applications/Peter_Hollas_CV_x.docx --dry-run
  .venv/bin/python tools/gmail_send.py ... --attach cv.pdf --attach letter.pdf --signature

Config (optional): config/email.json
  {"from": "...", "signature": "...", "attachment_dir": "documents/applications",
   "max_attachment_mb": 20}
Relative attachment paths that don't exist are also looked up in attachment_dir.
"""
import argparse
import base64
import json
import mimetypes
import os
import re
import sys
from email.message import EmailMessage

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG = os.environ.get("EMAIL_CONFIG", os.path.join(ROOT, "config", "email.json"))
DEFAULTS = {
    "signature": "",
    "attachment_dir": "documents/applications",
    "max_attachment_mb": 20,
}


def _config():
    cfg = dict(DEFAULTS)
    try:
        with open(CONFIG, encoding="utf-8") as fh:
            cfg.update(json.load(fh))
    except FileNotFoundError:
        pass
    except (OSError, ValueError) as exc:
        print(f"warning: ignoring {CONFIG}: {exc}", file=sys.stderr)
    return cfg


def _parse_draft(path):
    """Read a draft: `To:`/`Cc:`/`Subject:`/`Attachment:` header, `---`, body."""
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    header, sep, body = text.partition("\n---\n")
    if not sep:
        header, body = "", text
    meta = {}
    for line in header.splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            meta[key.strip().lower()] = value.strip()
    attaches = re.findall(r"[^\s,;()]+\.(?:docx|pdf|doc|txt|png|jpe?g)", meta.get("attachment", ""))
    return meta, body.strip("\n"), attaches


def _resolve_attachment(path, attachment_dir):
    if os.path.isabs(path) and os.path.isfile(path):
        return path
    if os.path.isfile(path):
        return path
    alt = os.path.join(ROOT, attachment_dir, os.path.basename(path))
    return alt if os.path.isfile(alt) else path


def main():
    cfg = _config()
    ap = argparse.ArgumentParser(description="Send an email (with attachments) via Gmail.")
    ap.add_argument("--draft", help="read To/Subject/Attachment/body from a draft file (see state/letters-content/)")
    ap.add_argument("--to", help="recipient(s), comma separated")
    ap.add_argument("--cc", action="append", default=[], help="cc recipient (repeatable)")
    ap.add_argument("--bcc", action="append", default=[], help="bcc recipient (repeatable)")
    ap.add_argument("--subject")
    ap.add_argument("--body", default="")
    ap.add_argument("--body-file", default="")
    ap.add_argument("--attach", action="append", default=[],
                    help="file to attach (repeatable); relative names fall back to attachment_dir")
    ap.add_argument("--signature", action="store_true",
                    help="append the signature from config/email.json")
    ap.add_argument("--max-attachment-mb", type=float, default=None)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    meta = {}
    draft_attaches = []
    if args.draft:
        meta, draft_body, draft_attaches = _parse_draft(args.draft)
        if not args.body and not args.body_file:
            args.body = draft_body
    args.to = args.to or meta.get("to")
    args.subject = args.subject or meta.get("subject")
    if not args.cc and meta.get("cc"):
        args.cc = [meta["cc"]]
    if not args.bcc and meta.get("bcc"):
        args.bcc = [meta["bcc"]]
    if not args.to or not args.subject:
        print("--to and --subject are required (or provide them in --draft)", file=sys.stderr)
        sys.exit(2)
    args.attach = list(args.attach) + draft_attaches

    body = args.body
    if args.body_file:
        with open(args.body_file, encoding="utf-8") as fh:
            body = fh.read()
    if args.signature and cfg.get("signature"):
        body = body.rstrip() + "\n" + cfg["signature"]
    if not body.strip():
        print("empty body", file=sys.stderr)
        sys.exit(2)

    max_mb = args.max_attachment_mb if args.max_attachment_mb is not None \
        else float(cfg.get("max_attachment_mb") or DEFAULTS["max_attachment_mb"])

    msg = EmailMessage()
    msg["To"] = args.to
    if args.cc:
        msg["Cc"] = ", ".join(args.cc)
    if args.bcc:
        msg["Bcc"] = ", ".join(args.bcc)
    msg["Subject"] = args.subject
    msg.set_content(body)

    attached = []
    total = 0
    seen = set()
    for path in args.attach:
        resolved = _resolve_attachment(path, cfg.get("attachment_dir") or DEFAULTS["attachment_dir"])
        key = os.path.abspath(resolved)
        if key in seen:
            continue
        seen.add(key)
        if not os.path.isfile(resolved):
            print(f"attachment not found: {path}" +
                  ("" if resolved == path else f" (also tried {resolved})"), file=sys.stderr)
            sys.exit(2)
        with open(resolved, "rb") as fh:
            data = fh.read()
        if not data:
            print(f"attachment is empty: {resolved}", file=sys.stderr)
            sys.exit(2)
        total += len(data)
        name = os.path.basename(resolved)
        ctype, _ = mimetypes.guess_type(name)
        if ctype:
            maintype, subtype = ctype.split("/", 1)
        else:
            maintype, subtype = "application", "octet-stream"
        msg.add_attachment(data, maintype=maintype, subtype=subtype, filename=name)
        attached.append((name, len(data)))

    if total > max_mb * 1024 * 1024:
        print(f"attachments total {total / 1048576:.1f} MB, over the {max_mb:g} MB limit", file=sys.stderr)
        sys.exit(2)

    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()

    if args.dry_run:
        print(f"DRY RUN -> {args.to} | {args.subject}")
        for name, size in attached:
            print(f"  attach: {name} ({size} bytes)")
        print(body)
        return

    # Sending email is risky and irreversible: require explicit human approval
    # (interactive y/N, or APPROVE_SEND_EMAIL=1 for this one command).
    import approval
    detail = f"sending email to {args.to} (subject: {args.subject!r}"
    if attached:
        detail += f", attachments: {', '.join(n for n, _ in attached)}"
    detail += ")"
    if not approval.approved(detail, "SEND-EMAIL"):
        print("refused: sending email needs explicit approval "
              "(answer y at the prompt, or set APPROVE_SEND_EMAIL=1 for this command).", file=sys.stderr)
        sys.exit(4)

    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import gmail_readonly as G
    svc = G.authenticate()
    sent = svc.users().messages().send(userId="me", body={"raw": raw}).execute()
    print("sent", sent.get("id"))


if __name__ == "__main__":
    main()
