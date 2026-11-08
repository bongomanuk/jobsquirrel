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
