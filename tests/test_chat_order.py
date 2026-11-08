import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP = os.path.join(ROOT, "tools", "web", "app.js")


def _app():
    with open(APP, encoding="utf-8") as fh:
        return fh.read()


def test_action_and_finished_task_cards_are_inserted_in_the_transcript():
    app = _app()
    # The card remembers the segment index where it started or finished and is
    # emitted at that boundary, not appended after the whole transcript.
    assert "let ACT_AT = 0, ACT_KEY = '', ACT_SEQ = 0, CARD_SEQ = 1;" in app
    assert "cards.push({ at: Math.min(ACT_AT, segs.length)" in app
    assert "for (const c of chunks) { emit(c.start); h += c.html; }" in app
    assert "emit(segs.length);" in app


def test_page_load_does_not_replay_an_old_finished_task_at_the_bottom():
    app = _app()
    assert "DONE_CARDS = done.slice(0, 1)" not in app
    assert "DELEGATED_DONE_SEEN = doneIds;" in app
    # A fresh completion is still placed at the point it finished.
    assert "const at = (CHAT.segments || []).length;" in app
    assert "DONE_CARDS.push(...freshDone.slice(-3)" in app
