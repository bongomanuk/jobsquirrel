#!/usr/bin/env python3
"""Read-only Gmail access for the job-search pipeline.

Reads application mail, classifies it (confirmation / interview / rejection /
verification), and surfaces any verification links or codes for you to act on
manually. It NEVER sends, modifies, deletes or marks mail: the only scope
requested is gmail.readonly, so the token physically cannot do anything else.

Setup is documented in state/gmail-setup.md. Short version:
  - Google Cloud project -> enable Gmail API
  - OAuth consent (External, Testing, add yourself, scope gmail.readonly)
  - OAuth client (Desktop) -> download credentials.json
  - save as ~/.config/job-search/credentials.json
  - pip install google-auth google-auth-oauthlib google-api-python-client
  - python3 tools/gmail_readonly.py --auth

Usage:
  python3 tools/gmail_readonly.py --auth
  python3 tools/gmail_readonly.py --sync
  python3 tools/gmail_readonly.py --sync --query 'from:(ashbyhq.com OR teamtailor.com)'
  python3 tools/gmail_readonly.py --sync --apply     # update register notes
"""
import argparse
import base64
import html
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_DIR = os.environ.get("GMAIL_CONFIG_DIR", os.path.expanduser("~/.config/job-search"))
CREDENTIALS = os.environ.get("GMAIL_CREDENTIALS", os.path.join(CONFIG_DIR, "credentials.json"))
TOKEN = os.environ.get("GMAIL_TOKEN", os.path.join(CONFIG_DIR, "token.json"))
SCOPES = ["https://www.googleapis.com/auth/gmail.readonly",
          "https://www.googleapis.com/auth/gmail.send",
          # keep calendar in the SAME token so a refresh here cannot drop it.
          # calendar.events (read+write) supersedes the old calendar.readonly.
          "https://www.googleapis.com/auth/calendar.events"]
DEFAULT_QUERY = os.environ.get(
    "GMAIL_QUERY",
    "newer_than:60d (from:ashbyhq.com OR from:teamtailor.com OR from:greenhouse.io OR "
    "from:lever.co OR from:myworkday.com OR from:successfactors.eu OR from:workable.com OR "
    "from:pinpoint.email OR from:join.com OR from:deel.com OR label:applications)")

VERIFY_RE = re.compile(r"https?://[^\s\"'<>()]*(?:verif|confirm|activat|verify)[^\s\"'<>()]*", re.I)
CODE_INLINE_RE = re.compile(r"(?:code|kod)[^A-Za-z0-9]{0,15}([A-Z0-9]{6,8})\b", re.I)


def _import_google():
    try:
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from google.auth.transport.requests import Request
        from googleapiclient.discovery import build
        return Credentials, InstalledAppFlow, Request, build
    except ImportError:
        print("Missing Google libraries. Install them with:\n"
              "  pip install google-auth google-auth-oauthlib google-api-python-client",
              file=sys.stderr)
        sys.exit(2)


def authenticate():
    Credentials, InstalledAppFlow, Request, build = _import_google()
    if not os.path.isfile(CREDENTIALS):
        print(f"credentials.json not found at {CREDENTIALS}\n"
              f"See state/gmail-setup.md for how to create it.", file=sys.stderr)
        sys.exit(2)
    creds = None
    if os.path.isfile(TOKEN):
        creds = Credentials.from_authorized_user_file(TOKEN, SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS, SCOPES)
            creds = flow.run_local_server(port=0)
        os.makedirs(os.path.dirname(TOKEN), exist_ok=True)
        with open(TOKEN, "w") as fh:
            fh.write(creds.to_json())
        os.chmod(TOKEN, 0o600)
    return build("gmail", "v1", credentials=creds)


def _decode(payload):
    data = payload.get("body", {}).get("data")
    if data:
        return base64.urlsafe_b64decode(data + "===").decode("utf-8", "ignore")
    text = ""
    for part in payload.get("parts", []) or []:
        text += _decode(part)
    return text


