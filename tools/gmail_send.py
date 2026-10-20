#!/usr/bin/env python3
"""Send email via Gmail using the pipeline's OAuth token.

Requires the gmail.send scope (see tools/gmail_readonly.py SCOPES). If the token
only has gmail.readonly, re-consent once:

  .venv/bin/python tools/gmail_readonly.py --auth

Sending is draft-first: save a reply with tools/draft_email.py, then a human
approves it in the role drawer (Send with approval). This tool refuses to send
anything that is not a saved draft with a valid dashboard receipt; there is no
environment-variable bypass. A human at a terminal gets an explicit y/N preview.

Usage:
  .venv/bin/python tools/gmail_send.py --draft state/drafts/... --dry-run
  .venv/bin/python tools/gmail_send.py --draft state/drafts/...   # human-approved / TTY

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
    ap.add_argument("--company", default="", help="register company (or Company: in the draft)")
    ap.add_argument("--role", default="", help="register role (or Role: in the draft)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    meta = {}
    draft_attaches = []
    cli_overrides = bool(args.to or args.cc or args.bcc or args.subject or args.attach
                         or args.body or args.body_file or args.signature)
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
    company = (args.company or meta.get("company") or "").strip()
    role = (args.role or meta.get("role") or "").strip()

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

    # Draft-first + human confirmation. A dashboard receipt is tied to this exact
    # draft's SHA-256; the agent cannot self-approve with an env variable.
    if args.draft and cli_overrides:
        print("refused: a saved draft cannot be overridden on send (edit the draft and re-approve)",
              file=sys.stderr)
        sys.exit(4)
    if not args.draft:
        print("refused: save the email as a draft first (tools/draft_email.py) and send it "
              "from the role drawer; direct --to/--body sends are disabled.", file=sys.stderr)
        sys.exit(4)
    import send_receipt as SR
    receipt = SR.valid(args.draft)
    if not receipt:
        if not sys.stdin.isatty():
            print("refused: this draft has not been approved by a human in the dashboard. "
                  "Open the role drawer and press Send with approval.", file=sys.stderr)
            sys.exit(4)
        print("\n--- email preview ---")
        print(f"To: {args.to}")
        print(f"Subject: {args.subject}")
        for name, size in attached:
            print(f"Attachment: {name} ({size} bytes)")
        print("\n" + body[:3000] + ("\n…" if len(body) > 3000 else ""))
        try:
            ans = input("\nSend this email now? [y/N] ").strip().lower()
        except EOFError:
            ans = ""
        if ans not in ("y", "yes"):
            print("refused: not confirmed", file=sys.stderr)
            sys.exit(4)
    else:
        SR.consume(args.draft)

    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import gmail_readonly as G
    svc = G.authenticate()
    sent = svc.users().messages().send(userId="me", body={"raw": raw}).execute()
    mid = sent.get("id", "")
    print("sent", mid)
    if company and role:
        try:
            import register as R
            if R.log_outbound(company, role, args.to, args.subject, mid):
                print(f"register: recorded outbound email on {company} — {role}")
        except Exception as exc:
            print(f"warning: email sent but register update failed: {exc}", file=sys.stderr)
    else:
        print("note: no Company:/Role: on the draft and no --company/--role; "
              "email not linked to a register row", file=sys.stderr)


if __name__ == "__main__":
    main()
