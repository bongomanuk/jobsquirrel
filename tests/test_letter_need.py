import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))

import letter_need as L


def test_a_named_letter_is_required():
    for text in (
        "Please attach a cover letter with your application.",
        "A cover letter is required.",
        "Submit your CV and a brief cover letter.",
        "Click apply and include your resume and cover letter in English.",
        "Du skickar in ditt CV och personliga brev via ansökningsknappen.",
        "Bifoga gärna ett personligt brev.",
    ):
        assert L.required(text)[0] is True, text


def test_optional_and_negated_letters_are_not_generated():
    for text in (
        "Cover letter (optional).",
        "No cover letter required.",
        "We do not require a cover letter.",
        "Cover letter: not mandatory, but nice to have.",
        "Personligt brev är meriterande.",
        "Sök utan personligt brev.",
        "I den här rekryteringsprocessen önskar vi inget personligt brev.",
        "Istället för ett personligt brev besvarar du urvalsfrågor.",
        "Personligt brev använder vi inte som urvalsmetod och behöver därför inte bifogas.",
    ):
        assert L.required(text)[0] is False, text


def test_no_mention_means_cv_only():
    assert L.required("Send your CV. Interviews start in May.")[0] is False
    assert L.required("")[0] is False


def test_the_prepare_prompts_follow_the_need_file():
    with open(os.path.join(ROOT, "tools", "run_queue.sh"), encoding="utf-8") as fh:
        sh = fh.read()
    assert "state/letters/$key.need" in sh
    assert "--letter-mode yes" in sh
    assert "${LETTER_GATE}--cv" in sh
    assert "only when the advert" in sh or "only if required" in sh