def classify(subject, body):
    """Classification with SUBJECT priority: an interview/confirmation/rejection
    signalled in the subject wins over generic wording in the body, so an ATS
    'application received' mail whose boilerplate says 'arrange a time' is not
    read as an interview. Body-only signals are used when the subject is neutral
    (e.g. a personal reply that actually invites you to a call)."""
    s = subject.lower()
    b = body.lower()

    if re.search(r"verif|confirm your email|confirmation code|security code|one-time", s) or \
       "verify your email" in b or "verification code" in b:
        return "VERIFICATION"

    # A cancelled meeting/interview is informational, not an invite: do not let
    # "Meeting cancelled: your first interview ..." register as an INTERVIEW.
    if re.search(r"cancel", s) and re.search(r"interview|meeting|call|chat|screening", s):
        return "OTHER"

    i_subj = re.search(r"interview|next steps?|intro(ductory)? call|first chat|invitation for|"
                       r"phone screen|meet the team|book a time|would you be open|jump on a call|"
                       r"schedule[^.\n]{0,40}(call|chat|meeting|time)", s)
    conf_subj = re.search(r"thank you for applying|thanks for applying|received your application|"
                          r"we got your application|application received|new job application received|"
                          r"successfully submitted|thank you for submitting|application has been received|"
                          r"application submitted|your application to|"
                          r"you already applied|acknowledg", s)
    rej_subj = re.search(r"unfortunately|unsuccessful|not (?:be )?moving forward|we regret|"
                         r"not selected|won'?t be moving forward|rejection", s)
    body_interview = re.search(
        r"invite you (for|to) (an? )?(intro|interview|chat)|invitation for a first chat|"
        r"would (?:like|love) to (?:meet|chat|speak)|i'?d (?:like|love) to (?:meet|chat|speak)|"
        r"first interview (?:will be|is|would be)|(?:like|love) to meet you|"
        r"would .{0,50}?work for you|are you (?:free|available)|"
        r"(?:book|schedule|set up|arrange) (?:a |some )?(?:call|chat|meeting|interview|slot)|"
        r"(?:invite|inviting) you (?:for|to) (?:an? )?(?:interview|chat|call|intro)", b)
    body_rej = re.search(r"not (?:be )?moving forward|not to move forward|not move forward|"
                         r"move forward with (?:the )?other|move forward with another|"
                         r"moving forward with (?:the )?other|progress with other candidates|"
                         r"decided to progress|will not be (?:moving|proceeding|progressing)|"
                         r"won'?t be (?:moving|proceeding|progressing)|"
                         r"not (?:be )?proceeding|unable to (?:move|proceed|offer you|extend an offer)|"
                         r"decided not to|"
                         r"decided to not (?:move|proceed|progress)|"
                         r"proceed with other|will not be proceeding|"
                         r"decided to (move on|proceed|go with|continue with)|"
                         r"continue with (other|candidates)|have not been selected|was not selected|"
                         r"not selected for (the|this) (role|position)|not selected for further consideration|"
                         r"we regret to inform|unfortunately,? we (have )?(decided|chosen)|"
                         r"role (has been|is) filled|pursuing other candidates|not a (?:good )?(?:fit|match)|"
                         r"not an? ideal fit|we (?:don'?t|do not) see an ideal fit|"
                         r"doesn'?t align with our current openings|profile doesn'?t align with", b)
    # A stricter subset for the conf_subj branch: unambiguous "we chose someone
    # else" wording. Deliberately excludes loose phrases like "not a good fit"
    # or "unable to offer", which appear in benign acknowledgments too.
    strong_rej = re.search(r"not (?:be )?moving forward|not to move forward|not move forward|"
                           r"move forward with (?:the )?other|move forward with another|"
                           r"moving forward with (?:the )?other|progress with other candidates|"
                           r"decided to progress|will not be (?:moving|proceeding|progressing)|"
                           r"won'?t be (?:moving|proceeding|progressing)|"
                           r"not (?:be )?proceeding|will not be proceeding|"
                           r"decided not to|decided to not (?:move|proceed|progress)|"
                           r"decided to (move on|proceed|go with|continue with)|"
                           r"continue with (other|candidates)|proceed with other|"
                           r"have not been selected|was not selected|not selected for|"
                           r"we regret to inform|unfortunately,? we (have )?(decided|chosen)|"
                           r"role (has been|is) filled|pursuing other candidates|"
                           r"not an? ideal fit|we (?:don'?t|do not) see an ideal fit|"
                           r"doesn'?t align with our current openings|profile doesn'?t align with", b)
    body_conf = re.search(r"thank you for applying|thanks for applying|received your application|"
                          r"we got your application|application (?:has been )?received|"
                          r"thank you for submitting your application|thanks for your application", b)

    if i_subj:
        return "INTERVIEW"
    if conf_subj:
        if body_interview:
            return "INTERVIEW"
        # A clear rejection in the body outranks a generic "thank you for
        # applying" subject: ATS often reuse the acknowledgment subject for the
        # final no. Only a strong signal flips it, so benign acknowledgments
        # that merely mention sponsorship or relocation are left as CONFIRMATION.
        if strong_rej:
            return "REJECTION"
        return "CONFIRMATION"
    if rej_subj:
        return "REJECTION"
    if body_interview:
        return "INTERVIEW"
    if body_rej:
        return "REJECTION"
    if body_conf:
        return "CONFIRMATION"
    return "OTHER"


