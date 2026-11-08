import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_draft_replies_do_not_volunteer_salary():
    with open(os.path.join(ROOT, "tools", "web", "app.js"), encoding="utf-8") as fh:
        app = fh.read()
    assert "Do not mention salary, rate, pay or benefits unless I explicitly ask" in app
    assert "[rate to confirm]" in app
    with open(os.path.join(ROOT, "AGENTS.md"), encoding="utf-8") as fh:
        agents = fh.read()
    assert "Never volunteer salary, rate, pay or benefits" in agents
    assert "[rate to confirm]" in agents
    assert "never name employers, stages or deadlines" in " ".join(app.split()).lower()
    assert "never name employers, stages or deadlines" in " ".join(agents.split()).lower()


def test_an_approved_email_advances_an_email_only_blocked_row():
    with open(os.path.join(ROOT, "tools", "gmail_send.py"), encoding="utf-8") as fh:
        send = fh.read()
    assert 'row["status"] == "BLOCKED" and email_block' in send
    assert "email application" in send
