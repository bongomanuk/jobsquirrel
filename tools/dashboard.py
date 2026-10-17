#!/usr/bin/env python3
"""Jobsquirrel WebUI server - stdlib http.server + static zero-build frontend.

Serves tools/web/ (index.html, app.css, app.js) and a JSON API over the pipeline
state. Binds 127.0.0.1 by default; every write needs the per-session token
(X-Session) injected into the page. Irreversible actions (submitting the queue)
require an explicit approval token. See docs/PRODUCT-SPEC.md.

    python3 tools/dashboard.py [--host 127.0.0.1] [--port 8765] [--open]
"""
import argparse
import csv
import json
import os
import re
import secrets
import subprocess
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATE = os.environ.get("DASHBOARD_STATE", os.path.join(ROOT, "state"))
LOGS = os.path.join(STATE, "logs")
WEB = os.path.join(ROOT, "tools", "web")
SESSION_TOKEN = secrets.token_urlsafe(24)

try:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import watch_queue as WQ
except Exception:
    WQ = None

ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")
KEEP = re.compile(r"STATUS|RESULT:|\b(ERROR|FAIL|PASS)\b|recorded|submitted|verified|"
                  r"BLOCKED|CLOSED|PREPARED|SUBMITTED|INTERVIEW|REJECTED|thank you|thanks for|"
                  r"confirmation|not moving forward|unfortunately|record_submission|check_documents|"
                  r"kb_graphrag|email_verify|nav |fill |click |submit", re.I)
CONFIG_FILES = {"profile": "config/profile.md", "cv": "config/cv.json",
                "archetypes": "config/archetypes.json"}
STATUSES = ["SUBMITTED", "IN_PROGRESS", "INTERVIEW", "OFFER", "REJECTED",
            "BLOCKED", "MANUAL", "PREPARED", "CLOSED"]


# ---------------------------------------------------------------- helpers
def _read(path, cap=400_000):
    try:
        with open(path, encoding="utf-8", errors="ignore") as fh:
            return fh.read()[:cap]
    except OSError:
        return ""


def _rows(path):
    try:
        with open(path, newline="", encoding="utf-8") as fh:
            return list(csv.DictReader(fh))
    except OSError:
        return []


def _lines(path):
    return [l.rstrip("\n") for l in _read(path).splitlines() if l.strip() and not l.lstrip().startswith("#")]


def _count(path):
    return len(_lines(path))


def curate(text, limit=600):
    text = ANSI.sub("", text or "")
    out, last_phase = [], None
    for raw in text.splitlines():
        s = raw.strip()
        if not s or re.fullmatch(r"\d+\s*/\s*\d+", s) or s[:4] in ("0%|", "5%|"):
            continue
        if WQ and WQ._is_noise(s):
            continue
        if re.match(r"\d{4}-\d{2}-\d{2}[,\s]", s) or s.count(",") >= 4:
            continue
        phase = None
        if WQ:
            for pat, label in WQ.PHASES:
                if re.search(pat, s, re.I):
                    phase = label
                    break
        if phase and phase != last_phase:
            out.append({"k": "phase", "t": phase})
            last_phase = phase
        elif KEEP.search(s):
            out.append({"k": "line", "t": s[:240]})
    ded = []
    for it in out:
        if not ded or ded[-1] != it:
            ded.append(it)
    return ded[-limit:]


# ---------------------------------------------------------------- health
_HEALTH = {"t": 0, "v": "unknown", "detail": ""}


def health():
    if time.time() - _HEALTH["t"] < 30:
        return _HEALTH
    v, detail = "unknown", ""
    try:
        r = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "doctor.py"), "--json"],
                           cwd=ROOT, capture_output=True, text=True, timeout=60)
        d = json.loads(r.stdout)
        v = "PASS" if d.get("ok") else "FAIL"
        detail = "; ".join(f"{c['name']}:{c['status']}" for c in d.get("checks", []) if c["status"] != "pass") or "all ok"
    except Exception as e:
        v, detail = "unknown", str(e)[:120]
    _HEALTH.update(t=time.time(), v=v, detail=detail)
    return _HEALTH


