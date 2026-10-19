#!/usr/bin/env python3
"""Create, update and import Google Calendar events (interviews, calls).

Uses the same OAuth token as Gmail (gmail.readonly + gmail.send +
calendar.events). Config: config/calendar.json

Usage:
  python3 tools/calendar_event.py list [--days 14]
  python3 tools/calendar_event.py create --title "Interview: Acme" \
      --start "2026-10-22 14:00" --duration 45 --attendees a@b.com --location "Teams"
  python3 tools/calendar_event.py from-message <gmail-message-id>
  python3 tools/calendar_event.py update <event-id> --start "2026-10-23 10:00"

Writes are approval-gated (APPROVE_CALENDAR_WRITE=1, or answer y). Use --dry-run
to print the event that would be created without writing anything.
"""
import argparse
import base64
import html as htmllib
import json
import os
import re
import sys
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG = os.environ.get("CALENDAR_CONFIG", os.path.join(ROOT, "config", "calendar.json"))
DEFAULT_DURATION = 45
DEFAULTS = {
    "calendar_id": "primary",
    "timezone": "Europe/Stockholm",
    "default_duration_minutes": 45,
    "invite_attendees": True,
    "working_hours": {"start": "08:00", "end": "18:00"},
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


def _service():
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import gmail_calendar_auth as C
    creds = C.authenticate()
    _, _, _, build = C._import_google()
    return build("calendar", "v3", credentials=creds)


def _parse_dt(value, tzname):
    tz = ZoneInfo(tzname)
    s = (value or "").strip()
    if not s:
        raise ValueError("empty date/time")
    if s.endswith("Z"):
        return datetime.fromisoformat(s[:-1]).replace(tzinfo=ZoneInfo("UTC"))
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M:%S",
                "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d", "%d/%m/%Y %H:%M", "%Y%m%dT%H%M%S"):
        try:
            dt = datetime.strptime(s, fmt)
            return dt.replace(tzinfo=tz) if dt.tzinfo is None else dt
        except ValueError:
            continue
    dt = datetime.fromisoformat(s)
    return dt.replace(tzinfo=tz) if dt.tzinfo is None else dt


def _working_hours_warning(start, cfg):
    wh = cfg.get("working_hours") or {}
    try:
        lo = time.fromisoformat(wh.get("start", "00:00"))
        hi = time.fromisoformat(wh.get("end", "23:59"))
    except ValueError:
        return
    if start.weekday() >= 5 or not (lo <= start.time() <= hi):
        print(f"note: {start:%a %H:%M} is outside working hours "
              f"({wh.get('start')}-{wh.get('end')}, Mon-Fri)", file=sys.stderr)


def _event_body(args, cfg):
    tzname = args.timezone or cfg.get("timezone") or DEFAULTS["timezone"]
    start = _parse_dt(args.start, tzname)
    if args.end:
        end = _parse_dt(args.end, tzname)
    else:
        minutes = args.duration or int(cfg.get("default_duration_minutes") or 45)
        end = start + timedelta(minutes=minutes)
    if end <= start:
        raise SystemExit("end must be after start")
    _working_hours_warning(start, cfg)
    body = {
        "summary": args.title,
        "start": {"dateTime": start.isoformat(), "timeZone": tzname},
        "end": {"dateTime": end.isoformat(), "timeZone": tzname},
    }
    if args.location:
        body["location"] = args.location
    if args.description:
        body["description"] = args.description
    attendees = [a.strip() for a in (args.attendees or []) if a.strip()]
    if attendees:
        body["attendees"] = [{"email": a} for a in attendees]
    return body, attendees, start, end


def _create(args, cfg, svc):
    body, attendees, start, end = _event_body(args, cfg)
    if args.dry_run:
        print(json.dumps(body, indent=2))
        return
    import approval
    who = f", inviting {', '.join(attendees)}" if attendees else ""
    if not approval.approved(f"adding calendar event {args.title!r} at {start:%Y-%m-%d %H:%M}{who}",
                             "CALENDAR-WRITE"):
        print("refused: calendar writes need explicit approval "
              "(APPROVE_CALENDAR_WRITE=1, or answer y).", file=sys.stderr)
        sys.exit(4)
    invite = bool(attendees) and cfg.get("invite_attendees", True) and not args.no_invite
    ev = svc.events().insert(calendarId=cfg.get("calendar_id") or "primary", body=body,
                             sendUpdates="all" if invite else "none").execute()
    print(f"created {ev.get('id')}  {start:%Y-%m-%d %H:%M}-{end:%H:%M}")
    if ev.get("htmlLink"):
        print(ev["htmlLink"])


