import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as fh:
        return fh.read()


def test_the_cascade_bundle_is_vendored_and_exported():
    bundle = _read("tools/web/vendor/cascade.js")
    assert len(bundle) > 50_000
    assert "flipAnimationContainer" in bundle
    assert "DOMElementTarget" in bundle
    assert os.path.exists(os.path.join(ROOT, "tools/web/vendor/cascade.NOTICE"))


def test_the_activity_island_is_wired_into_the_page():
    html = _read("tools/web/index.html")
    module = _read("tools/web/cascade-islands.js")
    assert 'id="act-roster"' in html
    assert "/cascade-islands.js" in html
    assert "./vendor/cascade.js" in module
    assert "window.CascadeIslands" in module
    assert "flipAnimationContainer" in module


def test_the_dashboard_serves_the_island_and_the_bundle():
    dash = _read("tools/dashboard.py")
    assert '"/cascade-islands.js"' in dash
    assert '"/vendor/cascade.js"' in dash
    assert '"cascade-islands.js"' in dash  # asset fingerprint


def test_the_grid_and_the_drawer_are_cascade_islands():
    module = _read("tools/web/cascade-islands.js")
    for name in ("class GridRows", "class RawRow", "class DrawerTabs", "class DrawerBody"):
        assert name in module, name
    assert "window.CascadeIslands.grid" in module
    assert "window.CascadeIslands.drawer" in module
    app = _read("tools/web/app.js")
    assert "window.CascadeIslands.grid" in app
    assert "window.CascadeIslands.drawer" in app
    assert "display: 'contents'" in module


def test_deep_links_and_the_page_title_use_cascade_routing():
    module = _read("tools/web/cascade-islands.js")
    app = _read("tools/web/app.js")
    dash = _read("tools/dashboard.py")
    assert "browserLocation" in module
    assert "documentHead" in module
    assert "window.CascadeIslands.router" in module
    assert "window.CascadeIslands.head" in module
    assert "routeFromUrl" in app and "router.navigate(['role'" in app
    assert '"/role"' in dash or "startswith(\"/role/\")" in dash


def test_the_toolbar_and_knowledge_search_are_cascade_islands():
    module = _read("tools/web/cascade-islands.js")
    app = _read("tools/web/app.js")
    for name in ("class ToolbarExtra", "class KgResults", "class KgTabs"):
        assert name in module, name
    assert "overflowContainer" in module
    assert "window.CascadeIslands.knowledge" in module
    assert "kgShowResults" in app
    assert 'id="toolbar-extra"' in _read("tools/web/index.html")


def test_the_context_menu_is_a_cascade_overlay():
    module = _read("tools/web/cascade-islands.js")
    app = _read("tools/web/app.js")
    assert "class CtxMenuRoot" in module
    assert "overlayFrame" in module and "overlay(" in module
    assert "window.CascadeIslands.menu" in module
    assert "CascadeIslands.menu" in app
    assert 'id="cascade-overlays"' in _read("tools/web/index.html")