# ---------------------------------------------------------------- state
def state():
    apps = _rows(os.path.join(STATE, "applications.csv"))
    counts = {}
    for r in apps:
        k = (r.get("status") or "?").upper()
        counts[k] = counts.get(k, 0) + 1
    inproc = sum(counts.get(k, 0) for k in ("SUBMITTED", "IN_PROGRESS", "INTERVIEW", "OFFER"))
    interviews = [r for r in apps if (r.get("status") or "").upper() == "INTERVIEW"]
    q_total, q_done = _count(os.path.join(STATE, "queue.tsv")), _count(os.path.join(STATE, "queue.done"))
    return {"kpis": {"in_process": inproc, "interviews": counts.get("INTERVIEW", 0),
                     "blocked": counts.get("BLOCKED", 0), "offers": counts.get("OFFER", 0),
                     "human": _count(os.path.join(STATE, "queue-human.tsv")),
                     "total": len(apps), "submissions": _count(os.path.join(STATE, "submissions.csv"))},
            "counts": counts,
            "queue_counts": {"pending": q_total, "done": q_done},
            "interviews": [{"company": r["company"], "role": r["role"]} for r in interviews][:40]}


# ---------------------------------------------------------------- register
def register_api(q="", status="", limit=200, offset=0):
    rows = _rows(os.path.join(STATE, "applications.csv"))
    q, status = (q or "").lower(), (status or "").upper()
    if q:
        rows = [r for r in rows if q in r["company"].lower() or q in r["role"].lower()]
    if status:
        rows = [r for r in rows if (r.get("status") or "").upper() == status]
    total = len(rows)
    try:
        offset, limit = int(offset), int(limit)
    except (TypeError, ValueError):
        offset, limit = 0, 200
    rows = sorted(rows, key=lambda r: (r.get("date") or ""), reverse=True)
    return {"total": total, "rows": rows[offset:offset + limit]}


def provenance(company, role):
    for r in _rows(os.path.join(STATE, "submissions.csv")):
        if r["company"].strip() == company.strip() and r["role"].strip() == role.strip():
            snap = r.get("snapshot_dir", "")
            shots = []
            try:
                for f in os.listdir(os.path.join(ROOT, snap)):
                    if f.lower().endswith((".png", ".jpg")):
                        shots.append(os.path.join(snap, f))
            except OSError:
                pass
            return {"company": r["company"], "role": r["role"], "date": r.get("date"),
                    "status": r.get("status"), "confidence": r.get("confidence"),
                    "cv_file": r.get("cv_file"), "cv_sha256": r.get("cv_sha256"),
                    "letter_file": r.get("letter_file"), "letter_sha256": r.get("letter_sha256"),
                    "evidence": r.get("evidence"),"snapshot_dir": snap, "screenshots": shots}
    return {}


def update_row(company, role, status, note):
    if not (company and role):
        return {"error": "company and role required"}
    sys.path.insert(0, os.path.join(ROOT, "tools"))
    import register as REG
    REG.set_row(company, role, status=(status or "").upper(), note=note or "")
    return {"ok": f"updated {company} / {role}"}


# ---------------------------------------------------------------- queue
def _queue_rows(path):
    out = []
    for ln in _lines(path):
        p = (ln.split("\t") + [""] * 6)[:6]
        out.append({"company": p[0], "role": p[1], "url": p[2], "cv": p[3], "ats": p[4], "key": p[5]})
    return out


def queue_files():
    return {"pending": _queue_rows(os.path.join(STATE, "queue.tsv")),
            "human": _queue_rows(os.path.join(STATE, "queue-human.tsv")),
            "retry": _queue_rows(os.path.join(STATE, "queue.retry")),
            "done": [l.replace("|", " — ") for l in _lines(os.path.join(STATE, "queue.done"))]}


def queue_action(action, company, role):
    files = {"pending": "queue.tsv", "human": "queue-human.tsv", "retry": "queue.retry"}
    q, h = os.path.join(STATE, "queue.tsv"), os.path.join(STATE, "queue-human.tsv")
    key = f"{company}|{role}"

    def drop(path):
        keep, n = [], 0
        for ln in _read(path).splitlines():
            p = (ln.split("\t") + [""] * 6)[:6]
            if (p[0] + "|" + p[1]) == key or (p[0] + "|" + p[1]).lower() == key.lower():
                n += 1
                continue
            keep.append(ln)
        open(path, "w", encoding="utf-8").write("\n".join(keep).rstrip("\n") + "\n" if keep else "")
        return n

    if action == "delete":
        n = sum(drop(os.path.join(STATE, f)) for f in files.values())
        return {"ok": f"removed {n} row(s)"}
    if action == "retry":
        drop(os.path.join(STATE, "queue.done"))
        with open(q, "a", encoding="utf-8") as fh:
            fh.write(f"{company}\t{role}\t\t\t\t\n")
        return {"ok": f"re-queued {company} / {role}"}
    if action == "unblock":
        drop(h)
        with open(q, "a", encoding="utf-8") as fh:
            fh.write(f"{company}\t{role}\t\t\t\t\n")
        return {"ok": f"moved to pending: {company} / {role}"}
    return {"error": "unknown action"}


