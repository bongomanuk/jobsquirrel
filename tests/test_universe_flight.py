import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as fh:
        return fh.read()


def test_the_flight_demo_is_wired_into_the_universe():
    html = _read("tools/web/index.html")
    js = _read("tools/web/graph-universe.js")
    assert 'id="uni-flight"' in html
    assert 'class="uni-hud-link"' in html
    assert "uni-flight-cta" not in html
    assert 'id="uni-flight-hud"' in html
    assert 'id="uf-take"' in html
    assert 'id="uf-tip"' in html
    assert "export function startFlight" in js
    assert "export function stopFlight" in js
    assert "export function flightTakeControls" in js
    assert "export function flightAutopilot" in js


def test_the_flight_has_a_squirrel_pilot_and_an_r2_unit():
    js = _read("tools/web/graph-universe.js")
    assert "function makeSquirrel" in js
    assert "function makeR2" in js
    assert "userData.squirrel" in js
    assert "userData.r2" in js
    assert "FLIGHT_TIPS" in js


def test_the_demo_has_several_enemy_types():
    js = _read("tools/web/graph-universe.js")
    for label in ("TIE Fighter", "TIE Interceptor", "TIE Bomber", "TIE Advanced"):
        assert label in js
    assert "makeTie" in js


def test_the_demo_keeps_flying_until_take_controls():
    js = _read("tools/web/graph-universe.js")
    # The page-level pointermove must return while autopilot is on, so moving
    # the mouse cannot silently drop the demo into manual control.
    block = js.split("page.addEventListener('pointermove'", 1)[1].split("});", 1)[0]
    assert "if (S.flight.autopilot) return;" in block
    assert "flightTakeControls()" not in block
