"""Page-fill and content-budget checks: a two-page CV must actually be full."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))

import cv_fill
import cv_target


def _fake(pages, fills, words=1000):
    return {
        "pages": pages,
        "words": words,
        "page": [{"height": 842.0, "bottom": f * 842.0, "fill": f, "words": words // pages}
                 for f in fills],
    }


def test_full_two_pages_pass(monkeypatch):
    monkeypatch.setattr(cv_fill, "measure", lambda p: _fake(2, [0.99, 0.88]))
    ok, problems, m = cv_fill.assess("x.pdf")
    assert ok and not problems and m["pages"] == 2


def test_half_empty_second_page_fails(monkeypatch):
    monkeypatch.setattr(cv_fill, "measure", lambda p: _fake(2, [0.99, 0.49]))
    ok, problems, _ = cv_fill.assess("x.pdf")
    assert not ok
    assert any("only 49%" in p for p in problems)


def test_single_page_fails(monkeypatch):
    monkeypatch.setattr(cv_fill, "measure", lambda p: _fake(1, [0.95]))
    ok, problems, _ = cv_fill.assess("x.pdf")
    assert not ok
    assert any("only 1 page" in p for p in problems)


def test_third_page_fails(monkeypatch):
    monkeypatch.setattr(cv_fill, "measure", lambda p: _fake(3, [0.95, 0.99, 0.4]))
    ok, problems, _ = cv_fill.assess("x.pdf")
    assert not ok
    assert any("trim to 2" in p for p in problems)


def test_threshold_is_configurable(monkeypatch):
    monkeypatch.setattr(cv_fill, "measure", lambda p: _fake(2, [0.95, 0.62]))
    assert not cv_fill.assess("x.pdf", min_fill=0.70)[0]
    assert cv_fill.assess("x.pdf", min_fill=0.60)[0]


def test_content_stats_counts_split_bullets_and_groups():
    data = {
        "profile": "one two three",
        "skills": ["a", "b"],
        "experience": [
            {"bullets": ["a b c", "d e"], "groups": [{"bullets": ["f g h"]}]},
            {"bullets": ["i j"]},
        ],
        "selected_work": ["x"],
    }
    st = cv_target.content_stats(data)
    assert st["roles"] == 2
    assert st["bullets"] == 4
    assert st["experience_words"] == 10
    assert st["profile_words"] == 3


def test_thin_pack_names_what_to_fix():
    reasons = cv_target.thin_reasons(
        {"bullets": 21, "profile_words": 79, "selected": 2, "skills": 4})
    joined = " ".join(reasons)
    assert "21 bullets" in joined
    assert "79 words" in joined
    assert "2 selected-work" in joined
