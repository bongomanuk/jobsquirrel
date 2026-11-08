import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as fh:
        return fh.read()


def test_every_view_is_a_dockable_panel():
    html = _read("tools/web/index.html")
    for key in ("grid", "states", "activity", "agent", "detail"):
        assert f'data-panel="{key}"' in html, key
    assert 'data-edge="center"' in html
    assert 'id="zone-center"' in html


def test_panels_support_the_centre_cell_and_stacking():
    js = _read("tools/web/app.js")
    assert "grid: { pos: localStorage.getItem('grid.pos') || 'center'" in js
    assert "activity: { pos: localStorage.getItem('activity.pos') || 'left'" in js
    assert "states: { pos: localStorage.getItem('states.pos') || 'center'" in js
    assert "edge === 'left' || edge === 'right' || edge === 'center'" in js
    assert "return 'center';" in js
    # a panel dropped on an edge is appended to that edge's stack
    assert "if (cont && el.parentElement !== cont) cont.appendChild(el);" in js


def test_reconcile_is_an_activity_header_action_not_panel_content():
    html = _read("tools/web/index.html")
    activity = html.split('<aside class="panel" id="activity"', 1)[1].split("</aside>", 1)[0]
    head = activity.split('<div class="dock-head">', 1)[1].split("</div>", 1)[0]
    assert 'id="btn-reconcile"' in head
    agent = html.split('<aside class="panel" id="dock"', 1)[1].split("</aside>", 1)[0]
    assert 'id="btn-reconcile"' not in agent
    js = _read("tools/web/app.js")
    assert 'class="act-actions"' not in js
