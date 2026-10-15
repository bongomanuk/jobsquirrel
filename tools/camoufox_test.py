#!/usr/bin/env python3
"""Camoufox test harness — detection testing against any URL.

Every request also carries identifying headers so your own WAF/logs can tell
this traffic apart (X-Request-Source: camoufox-selftest).

Usage:
  python3 tools/camoufox_test.py --url https://example.com/
  python3 tools/camoufox_test.py --url http://localhost:3000/ --log-headers
  python3 tools/camoufox_test.py --url https://example.com/ --screenshot state/logs/camoufox.png --wait 5
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import uuid

SIGNAL_JS = """() => {
  const gl = document.createElement('canvas').getContext('webgl');
  const dbg = gl && gl.getExtension('WEBGL_debug_renderer_info');
  const uaData = navigator.userAgentData;
  return {
    userAgent: navigator.userAgent,
    platform: navigator.platform,
    languages: navigator.languages,
    timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
    hardwareConcurrency: navigator.hardwareConcurrency,
    deviceMemory: navigator.deviceMemory,
    webdriver: navigator.webdriver,
    plugins: navigator.plugins.length,
    languagesHeadlessHint: !navigator.languages || navigator.languages.length === 0,
    vendor: navigator.vendor,
    screen: [screen.width, screen.height, screen.colorDepth],
    maxTouchPoints: navigator.maxTouchPoints,
    userAgentDataBrands: uaData ? uaData.brands.map(b => b.brand + '/' + b.version) : null,
    userAgentDataMobile: uaData ? uaData.mobile : null,
    webglVendor: dbg ? gl.getParameter(dbg.UNMASKED_VENDOR_WEBGL) : null,
    webglRenderer: dbg ? gl.getParameter(dbg.UNMASKED_RENDERER_WEBGL) : null,
    documentTitle: document.title,
    href: location.href
  };
}"""


def main() -> int:
    ap = argparse.ArgumentParser(description="Camoufox detection test")
    ap.add_argument("--url", help="target URL")
    ap.add_argument("--wait", type=float, default=3.0, help="seconds to settle after load")
    ap.add_argument("--screenshot", metavar="PATH", help="save a screenshot here")
    ap.add_argument("--dump", action="store_true", default=True, help="print fingerprint signals (default on)")
    ap.add_argument("--no-dump", dest="dump", action="store_false")
    ap.add_argument("--log-headers", action="store_true", help="print request/response headers seen")
    ap.add_argument("--headful", action="store_true", help="run with a visible window")
    ap.add_argument("--timeout", type=float, default=30.0, help="navigation timeout seconds")
    args = ap.parse_args()

    if not args.url:
        ap.error("--url is required")

    try:
        from camoufox.sync_api import Camoufox
    except ImportError:
        print("camoufox python package not installed. Run:\n  pip install camoufox\n"
              "then fetch the browser:\n  python3 -m camoufox fetch", file=sys.stderr)
        return 3

    run_id = uuid.uuid4().hex[:8]
    headers = {
        "X-Request-Source": "camoufox-selftest",
        "X-Test-Run": run_id,
        "X-Test-Owner": os.environ.get("CAMOUFOX_OWNER", "camoufox-selftest"),
    }
    print(f"target   : {args.url}")
    print(f"test-run : {run_id}  (headers sent: {', '.join(headers)})")

    requests_seen: list[dict] = []

    with Camoufox(headless=not args.headful, humanize=True, os="windows") as browser:
        context = browser.new_context(extra_http_headers=headers)
        page = context.new_page()

        if args.log_headers:
            def on_request(req):
                try:
                    hdr = req.headers
                except Exception:
                    hdr = {}
                requests_seen.append({"event": "request", "url": req.url,
                                      "method": req.method, "headers": hdr})

            def on_response(resp):
                try:
                    rh = resp.headers
                except Exception:
                    rh = {}
                requests_seen.append({"event": "response", "url": resp.url,
                                      "status": resp.status, "headers": rh})

            page.on("request", on_request)
            page.on("response", on_response)

        page.goto(args.url, timeout=int(args.timeout * 1000), wait_until="domcontentloaded")
        page.wait_for_timeout(int(args.wait * 1000))

        if args.dump:
            signals = page.evaluate(SIGNAL_JS)
            print("\n--- what the page sees ---")
            print(json.dumps(signals, indent=2, default=str))

        if args.screenshot:
            page.screenshot(path=args.screenshot, full_page=True)
            print(f"\nscreenshot: {args.screenshot}")

        if args.log_headers:
            print("\n--- traffic ---")
            for e in requests_seen:
                if e["event"] == "response":
                    print(f"  {e.get('status')} {e['url']}")
            with open("state/logs/camoufox_test_headers.json", "w") as fh:
                json.dump({"run": run_id, "url": args.url, "events": requests_seen}, fh, indent=2, default=str)
            print("  full header log: state/logs/camoufox_test_headers.json")

    print("\nOK — test run finished.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
