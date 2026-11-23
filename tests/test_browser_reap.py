"""The browser reaper's decision table.

The rules exist so a live session is never killed: a page showing a real URL is
always kept, a runner in progress suppresses age-based cleanup, and ports in
browser-affinity.json survive while their page is alive.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

import browser_reap as BR  # noqa: E402

CTX = {"protected": {9896}, "runner_active": False, "max_age_h": 6.0, "min_ephemeral_h": 1.0}


def srv(port=9800, profile="/home/pete/.config/job-search/profiles/work-9800", age=10.0):
    return {"pid": 1, "port": port, "profile": profile, "ppid": 1546, "age_h": age}


def test_dead_page_is_reaped():
    assert BR.classify(srv(), page_alive=False, health_ok=True, url="", ctx=CTX) == "dead page"


def test_silent_port_is_reaped():
    assert BR.classify(srv(), page_alive=False, health_ok=False, url="", ctx=CTX) == "not answering"


def test_live_page_is_kept():
    assert BR.classify(srv(), page_alive=True, health_ok=True,
                       url="https://www.linkedin.com/feed/", ctx=CTX) == ""


def test_protected_port_survives_while_alive():
    assert BR.classify(srv(port=9896), page_alive=True, health_ok=True,
                       url="about:blank", ctx=CTX) == ""


def test_protected_port_is_reaped_when_dead():
    assert BR.classify(srv(port=9896), page_alive=False, health_ok=True, url="", ctx=CTX)


def test_old_blank_server_is_reaped():
    assert BR.classify(srv(), page_alive=True, health_ok=True,
                       url="about:blank", ctx=CTX) == "idle and old"


def test_young_blank_server_is_kept():
    assert BR.classify(srv(age=0.2), page_alive=True, health_ok=True,
                       url="about:blank", ctx=CTX) == ""


def test_tmp_profile_is_reaped_once_past_the_grace_period():
    assert BR.classify(srv(profile="/tmp/playwright_firefoxdev_profile-x", age=2),
                       page_alive=True, health_ok=True, url="about:blank",
                       ctx=CTX) == "ephemeral profile"
    assert BR.classify(srv(profile="/tmp/playwright_firefoxdev_profile-x", age=0.1),
                       page_alive=True, health_ok=True, url="about:blank",
                       ctx={**CTX, "max_age_h": 99}) == ""


def test_runner_in_progress_suppresses_age_cleanup():
    ctx = {**CTX, "runner_active": True, "protected": set()}
    assert BR.classify(srv(), page_alive=True, health_ok=True,
                       url="about:blank", ctx=ctx) == ""


def test_runner_does_not_protect_a_dead_page():
    ctx = {**CTX, "runner_active": True}
    assert BR.classify(srv(), page_alive=False, health_ok=True, url="", ctx=ctx) == "dead page"


def test_dashboard_left_open_is_reaped():
    url = "http://127.0.0.1:8765/?v=1#universe"
    assert BR.classify(srv(age=3), page_alive=True, health_ok=True,
                       url=url, ctx=CTX) == "dashboard left open"


def test_dashboard_is_kept_while_a_runner_is_active():
    ctx = {**CTX, "runner_active": True}
    url = "http://127.0.0.1:8765/#universe"
    got = BR.classify(srv(age=3), page_alive=True, health_ok=True, url=url, ctx=ctx)
    assert got != "dashboard left open"


def test_dashboard_is_kept_while_young():
    url = "http://localhost:8765/#universe"
    assert BR.classify(srv(age=0.1), page_alive=True, health_ok=True,
                       url=url, ctx=CTX) == ""


def test_a_real_site_is_never_mistaken_for_the_dashboard():
    url = "https://127.0.0.1.evil.example/8765/"
    got = BR.classify(srv(age=9), page_alive=True, health_ok=True, url=url, ctx=CTX)
    assert got != "dashboard left open"