def _update(args, cfg, svc):
    cid = cfg.get("calendar_id") or "primary"
    ev = svc.events().get(calendarId=cid, eventId=args.event_id).execute()
    tzname = args.timezone or (ev.get("start") or {}).get("timeZone") or cfg.get("timezone")
    patch = {}
    if args.title:
        patch["summary"] = args.title
    if args.start:
        start = _parse_dt(args.start, tzname)
        minutes = args.duration or int(cfg.get("default_duration_minutes") or 45)
        end = _parse_dt(args.end, tzname) if args.end else start + timedelta(minutes=minutes)
        patch["start"] = {"dateTime": start.isoformat(), "timeZone": tzname}
        patch["end"] = {"dateTime": end.isoformat(), "timeZone": tzname}
    if args.location is not None:
        patch["location"] = args.location
    if args.description is not None:
        patch["description"] = args.description
    if not patch:
        raise SystemExit("nothing to update")
    if args.dry_run:
        print(json.dumps(patch, indent=2))
        return
    import approval
    if not approval.approved(f"updating calendar event {ev.get('summary', args.event_id)!r}",
                             "CALENDAR-WRITE"):
        print("refused: calendar writes need explicit approval "
              "(APPROVE_CALENDAR_WRITE=1, or answer y).", file=sys.stderr)
        sys.exit(4)
    out = svc.events().patch(calendarId=cid, eventId=args.event_id, body=patch,
                             sendUpdates="all").execute()
    start = (out.get("start") or {}).get("dateTime", (out.get("start") or {}).get("date"))
    print(f"updated {out.get('id')}  {start}  {out.get('summary', '')}")


def _list(args, cfg, svc):
    now = datetime.now(ZoneInfo("UTC"))
    later = now + timedelta(days=args.days)
    evs = svc.events().list(calendarId=cfg.get("calendar_id") or "primary",
                            timeMin=now.isoformat(), timeMax=later.isoformat(),
                            singleEvents=True, orderBy="startTime").execute()
    items = evs.get("items", [])
    if not items:
        print(f"no events in the next {args.days} days")
        return
    for ev in items:
        start = (ev.get("start") or {}).get("dateTime") or (ev.get("start") or {}).get("date")
        print(f"  {start}  {ev.get('summary', '(no title)')}  [{ev.get('id')}]")


def _decode_part(part, gmail=None, message_id=None):
    body = part.get("body") or {}
    data = body.get("data")
    if not data and gmail and message_id and body.get("attachmentId"):
        att = gmail.users().messages().attachments().get(
            userId="me", messageId=message_id, id=body["attachmentId"]).execute()
        data = att.get("data")
    if not data:
        return None
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4)).decode("utf-8", "replace")


def _find_ics(payload, gmail=None, message_id=None):
    stack = [payload]
    while stack:
        part = stack.pop()
        if not part:
            continue
        mime = (part.get("mimeType") or "").lower()
        name = (part.get("filename") or "").lower()
        if mime in ("text/calendar", "application/ics") or name.endswith(".ics"):
            text = _decode_part(part, gmail, message_id)
            if text:
                return text
        stack.extend(part.get("parts") or [])
    return None


def _unfold(text):
    return text.replace("\r\n", "\n").replace("\n ", "").replace("\n\t", "").split("\n")


def _unescape(value):
    value = (value.replace("\\n", "\n").replace("\\N", "\n")
             .replace("\\,", ",").replace("\\;", ";").replace("\\\\", "\\"))
    return htmllib.unescape(value)


def _clean_description(value):
    if "<" in value and ">" in value:
        value = re.sub(r"<br\s*/?>|</p>|</li>|</div>", "\n", value, flags=re.I)
        value = re.sub(r"<[^>]+>", "", value)
        value = htmllib.unescape(value)
        value = re.sub(r"\n{3,}", "\n\n", value)
    return value.strip()


