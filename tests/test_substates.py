"""Date-aware sub-states: past interviews and missed assessment deadlines."""
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))
import dashboard as D  # noqa: E402


def _when(days):
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(time.time() + days * 86400))


def test_past_interview_is_held_not_scheduled():
    notes = f"{_when(-2)} interview booked with the team | confirmed"
    label, _ = D._interview_label("INTERVIEW", notes)
    assert label == "INTERVIEW"
    assert D._substate("INTERVIEW", notes, "", label)[0] == "held"


def test_old_interview_follows_up():
    notes = f"{_when(-10)} interview booked with the team"
    label, _ = D._interview_label("INTERVIEW", notes)
    assert D._substate("INTERVIEW", notes, "", label)[0] == "held-followup"


def test_future_interview_is_scheduled():
    notes = f"{_when(3)} interview booked with the team"
    label, _ = D._interview_label("INTERVIEW", notes)
    assert label == "SCHEDULED"
    assert D._substate("INTERVIEW", notes, "", label)[0] == "scheduled"


def test_interview_today():
    today = time.strftime("%Y-%m-%d") + " 23:59"
    notes = f"{today} interview booked with the team"
    label, _ = D._interview_label("INTERVIEW", notes)
    assert D._substate("INTERVIEW", notes, "", label)[0] == "today"


def test_next_round_marker_wins():
    notes = f"{_when(-2)} interview held | next round with the hiring manager"
    label, _ = D._interview_label("INTERVIEW", notes)
    assert D._substate("INTERVIEW", notes, "", label)[0] == "next"


def test_assessment_deadline_past_and_future():
    assert D._substate("SUBMITTED", f"assessment test link expires ~{_when(-2)}",
                       "", "SUBMITTED")[0] == "assessment-overdue"
    assert D._substate("SUBMITTED", f"assessment test link expires ~{_when(3)}",
                       "", "SUBMITTED")[0] == "assessment"
