import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

import calendar_event as ce


def _event(tzid):
    return "\n".join([
        "BEGIN:VCALENDAR",
        "BEGIN:VEVENT",
        f"DTSTART;TZID={tzid}:20261118T143000",
        f"DTEND;TZID={tzid}:20261118T151500",
        "SUMMARY:Interview",
        "END:VEVENT",
        "END:VCALENDAR",
    ])


def test_outlook_romance_standard_time_maps_to_cet():
    ev = ce._parse_ics(_event("Romance Standard Time"), "Europe/Berlin")
    assert ev["start"].isoformat() == "2026-11-18T14:30:00+01:00"
    assert ev["end"].isoformat() == "2026-11-18T15:15:00+01:00"


def test_outlook_w_europe_standard_time_maps_to_cet():
    ev = ce._parse_ics(_event("W. Europe Standard Time"), "Europe/Berlin")
    assert ev["start"].isoformat() == "2026-11-18T14:30:00+01:00"


def test_unknown_tzid_falls_back_to_the_default():
    ev = ce._parse_ics(_event("Somewhere Standard Time"), "Europe/Berlin")
    assert ev["start"].isoformat() == "2026-11-18T14:30:00+01:00"
