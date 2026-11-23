#!/usr/bin/env python3
"""Find and stop leftover Camoufox browser servers.

Each server is a full headless browser. A run that launches one and dies, or a
server started by hand and forgotten, leaves it holding a port until the machine
runs out of memory. This finds them and stops the ones that are provably idle:

  dead page       /health answers but /cmd fails (the window was closed)
  not answering   the port is open but the server does not respond at all
  ephemeral       profile under /tmp, /var/tmp or /dev/shm (a throwaway session)
  idle and old    older than --max-age-hours, sitting on about:blank, and no
                  runner (run_queue.sh, run_linkedin.sh, human_assist.sh) is up

A server showing a real page is never touched, and ports listed in
state/browser-affinity.json (the LinkedIn sign-in) are protected.

    python3 tools/browser_reap.py                # report only
    python3 tools/browser_reap.py --apply        # stop what it reports
    python3 tools/browser_reap.py --json
"""
import argparse
import json
import os
import re
import signal
import subprocess
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AFFINITY = os.path.join(ROOT, "state", "browser-affinity.json")
RUNNERS = ("run_queue.sh", "run_linkedin.sh", "human_assist.sh")
DASHBOARD_RE = re.compile(r"^https?://(?:127\.0\.0\.1|localhost):8765(?:/|$)")


def servers():
    """Every camoufox_server.py on this machine: pid, port, profile, age."""
    out = []
    for name in os.listdir("/proc"):
        if not name.isdigit():
            continue
        pid = int(name)
        try:
            with open(f"/proc/{pid}/cmdline", "rb") as fh:
                argv = fh.read().split(b"\0")
        except OSError:
            continue
        argv = [a.decode("utf-8", "replace") for a in argv if a]
        if not any(a.endswith("camoufox_server.py") for a in argv):
            continue
        port, profile = 0, ""
        for i, a in enumerate(argv):
            if a == "--port" and i + 1 < len(argv):
                try:
                    port = int(argv[i + 1])
                except ValueError:
                    pass
            elif a == "--profile" and i + 1 < len(argv):
                profile = argv[i + 1]
        out.append({"pid": pid, "port": port, "profile": profile,
                    "ppid": _ppid(pid), "age_h": _age_hours(pid)})
    return sorted(out, key=lambda s: s["port"])


def _ppid(pid):
    try:
        with open(f"/proc/{pid}/status") as fh:
            for line in fh:
                if line.startswith("PPid:"):
                    return int(line.split()[1])
    except OSError:
        pass
    return 0


def _age_hours(pid):
    r = subprocess.run(["ps", "-o", "etimes=", "-p", str(pid)],
                       capture_output=True, text=True)
    try:
        return int(r.stdout.strip()) / 3600.0
    except ValueError:
        return 0.0


def probe(port):
    """(health_ok, page_alive, url_or_error) for a server port."""
    base = f"http://127.0.0.1:{port}"
    try:
        with urllib.request.urlopen(base + "/health", timeout=3) as r:
            health = json.loads(r.read().decode() or "{}")
    except Exception as exc:  # noqa: BLE001
        return False, False, f"{type(exc).__name__}"
    if "page" in health:
        return True, bool(health.get("page")), health.get("url") or ""
    # older server without the page field: ask it for its status
    try:
        req = urllib.request.Request(base + "/cmd",
                                     data=b'{"cmd":"status"}',
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=5) as r:
            st = json.loads(r.read().decode() or "{}")
        return True, bool(st.get("ok")), st.get("url") or st.get("error") or ""
    except Exception:
        return True, False, "status failed"


def runner_active():
    r = subprocess.run(["ps", "-eo", "args"], capture_output=True, text=True)
    for line in (r.stdout or "").splitlines():
        if any(name in line for name in RUNNERS) and "browser_reap" not in line:
            return True
    return False


