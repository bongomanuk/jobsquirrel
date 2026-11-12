#!/usr/bin/env python3
"""Camoufox pipeline browser server (Camoufox/Firefox only — no Chromium anywhere).

Wraps one Camoufox (patched Firefox) browser behind a tiny HTTP API so agents
can drive a persistent session via tools/camoufox_browser.py.

Usage:
  python3 tools/camoufox_server.py --port 9872            # headless
  python3 tools/camoufox_server.py --port 9871 --headful  # visible to the human
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import quote, unquote, urlsplit, urlunsplit

LOCK = threading.Lock()
PAGE = None
HEADFUL = False
CONSOLE_LOGS = []
DIALOG = {"mode": None}      # None=dismiss (Playwright default), "accept", "once", "dismiss"


def _on_dialog(d):
    """Answer JS confirm()/alert()/prompt() like a human clicking OK/Cancel."""
    mode = DIALOG.get("mode")
    try:
        if mode in ("accept", "once"):
            d.accept()
        else:
            d.dismiss()
    except Exception:
        pass
    if mode == "once":
        DIALOG["mode"] = None
EXTRA_HEADERS = {
    "X-Request-Source": "camoufox-pipeline",
    "X-Test-Owner": "jobsquirrel",
}

INTERACTIVE_JS = """() => {
  const sel = 'a[href],button,input:not([type=hidden]),textarea,select,[role=button],[role=link],[role=checkbox],[role=menuitem],[role=tab]';
  const els = [...document.querySelectorAll(sel)].filter(e => {
    const r = e.getBoundingClientRect();
    return r.width > 0 && r.height > 0 && !e.disabled;
  });
  return els.slice(0, 100).map((e, i) => ({
    ref: i,
    tag: e.tagName.toLowerCase(),
    text: (e.innerText || e.value || e.getAttribute('aria-label')
           || e.getAttribute('placeholder') || e.getAttribute('title') || '')
           .trim().slice(0, 80)
  }));
}"""

CLICK_BY_REF_JS = """(idx) => {
  const sel = 'a[href],button,input:not([type=hidden]),textarea,select,[role=button],[role=link],[role=checkbox],[role=menuitem],[role=tab]';
  const els = [...document.querySelectorAll(sel)].filter(e => {
    const r = e.getBoundingClientRect();
    return r.width > 0 && r.height > 0 && !e.disabled;
  });
  if (idx >= els.length) return null;
  els[idx].click();
  return {ref: idx, tag: els[idx].tagName.toLowerCase(),
          text: (els[idx].innerText || els[idx].value || '').trim().slice(0, 80)};
}"""


def _page():
    if PAGE is None or not PAGE.is_closed():
        return PAGE
    raise RuntimeError("browser page closed — restart camoufox_server.py")


def _as_ref(target: str):
    """Return the integer ref if target is a ref, else None.

    Agents routinely pass legacy "ref" style handles ("ref 25", "ref:25", "ref25") to
    `click`; without normalising them they are handed to Playwright as CSS
    selectors and blow up with "Unexpected token ... parsing css selector".
    A leading '#' is deliberately NOT treated as a ref (it is a CSS id).
    """
    t = (target or "").strip()
    m = re.fullmatch(r"ref[:\s]*(\d+)", t, re.I) or re.fullmatch(r"(\d+)", t)
    return int(m.group(1)) if m else None



ERROR_TITLES = ("error 400", "bad request", "that\u2019s an error", "that's an error",
                "error 403", "error 429", "error 500", "500 internal server error")


def _repair_url(url: str) -> str:
    """Undo a double-encoded query.

    Job-board and careers links are routinely copied one layer too deep, so the
    whole query arrives encoded: apply?jobId%3D...%26loc%3DGB. Google answers
    that with a 400 page. If the query has no plain key=value pair but does have
    %3D, decode it once.
    """
    try:
        parts = urlsplit(url)
    except Exception:
        return url
    q = parts.query
    if q and "%3D" in q.upper() and "=" not in q.split("&", 1)[0]:
        q = unquote(q)
        url = urlunsplit((parts.scheme, parts.netloc, parts.path, q, parts.fragment))
    return url


def _error_page(title: str, body_text: str) -> str:
    """Return a hint when the page is a bare error page, else ''."""
    t = (title or "").strip().lower()
    if any(t.startswith(e) or e in t for e in ERROR_TITLES):
        return (f"the page is an error page ({title.strip()}), not the form. The URL "
                "is probably malformed or double-encoded: go back to the application "
                "URL and let the site redirect, and never hand-build a sign-in URL.")
    return ""

def dispatch(cmd: str, body: dict) -> dict:
    page = _page()

    if cmd == "status":
        return {"ok": True, "url": page.url, "title": page.title()}

    if cmd == "nav":
        url = _repair_url((body.get("url") or "").strip())
        page.goto(url, timeout=30000, wait_until="domcontentloaded")
        # Kill CSS animations/transitions: Ashby (and others) animate widgets,
        # which makes Playwright's actionability "stable" check time out forever.
        try:
            page.add_style_tag(content="*{animation:none!important;transition:none!important;scroll-behavior:auto!important}")
        except Exception:
            pass
        hint = _error_page(page.title(), "")
        if hint:
            return {"ok": False, "error": hint, "url": page.url,
                    "title": page.title(), "repaired_url": url}
        return {"ok": True, "url": page.url, "title": page.title()}

    if cmd == "snap":
        path = body.get("path") or ""
        if path:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=path, full_page=True)
        refs = page.evaluate(INTERACTIVE_JS)
        total = len(refs)
        # `match` narrows the list without renumbering: the refs keep the index
        # the click handler uses, so a filtered snap is still safe to click from.
        # A full 100-ref dump is ~6KB of transcript per turn; filtering it to the
        # few controls that matter is most of the token saving in a form flow.
        match = str(body.get("match") or "").strip()
        if match:
            try:
                rx = re.compile(match, re.I)
            except re.error as e:
                return {"ok": False, "error": f"snap: bad match regex: {e}"}
            refs = [r for r in refs
                    if rx.search(str(r.get("text") or "")) or rx.search(str(r.get("tag") or ""))]
        return {"ok": True, "url": page.url, "title": page.title(),
                "path": path, "refs": refs, "refs_total": total}

    if cmd == "text":
        # Trimmed visible text: enough to read a confirmation or an error, far
        # cheaper than a full-page eval that the agent re-reads every turn.
        maxc = max(200, min(int(body.get("max") or 1500), 20000))
        txt = page.evaluate("() => (document.body && document.body.innerText) || ''") or ""
        txt = re.sub(r"[ \t]+", " ", txt)
        txt = re.sub(r"\n{3,}", "\n\n", txt).strip()
        return {"ok": True, "url": page.url, "title": page.title(),
                "chars": len(txt), "text": txt[:maxc]}

    if cmd == "waitfor":
        sel = str(body.get("selector") or "").strip()
        if not sel:
            return {"ok": False, "error": "waitfor: missing selector"}
        state = str(body.get("state") or "visible")
        ms = max(100, min(int(body.get("timeout") or 15000), 120000))
        t0 = time.time()
        try:
            page.wait_for_selector(sel, state=state, timeout=ms)
        except Exception as e:
            return {"ok": False,
                    "error": f"waitfor: {state} {sel!r} not seen in {ms}ms ({str(e)[:100]})",
                    "url": page.url, "title": page.title()}
        return {"ok": True, "selector": sel, "state": state,
                "waited_ms": int((time.time() - t0) * 1000), "url": page.url}

    if cmd == "waittext":
        # Event wait instead of `sleep N`: returns the moment the text appears,
        # so a fast confirmation costs 300ms and a slow one still gets its time.
        needle = str(body.get("text") or "").strip()
        if not needle:
            return {"ok": False, "error": "waittext: missing text"}
        ms = max(200, min(int(body.get("timeout") or 20000), 180000))
        rx = None
        if body.get("regex"):
            try:
                rx = re.compile(needle, re.I | re.S)
            except re.error as e:
                return {"ok": False, "error": f"waittext: bad regex: {e}"}
        t0 = time.time()
        last = ""
        while (time.time() - t0) * 1000 < ms:
            last = page.evaluate("() => (document.body && document.body.innerText) || ''") or ""
            hit = bool(rx.search(last)) if rx else (needle.lower() in last.lower())
            if hit:
                return {"ok": True, "matched": needle,
                        "waited_ms": int((time.time() - t0) * 1000),
                        "url": page.url, "title": page.title()}
            page.wait_for_timeout(250)
        return {"ok": False,
                "error": f"waittext: {needle!r} not seen in {ms}ms",
                "url": page.url, "title": page.title(),
                "text": re.sub(r"\s+", " ", last)[:300]}

    if cmd == "waiturl":
        want = str(body.get("url") or "").strip()
        if not want:
            return {"ok": False, "error": "waiturl: missing url"}
        ms = max(200, min(int(body.get("timeout") or 20000), 180000))
        rx = None
        if body.get("regex"):
            try:
                rx = re.compile(want, re.I)
            except re.error as e:
                return {"ok": False, "error": f"waiturl: bad regex: {e}"}
        t0 = time.time()
        while (time.time() - t0) * 1000 < ms:
            cur = page.url or ""
            if (rx.search(cur) if rx else want.lower() in cur.lower()):
                return {"ok": True, "url": cur, "title": page.title(),
                        "waited_ms": int((time.time() - t0) * 1000)}
            page.wait_for_timeout(250)
        return {"ok": False, "error": f"waiturl: {want!r} not reached in {ms}ms",
                "url": page.url, "title": page.title()}

    if cmd == "click":
        target = str(body.get("target") or "").strip()
        ref = _as_ref(target)
        if ref is not None:
            el = page.evaluate(CLICK_BY_REF_JS, ref)
            if el is None:
                return {"ok": False, "error": f"ref {ref} out of range (re-snap)"}
            page.wait_for_timeout(400)
            return {"ok": True, "clicked": el, "url": page.url, "title": page.title()}
        force = bool(body.get("force"))
        try:
            page.click(target, timeout=15000, force=force)
        except Exception as first:
            # Workday/ATS overlays routinely sit over the real control. A
            # normal click then times out; retrying with force dispatches the
            # same trusted event at the same coordinates without waiting for
            # actionability, which is what a human click would do anyway.
            if force:
                return {"ok": False, "error": str(first),
                        "url": page.url, "title": page.title()}
            try:
                page.click(target, timeout=8000, force=True)
            except Exception as second:
                return {"ok": False,
                        "error": f"{first} | force retry: {second}",
                        "url": page.url, "title": page.title()}
            page.wait_for_timeout(400)
            return {"ok": True, "clicked": {"selector": target, "force_fallback": True},
                    "url": page.url, "title": page.title()}
        page.wait_for_timeout(400)
        return {"ok": True, "clicked": {"selector": target},
                "url": page.url, "title": page.title()}

    if cmd == "pick":
        # Select an option from a custom listbox (Workday uxi prompts, react
        # select, etc). Synthetic JS click events are IGNORED by these widgets;
        # this locates the visible option - scrolling virtualised lists - and
        # clicks it with trusted input at its coordinates.
        text = (body.get("text") or body.get("target") or "").strip()
        open_sel = (body.get("open") or "").strip()
        if not text:
            return {"ok": False, "error": "pick: missing text"}
        if open_sel:
            try:
                page.click(open_sel, timeout=8000, force=True)
            except Exception:
                pass
            page.wait_for_timeout(900)
        FIND_JS = """(t)=>{
            const norm = s => (s||'').replace(/\\s+/g,' ').trim().toLowerCase();
            const want = norm(t);
            const boxes = [...document.querySelectorAll('[role="listbox"]')]
                .filter(b => b.offsetWidth || b.offsetHeight);
            const scopes = boxes.length ? boxes : [document];
            for (const scope of scopes) {
              const opts = [...scope.querySelectorAll('[role="option"]')];
              const hit = opts.find(o => norm(o.innerText) === want)
                       || opts.find(o => norm(o.innerText).includes(want));
              if (hit && (hit.offsetWidth || hit.offsetHeight)) {
                const r = hit.getBoundingClientRect();
                if (r.width && r.height)
                  return {found: true, x: r.left + r.width/2, y: r.top + r.height/2,
                          label: hit.innerText.trim().slice(0,80)};
              }
            }
            for (const b of boxes) b.scrollTop = Math.min(b.scrollTop + 192, b.scrollHeight);
            return {found: false};
        }"""
        hit = None
        for _ in range(40):
            res = page.evaluate(FIND_JS, text) or {}
            if res.get("found"):
                hit = res
                break
            page.wait_for_timeout(300)
        if not hit:
            return {"ok": False, "error": f"pick: no visible option matching {text!r}",
                    "url": page.url}
        page.mouse.click(hit["x"], hit["y"])
        page.wait_for_timeout(700)
        return {"ok": True, "picked": hit.get("label") or text,
                "url": page.url, "title": page.title()}

    if cmd == "fill":
        sel, text = body.get("selector") or "", body.get("text") or ""
        page.fill(sel, text, timeout=15000)
        page.wait_for_timeout(200)
        return {"ok": True, "filled": sel}

    if cmd == "type":
        # Human-like typing: focus the field, then type character by character
        # with jittered per-key delays so it is never "impossibly fast".
        import random
        sel, text = body.get("selector") or "", body.get("text") or ""
        page.click(sel, timeout=15000)
        page.wait_for_timeout(random.randint(180, 420))
        for ch in text:
            page.keyboard.type(ch, delay=random.randint(45, 155))
            page.wait_for_timeout(random.randint(25, 110))
        page.wait_for_timeout(random.randint(150, 400))
        return {"ok": True, "typed": sel}

    if cmd == "select":
        sel, value = body.get("selector") or "", body.get("value") or ""
        page.select_option(sel, value, timeout=15000)
        return {"ok": True, "selected": sel, "value": value}

    if cmd == "press":
        # Trusted key press via Playwright's keyboard. Unlike eval-dispatched
        # KeyboardEvents these are real input events, which is what Workday's
        # custom multiselect prompts listen for.
        sel = body.get("selector") or ""
        key = body.get("key") or "Enter"
        delay = int(body.get("delay") or 70)
        if sel:
            page.click(sel, timeout=15000)
            page.wait_for_timeout(250)
        page.keyboard.press(key, delay=delay)
        page.wait_for_timeout(400)
        return {"ok": True, "pressed": key, "selector": sel}

    if cmd == "check":
        sel = body.get("selector") or ""
        page.check(sel, timeout=15000)
        return {"ok": True, "checked": sel}

    if cmd == "value":
        sel = body.get("selector") or ""
        try:
            v = page.input_value(sel, timeout=5000)
        except Exception:
            v = page.text_content(sel) or ""
        return {"ok": True, "selector": sel, "value": v}

    if cmd == "frames":
        return {"ok": True, "frames": [{"url": f.url, "name": f.name}
                                        for f in page.frames]}

    if cmd in ("frame_eval", "frame_click", "frame_fill", "frame_press", "frame_snap"):
        match = str(body.get("match") or "bframe")
        frame = None
        for f in page.frames:
            if match and match in (f.url or ""):
                frame = f
                break
        if frame is None:
            # reCAPTCHA's bframe often reports an empty URL; find it by content.
            for f in page.frames:
                try:
                    text = f.evaluate("document.body ? document.body.innerText : ''")
                except Exception:
                    continue
                if any(x in text for x in ("Select all", "Press PLAY", "verify",
                                           "Verifying", "Try again")):
                    frame = f
                    break
        if frame is None:
            return {"ok": False, "error": f"no frame matching {match!r}",
                    "frames": [f.url for f in page.frames]}
        if cmd == "frame_eval":
            return {"ok": True, "result": frame.evaluate(body.get("js") or ""),
                    "url": frame.url}
        if cmd == "frame_snap":
            path = str(body.get("path") or "")
            if not path:
                return {"ok": False, "error": "frame_snap: need path"}
            frame.locator("body").screenshot(path=path)
            return {"ok": True, "path": path, "url": frame.url}
        sel = body.get("selector") or ""
        if cmd == "frame_click":
            frame.click(sel, timeout=15000)
            page.wait_for_timeout(250)
            return {"ok": True, "clicked": sel, "url": frame.url}
        if cmd == "frame_fill":
            frame.fill(sel, body.get("text") or "", timeout=15000)
            return {"ok": True, "filled": sel, "url": frame.url}
        frame.press(sel, body.get("key") or "Enter", timeout=15000)
        return {"ok": True, "pressed": sel, "url": frame.url}

    if cmd == "eval":
        js = body.get("js") or ""
        return {"ok": True, "result": page.evaluate(js)}

    if cmd == "addinit":
        # Install a script that runs in every new document before the page's
        # own scripts (used when a site ships a broken/missing vendor bundle
        # such as jQuery and its handlers throw on load).
        path = body.get("path") or ""
        js = body.get("js") or ""
        if path:
            page.add_init_script(path=str(Path(path).resolve()))
            return {"ok": True, "addinit": path}
        if not js:
            return {"ok": False, "error": "addinit: need 'path' or 'js'"}
        page.add_init_script(script=js)
        return {"ok": True, "addinit": "inline", "bytes": len(js)}

    if cmd == "preload":
        # Inject a <script src> into matching documents as they are served, for
        # sites whose own vendor bundle 404s/403s so their handlers never bind.
        url_match = body.get("match") or "**/*"
        src = (body.get("src") or "").strip()
        placement = body.get("placement") or "<head>"
        if not src:
            return {"ok": False, "error": "preload: need 'src'"}

        def _inject(route):
            try:
                if route.request.resource_type != "document":
                    return route.continue_()
                resp = route.fetch()
                html = resp.text()
                tag = f'<script src="{src}"></script>'
                if placement in html:
                    html = html.replace(placement, placement + tag, 1)
                else:
                    html = tag + html
                route.fulfill(response=resp, body=html)
            except Exception:
                try:
                    route.continue_()
                except Exception:
                    pass

        page.route(url_match, _inject)
        return {"ok": True, "preload": src, "match": url_match}

    if cmd == "wait":
        ms = int(body.get("ms") or 1000)
        page.wait_for_timeout(max(0, min(ms, 60000)))
        return {"ok": True, "waited_ms": ms}

    if cmd == "upload":
        sel, path = body.get("selector") or "", body.get("path") or ""
        page.set_input_files(sel, path, timeout=15000)
        return {"ok": True, "uploaded": path, "selector": sel}

    if cmd == "download":
        # Fetch a URL through the browser's own session (cookies apply) and
        # write the bytes to disk. Used for LinkedIn's signed resume URLs.
        url = body.get("url") or ""
        path = body.get("path") or ""
        resp = page.context.request.get(url, timeout=60000)
        data = resp.body()
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_bytes(data)
        return {"ok": True, "path": path, "bytes": len(data), "status": resp.status}

    if cmd == "fillmap":
        # Batch form fill: many fields in ONE round-trip. The agent re-reads the
        # whole transcript on every turn, so filling field-by-field is the single
        # biggest token cost in an application. steps is a list of
        # {op, selector, value|path|key}; op defaults to "fill".
        steps = body.get("steps") or []
        if not isinstance(steps, list) or not steps:
            return {"ok": False, "error": "fillmap: need a non-empty 'steps' list"}
        results = []
        for st in steps:
            op = (st.get("op") or "fill").lower()
            sel = st.get("selector") or ""
            try:
                if op == "fill":
                    page.fill(sel, st.get("value", ""), timeout=int(st.get("timeout", 10000)))
                elif op == "type":
                    page.click(sel, timeout=10000)
                    page.keyboard.type(st.get("value", ""), delay=int(st.get("delay", 60)))
                elif op == "select":
                    page.select_option(sel, st.get("value", ""), timeout=10000)
                elif op == "check":
                    page.check(sel, timeout=10000)
                elif op == "uncheck":
                    page.uncheck(sel, timeout=10000)
                elif op == "upload":
                    page.set_input_files(sel, st.get("path", ""), timeout=15000)
                elif op == "press":
                    if sel:
                        page.click(sel, timeout=10000)
                    page.keyboard.press(st.get("key", "Enter"))
                elif op == "click":
                    page.click(sel, timeout=10000)
                else:
                    results.append({"selector": sel, "op": op, "ok": False,
                                    "error": "unknown op"})
                    continue
                results.append({"selector": sel, "op": op, "ok": True})
            except Exception as e:
                results.append({"selector": sel, "op": op, "ok": False,
                                "error": str(e)[:200]})
        applied = sum(1 for r in results if r["ok"])
        page.wait_for_timeout(300)
        return {"ok": True, "applied": applied, "total": len(results),
                "failed": [r for r in results if not r["ok"]], "results": results}

    if cmd == "mouse":
        # trusted coordinate click (needed for cross-origin widgets like the
        # hCaptcha checkbox, which cannot be reached by selector)
        page.mouse.click(int(body.get("x", 0)), int(body.get("y", 0)))
        page.wait_for_timeout(500)
        return {"ok": True, "clicked": {"x": body.get("x"), "y": body.get("y")},
                "url": page.url, "title": page.title()}

    if cmd == "drag":
        # Trusted pointer drag between two points. Needed to exercise the
        # dashboard's dockable panels: synthetic pointer events cannot capture
        # a pointer, so a JS-only drag never moves a panel.
        x1, y1 = int(body.get("x1", 0)), int(body.get("y1", 0))
        x2, y2 = int(body.get("x2", 0)), int(body.get("y2", 0))
        page.mouse.move(x1, y1)
        page.mouse.down()
        for i in range(1, 9):
            page.mouse.move(x1 + (x2 - x1) * i / 8, y1 + (y2 - y1) * i / 8)
            page.wait_for_timeout(25)
        page.mouse.up()
        page.wait_for_timeout(350)
        return {"ok": True, "from": [x1, y1], "to": [x2, y2],
                "url": page.url, "title": page.title()}

    if cmd == "dialog":
        mode = (body.get("mode") or "accept").strip().lower()
        DIALOG["mode"] = mode if mode in ("accept", "dismiss", "once") else "accept"
        return {"ok": True, "mode": DIALOG["mode"]}

    if cmd == "console":
        return {"ok": True, "logs": CONSOLE_LOGS[-300:]}

    if cmd == "headers":
        return {"ok": True, "url": page.url, "title": page.title(),
                "extra_http_headers": EXTRA_HEADERS}

    if cmd == "flow":
        # A whole form page in ONE round-trip. Every browser call is a separate
        # agent turn that re-sends the transcript, so a 20-control form cost 20
        # model turns and a growing context. A flow runs the same steps here,
        # in-process, and returns one compact log.
        steps = body.get("steps") or []
        if not isinstance(steps, list) or not steps:
            return {"ok": False, "error": "flow: need a non-empty 'steps' list"}
        stop = not bool(body.get("continue"))
        log = []
        for i, raw in enumerate(steps):
            if not isinstance(raw, dict):
                return {"ok": False, "failed_at": i, "error": "flow: step is not an object",
                        "steps": log, "url": page.url}
            st = dict(raw)
            op = str(st.pop("op", "fill") or "fill").strip().lower()
            if op == "sleep":                 # documented alias for the wait command
                op = "wait"
            optional = bool(st.pop("optional", False))
            # `fill`/`type` take "text" in the single-command API; a flow step
            # reads more naturally as {selector, value}, so accept both.
            if op in ("fill", "type") and "text" not in st and "value" in st:
                st["text"] = st.pop("value")
            if op == "flow":
                return {"ok": False, "failed_at": i,
                        "error": "flow: nested flow is not allowed", "steps": log}
            try:
                res = dispatch(op, st)
            except Exception as e:
                res = {"ok": False, "error": f"{type(e).__name__}: {e}"}
            ok = bool(res.get("ok"))
            entry = {"i": i, "op": op, "ok": ok}
            if not ok:
                entry["error"] = str(res.get("error") or "failed")[:240]
            else:
                if op == "snap":
                    entry["refs"] = res.get("refs") or []
                    entry["refs_total"] = res.get("refs_total")
                for k in ("clicked", "picked", "pressed", "filled", "typed", "uploaded",
                          "selected", "checked", "applied", "waited_ms", "matched",
                          "value", "result", "url"):
                    if k in res:
                        v = res[k]
                        entry[k] = v if isinstance(v, (int, float, bool)) else str(v)[:160]
                        break
            log.append(entry)
            if not ok and not optional and stop:
                return {"ok": False, "failed_at": i, "failed_op": op,
                        "error": entry["error"], "steps": log,
                        "url": page.url, "title": page.title()}
        done = {"ok": True, "steps": log, "step_count": len(log),
                "url": page.url, "title": page.title()}
        if body.get("text"):
            maxc = max(100, min(int(body.get("text_max") or 400), 20000))
            txt = page.evaluate("() => (document.body && document.body.innerText) || ''") or ""
            done["text"] = re.sub(r"\s+", " ", txt).strip()[:maxc]
        return done

    return {"ok": False, "error": f"unknown cmd: {cmd}"}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, obj: dict, code: int = 200):
        data = json.dumps(obj, default=str).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path.rstrip("/") in ("", "/health"):
            self._send({"ok": True, "service": "camoufox-server"})
        else:
            self._send({"ok": False, "error": "use POST /cmd"}, 404)

    def do_POST(self):
        if not self.path.startswith("/cmd"):
            self._send({"ok": False, "error": "use POST /cmd"}, 404)
            return
        length = int(self.headers.get("Content-Length") or 0)
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except Exception:
            self._send({"ok": False, "error": "invalid JSON"}, 400)
            return
        cmd = (body.get("cmd") or "").strip()
        with LOCK:
            try:
                out = dispatch(cmd, body)
            except Exception as e:
                out = {"ok": False, "error": f"{type(e).__name__}: {e}"}
        self._send(out)


def _proxy_opt(url):
    """Playwright/Camoufox proxy dict from a URL (scheme://user:pass@host:port)."""
    from urllib.parse import urlparse
    if "://" not in url:
        url = "http://" + url
    p = urlparse(url)
    opt = {"server": f"{p.scheme}://{p.hostname}:{p.port}"}
    if p.username:
        opt["username"] = p.username
    if p.password:
        opt["password"] = p.password
    return opt


def _resolve_proxy(explicit, path):
    """[unhinged] Pick a proxy: --proxy > BROWSER_PROXY_FILE (rotate) > BROWSER_PROXY."""
    import os
    import random
    if explicit:
        return explicit
    path = path or os.environ.get("BROWSER_PROXY_FILE", "")
    if path and os.path.isfile(path):
        lines = [l.strip() for l in open(path) if l.strip() and not l.startswith("#")]
        if lines:
            return random.choice(lines)
    return os.environ.get("BROWSER_PROXY", "")


def main() -> int:
    global PAGE, HEADFUL
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=9872)
    ap.add_argument("--headful", action="store_true",
                    help="visible browser window (human assist)")
    ap.add_argument("--profile", default="",
                    help="persistent user-data dir (keeps logins, e.g. LinkedIn); "
                         "omit for an ephemeral session")
    ap.add_argument("--os", dest="os", default="windows",
                    help="spoofed OS: windows|macos|linux|none. Match your host "
                         "(use 'linux' on Linux). 'none' = Camoufox default.")
    ap.add_argument("--disable-coop", action="store_true",
                    help="drop Cross-Origin-Opener-Policy so widgets inside "
                         "cross-origin iframes (hCaptcha / reCAPTCHA / Turnstile "
                         "checkbox + challenge) can actually be clicked")
    ap.add_argument("--main-world-eval", action="store_true",
                    help="run page.evaluate in the page's own scope (needed to "
                         "touch the real DOM, e.g. set a captcha token)")
    ap.add_argument("--window", default="",
                    help="spoofed window size WxH in CSS px (e.g. 1440x900); also sets "
                         "the viewport so screenshots come out that size")
    ap.add_argument("--proxy", default="",
                    help="[unhinged] proxy URL for this session (scheme://user:pass@host:port)")
    ap.add_argument("--proxy-file", default="",
                    help="[unhinged] file of proxy URLs (one per line); one is picked per launch")
    args = ap.parse_args()

    try:
        from camoufox.sync_api import Camoufox
    except ImportError:
        print("camoufox not installed. pip install camoufox && python3 -m camoufox fetch",
              file=sys.stderr)
        return 3

    HEADFUL = args.headful
    profile = str(Path(args.profile).resolve()) if args.profile else ""
    if profile:
        Path(profile).mkdir(parents=True, exist_ok=True)
    print(f"camoufox server: http://127.0.0.1:{args.port}  "
          f"({'headful' if HEADFUL else 'headless'})  os={args.os}"
          f"{'  profile: ' + profile if profile else ''}", flush=True)

    launch = dict(headless=not HEADFUL, humanize=True)
    if args.os and args.os != "none":
        launch["os"] = args.os
    if args.window:
        try:
            w, h = (int(x) for x in re.split(r"[x,]", args.window))
            launch["window"] = (w, h)
        except ValueError:
            print(f"bad --window {args.window!r}; expected WxH", file=sys.stderr)
            return 2
    if args.disable_coop:
        launch["disable_coop"] = True
    if args.main_world_eval:
        launch["main_world_eval"] = True
    proxy = _resolve_proxy(args.proxy, args.proxy_file)
    if proxy:
        launch["proxy"] = _proxy_opt(proxy)
        print(f"proxy: {launch['proxy']['server']}  [unhinged/ip-rotation]", flush=True)
    if profile:
        cm = Camoufox(persistent_context=True, user_data_dir=profile,
                      extra_http_headers=EXTRA_HEADERS, **launch)
    else:
        cm = Camoufox(**launch)
    with cm as browser:
        if profile:
            context = browser
            PAGE = context.pages[0] if context.pages else context.new_page()
        else:
            context = browser.new_context(extra_http_headers=EXTRA_HEADERS)
            PAGE = context.new_page()
        # Single-threaded on purpose: Playwright's sync API (greenlets) is not
        # thread-safe and must be driven from the thread that created it.
        try:
            PAGE.on("console", lambda m: CONSOLE_LOGS.append(f"[{m.type}] {m.text}"))
            PAGE.on("pageerror", lambda e: CONSOLE_LOGS.append(f"[pageerror] {e}"))
            PAGE.on("dialog", _on_dialog)
        except Exception:
            pass
        server = HTTPServer(("127.0.0.1", args.port), Handler)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