# ---------------------------------------------------------------- roles
def _archetype_for(key):
    for r in _queue_rows(os.path.join(STATE, "queue.tsv")):
        if r["key"] == key:
            return r["cv"]
    return ""


def roles_list():
    out = []
    for key in sorted(f[:-3] for f in (os.listdir(os.path.join(STATE, "job-descriptions"))
                                        if os.path.isdir(os.path.join(STATE, "job-descriptions")) else [])
                      if f.endswith(".md")):
        m = _MATCH_CACHE.get(key, {})
        out.append({"key": key, "company": m.get("company", ""), "role": m.get("role", ""),
                    "ats": m.get("ats", ""), "match_pct": m.get("coverage"), "alignment": m.get("alignment")})
    return out


_MATCH_CACHE = {}


def match_score(key, cache=True):
    if cache and key in _MATCH_CACHE:
        return _MATCH_CACHE[key]
    cv = _archetype_for(key)
    jd = os.path.join(STATE, "job-descriptions", key + ".md")
    res = {"key": key, "archetype": os.path.basename(cv) if cv else "",
           "alignment": "unknown", "alignment_detail": "", "coverage": None, "missing": []}
    if cv and os.path.isfile(jd):
        cvpath = cv if os.path.isabs(cv) else os.path.join(ROOT, cv)
        if os.path.isfile(cvpath):
            try:
                r = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "check_alignment.py"),
                                    "--cv", cvpath, "--jd", jd], cwd=ROOT, capture_output=True, text=True, timeout=90)
                out = ANSI.sub("", r.stdout + r.stderr)
                res["alignment"] = ("PASS" if "RESULT: PASS" in out else
                                    "FAIL" if "RESULT: FAIL" in out else "?")
                res["alignment_detail"] = out.strip()[-500:]
            except (OSError, subprocess.SubprocessError) as e:
                res["alignment_detail"] = str(e)
    kws = [l.strip() for l in _lines(os.path.join(STATE, "ats", key + ".txt"))]
    content = _read(os.path.join(STATE, "cv-content", key + ".json"))
    letters = _read(os.path.join(STATE, "letters-content", key + ".json"))
    if kws and (content or letters):
        hay = (content + " " + letters).lower()
        hit = [k for k in kws if k.lower() in hay]
        res["coverage"] = round(100 * len(hit) / len(kws))
        res["missing"] = [k for k in kws if k.lower() not in hay][:24]
    _MATCH_CACHE[key] = res
    return res


def role_detail(key):
    key = os.path.basename(key)[:120]
    return {"key": key,
            "jd": _read(os.path.join(STATE, "job-descriptions", key + ".md")),
            "ats": _read(os.path.join(STATE, "ats", key + ".txt")),
            "kb": _read(os.path.join(STATE, "kb-context", key + ".md"))[:12000],
            "tailored_cv": _read(os.path.join(STATE, "cv-content", key + ".json"))[:12000],
            "letter": _read(os.path.join(STATE, "letters-content", key + ".json"))[:12000],
            "match": match_score(key)}


def discover(url):
    url = (url or "").strip()
    if not url.startswith("http"):
        return {"error": "need an http(s) URL"}
    import urllib.request
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 jobsquirrel"})
        page = urllib.request.urlopen(req, timeout=25).read().decode("utf-8", "ignore")
    except Exception as e:
        return {"error": f"could not fetch: {e}"}
    text = re.sub(r"(?is)<(script|style|head)\b[^>]*>.*?</\1>", " ", page)
    text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", text)).strip()
    slug = re.sub(r"[^a-z0-9]+", "-", urlparse(url).netloc + "-" + urlparse(url).path).strip("-")[:80]
    os.makedirs(os.path.join(STATE, "job-descriptions"), exist_ok=True)
    with open(os.path.join(STATE, "job-descriptions", slug + ".md"), "w", encoding="utf-8") as fh:
        fh.write(f"# {url}\n\n{text[:20000]}\n")
    return {"ok": f"saved role {slug}", "key": slug}


