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
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

LOCK = threading.Lock()
PAGE = None
HEADFUL = False
CONSOLE_LOGS = []
EXTRA_HEADERS = {
    "X-Request-Source": "camoufox-pipeline",
    "X-Test-Owner": "peter-hollas",
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


def dispatch(cmd: str, body: dict) -> dict:
    page = _page()

    if cmd == "status":
        return {"ok": True, "url": page.url, "title": page.title()}

    if cmd == "nav":
        url = (body.get("url") or "").strip()
        page.goto(url, timeout=30000, wait_until="domcontentloaded")
        # Kill CSS animations/transitions: Ashby (and others) animate widgets,
        # which makes Playwright's actionability "stable" check time out forever.
        try:
            page.add_style_tag(content="*{animation:none!important;transition:none!important;scroll-behavior:auto!important}")
        except Exception:
            pass
        return {"ok": True, "url": page.url, "title": page.title()}

    if cmd == "snap":
        path = body.get("path") or ""
        if path:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=path, full_page=True)
        refs = page.evaluate(INTERACTIVE_JS)
        return {"ok": True, "url": page.url, "title": page.title(),
                "path": path, "refs": refs}

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

    if cmd == "eval":
        js = body.get("js") or ""
        return {"ok": True, "result": page.evaluate(js)}

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

    if cmd == "console":
        return {"ok": True, "logs": CONSOLE_LOGS[-300:]}

    if cmd == "headers":
        return {"ok": True, "url": page.url, "title": page.title(),
                "extra_http_headers": EXTRA_HEADERS}

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
                    help="spoofed OS: windows|macos|linux|none. Use 'linux' on a "
                         "Linux host (a Windows spoof on Linux makes anti-bot "
                         "fingerprints inconsistent). 'none' = Camoufox default.")
    ap.add_argument("--disable-coop", action="store_true",
                    help="drop Cross-Origin-Opener-Policy so widgets inside "
                         "cross-origin iframes (hCaptcha / reCAPTCHA / Turnstile "
                         "checkbox + challenge) can actually be clicked")
    ap.add_argument("--main-world-eval", action="store_true",
                    help="run page.evaluate in the page's own scope (needed to "
                         "touch the real DOM, e.g. set a captcha token)")
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
