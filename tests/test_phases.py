import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import watch_queue  # noqa: E402


def phases(text):
    return [label for rx, label in watch_queue.PHASES if re.search(rx, text, re.I)]


def test_review_prose_is_not_an_apply_run():
    for text in (
        "You are PREPARING documents for ONE job (REVIEW, no submission). "
        "Do NOT open the browser, do NOT upload, do NOT submit anything.",
        "Read the job ad and select the best evidence for this role.",
        "Write the cover letter and fill both pages of the CV.",
    ):
        got = phases(text)
        assert "Filling application form" not in got, (text, got)
        assert "Submitting" not in got, (text, got)
        assert "Uploading CV + cover letter" not in got, (text, got)


def test_real_browser_commands_keep_their_labels():
    assert "Filling application form" in phases(
        'python3 tools/camoufox_browser.py --server http://127.0.0.1:9872 fill "#first" "Peter"')
    assert "Uploading CV + cover letter" in phases(
        'python3 tools/camoufox_browser.py --server http://127.0.0.1:9872 upload "#cv" documents/cv.docx')