def _ical_dt(line, default_tz):
    key, value = line.split(":", 1)
    params = key.split(";")[1:]
    tzid = None
    for p in params:
        if p.upper().startswith("TZID="):
            tzid = p.split("=", 1)[1]
    value = value.strip()
    if params and any(p.upper() == "VALUE=DATE" for p in params) or re.fullmatch(r"\d{8}", value):
        return date(int(value[0:4]), int(value[4:6]), int(value[6:8])), "date"
    utc = value.endswith("Z")
    raw = value.rstrip("Z")
    fmt = "%Y%m%dT%H%M%S" if "T" in raw else "%Y%m%dT%H%M"
    dt = datetime.strptime(raw, fmt)
    tz = ZoneInfo("UTC") if utc else ZoneInfo(tzid or default_tz)
    return dt.replace(tzinfo=tz), "datetime"


def _parse_ics(text, default_tz, default_minutes=DEFAULT_DURATION):
    ev = {}
    attendees = []
    inside = False
    for line in _unfold(text):
        if line == "BEGIN:VEVENT":
            inside = True
            ev = {}
            continue
        if line == "END:VEVENT":
            break
        if not inside or ":" not in line:
            continue
        prop = line.split(":", 1)[0].split(";")[0].upper()
        if prop == "ATTENDEE":
            email = line.split(":", 1)[1].strip()
            if email.lower().startswith("mailto:"):
                email = email[7:]
            if email:
                attendees.append(email)
        elif prop in ("SUMMARY", "LOCATION", "DESCRIPTION", "DTSTART", "DTEND"):
            ev.setdefault(prop, line.split(":", 1)[1])
            if prop in ("DTSTART", "DTEND"):
                ev[prop + "_LINE"] = line
    if "DTSTART_LINE" not in ev:
        raise SystemExit("the email contains a calendar file with no DTSTART")
    start, start_kind = _ical_dt(ev["DTSTART_LINE"], default_tz)
    if "DTEND_LINE" in ev:
        end, end_kind = _ical_dt(ev["DTEND_LINE"], default_tz)
    elif start_kind == "date":
        end, end_kind = start + timedelta(days=1), "date"
    else:
        end, end_kind = start + timedelta(minutes=int(default_minutes)), "datetime"
    return {
        "title": _unescape(ev.get("SUMMARY", "Calendar event")),
        "location": _unescape(ev.get("LOCATION", "")),
        "description": _clean_description(_unescape(ev.get("DESCRIPTION", ""))),
        "start": start,
        "end": end,
        "all_day": start_kind == "date" and end_kind == "date",
        "attendees": attendees,
    }


def _slots(args, cfg, svc):
    """Suggest free slots inside working hours, avoiding existing timed events."""
    tz = ZoneInfo(cfg.get("timezone") or DEFAULTS["timezone"])
    dur = args.duration or int(cfg.get("default_duration_minutes") or DEFAULT_DURATION)
    wh = cfg.get("working_hours") or {}
    lo = time.fromisoformat(wh.get("start", "08:00"))
    hi = time.fromisoformat(wh.get("end", "18:00"))
    now = datetime.now(tz)
    last = datetime.combine(now.date() + timedelta(days=args.days), time.max, tzinfo=tz)
    items = svc.events().list(calendarId=cfg.get("calendar_id") or "primary",
                              timeMin=now.isoformat(), timeMax=last.isoformat(),
                              singleEvents=True, orderBy="startTime").execute().get("items", [])
    busy = []
    for ev in items:
        s = (ev.get("start") or {}).get("dateTime")
        e = (ev.get("end") or {}).get("dateTime")
        if s and e:
            busy.append((datetime.fromisoformat(s), datetime.fromisoformat(e)))
    print(f"Free {dur}-minute slots ({tz}, next {args.days} days):")
    found = False
    for d in range(args.days):
        day = now.date() + timedelta(days=d)
        if day.weekday() >= 5:
            continue
        slots, t = [], datetime.combine(day, lo, tzinfo=tz)
        end = datetime.combine(day, hi, tzinfo=tz)
        while t + timedelta(minutes=dur) <= end and len(slots) < args.limit:
            if t >= now + timedelta(minutes=30) and not any(t < be and t + timedelta(minutes=dur) > bs for bs, be in busy):
                slots.append(t.strftime("%H:%M"))
            t += timedelta(minutes=dur)
        if slots:
            found = True
            print(f"  {day:%a %d %b}: " + ", ".join(slots))
    if not found:
        print("  (none — widen --days or working hours)")