def protected_ports():
    ports = set()
    try:
        data = json.load(open(AFFINITY, encoding="utf-8"))
        for entry in data.values():
            if (entry or {}).get("port"):
                ports.add(int(entry["port"]))
    except Exception:
        pass
    for p in (os.environ.get("CAMOUFOX_KEEP_PORTS") or "").replace(",", " ").split():
        if p.isdigit():
            ports.add(int(p))
    return ports


def classify(srv, page_alive, health_ok, url, ctx):
    """Why this server should stop, or '' to leave it alone."""
    if srv["port"] in ctx["protected"] and health_ok and page_alive:
        return ""
    if health_ok and not page_alive:
        return "dead page"
    if not health_ok:
        return "not answering"
    # The pipeline dashboard is a single-page app with a continuously rendered
    # 3D view. Parked in a headless worker it never throttles, so it burns CPU
    # for as long as it is left open. Nobody drives a worker by hand.
    if (not ctx["runner_active"] and url and DASHBOARD_RE.search(url)
            and srv["age_h"] >= ctx["min_ephemeral_h"]):
        return "dashboard left open"
    prof = srv["profile"] or ""
    ephemeral = prof.startswith(("/tmp/", "/var/tmp/", "/dev/shm/")) or not prof
    if ephemeral and srv["age_h"] >= ctx["min_ephemeral_h"]:
        return "ephemeral profile"
    if ctx["runner_active"]:
        return ""
    if srv["age_h"] >= ctx["max_age_h"] and (not url or url in ("about:blank", "about:newtab")):
        return "idle and old"
    return ""


def stop(pid, timeout=6.0):
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return "already gone"
    deadline = time.time() + timeout
    while time.time() < deadline:
        if not os.path.exists(f"/proc/{pid}"):
            return "stopped"
        time.sleep(0.2)
    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        return "stopped"
    return "killed"


def main():
    ap = argparse.ArgumentParser(description="Stop leftover Camoufox servers.")
    ap.add_argument("--apply", action="store_true", help="actually stop them")
    ap.add_argument("--max-age-hours", type=float, default=6.0,
                    help="an idle server older than this is stale (default 6)")
    ap.add_argument("--min-ephemeral-hours", type=float, default=1.0,
                    help="a throwaway profile this old is stale (default 1)")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--quiet", action="store_true", help="only print the summary line")
    args = ap.parse_args()

    ctx = {"protected": protected_ports(), "runner_active": runner_active(),
           "max_age_h": args.max_age_hours, "min_ephemeral_h": args.min_ephemeral_hours}
    rows = []
    for srv in servers():
        health_ok, page_alive, url = probe(srv["port"])
        reason = classify(srv, page_alive, health_ok, url, ctx)
        rows.append({**srv, "page": page_alive, "url": url[:80], "reap": reason})

    if args.json:
        print(json.dumps({"runner_active": ctx["runner_active"],
                          "protected": sorted(ctx["protected"]),
                          "servers": rows}, indent=2))
    elif not args.quiet:
        print(f"camoufox servers: {len(rows)}  (runner active: {ctx['runner_active']})")
        for r in rows:
            state = r["reap"] or "keep"
            print(f"  port {r['port']:<6} pid {r['pid']:<7} {r['age_h']:5.1f}h "
                  f"page={'yes' if r['page'] else 'no ':3s} {state:16s} {r['profile'] or '(ephemeral)'}")
            if r["url"]:
                print(f"       url: {r['url']}")

    todo = [r for r in rows if r["reap"]]
    if args.apply:
        for r in todo:
            print(f"  stopping {r['port']} (pid {r['pid']}, {r['reap']}): {stop(r['pid'])}")
            # a server that dies mid-launch can leave its browser behind
            subprocess.run(["pkill", "-f", "--", f"--port {r['port']}"], capture_output=True)
        todo = [r for r in rows if r["reap"]]

    if args.quiet or args.json:
        print(f"camoufox reap: {len(rows)} server(s), {len(todo)} stale"
              + (", stopped" if args.apply and todo else
                 (", nothing to do" if args.apply else ", dry run")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
