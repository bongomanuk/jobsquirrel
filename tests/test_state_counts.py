import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP = os.path.join(ROOT, "tools", "web", "app.js")
STATS = os.path.join(ROOT, "tools", "web", "grid-stats.js")


def _app():
    with open(APP, encoding="utf-8") as fh:
        return fh.read()


def test_state_map_counts_only_active_roles():
    app = _app()
    assert "const snap = gridStatsSnapshot();" in app
    assert "const counts = snap.status;" in app
    assert "const shelvedBy = snap.shelvedBy;" in app
    assert "shelvedBy[n.s]" in app
    assert "see SHELVED" in app


def test_a_state_node_clears_the_other_filters_so_its_count_is_what_it_shows():
    app = _app()
    handler = app.split("body.addEventListener('click', (e) => {", 1)[1]
    handler = handler.split("body.addEventListener('keydown'", 1)[0]
    clear = handler.index("clearFilterInputs();")
    assert clear < handler.index("if (st === 'SCAMS')")
    assert clear < handler.index("if (st === 'SHELVED')")
    assert clear < handler.index("const opening = SG_EXPANDED !== st;")


def test_a_shelved_role_is_counted_and_shown_under_shelved_only():
    app = _app()
    bucket = app.split("function bucketOf(r) {", 1)[1].split("}", 1)[0]
    assert bucket.index("if (r.shelved) return 'shelved';") < bucket.index("return 'scams';")
    with open(STATS, encoding="utf-8") as fh:
        stats = fh.read()
    assert "const b = r.shelved ? 'shelved' : classify(r);" in stats
    assert "if (r.shelved) {" in stats
    assert stats.index("if (r.shelved) {") < stats.index("if (r.scam &&")
    assert "if (r.focus || r.focus_unknown)" in stats
    assert "continue;" in stats


def test_no_result_is_not_an_application_state():
    app = _app()
    assert "{ s: 'NO RESULT'" not in app
    with open(os.path.join(ROOT, "tools", "web", "index.html"), encoding="utf-8") as fh:
        html = fh.read()
    assert "<option>NO RESULT</option>" not in html