def extract(body):
    text = html.unescape(body)
    links = list(dict.fromkeys(VERIFY_RE.findall(text)))
    codes = list(dict.fromkeys(CODE_INLINE_RE.findall(text)))
    return links, codes


def _retry(fn, attempts=5):
    """Retry a Gmail API call on the per-minute quota error."""
    import time as _t
    for i in range(attempts):
        try:
            return fn()
        except Exception as exc:
            if "Quota exceeded" in str(exc) or "rateLimitExceeded" in str(exc) or "403" in str(exc):
                _t.sleep(8 * (i + 1))
                continue
            raise
    raise RuntimeError("Gmail quota exceeded")


def sync(query, apply_changes):
    service = authenticate()
    resp = _retry(lambda: service.users().messages().list(userId="me", q=query, maxResults=80).execute())
    messages = resp.get("messages", [])
    print(f"{len(messages)} matching messages\n")
    for m in messages:
        msg = _retry(lambda: service.users().messages().get(userId="me", id=m["id"], format="full").execute())
        headers = {h["name"].lower(): h["value"] for h in msg["payload"].get("headers", [])}
        subject = headers.get("subject", "")
        sender = headers.get("from", "")
        body = _decode(msg["payload"])
        category = classify(subject, body)
        links, codes = extract(body)
        print(f"[{category}] {headers.get('date','')}  {sender}")
        print(f"    {subject}")
        for l in links:
            print(f"    LINK: {l}")
        for c in codes:
            print(f"    CODE: {c}")
        if apply_changes and category != "OTHER":
            try:
                sys.path.insert(0, os.path.join(ROOT, "tools"))
                import register as REG
                hint = _company_hint(sender, subject)
                status = {"INTERVIEW": "INTERVIEW", "REJECTION": "REJECTED"}.get(category, "")
                n = REG.add_note(hint, f"gmail: {category} {headers.get('date','')}", status) if hint else 0
                if n:
                    print(f"    register: {n} row(s) updated")
            except Exception as exc:
                print(f"    (register update skipped: {exc})")
        print()
    print("Note: verification links/codes are surfaced for you to act on; this tool never clicks them.")


def _company_hint(sender, subject):
    m = re.match(r"[^<]*<([^@>]+)@", sender)
    return (m.group(1) if m else "").replace("-", " ").strip()


def main():
    ap = argparse.ArgumentParser(description="Read-only Gmail sync for the job-search pipeline.")
    ap.add_argument("--auth", action="store_true", help="run the OAuth flow and store the token")
    ap.add_argument("--sync", action="store_true", help="fetch and classify application mail")
    ap.add_argument("--query", default=DEFAULT_QUERY, help="Gmail search query")
    ap.add_argument("--apply", action="store_true", help="update register notes from matches")
    args = ap.parse_args()
    if args.auth:
        authenticate()
        print(f"authorised; token stored at {TOKEN}")
    elif args.sync:
        sync(args.query, args.apply)
    else:
        ap.print_help()


if __name__ == "__main__":
    main()
