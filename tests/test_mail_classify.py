"""Mail classification: conditional boilerplate must not read as a rejection."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))

from gmail_readonly import classify  # noqa: E402


def test_conditional_not_selected_is_not_a_rejection():
    body = (
        "Hello Peter Thank you for taking the time to send us your application for the position of "
        "Lead AI Engineer (Remote) at Finom. Our team will review your application and will be in "
        "touch within 1 week. If you are not selected for this position, keep an eye on our jobs page."
    )
    assert classify("Thank you for your application to Finom", body) == "CONFIRMATION"


def test_real_rejection_still_reads_as_rejection():
    body = (
        "Dear Peter, Thank you for your application. After careful review we have decided to move "
        "forward with other candidates."
    )
    assert classify("Thank you for your application", body) == "REJECTION"


def test_refusal_phrased_as_invitation_is_a_rejection():
    body = (
        "Unfortunately, we can't invite you for an interview this time, but there are always new "
        "opportunities. It's not a match this time."
    )
    assert classify("Your application at Maandag", body) == "REJECTION"


def test_cancelled_meeting_is_not_an_interview():
    body = "Hi Peter, your meeting with Bannerflow has been cancelled."
    assert classify("Meeting cancelled: A first call with Bannerflow", body) == "OTHER"


def test_verification_mail_wins():
    assert classify("Please verify your new device", "Confirm this sign-in") == "VERIFICATION"


def test_an_interview_reply_that_withdraws_is_not_an_invitation():
    """'Re: Interview Invitation' can cancel or redirect: it is not an interview."""
    from gmail_readonly import classify
    subject = "Re: Thomson Reuters Interview Invitation for Senior Manager, Product Analytics"
    body = ("Hi Peter, I'm very sorry about the confusion. The opening for Sweden is still active so I "
            "will include the link so you can apply to the correct listing. This is managed by a "
            "different team so I would not be able to progress your application myself.")
    assert classify(subject, body) == "OTHER"


def test_a_real_invitation_and_a_reschedule_still_count():
    from gmail_readonly import classify
    assert classify("Your interview invitation @ Datatonic",
                    "Tuesday 10 Nov 2026 14:00-15:00. Join with the Google Meet link.") == "INTERVIEW"
    assert classify("Rescheduled: interview with Acme",
                    "Your interview has been moved to Thursday 10:00.") == "INTERVIEW"
    assert classify("Canceled: Interview", "The meeting has been cancelled.") == "OTHER"
