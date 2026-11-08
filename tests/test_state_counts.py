import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_state_map_counts_only_active_roles():
    with open(os.path.join(ROOT, "tools", "web", "app.js"), encoding="utf-8") as fh:
        app = fh.read()
    assert "const liveRows = GRID.filter(r => !r.shelved);" in app
    assert "liveRows.forEach(r => { counts[r.status]" in app
    assert "shelvedBy[n.s]" in app
    assert "see SHELVED" in app
