import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))

import writing_style as WS


def test_plain_prose_passes():
    text = ("Hi Anders,\n\nCircling back on the call we pencilled in for today. "
            "Happy to move it rather than keep trading emails.\n\nBest regards,\nAlex")
    assert WS.check(text) == []


def test_em_dash_is_a_hard_failure():
    errors = WS.check("The build was slow \u2014 forty minutes \u2014 so we fixed it.")
    assert any("em dash" in e for e in errors)


def test_slop_vocabulary_and_phrases_are_caught():
    for text in ("We leverage the platform to unlock value.",
                 "It's worth noting that the team shipped it.",
                 "This is not just a migration but a rebuild.",
                 "Here's the thing: the evals mattered more."):
        assert WS.check(text), text


def test_harness_as_a_noun_is_allowed():
    assert WS.check("The agent harness runs each task in its own profile.") == []


def test_email_draft_is_refused_when_sloppy(tmp_path):
    body = tmp_path / "body.txt"
    body.write_text("Hi,\n\nWe leverage a robust pipeline \u2014 it is seamless.\n\nAlex\n",
                    encoding="utf-8")
    out = subprocess.run(
        [sys.executable, "tools/draft_email.py", "--company", "Example AB",
         "--role", "Test Role", "--to", "someone@example.com",
         "--subject", "Hello", "--body-file", str(body)],
        cwd=ROOT, capture_output=True, text=True)
    assert out.returncode == 2
    assert "plain English" in (out.stderr + out.stdout)
    assert not os.path.isdir(os.path.join(ROOT, "state", "drafts", "example-ab-test-role"))


def test_pre_submit_gate_uses_the_same_rules():
    sys.path.insert(0, os.path.join(ROOT, "tools"))
    import check_documents as CD
    errors, warnings = [], []
    CD.check_slop(["We leverage a robust platform."], errors, warnings, label="CV")
    assert errors and any("CV:" in e for e in errors)
