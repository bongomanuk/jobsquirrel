#!/usr/bin/env python3
"""Request Google Calendar read-only access and save the token.

Usage:
  python3 tools/gmail_calendar_auth.py          # initiate OAuth flow, print auth URL
  python3 tools/gmail_calendar_auth.py --check  # verify calendar access works
"""
import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import google_config as GC          # noqa: E402  (paths are configurable: config/google.json)

CONFIG_DIR, CREDENTIALS, TOKEN = GC.paths()
CALENDAR_SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/calendar.events",  # read + write events (add/update interviews)
]


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
    creds = None
    if os.path.exists(TOKEN):
        creds = Credentials.from_authorized_user_file(TOKEN, CALENDAR_SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not os.path.exists(CREDENTIALS):
                print(f"ERROR: {CREDENTIALS} not found. Follow state/gmail-setup.md.",
                      file=sys.stderr)
                sys.exit(2)
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS, CALENDAR_SCOPES)
            creds = flow.run_local_server(port=0)
        with open(TOKEN, "w") as f:
            f.write(creds.to_json())
    return creds


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true",
                        help="verify calendar access works and list upcoming events")
    parser.add_argument("--days", type=int, default=7,
                        help="number of days to list events for (with --check)")
    args = parser.parse_args()

    if not args.check:
        creds = authenticate()
        print(f"Token saved to {TOKEN}")
        print("Scopes:", CALENDAR_SCOPES)
        return

    creds = authenticate()
    _, _, _, build = _import_google()
    service = build("calendar", "v3", credentials=creds)
    from datetime import datetime, timedelta, timezone
    now = datetime.now(timezone.utc).isoformat()
    later = (datetime.now(timezone.utc) + timedelta(days=args.days)).isoformat()
    events = service.events().list(
        calendarId="primary", timeMin=now, timeMax=later,
        singleEvents=True, orderBy="startTime",
    ).execute()
    print(f"\nUpcoming events (next {args.days} days):\n")
    for ev in events.get("items", []):
        start = ev["start"].get("dateTime", ev["start"].get("date"))
        print(f"  {start}  {ev.get('summary', '(no title)')}")


if __name__ == "__main__":
    main()