# ---------------------------------------------------------------- config / outcomes
def config_get(target):
    target = target if target in CONFIG_FILES else "profile"
    return {"target": target, "content": _read(os.path.join(ROOT, CONFIG_FILES[target])),
            "format": "json" if target != "profile" else "md"}


def config_save(target, content):
    if target not in CONFIG_FILES:
        return {"error": "unknown config target"}
    if target != "profile":
        try:
            json.loads(content)
        except ValueError as e:
            return {"error": f"invalid JSON: {e}"}
    p = os.path.join(ROOT, CONFIG_FILES[target])
    try:
        if os.path.isfile(p):
            open(p + ".bak", "w", encoding="utf-8").write(_read(p))
        open(p, "w", encoding="utf-8").write(content)
    except OSError as e:
        return {"error": str(e)}
    return {"ok": f"saved {CONFIG_FILES[target]} (backup .bak)"}


def _slug(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def _key_map():
    m = {}
    for path in ("queue.tsv", "queue-human.tsv", "queue.retry"):
        for r in _queue_rows(os.path.join(STATE, path)):
            if r["key"]:
                m[(r["company"].lower(), r["role"].lower())] = r["key"]
    return m


def grid():
    """One canonical row per application, joined with queue state, spec, provenance."""
    apps = _rows(os.path.join(STATE, "applications.csv"))
    km = _key_map()
    qstate = {}
    for st, path in (("pending", "queue.tsv"), ("human", "queue-human.tsv"), ("retry", "queue.retry")):
        for r in _queue_rows(os.path.join(STATE, path)):
            qstate[(r["company"].lower(), r["role"].lower())] = st
    done = set(l.strip() for l in _lines(os.path.join(STATE, "queue.done")))
    subm = {(r["company"].lower(), r["role"].lower())
            for r in _rows(os.path.join(STATE, "submissions.csv"))}
    try:
        specs = {f[:-3] for f in os.listdir(os.path.join(STATE, "job-descriptions")) if f.endswith(".md")}
    except OSError:
        specs = set()
    out = []
    for r in apps:
        co, role = r["company"], r["role"]
        ck = (co.lower(), role.lower())
        key = km.get(ck) or _slug(f"{co}-{role}")
        m = _MATCH_CACHE.get(key, {})
        out.append({"date": r.get("date", ""), "company": co, "role": role, "ats": r.get("ats", ""),
                    "status": (r.get("status") or "").upper(), "key": key,
                    "queue": qstate.get(ck, "done" if f"{co}|{role}" in done else ""),
                    "spec": key in specs, "applied": ck in subm,
                    "match": m.get("coverage"), "alignment": m.get("alignment")})
    out.sort(key=lambda x: (x["date"] or ""), reverse=True)
    return out


def outcomes():
    rows = _rows(os.path.join(STATE, "applications.csv"))
    by_ats = {}
    for r in rows:
        a = (r.get("ats") or "(none)").strip() or "(none)"
        s = (r.get("status") or "").upper()
        d = by_ats.setdefault(a, {"total": 0, "interview": 0, "offer": 0})
        d["total"] += 1
        if s in ("INTERVIEW", "OFFER"):
            d["interview"] += 1
        if s == "OFFER":
            d["offer"] += 1
    iv = sum(1 for r in rows if (r.get("status") or "").upper() in ("INTERVIEW", "OFFER"))
    return {"by_ats": by_ats, "interview_rate": round(100 * iv / max(1, len(rows)), 1)}


# ---------------------------------------------------------------- runs / live / logs
def runs(n=40):
    path = os.path.join(LOGS, "runs.jsonl")
    out = []
    for ln in _read(path).splitlines()[-n:]:
        try:
            out.append(json.loads(ln))
        except ValueError:
            pass
    return out[::-1]


def task_logs():
    try:
        return sorted(f[:-4] for f in os.listdir(LOGS) if f.endswith(".log"))
    except OSError:
        return []


def read_task_log(name):
    name = os.path.basename(name)[:120]
    return {"name": name, "curated": curate(_read(os.path.join(LOGS, name + ".log"), cap=200_000))}


def live():
    active = bool(WQ and WQ.runner_active())
    running = sorted(WQ.live_tasks()) if WQ else []
    tail_name, tail = "", []
    if running:
        cand = []
        for key in running:
            co, _, role = key.partition("|")
            name = f"{co}-{role}".translate(str.maketrans(" /|", "___"))
            if os.path.isfile(os.path.join(LOGS, name + ".log")):
                cand.append((os.path.getmtime(os.path.join(LOGS, name + ".log")), name))
        if cand:
            tail_name = max(cand)[1]
            tail = read_task_log(tail_name)["curated"][-150:]
    return {"active": active, "running": [k.replace("|", " — ") for k in running],
            "tail_name": tail_name, "tail": tail}


def logs_tail(lines=100):
    p = os.path.join(LOGS, "run_queue.out")
    return {"logs": ANSI.sub("", _read(p, cap=200_000)).splitlines()[-int(lines or 100):]}


# ---------------------------------------------------------------- chat
CHAT_LOG = os.path.join(LOGS, "dashboard-chat.log")
_CHAT = {"proc": None}


def chat_agent():
    try:
        r = subprocess.run(["bash", os.path.join(ROOT, "tools", "agent_run.sh"), "--which"],
                           cwd=ROOT, capture_output=True, text=True, timeout=10)
        return (r.stdout or "").strip() or "?"
    except (OSError, subprocess.SubprocessError):
        return "?"


def chat_start(message):
    if _CHAT["proc"] and _CHAT["proc"].poll() is None:
        return {"error": "a message is still running"}
    message = (message or "").strip()[:8000]
    if not message:
        return {"error": "empty message"}
    preamble = ("You are the coding agent embedded in the Jobsquirrel dashboard, chatting with the "
                "operator about their job-search pipeline (repo root is the cwd). Be concise; use the "
                "repo's tools; never take an irreversible action without explicit approval.")
    os.makedirs(LOGS, exist_ok=True)
    with open(CHAT_LOG, "w", encoding="utf-8") as fh:
        fh.write(f"> {message}\n\n")
    f = open(CHAT_LOG, "a", encoding="utf-8")
    _CHAT["proc"] = subprocess.Popen(["bash", os.path.join(ROOT, "tools", "agent_run.sh"),
                                      preamble + "\n\n---\n" + message], cwd=ROOT,
                                     stdout=f, stderr=subprocess.STDOUT, start_new_session=True)
    return {"status": "queued", "run_id": "chat", "agent": chat_agent()}


def chat_stream(run_id, since):
    try:
        size = os.path.getsize(CHAT_LOG)
    except OSError:
        size = 0
    try:
        since = max(0, min(int(since or 0), size))
    except (TypeError, ValueError):
        since = 0
    with open(CHAT_LOG, encoding="utf-8", errors="ignore") as fh:
        fh.seek(since)
        text = ANSI.sub("", fh.read())
    running = bool(_CHAT["proc"] and _CHAT["proc"].poll() is None)
    return {"chunk": text, "offset": size, "done": not running}


# ---------------------------------------------------------------- actions
ACTIONS = {
    "prepare": {"argv": ["bash", "tools/run_queue.sh"], "env": {"REVIEW": "1", "PARALLEL": "1"},
                "purpose": "prepare documents (review run)", "token": None},
    "submit_queue": {"argv": ["bash", "tools/run_queue.sh"], "env": {},
                     "purpose": "run the apply queue (submits applications)", "token": "APPROVE_RUN_QUEUE"},
    "reconcile": {"argv": [sys.executable, "tools/gmail_reconcile.py"], "env": {},
                  "purpose": "reconcile the register with Gmail", "token": None},
    "build_archetypes": {"argv": [sys.executable, "tools/build_archetypes.py"], "env": {},
                         "purpose": "regenerate archetype CVs", "token": None},
}


def start_action(command, approval_token=""):
    spec = ACTIONS.get(command)
    if not spec:
        return {"error": "unknown action"}
    if WQ and WQ.runner_active() and command in ("prepare", "submit_queue"):
        return {"error": "a queue run is already active"}
    if spec["token"]:
        sys.path.insert(0, os.path.join(ROOT, "tools"))
        import approval
        if approval_token != spec["token"]:
            approval._record(spec["purpose"], "REFUSED (no approval token)")
            return {"error": f"refused: this action is irreversible; confirm to send {spec['token']}"}
        approval._record(spec["purpose"], f"ui-token:{spec['token']}")
    os.makedirs(LOGS, exist_ok=True)
    logf = open(os.path.join(LOGS, "dashboard-action.log"), "a", encoding="utf-8")
    logf.write(f"\n=== {time.strftime('%Y-%m-%dT%H:%M:%S')} action={command} ===\n")
    logf.flush()
    subprocess.Popen(spec["argv"], cwd=ROOT, env=dict(os.environ, ROOT=ROOT, **spec["env"]),
                     stdout=logf, stderr=subprocess.STDOUT, start_new_session=True)
    return {"ok": f"started: {spec['purpose']}"}


# ---------------------------------------------------------------- HTTP
class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _json(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _file(self, path, ctype):
        try:
            body = open(path, "rb").read()
        except OSError:
            self.send_response(404); self.end_headers(); return
        if path.endswith("index.html"):
            body = body.replace(b"{{TOKEN}}", SESSION_TOKEN.encode())
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        u = urlparse(self.path)
        p, qs = u.path, parse_qs(u.query)
        static = {"/": ("index.html", "text/html; charset=utf-8"),
                  "/app.css": ("app.css", "text/css; charset=utf-8"),
                  "/app.js": ("app.js", "application/javascript; charset=utf-8")}
        if p in static:
            return self._file(os.path.join(WEB, static[p][0]), static[p][1])
        if p == "/api/state":
            return self._json(state())
        if p == "/api/health":
            return self._json(health())
        if p == "/api/register":
            return self._json(register_api(qs.get("q", [""])[0], qs.get("status", [""])[0],
                                           qs.get("limit", ["200"])[0], qs.get("offset", ["0"])[0]))
        if p == "/api/grid":
            return self._json(grid())
        if p == "/api/provenance":
            return self._json(provenance(qs.get("company", [""])[0], qs.get("role", [""])[0]))
        if p == "/api/queue":
            return self._json(queue_files())
        if p == "/api/roles":
            return self._json(roles_list())
        if p.startswith("/api/roles/"):
            return self._json(role_detail(p[len("/api/roles/"):]))
        if p == "/api/config":
            return self._json(config_get(qs.get("target", ["profile"])[0]))
        if p == "/api/outcomes":
            return self._json(outcomes())
        if p == "/api/runs":
            return self._json(runs())
        if p == "/api/tasks":
            return self._json(task_logs())
        if p == "/api/log":
            return self._json(read_task_log(qs.get("task", [""])[0]))
        if p == "/api/live":
            return self._json(live())
        if p == "/api/logs/tail":
            return self._json(logs_tail(qs.get("lines", ["100"])[0]))
        if p == "/api/agent":
            return self._json({"agent": chat_agent()})
        if p == "/api/chat/stream":
            return self._json(chat_stream(qs.get("run_id", ["chat"])[0], qs.get("since", ["0"])[0]))
        self._json({"error": "not found"}, 404)

    def _body(self):
        n = int(self.headers.get("Content-Length", "0") or 0)
        try:
            return json.loads(self.rfile.read(n).decode() or "{}")
        except ValueError:
            return {}

    def _authed(self):
        if self.headers.get("X-Session") == SESSION_TOKEN:
            return True
        self._json({"error": "bad session token"}, 403)
        return False

    def do_POST(self):
        p, data = urlparse(self.path).path, self._body()
        if not self._authed():
            return
        if p == "/api/register/row":
            return self._json(update_row(data.get("company", ""), data.get("role", ""),
                                         data.get("status", ""), data.get("notes", "")))
        if p == "/api/queue/action":
            return self._json(queue_action(data.get("action", ""), data.get("company", ""), data.get("role", "")))
        if p == "/api/roles/discover":
            return self._json(discover(data.get("url", "")))
        if p == "/api/config":
            return self._json(config_save(data.get("target", ""), data.get("content", "")))
        if p == "/api/action/run":
            return self._json(start_action(data.get("command", ""), data.get("approval_token", "")))
        if p == "/api/chat":
            return self._json(chat_start(data.get("message", "")))
        self._json({"error": "not found"}, 404)


def main():
    ap = argparse.ArgumentParser(description="Jobsquirrel WebUI server.")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--open", action="store_true")
    args = ap.parse_args()
    if not os.path.isfile(os.path.join(WEB, "index.html")):
        print(f"missing frontend: {WEB}/index.html", file=sys.stderr)
        return 2
    url = f"http://{args.host}:{args.port}/"
    srv = ThreadingHTTPServer((args.host, args.port), H)
    print(f"🐿️  Jobsquirrel WebUI  ->  {url}   (Ctrl-C to stop)")
    if args.open:
        threading.Timer(0.7, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nbye")
    return 0


if __name__ == "__main__":
    sys.exit(main())
