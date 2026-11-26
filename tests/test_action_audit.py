"""The action column's decision table.

The rules exist so the register only shows work that is genuinely owed: a person
who asked something, recently, on a role that is still alive. Everything else is
a note. These cases are the ones that used to leak into the column.

Names, addresses and companies here are synthetic on purpose: this file ships in
the public clone.
"""
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

import action_audit as AA  # noqa: E402

TODAY = date(2026, 11, 26)


def test_closed_role_never_needs_you():
    keep, why, _ = AA.decide("REJECTED", "reply to the recruiter", date(2026, 10, 16), None, TODAY)
    assert not keep and "closed" in why


def test_our_own_idea_is_not_an_action():
    keep, why, _ = AA.decide("INTERVIEW", "decide whether to send the follow-up draft",
                             date(2026, 11, 20), None, TODAY)
    assert not keep


def test_no_inbound_mail_at_all():
    keep, why, _ = AA.decide("SUBMITTED", "reply about the travel question", None,
                             date(2026, 11, 11), TODAY)
    assert not keep and "no mail" in why


def test_last_word_was_ours():
    keep, why, _ = AA.decide("SUBMITTED", "reply with an expected rate",
                             date(2026, 11, 13), date(2026, 11, 14), TODAY)
    assert not keep and "ours" in why


def test_quiet_thread_expires():
    keep, why, _ = AA.decide("INTERVIEW", "reply to the recruiter", date(2026, 10, 16), None,
                             TODAY, max_age=21)
    assert not keep and "quiet" in why


def test_recent_question_is_kept():
    keep, why, prefix = AA.decide("INTERVIEW", "reply to the recruiter", date(2026, 11, 25),
                                  None, TODAY)
    assert keep and prefix == ""


def test_older_but_live_question_is_marked_stale():
    keep, why, prefix = AA.decide("INTERVIEW", "reply to the recruiter", date(2026, 11, 13),
                                  None, TODAY, warn_after=7)
    assert keep and prefix == "stale 13d: "


def test_stale_prefix_is_not_doubled():
    keep, why, prefix = AA.decide("INTERVIEW", "stale 13d: reply to the recruiter",
                                  date(2026, 11, 13), None, TODAY)
    assert keep and prefix == "stale 13d: "
    assert AA.strip_stale(prefix + "reply to the recruiter") == "reply to the recruiter"


def test_same_day_answer_keeps_the_later_question():
    # A question at 15:15 after our 14:51 reply is still owed: same day, later hour.
    asked = AA.parse_date("Fri, 13 Nov 2026 15:15:19 +0000")
    replied = AA.parse_date("Fri, 13 Nov 2026 14:51:32 +0000")
    keep, why, _ = AA.decide("SUBMITTED", "reply to the recruiter", asked, replied, TODAY)
    assert keep, why


def test_same_day_where_we_had_the_last_word_clears():
    replied = AA.parse_date("Fri, 13 Nov 2026 15:15:19 +0000")
    asked = AA.parse_date("Fri, 13 Nov 2026 14:51:32 +0000")
    keep, why, _ = AA.decide("SUBMITTED", "reply to the recruiter", asked, replied, TODAY)
    assert not keep and "ours" in why


def test_contacts_come_from_the_rows_own_notes():
    row = {"notes": "2026-11-13: email sent to alex@example.com (message id 1)", "action": ""}
    got = AA.contacts(row)
    assert "alex@example.com" in got


def test_query_uses_known_addresses_before_a_company_word():
    row = {"company": "ExampleCorp", "notes": "alex@example.com", "action": ""}
    q = AA.query_for(row, 180)
    assert "from:(alex@example.com)" in q and "newer_than:180d" in q
