import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP = os.path.join(ROOT, "tools", "web", "app.js")


def _app():
    with open(APP, encoding="utf-8") as fh:
        return fh.read()


def test_state_map_counts_only_active_roles():
    app = _app()
    assert "const liveRows = GRID.filter(r => !r.shelved);" in app
    assert "liveRows.forEach(r => { counts[r.status]" in app
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
    assert "live.filter(r => !r.shelved && (r.focus || r.focus_unknown)).length" in app
    assert "if (r.shelved || !r.substate) return;" in app


def test_no_result_has_its_own_state_node():
    app = _app()
    assert "{ s: 'NO RESULT', x: 370, note: 'run produced nothing' }" in app
