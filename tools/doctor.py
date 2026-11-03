#!/usr/bin/env python3
"""One-shot health check for the pipeline.

    python3 tools/doctor.py           # human-readable PASS/WARN/FAIL lines
    python3 tools/doctor.py --json    # machine-readable (for scripts/agents)

Checks, in order: Python + key deps, the project venv, `config/` (present and
not placeholder), the knowledge base (index + embeddings backend), the browser
(Camoufox), the register/queue, and git. Exit status is 0 when nothing FAILs, 1
otherwise (WARNs never fail the run).
"""
import argparse
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATE = os.path.join(ROOT, "state")
EMB_URL = os.environ.get("EMBEDDINGS_URL", "http://127.0.0.1:11435")
PLACEHOLDERS = ("your name", "example", "jane doe", "test name", "lorem ipsum")


def _run(cmd, timeout=15):
    try:
        return subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return None


def _has_module(name):
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


def _read(path):
    try:
        return open(path, encoding="utf-8", errors="ignore").read()
    except OSError:
        return ""


def _size(path):
    total = 0
    for base, _dirs, names in os.walk(path):
        for name in names:
            try:
                total += os.stat(os.path.join(base, name)).st_size
            except OSError:
                pass
    return total


def _gb(n):
    return f"{n / 1073741824:.2f} GB" if n >= 1073741824 else f"{n / 1048576:.0f} MB"


def _storage_detail():
    """Size of the machine-local data, and what compression could reclaim now."""
    logs = _size(os.path.join(STATE, "logs"))
    cache = _size(os.path.join(ROOT, "kb", "graphrag", "cache"))
    gmail = os.path.join(STATE, "gmail_cache.json")
    gmail_size = os.path.getsize(gmail) if os.path.exists(gmail) else 0
    old = old_count = 0
    cutoff = time.time() - 7 * 86400
    try:
        names = os.listdir(os.path.join(STATE, "logs"))
    except OSError:
        names = []
    for name in names:
        if not name.endswith(".log"):
            continue
        try:
            st = os.stat(os.path.join(STATE, "logs", name))
        except OSError:
            continue
        if st.st_mtime < cutoff and st.st_size >= 1024:
            old += st.st_size
            old_count += 1
    parts = [f"logs {_gb(logs)}", f"graphrag cache {_gb(cache)}"]
    if gmail_size:
        parts.append(f"gmail cache {_gb(gmail_size)}")
    reclaim = int(old * 0.78) + (int(gmail_size * 0.89) if gmail_size else 0)
    if old_count or gmail_size:
        parts.append(f"{_gb(reclaim)} reclaimable (tools/storage.py --all)")
    return "; ".join(parts)


def checks():
    out = []

    def add(name, ok, detail="", warn=False):
        out.append({"name": name, "status": "warn" if (warn and not ok) else ("pass" if ok else "fail"),
                    "detail": detail})

    py = ".".join(str(v) for v in sys.version_info[:3])
    add("python", sys.version_info >= (3, 9), py)
    for mod in ("docx", "rich"):
        add(f"python:{mod}", _has_module(mod), "" if _has_module(mod) else "pip install python-docx rich",
            warn=(mod == "rich"))

    venv = os.path.join(ROOT, ".venv", "bin", "python3")
    add("venv", os.path.exists(venv), ".venv/bin/python3" if os.path.exists(venv) else "run tools/install.sh",
        warn=True)

    for name in ("profile.md", "cv.json", "archetypes.json"):
        p = os.path.join(ROOT, "config", name)
        if not os.path.isfile(p):
            add(f"config:{name}", False, "missing")
            continue
        low = _read(p).lower()
        placeholder = any(tok in low for tok in PLACEHOLDERS)
        add(f"config:{name}", not placeholder, "placeholder content" if placeholder else "ok")

    idx = os.path.join(ROOT, "kb", "graphrag", "output", "entities.parquet")
    add("kb:index", os.path.isfile(idx), "run tools/setup_kb.sh" if not os.path.isfile(idx) else "ok",
        warn=True)

    emb_ok = False
    try:
        import urllib.request
        urllib.request.urlopen(EMB_URL + "/health", timeout=4)
        emb_ok = True
    except Exception:
        pass
    add("kb:embeddings", emb_ok, f"{EMB_URL} reachable" if emb_ok else f"{EMB_URL} down (run tools/embeddings.sh)",
        warn=True)

    add("browser:camoufox", _has_module("camoufox"),
        "" if _has_module("camoufox") else "pip install camoufox && camoufox fetch", warn=True)

    try:
        sys.path.insert(0, os.path.join(ROOT, "tools"))
        import secrets_store as SS
        st = SS.check()
        mig = SS.migration_status()
        detail = f"{st['path']} ({st['mode'] or 'not created yet'})"
        if mig.get("needed"):
            detail += f"; {len(mig['needed'])} source(s) to import"
        add("secrets", st["ok"] and not mig.get("needed"), detail,
            warn=True)
    except Exception as exc:
        add("secrets", False, f"secrets store unreadable: {exc}", warn=True)

    reg = os.path.join(ROOT, "tools", "register.py")
    csvp = os.environ.get("APPLICATIONS_CSV", os.path.join(STATE, "applications.csv"))
    if not os.path.isfile(csvp):
        add("register", False, "no state/applications.csv yet", warn=True)
    else:
        r = _run([sys.executable, reg, "--check"])
        add("register", bool(r and r.returncode == 0),
            (r.stdout.strip().splitlines() or ["?"])[-1] if r and r.stdout else "check failed")
        a = _run([sys.executable, reg, "--audit"])
        add("register:audit", bool(a and a.returncode == 0),
            (a.stdout.strip().splitlines() or ["?"])[-1] if a and a.stdout else "audit failed",
            warn=True)

    q = os.environ.get("QUEUE", os.path.join(STATE, "queue.tsv"))
    add("queue", os.path.isfile(q), "state/queue.tsv" if os.path.isfile(q) else "empty queue", warn=True)

    add("storage", True, _storage_detail(), warn=True)

    add("git", shutil.which("git") is not None and os.path.isdir(os.path.join(ROOT, ".git")),
        "not a git checkout" if not os.path.isdir(os.path.join(ROOT, ".git")) else "ok", warn=True)
    return out


def main():
    ap = argparse.ArgumentParser(description="Health check for the pipeline.")
    ap.add_argument("--json", action="store_true", help="print JSON instead of lines")
    args = ap.parse_args()

    results = checks()
    failed = [c for c in results if c["status"] == "fail"]
    if args.json:
        print(json.dumps({"ok": not failed, "checks": results}, indent=2))
    else:
        icon = {"pass": "PASS", "warn": "WARN", "fail": "FAIL"}
        print(f"doctor - {ROOT}")
        for c in results:
            detail = f"  {c['detail']}" if c["detail"] else ""
            print(f"  {icon[c['status']]}  {c['name']}{detail}")
        print(f"\n{len(results) - len(failed)}/{len(results)} ok"
              + (f" - {len(failed)} FAIL" if failed else ""))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