def _from_message(args, cfg, svc):
    import gmail_readonly as G
    gmail = G.authenticate()
    msg = gmail.users().messages().get(userId="me", id=args.message_id, format="full").execute()
    ics = _find_ics(msg.get("payload") or {}, gmail, args.message_id)
    if not ics:
        raise SystemExit("no .ics / text/calendar part in that message")
    parsed = _parse_ics(ics, cfg.get("timezone") or DEFAULTS["timezone"],
                        int(cfg.get("default_duration_minutes") or DEFAULT_DURATION))
    cid = cfg.get("calendar_id") or "primary"
    start, end = parsed["start"], parsed["end"]
    if parsed["all_day"]:
        body = {"summary": parsed["title"], "start": {"date": start.isoformat()},
                "end": {"date": end.isoformat()}}
    else:
        body = {"summary": parsed["title"],
                "start": {"dateTime": start.isoformat(), "timeZone": str(start.tzinfo)},
                "end": {"dateTime": end.isoformat(), "timeZone": str(end.tzinfo)}}
    if parsed["location"]:
        body["location"] = parsed["location"]
    if parsed["description"]:
        body["description"] = parsed["description"]
    me = gmail.users().getProfile(userId="me").execute().get("emailAddress", "").lower()
    attendees = [a for a in parsed["attendees"] if a.lower() != me]
    if attendees:
        body["attendees"] = [{"email": a} for a in attendees]
    print(f"found: {parsed['title']}  {start} -> {end}")
    if args.dry_run:
        print(json.dumps(body, indent=2, default=str))
        return
    if isinstance(start, datetime):
        lo, hi = start - timedelta(hours=1), end + timedelta(hours=1)
    else:
        lo = datetime.combine(start, time.min).replace(tzinfo=ZoneInfo("UTC"))
        hi = datetime.combine(end, time.min).replace(tzinfo=ZoneInfo("UTC"))
    existing = svc.events().list(calendarId=cid, timeMin=lo.isoformat(), timeMax=hi.isoformat(),
                                 singleEvents=True).execute().get("items", [])
    for ev in existing:
        if (ev.get("summary") or "").strip() == parsed["title"].strip():
            print(f"already on the calendar: {ev.get('htmlLink', ev.get('id'))}")
            return
    import approval
    if not approval.approved(f"adding calendar invite {parsed['title']!r} ({start})", "CALENDAR-WRITE"):
        print("refused: calendar writes need explicit approval "
              "(APPROVE_CALENDAR_WRITE=1, or answer y).", file=sys.stderr)
        sys.exit(4)
    notify = bool(body.get("attendees")) and not args.no_invite
    ev = svc.events().insert(calendarId=cid, body=body,
                             sendUpdates="all" if notify else "none").execute()
    print(f"created {ev.get('id')}")
    if ev.get("htmlLink"):
        print(ev["htmlLink"])


def main():
    cfg = _config()
    ap = argparse.ArgumentParser(description="Create/import/list calendar events.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def add_common(p, require_title=False):
        p.add_argument("--title", required=require_title)
        p.add_argument("--start", required=require_title)
        p.add_argument("--end")
        p.add_argument("--duration", type=int, help="minutes (default from config)")
        p.add_argument("--timezone")
        p.add_argument("--attendees", action="append", default=[])
        p.add_argument("--location")
        p.add_argument("--description")
        p.add_argument("--no-invite", action="store_true", help="do not email attendees")
        p.add_argument("--dry-run", action="store_true")

    p = sub.add_parser("create", help="create an event")
    add_common(p, require_title=True)
    p = sub.add_parser("update", help="update an existing event")
    p.add_argument("event_id")
    add_common(p)
    p = sub.add_parser("from-message", help="import the .ics attached to a Gmail message")
    p.add_argument("message_id")
    p.add_argument("--no-invite", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    p = sub.add_parser("list", help="list upcoming events")
    p.add_argument("--days", type=int, default=14)
    p = sub.add_parser("slots", help="suggest free interview slots (read-only)")
    p.add_argument("--days", type=int, default=5)
    p.add_argument("--duration", type=int)
    p.add_argument("--limit", type=int, default=4, help="slots per day")

    args = ap.parse_args()
    svc = _service()
    if args.cmd == "create":
        _create(args, cfg, svc)
    elif args.cmd == "update":
        _update(args, cfg, svc)
    elif args.cmd == "from-message":
        _from_message(args, cfg, svc)
    elif args.cmd == "slots":
        _slots(args, cfg, svc)
    else:
        _list(args, cfg, svc)


if __name__ == "__main__":
    main()
