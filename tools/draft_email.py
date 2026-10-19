#!/usr/bin/env python3
"""Draft replies tied to one application (company + role).

The dashboard's row drawer lists these, lets you edit them, and sends one only
with your explicit approval. Agents should save drafts here instead of pasting
an email into chat, so the human can review/change/send it from the UI.

Files live in `state/drafts/<company-role>/<timestamp>.txt`:

    To: recruiter@example.com
    Cc:
    Subject: Re: Interview
    Attachment: documents/applications/CV_x.docx, documents/applications/Motivation_x.docx
    ---
    body text

CLI:
  python3 tools/draft_email.py --company "Acme Corp" --role "AI Solutions..." \
      --to recruiter@example.com --subject "Re: ..." --body-file /tmp/reply.txt
  python3 tools/draft_email.py --list [--company ...] [--role ...]
  python3 tools/draft_email.py --show state/drafts/...
  python3 tools/draft_email.py --delete state/drafts/...
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIR = os.path.join(ROOT, "state", "drafts")
SENT = os.path.join(DIR, "sent.json")
HEADERS = ("To", "Cc", "Subject", "Attachment")


def _slug(value: str) -> str:
    value = re.sub(r"[^a-z0-9]+", "-", (value or "").lower()).strip("-")
    return value[:90] or "draft"


def _folder(company: str, role: str) -> str:
    return os.path.join(DIR, _slug(f"{company}-{role}"))


def _inside(path: str) -> bool:
    real = os.path.realpath(path)
    return real.startswith(os.path.realpath(DIR) + os.sep)


def _clean_attachments(attachments) -> list[str]:
    out = []
    if isinstance(attachments, str):
        attachments = [attachments]
    for a in attachments or []:
        for part in str(a).replace(";", ",").split(","):
            part = part.strip()
            if part:
                out.append(part)
    return list(dict.fromkeys(out))


def save_draft(company: str, role: str, to: str = "", cc: str = "", subject: str = "",
               body: str = "", attachments=None) -> str:
    folder = _folder(company, role)
    os.makedirs(folder, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    path = os.path.join(folder, f"{stamp}.txt")
    n = 1
    while os.path.exists(path):
        n += 1
        path = os.path.join(folder, f"{stamp}-{n}.txt")
    return update_draft(path, to=to, cc=cc, subject=subject, body=body,
                        attachments=attachments, company=company, role=role, create=True)


def update_draft(path: str, to: str = "", cc: str = "", subject: str = "", body: str = "",
                 attachments=None, company: str = "", role: str = "", create: bool = False) -> str:
    path = os.path.abspath(path)
    if not create and not (os.path.isfile(path) and _inside(path)):
        raise ValueError("draft path must be an existing file under state/drafts/")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    lines = [f"To: {(to or '').strip()}", f"Cc: {(cc or '').strip()}",
             f"Subject: {(subject or '').strip()}",
             "Attachment: " + ", ".join(_clean_attachments(attachments))]
    if company:
        lines.append(f"Company: {company}")
    if role:
        lines.append(f"Role: {role}")
    text = "\n".join(lines) + "\n---\n" + (body or "").strip() + "\n"
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    return path


def load_draft(path: str) -> dict:
    path = os.path.abspath(path)
    if not _inside(path) or not os.path.isfile(path):
        raise ValueError("not a draft under state/drafts/")
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    header, sep, body = text.partition("\n---\n")
    meta = {}
    if sep:
        for line in header.splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                meta[k.strip().lower()] = v.strip()
    sent = sent_map().get(path, {})
    return {"path": path, "to": meta.get("to", ""), "cc": meta.get("cc", ""),
            "subject": meta.get("subject", ""),
            "attachments": [x.strip() for x in meta.get("attachment", "").split(",") if x.strip()],
            "company": meta.get("company", ""), "role": meta.get("role", ""),
            "body": body.strip("\n"), "sent_at": sent.get("at", ""),
            "message_id": sent.get("message_id", ""),
            "modified": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(os.path.getmtime(path))),
            "name": os.path.basename(path)}


def list_drafts(company: str = "", role: str = "") -> list[dict]:
    if not os.path.isdir(DIR):
        return []
    out = []
    for root, _dirs, files in os.walk(DIR):
        for f in files:
            if not f.endswith(".txt"):
                continue
            try:
                d = load_draft(os.path.join(root, f))
            except (OSError, ValueError):
                continue
            if company and company.strip().lower() not in (d["company"] or "").lower():
                continue
            if role and role.strip().lower() not in (d["role"] or "").lower():
                continue
            out.append(d)
    out.sort(key=lambda d: d["modified"], reverse=True)
    return out


def delete_draft(path: str) -> bool:
    path = os.path.abspath(path)
    if not (_inside(path) and os.path.isfile(path)):
        return False
    os.remove(path)
    sent = sent_map()
    if path in sent:
        sent.pop(path)
        _save_sent(sent)
    return True


def sent_map() -> dict:
    try:
        with open(SENT, encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_sent(data: dict) -> None:
    os.makedirs(DIR, exist_ok=True)
    tmp = SENT + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
    os.replace(tmp, SENT)


def mark_sent(path: str, message_id: str = "") -> None:
    path = os.path.abspath(path)
    sent = sent_map()
    sent[path] = {"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "message_id": message_id}
    _save_sent(sent)


def main() -> int:
    ap = argparse.ArgumentParser(description="Draft replies for a role (managed in the dashboard).")
    ap.add_argument("--company", default="")
    ap.add_argument("--role", default="")
    ap.add_argument("--to", default="")
    ap.add_argument("--cc", default="")
    ap.add_argument("--subject", default="")
    ap.add_argument("--body", default="")
    ap.add_argument("--body-file", default="")
    ap.add_argument("--attach", action="append", default=[])
    ap.add_argument("--update", default="", help="path of an existing draft to overwrite")
    ap.add_argument("--show", default="")
    ap.add_argument("--delete", default="")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    if args.list:
        drafts = list_drafts(args.company, args.role)
        if args.json:
            print(json.dumps(drafts, indent=2))
        else:
            for d in drafts:
                who = d["to"] or "(no recipient)"
                when = f"  [sent {d['sent_at']}]" if d["sent_at"] else ""
                print(f"{d['path']}  |  {who}  |  {d['subject'][:70]}{when}")
        return 0
    if args.show:
        print(json.dumps(load_draft(args.show), indent=2))
        return 0
    if args.delete:
        print("deleted" if delete_draft(args.delete) else "not found")
        return 0

    body = args.body
    if args.body_file:
        with open(args.body_file, encoding="utf-8") as fh:
            body = fh.read()
    if not body.strip():
        print("empty body (use --body or --body-file)", file=sys.stderr)
        return 2
    if args.update:
        path = update_draft(args.update, args.to, args.cc, args.subject, body, args.attach,
                            args.company, args.role)
    else:
        if not (args.company and args.role):
            print("--company and --role are required for a new draft", file=sys.stderr)
            return 2
        path = save_draft(args.company, args.role, args.to, args.cc, args.subject, body, args.attach)
    print(path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
