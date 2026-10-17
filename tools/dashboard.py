#!/usr/bin/env python3
"""Squirrel Dashboard - a slick, read-only web UI over the pipeline.

Wraps the agent harness: shows the register (counts + in-process), the queue
progress, live/recent runs from state/logs/runs.jsonl, human/blocked items, and a
CURATED view of each task's opencode log - only the lines that actually mean
something (phase changes, gate results, submissions, errors), never the raw tool
spam. Pure stdlib, no build step, vanilla JS.

    python3 tools/dashboard.py                 # http://127.0.0.1:8765
    python3 tools/dashboard.py --port 9000 --open
"""
import argparse
import csv
import html
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

# Reuse the queue tool's phase/noise knowledge when present.
try:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import watch_queue as WQ  # noqa: E402
except Exception:
    WQ = None

ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")
KEEP = re.compile(r"STATUS|RESULT:|\b(ERROR|FAIL|PASS)\b|recorded|submitted|verified|"
                  r"BLOCKED|CLOSED|PREPARED|SUBMITTED|INTERVIEW|REJECTED|"
                  r"thank you|thanks for|confirmation|not moving forward|unfortunately|"
                  r"record_submission|check_documents|kb_graphrag|email_verify|"
                  r"nav |fill |click |submit", re.I)


def curate(text, limit=500):
    """Turn a raw opencode log into the lines a human cares about."""
    text = ANSI.sub("", text or "")
    out, last_phase = [], None
    for raw in text.splitlines():
        s = raw.strip()
        if not s:
            continue
        if re.fullmatch(r"\d+\s*/\s*\d+", s) or s[:4] in ("0%|", "5%|"):
            continue
        if WQ and WQ._is_noise(s):
            continue
        # skip register CSV dumps and other table rows (they merely *contain*
        # status words, they are not narrative)
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
    # collapse consecutive duplicates
    ded = []
    for item in out:
        if not ded or ded[-1] != item:
            ded.append(item)
    return ded[-limit:]


def _rows(path):
    try:
        with open(path, newline="", encoding="utf-8") as fh:
            return list(csv.DictReader(fh))
    except OSError:
        return []


def _count_lines(path):
    try:
        with open(path, encoding="utf-8", errors="ignore") as fh:
            return sum(1 for ln in fh if ln.strip() and not ln.lstrip().startswith("#"))
    except OSError:
        return 0


def gather_state():
    apps = _rows(os.path.join(STATE, "applications.csv"))
    counts = {}
    for r in apps:
        counts[(r.get("status") or "?").upper()] = counts.get((r.get("status") or "?").upper(), 0) + 1
    in_process = sum(counts.get(k, 0) for k in ("SUBMITTED", "IN_PROGRESS", "INTERVIEW", "OFFER"))
    queue_total = _count_lines(os.path.join(STATE, "queue.tsv"))
    queue_done = _count_lines(os.path.join(STATE, "queue.done"))
    subs = _rows(os.path.join(STATE, "submissions.csv"))
    interviews = [r for r in apps if (r.get("status") or "").upper() == "INTERVIEW"]
    blocked = [r for r in apps if (r.get("status") or "").upper() == "BLOCKED"]
    return {
        "total": len(apps),
        "counts": counts,
        "in_process": in_process,
        "queue": {"total": queue_total, "done": queue_done},
        "submissions": len(subs),
        "interviews": [{"company": r["company"], "role": r["role"]} for r in interviews][:30],
        "blocked": len(blocked),
        "human": _count_lines(os.path.join(STATE, "queue-human.tsv")),
    }


def gather_runs(n=40):
    path = os.path.join(LOGS, "runs.jsonl")
    if not os.path.isfile(path):
        return []
    try:
        lines = open(path, encoding="utf-8", errors="ignore").read().splitlines()[-n:]
    except OSError:
        return []
    out = []
    for ln in lines:
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
    path = os.path.join(LOGS, name + ".log")
    if not os.path.isfile(path):
        return {"name": name, "curated": []}
    try:
        with open(path, encoding="utf-8", errors="ignore") as fh:
            fh.seek(0, os.SEEK_END)
            size = fh.tell()
            fh.seek(max(0, size - 200_000))
            text = fh.read()
    except OSError:
        text = ""
    return {"name": name, "curated": curate(text)}


SESSION_TOKEN = secrets.token_urlsafe(18)
CONFIG_FILES = {"profile.md": "config/profile.md",
                "cv.json": "config/cv.json",
                "archetypes.json": "config/archetypes.json"}


def _read(path, cap=400_000):
    try:
        with open(path, encoding="utf-8", errors="ignore") as fh:
            return fh.read()[:cap]
    except OSError:
        return ""


def jobs_list():
    d = os.path.join(STATE, "job-descriptions")
    try:
        return sorted(f[:-3] for f in os.listdir(d) if f.endswith(".md"))
    except OSError:
        return []


def _app_rows():
    return _rows(os.path.join(STATE, "applications.csv"))


def register_api(q="", status="", limit=60, offset=0):
    rows = _app_rows()
    q = (q or "").lower()
    status = (status or "").upper()
    if q:
        rows = [r for r in rows if q in r["company"].lower() or q in r["role"].lower()]
    if status:
        rows = [r for r in rows if (r.get("status") or "").upper() == status]
    total = len(rows)
    try:
        offset, limit = int(offset), int(limit)
    except (TypeError, ValueError):
        offset, limit = 0, 60
    return {"total": total, "rows": rows[offset:offset + limit]}


def _archetype_for(key):
    """CV archetype recorded for a role key in state/queue.tsv (col 4)."""
    for line in _read(os.path.join(STATE, "queue.tsv")).splitlines():
        p = (line.split("\t") + [""] * 6)[:6]
        if p[5] == key:
            return p[3]
    return ""


def match_score(key):
    """Alignment (CV archetype vs JD) + ATS keyword coverage for a role."""
    cv = _archetype_for(key)
    jd = os.path.join(STATE, "job-descriptions", key + ".md")
    res = {"key": key, "archetype": os.path.basename(cv) if cv else "", "alignment": "unknown",
           "alignment_detail": "", "coverage": None, "missing": [], "have_docs": False}
    if cv and os.path.isfile(jd):
        cvpath = cv if os.path.isabs(cv) else os.path.join(ROOT, cv)
        if os.path.isfile(cvpath):
            try:
                r = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "check_alignment.py"),
                                    "--cv", cvpath, "--jd", jd],
                                   cwd=ROOT, capture_output=True, text=True, timeout=90)
                out = ANSI.sub("", r.stdout + r.stderr)
                res["alignment"] = ("PASS" if "RESULT: PASS" in out
                                    else "FAIL" if "RESULT: FAIL" in out else "?")
                res["alignment_detail"] = out.strip()[-500:]
            except (OSError, subprocess.SubprocessError) as e:
                res["alignment_detail"] = str(e)
    kws = [l.strip() for l in _read(os.path.join(STATE, "ats", key + ".txt")).splitlines()
           if l.strip() and not l.startswith("#")]
    content = _read(os.path.join(STATE, "cv-content", key + ".json"))
    letters = _read(os.path.join(STATE, "letters-content", key + ".json"))
    if kws and (content or letters):
        res["have_docs"] = True
        hay = (content + " " + letters).lower()
        hit = [k for k in kws if k.lower() in hay]
        res["coverage"] = round(100 * len(hit) / len(kws))
        res["missing"] = [k for k in kws if k.lower() not in hay][:24]
    return res


def job_detail(key):
    key = os.path.basename(key)[:120]
    return {"key": key,
            "jd": _read(os.path.join(STATE, "job-descriptions", key + ".md")),
            "ats": _read(os.path.join(STATE, "ats", key + ".txt")),
            "kb": _read(os.path.join(STATE, "kb-context", key + ".md"))[:12000],
            "content": _read(os.path.join(STATE, "cv-content", key + ".json"))[:12000],
            "letter": _read(os.path.join(STATE, "letters-content", key + ".json"))[:12000],
            "match": match_score(key)}


def config_get(name):
    name = name if name in CONFIG_FILES else "profile.md"
    return {"name": name, "content": _read(os.path.join(ROOT, CONFIG_FILES[name]))}


def config_save(name, content):
    if name not in CONFIG_FILES:
        return {"error": "unknown config file"}
    if name.endswith(".json"):
        try:
            json.loads(content)
        except ValueError as e:
            return {"error": f"invalid JSON: {e}"}
    p = os.path.join(ROOT, CONFIG_FILES[name])
    try:
        if os.path.isfile(p):
            open(p + ".bak", "w", encoding="utf-8").write(_read(p))
        open(p, "w", encoding="utf-8").write(content)
    except OSError as e:
        return {"error": str(e)}
    return {"ok": f"saved {CONFIG_FILES[name]} (backup: {CONFIG_FILES[name]}.bak)"}


def update_row(company, role, status, note):
    if not (company and role):
        return {"error": "company and role required"}
    sys.path.insert(0, os.path.join(ROOT, "tools"))
    import register as REG
    REG.set_row(company, role, status=status.upper() if status else "", note=note)
    return {"ok": f"updated {company} / {role}"}


def outcomes():
    rows = _app_rows()
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
    return {"by_ats": by_ats,
            "interview_rate": round(100 * sum(1 for r in rows if (r.get("status") or "").upper()
                                              in ("INTERVIEW", "OFFER")) / max(1, len(rows)), 1)}

ACTIONS = {
    # safe: prepares documents (REVIEW=1) and never submits or emails
    "review": {"argv": ["bash", "tools/run_queue.sh"], "env": {"REVIEW": "1", "PARALLEL": "1"},
               "purpose": "prepare documents (review run)", "token": "RUN-REVIEW", "gated": False},
    # risky: actually applies to roles (submits). Gated by approval.
    "queue": {"argv": ["bash", "tools/run_queue.sh"], "env": {},
              "purpose": "run the apply queue (submits applications)", "token": "RUN-QUEUE", "gated": True},
    # safe: regenerate the archetype CVs + letters from config/
    "regen": {"argv": [sys.executable, "tools/build_archetypes.py"], "env": {},
              "purpose": "regenerate archetype CVs from config/", "token": "REGEN", "gated": False},
}


def gather_live():
    active = bool(WQ and WQ.runner_active())
    running = sorted(WQ.live_tasks()) if WQ else []
    tail_name, tail = "", []
    if running:
        cand = []
        for key in running:
            co, _, role = key.partition("|")
            p = os.path.join(LOGS, f"{co}-{role}".translate(str.maketrans(" /|", "___")) + ".log")
            if os.path.isfile(p):
                cand.append((os.path.getmtime(p), f"{co}-{role}".translate(str.maketrans(" /|", "___"))))
        if cand:
            tail_name = max(cand)[1]
            tail = read_task_log(tail_name)["curated"][-150:]
    return {"active": active, "running": [k.replace("|", " — ") for k in running],
            "tail_name": tail_name, "tail": tail}


def start_action(name):
    spec = ACTIONS.get(name)
    if not spec:
        return {"error": "unknown action"}
    if WQ and WQ.runner_active():
        return {"error": "a queue run is already active"}
    if spec["gated"]:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import approval
        if not approval.approved(spec["purpose"], spec["token"]):
            env = "APPROVE_" + spec["token"].replace("-", "_")
            return {"error": f"refused: start the dashboard with {env}=1 to allow this"}
    os.makedirs(LOGS, exist_ok=True)
    logf = open(os.path.join(LOGS, "dashboard-action.log"), "a", encoding="utf-8")
    logf.write(f"\n=== {time.strftime('%Y-%m-%dT%H:%M:%S')}  action={name} ===\n")
    logf.flush()
    subprocess.Popen(spec["argv"], cwd=ROOT, env=dict(os.environ, ROOT=ROOT, **spec["env"]),
                     stdout=logf, stderr=subprocess.STDOUT, start_new_session=True)
    return {"ok": f"started: {spec['purpose']}"}


CHAT_LOG = os.path.join(LOGS, "dashboard-chat.log")
_CHAT = {"proc": None}


def chat_agent():
    """Which agent CLI the chat will drive (agent-agnostic, via agent_run.sh)."""
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
    preamble = (
        "You are the coding agent embedded in the Jobsquirrel dashboard, chatting with the operator "
        "about their job-search pipeline (the repo root is the cwd). Answer concisely and use the "
        "repo's tools when useful. Never take an irreversible action (submit an application, send "
        "email, delete mail) without explicit approval; those tools enforce their own approval gates."
    )
    os.makedirs(LOGS, exist_ok=True)
    with open(CHAT_LOG, "w", encoding="utf-8") as fh:
        fh.write(f"> {message}\n\n")
    f = open(CHAT_LOG, "a", encoding="utf-8")
    _CHAT["proc"] = subprocess.Popen(
        ["bash", os.path.join(ROOT, "tools", "agent_run.sh"), preamble + "\n\n---\n" + message],
        cwd=ROOT, stdout=f, stderr=subprocess.STDOUT, start_new_session=True)
    return {"ok": f"sent to {chat_agent()}"}


def chat_tail(since):
    try:
        size = os.path.getsize(CHAT_LOG)
    except OSError:
        size = 0
    running = bool(_CHAT["proc"] and _CHAT["proc"].poll() is None)
    try:
        since = max(0, min(int(since or 0), size))
    except (TypeError, ValueError):
        since = 0
    text = ""
    try:
        with open(CHAT_LOG, encoding="utf-8", errors="ignore") as fh:
            fh.seek(since)
            text = ANSI.sub("", fh.read())
    except OSError:
        pass
    return {"text": text, "offset": size, "running": running}


INDEX = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Jobsquirrel</title>
<style>
:root{--bg:#0e1116;--panel:#161b22;--panel2:#1c232c;--line:#26303b;--fg:#e6edf3;--dim:#8b98a5;
--accent:#d98a3b;--good:#3fb950;--bad:#f85149;--warn:#d29922;--info:#58a6ff}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);
font:14px/1.5 ui-sans-serif,system-ui,-apple-system,Segoe UI,Roboto,sans-serif}
header{display:flex;align-items:center;gap:14px;padding:14px 22px;border-bottom:1px solid var(--line);
background:linear-gradient(180deg,#12161c,#0e1116)}
.sq{font-size:32px;animation:bob 2.4s ease-in-out infinite}@keyframes bob{50%{transform:translateY(-5px) rotate(-6deg)}}
h1{font-size:18px;margin:0}.sub{color:var(--dim);font-size:12px}
.tabs{display:flex;gap:4px;padding:10px 22px 0;border-bottom:1px solid var(--line);background:var(--panel)}
.tabs a{padding:9px 15px;border-radius:8px 8px 0 0;color:var(--dim);cursor:pointer;font-weight:600;font-size:13px}
.tabs a.on{color:var(--fg);background:var(--bg);border:1px solid var(--line);border-bottom-color:var(--bg)}
section{display:none}section.on{display:block}
.wrap{padding:18px 22px;max-width:1240px;margin:0 auto}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin-bottom:18px}
.card{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:14px}
.card .n{font-size:26px;font-weight:700}.card .l{color:var(--dim);font-size:12px;text-transform:uppercase;letter-spacing:.06em}
.card.hero{border-color:var(--accent)}.card.hero .n{color:var(--accent)}
.bar{height:10px;background:var(--panel2);border-radius:999px;overflow:hidden;margin-top:8px}
.bar>i{display:block;height:100%;background:linear-gradient(90deg,var(--accent),#f0b072)}
h2{font-size:14px;color:var(--dim);text-transform:uppercase;letter-spacing:.08em;margin:22px 0 8px}
table{width:100%;border-collapse:collapse;background:var(--panel);border:1px solid var(--line);border-radius:12px;overflow:hidden}
th,td{text-align:left;padding:9px 12px;border-bottom:1px solid var(--line);font-size:13px}
th{color:var(--dim);font-weight:600;background:var(--panel2)}
tr:last-child td{border-bottom:0}tbody tr{cursor:pointer}tbody tr:hover{background:#1b222b}
.chip{display:inline-block;padding:1px 8px;border-radius:999px;font-size:11px;font-weight:700}
.s-SUBMITTED{background:#12351f;color:var(--good)}.s-INTERVIEW{background:#3a2c07;color:var(--warn)}
.s-REJECTED{background:#3a1414;color:var(--bad)}.s-CLOSED{background:#222a33;color:var(--dim)}
.s-PREPARED{background:#0d2a3f;color:var(--info)}.s-BLOCKED{background:#3a1414;color:var(--bad)}
.s-MANUAL{background:#2a2333;color:#c9a7ff}.s-IN_PROGRESS{background:#0d2a3f;color:var(--info)}
.log{background:#0b0e12;border:1px solid var(--line);border-radius:12px;padding:14px;max-height:52vh;overflow:auto;
font:12px/1.6 ui-monospace,SFMono-Regular,Menlo,monospace;white-space:pre-wrap}
.log .p{color:var(--accent);font-weight:700}
.muted{color:var(--dim)}a{color:var(--info);text-decoration:none}
.tools{display:flex;align-items:center;gap:8px}
button{background:var(--panel2);color:var(--fg);border:1px solid var(--line);border-radius:8px;padding:7px 12px;
font:600 13px inherit;cursor:pointer}button:hover{border-color:var(--accent)}
button.risky{border-color:#6e2b2b;color:#ffb4b4}button:disabled{opacity:.5;cursor:default}
#live .r{color:var(--accent);font-weight:700}
.hint{cursor:help;border-bottom:1px dotted var(--dim)}
button.help{padding:7px 12px;font-weight:800}
input,select,textarea{background:#0b0e12;border:1px solid var(--line);border-radius:8px;color:var(--fg);padding:7px 9px;font:13px inherit}
textarea{width:100%;font:12px/1.55 ui-monospace,monospace;min-height:46vh}
.row{display:flex;gap:8px;align-items:center;flex-wrap:wrap}
.grid2{display:grid;grid-template-columns:340px 1fr;gap:16px}
.list{background:var(--panel);border:1px solid var(--line);border-radius:12px;max-height:66vh;overflow:auto}
.list .it{padding:8px 12px;border-bottom:1px solid var(--line);cursor:pointer;font-size:13px}
.list .it:hover,.list .it.on{background:#1b222b}
.badge{display:inline-block;padding:2px 10px;border-radius:999px;font-weight:700;font-size:12px}
.bad{background:#3a1414;color:#ffb4b4}.good{background:#12351f;color:#8ce99a}.mid{background:#3a2c07;color:#ffd479}
pre.doc{background:#0b0e12;border:1px solid var(--line);border-radius:12px;padding:14px;max-height:46vh;overflow:auto;
white-space:pre-wrap;font:12px/1.6 ui-monospace,monospace}
#help{display:none;position:fixed;inset:0;background:rgba(2,4,8,.66);z-index:50;padding:40px 18px;overflow:auto}
#help.on{display:block}
#help .box{max-width:780px;margin:0 auto;background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:24px}
#help h3{margin:16px 0 2px;font-size:14px;color:var(--fg)}#help p{margin:0 0 2px;color:var(--dim);font-size:13px}
</style></head><body>
<header><div class="sq">🐿️</div>
<div style="flex:1"><h1>Jobsquirrel <span class="muted" style="font-size:12px">· dashboard</span></h1>
<div class="sub" id="ts">loading…</div></div>
<div class="tools">
<button id="b-review" onclick="act('review')" class="hint" title="Safe: builds a tailored CV + cover letter for each queued role and runs the pre-submit gate. Records PREPARED. Never submits or emails.">Prepare (review)</button>
<button id="b-queue" class="risky hint" onclick="act('queue')" title="Applies to queued roles for real (submits). Gated: start with APPROVE_RUN_QUEUE=1 and confirm.">Apply queue</button>
<button class="help hint" onclick="toggleHelp()" title="Help: what everything means">?</button>
<span id="amsg" class="sub"></span>
</div></header>
<nav class="tabs">
<a data-t="overview" class="on" onclick="tab('overview')">Overview</a>
<a data-t="register" onclick="tab('register')" title="Every application; search, filter, open, edit status/notes">Register</a>
<a data-t="roles" onclick="tab('roles')" title="Saved job specs, ATS keywords, KB context, and your match score">Roles</a>
<a data-t="config" onclick="tab('config')" title="View/edit your profile, CV and archetypes; regenerate the CVs">CV &amp; Config</a>
<a data-t="outcomes" onclick="tab('outcomes')" title="Conversion by source/ATS">Outcomes</a>
</nav>

<section id="tab-overview" class="on"><div class="wrap">
<div class="cards" id="cards"></div>
<div class="card"><div class="l">Queue progress</div><div id="qbar" class="bar"><i style="width:0%"></i></div>
<div class="sub" id="qtext" style="margin-top:6px"></div></div>
<h2>Chat <span class="muted" id="agentname" style="text-transform:none;letter-spacing:0"></span></h2>
<div class="card hint" title="Talk to the coding agent the pipeline uses; agent-agnostic via tools/agent_run.sh.">
<div class="log" id="chat" style="max-height:34vh">ask the agent anything about your pipeline…</div>
<div class="row" style="margin-top:10px"><input id="chatmsg" placeholder="e.g. which interviews are coming up?" style="flex:1"
 onkeydown="if(event.key==='Enter')chatSend()"><button onclick="chatSend()">Send</button></div>
<div class="sub" id="chatst"></div></div>
<h2 class="hint" title="Whether a runner is active, running tasks, and a curated tail of the newest task log.">Live</h2>
<div class="card" id="live"><span class="muted">idle — no run active</span></div>
<h2 class="hint" title="One row per finished task (state/logs/runs.jsonl). Click for a curated log.">Recent runs</h2>
<table><thead><tr><th>When</th><th>Company</th><th>Role</th><th>Outcome</th><th>Detail</th></tr></thead>
<tbody id="runs"></tbody></table>
<h2 class="hint" title="Roles at the interview stage.">Interviews</h2><div id="int" class="muted">—</div>
<h2 class="hint" title="Curated task log: phases, gate results, commands, submissions, errors.">Task log</h2>
<div class="log" id="log">click a run to see its curated log</div>
</div></section>

<section id="tab-register"><div class="wrap">
<h2>Register <span class="muted" id="regcount" style="text-transform:none"></span></h2>
<div class="row" style="margin-bottom:10px">
<input id="req" placeholder="search company / role…" oninput="loadRegister()" style="flex:1;max-width:340px">
<select id="rest" onchange="loadRegister()" class="hint" title="Filter by status">
<option value="">all statuses</option><option>SUBMITTED</option><option>INTERVIEW</option>
<option>OFFER</option><option>REJECTED</option><option>BLOCKED</option><option>MANUAL</option>
<option>PREPARED</option><option>IN_PROGRESS</option><option>CLOSED</option></select>
<button onclick="loadRegister(true)">refresh</button></div>
<div class="grid2">
<div class="list" id="reglist"></div>
<div id="regdetail" class="muted">select an application to see and edit it</div>
</div>
</div></section>

<section id="tab-roles"><div class="wrap">
<h2>Roles <span class="muted" id="jobscount" style="text-transform:none"></span></h2>
<div class="grid2">
<div class="list" id="jobslist"></div>
<div id="jobdetail" class="muted">select a role to see its job spec, keywords, KB context and match</div>
</div>
</div></section>

<section id="tab-config"><div class="wrap">
<h2>CV &amp; Config</h2>
<div class="row" style="margin-bottom:10px">
<select id="cfname" onchange="loadConfig()" class="hint" title="Which file to edit">
<option value="cv.json">config/cv.json (your experience)</option>
<option value="archetypes.json">config/archetypes.json (role-family CV templates)</option>
<option value="profile.md">config/profile.md (identity, eligibility, pay)</option>
</select>
<button onclick="saveConfig()">Save</button>
<button class="hint" title="Rebuild documents/archetypes/ from config/" onclick="act('regen')">Regenerate archetype CVs</button>
<span id="cfmsg" class="sub"></span></div>
<textarea id="cftext" spellcheck="false"></textarea>
<div class="sub">JSON files are validated before saving; a <code>.bak</code> copy is kept. After editing cv/archetypes, click <b>Regenerate archetype CVs</b>.</div>
</div></section>

<section id="tab-outcomes"><div class="wrap">
<h2>Outcomes <span class="muted" id="outrate" style="text-transform:none"></span></h2>
<table><thead><tr><th>Source / ATS</th><th>Applications</th><th>Interviews</th><th>Offers</th><th>Interview rate</th></tr></thead>
<tbody id="outbody"></tbody></table>
</div></section>

<div id="help" onclick="if(event.target.id==='help')toggleHelp()"><div class="box">
<h2 style="margin-top:0">What everything means</h2>
<h3>In process</h3><p>Applications you've sent and are still awaiting an outcome on: SUBMITTED + IN_PROGRESS + INTERVIEW + OFFER. The number that actually matters.</p>
<h3>Register</h3><p>Every row in <code>state/applications.csv</code>. Search/filter, click a row to view and edit status/notes (writes back to the register).</p>
<h3>Roles</h3><p>Saved job specs (<code>state/job-descriptions/*.md</code>). For each: the ad text, extracted ATS keywords, the GraphRAG context, and a <b>match score</b> (CV-alignment gate + keyword coverage of your generated CV/letter).</p>
<h3>CV &amp; Config</h3><p>View/edit <code>profile.md</code> (identity/eligibility/pay), <code>cv.json</code> (experience) and <code>archetypes.json</code> (role-family templates). JSON is validated, a <code>.bak</code> is kept, then <b>Regenerate archetype CVs</b> rebuilds the documents.</p>
<h3>Prepare vs Apply</h3><p><b>Prepare</b> is safe (builds docs + gates). <b>Apply</b> submits; gated by <code>APPROVE_RUN_QUEUE=1</code> + a confirm.</p>
<h3>Chat</h3><p>Drives whichever agent <code>tools/agent_run.sh</code> resolves (opencode, Claude Code, hermes, pi, …).</p>
<h3>Approvals</h3><p>Irreversible actions (send/delete email, apply) are approval-gated. The dashboard is localhost-only and every write needs a per-session token.</p>
<p style="margin-top:18px"><button onclick="toggleHelp()">close</button></p>
</div></div>
<script>
const TOKEN="__TOKEN__";
async function j(u){const r=await fetch(u);return r.json()}
function post(path,body){return fetch(path,{method:'POST',headers:{'Content-Type':'application/json','X-Session':TOKEN},body:JSON.stringify(body)}).then(r=>r.json())}
function esc(s){return (s+'').replace(/[&<>"]/g,x=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[x]))}
function chip(s){return '<span class="chip s-'+s+'">'+s+'</span>'}
function toggleHelp(){document.getElementById('help').classList.toggle('on')}
function tab(n){document.querySelectorAll('.tabs a').forEach(a=>a.classList.toggle('on',a.dataset.t===n));
 document.querySelectorAll('section').forEach(s=>s.classList.toggle('on',s.id==='tab-'+n));
 if(n==='register')loadRegister();if(n==='roles')loadJobs();if(n==='config')loadConfig();if(n==='outcomes')loadOutcomes();}
function card(c,l,n){return '<div class="card '+c+' hint" title="'+esc(CARDHELP[l]||'')+'"><div class="n">'+n+'</div><div class="l">'+l+'</div></div>'}
const CARDHELP={'In process':'Sent, still awaiting an outcome: SUBMITTED + IN_PROGRESS + INTERVIEW + OFFER.','Interviews':'Roles currently at the interview stage.','Rejected':'Applications that came back as a no.','Blocked':'Need a manual step (CAPTCHA / login).','Human queue':'Roles only a human can finish.','Total':'Every row in the register.'};
async function tick(){const s=await j('/api/state');
 document.getElementById('ts').textContent='updated '+new Date().toLocaleTimeString()+'  ·  '+s.total+' applications  ·  '+s.submissions+' recorded submissions';
 const c=s.counts||{};
 document.getElementById('cards').innerHTML=card('hero','In process',s.in_process)+card('','Interviews',(c.INTERVIEW||0))+
  card('','Rejected',(c.REJECTED||0))+card('','Blocked',s.blocked)+card('','Human queue',s.human)+card('','Total',s.total);
 const pct=s.queue.total?Math.round(100*s.queue.done/s.queue.total):0;
 document.querySelector('#qbar>i').style.width=pct+'%';
 document.getElementById('qtext').textContent=s.queue.done+' / '+s.queue.total+' done ('+pct+'%)';
 document.getElementById('int').innerHTML=s.interviews.length?s.interviews.map(x=>'· '+esc(x.company)+' — '+esc(x.role)).join('<br>'):'<span class=muted>none yet</span>';
 const runs=await j('/api/runs');
 document.getElementById('runs').innerHTML=runs.map(r=>'<tr onclick="loadlog(\''+esc(String(r.company+'-'+r.role).replace(/[/| ]/g,'_'))+'\')"><td class=muted>'+esc((r.ts||'').slice(11,19))+'</td><td>'+esc(r.company)+'</td><td>'+esc(r.role)+'</td><td>'+chip(r.outcome||'?')+'</td><td class=muted>'+esc(r.reason||'')+'</td></tr>').join('')||'<tr><td colspan=5 class=muted>no runs recorded yet</td></tr>';}
async function loadlog(name){const d=await j('/api/log?task='+encodeURIComponent(name));
 document.getElementById('log').innerHTML='<div class=muted>'+esc(d.name)+'</div>'+(d.curated||[]).map(x=>x.k=='phase'?'<span class=p>▶ '+esc(x.t)+'</span>':'  '+esc(x.t)).join('\n');}
async function act(name){const msg=document.getElementById('amsg');
 if(name==='queue'&&!confirm('Apply queue will submit applications. Continue?'))return;
 msg.textContent='starting…';const d=await post('/api/action',{action:name});msg.textContent=d.ok||d.error||'done';liveTick();}
async function liveTick(){const d=await j('/api/live'),el=document.getElementById('live'),running=d.running||[];
 if(!d.active&&!running.length){el.innerHTML='<span class=muted>idle — no run active</span>';return}
 let h='<div class=sub>'+(d.active?'● runner active':'○ runner idle')+'</div>';
 if(running.length)h+='<div>'+running.map(r=>'<div class=r>▶ '+esc(r)+'</div>').join('')+'</div>';
 if(d.tail&&d.tail.length)h+='<div class=log style="margin-top:10px;max-height:30vh">'+d.tail.map(x=>x.k=='phase'?'<span class=p>▶ '+esc(x.t)+'</span>':'  '+esc(x.t)).join('\n')+'</div>';
 el.innerHTML=h;}
async function agentName(){try{const d=await j('/api/agent');document.getElementById('agentname').textContent='· via '+d.agent}catch(e){}}
let chatOffset=0,chatTimer=null;
async function chatSend(){const inp=document.getElementById('chatmsg'),m=inp.value.trim();if(!m)return;inp.value='';
 document.getElementById('chatst').textContent='thinking…';const d=await post('/api/chat',{message:m});
 if(d.error){document.getElementById('chatst').textContent=d.error;return}
 chatOffset=0;document.getElementById('chat').textContent='';if(!chatTimer)chatTimer=setInterval(chatPoll,1200);chatPoll();}
async function chatPoll(){const d=await j('/api/chat/tail?since='+chatOffset);
 if(d.text){const el=document.getElementById('chat');el.textContent+=d.text;el.scrollTop=el.scrollHeight}
 chatOffset=d.offset;document.getElementById('chatst').textContent=d.running?'running…':'';
 if(!d.running&&chatTimer){clearInterval(chatTimer);chatTimer=null}}
async function loadRegister(){const q=document.getElementById('req').value,st=document.getElementById('rest').value;
 const d=await j('/api/register?q='+encodeURIComponent(q)+'&status='+st);
 document.getElementById('regcount').textContent='· '+d.total+' rows';
 document.getElementById('reglist').innerHTML=d.rows.map(r=>'<div class=it onclick="openRow(this)" data-c="'+esc(r.company)+'" data-r="'+esc(r.role)+'">'+chip(r.status)+' '+esc(r.company)+' — '+esc(r.role)+'</div>').join('')||'<div class=it>no matches</div>';}
async function openRow(el){document.querySelectorAll('#reglist .it').forEach(x=>x.classList.remove('on'));el.classList.add('on');
 const c=el.dataset.c,r=el.dataset.r,d=await j('/api/register?q='+encodeURIComponent(c));
 const row=d.rows.find(x=>x.company===c&&x.role===r)||{};
 document.getElementById('regdetail').innerHTML='<div class=card><h2 style="margin-top:0">'+esc(c)+'</h2><div>'+esc(r)+'</div>'+
  '<div class=row style="margin:12px 0"><span class=sub>status</span><select id=rst>'+['SUBMITTED','INTERVIEW','OFFER','REJECTED','BLOCKED','MANUAL','PREPARED','IN_PROGRESS','CLOSED'].map(s=>'<option'+(s===row.status?' selected':'')+'>'+s+'</option>').join('')+'</select>'+
  '<span class=sub>ATS</span><b>'+esc(row.ats||'—')+'</b><span class=sub>date</span><b>'+esc(row.date||'—')+'</b></div>'+
  '<div class=sub>notes</div><textarea id=rnote style="min-height:16vh">'+esc(row.notes||'')+'</textarea>'+
  '<div class=row style="margin-top:10px"><button onclick="saveRow()">Save</button><span id=rmsg class=sub></span></div>'+
  '<div class=sub style="margin-top:8px">key: '+esc(c)+' — '+esc(r)+'</div></div>';
 window.__row=[c,r];}
async function saveRow(){const[c,r]=window.__row,status=document.getElementById('rst').value,note=document.getElementById('rnote').value;
 const d=await post('/api/row',{company:c,role:r,status:status,note:note});document.getElementById('rmsg').textContent=d.ok||d.error;tick();}
async function loadJobs(){const jobs=await j('/api/jobs');
 document.getElementById('jobscount').textContent='· '+jobs.length+' saved job specs';
 document.getElementById('jobslist').innerHTML=jobs.map(k=>'<div class=it onclick="openJob(this)" data-k="'+esc(k)+'">'+esc(k)+'</div>').join('')||'<div class=it>none saved yet</div>';}
async function openJob(el){document.querySelectorAll('#jobslist .it').forEach(x=>x.classList.remove('on'));el.classList.add('on');
 const k=el.dataset.k;document.getElementById('jobdetail').innerHTML='<span class=muted>loading '+esc(k)+'…</span>';
 const d=await j('/api/job?key='+encodeURIComponent(k)),m=d.match||{};
 const badge=m.alignment==='PASS'?'<span class="badge good">alignment PASS</span>':m.alignment==='FAIL'?'<span class="badge bad">alignment FAIL</span>':'<span class="badge mid">no CV mapped</span>';
 const cov=m.coverage==null?'<span class="badge mid">no generated docs</span>':'<span class="badge '+(m.coverage>=70?'good':m.coverage>=40?'mid':'bad')+'">keyword coverage '+m.coverage+'%</span>';
 document.getElementById('jobdetail').innerHTML='<div class=card><h2 style="margin-top:0">'+esc(k)+'</h2><div class=row>'+badge+cov+(m.archetype?' <span class=sub>archetype: '+esc(m.archetype)+'</span>':'')+'</div>'+
  (m.missing&&m.missing.length?'<div class=sub style="margin-top:8px">missing keywords: '+m.missing.map(esc).join(', ')+'</div>':'')+'</div>'+
  '<h2>Job spec</h2><pre class=doc>'+esc(d.jd||'(no saved ad)')+'</pre>'+
  '<h2>ATS keywords</h2><pre class=doc style="max-height:20vh">'+esc(d.ats||'—')+'</pre>'+
  '<h2>GraphRAG context</h2><pre class=doc style="max-height:24vh">'+esc(d.kb||'(not generated)')+'</pre>';}
async function loadConfig(){const n=document.getElementById('cfname').value,d=await j('/api/config?name='+n);
 document.getElementById('cftext').value=d.content||'';document.getElementById('cfmsg').textContent='';}
async function saveConfig(){const n=document.getElementById('cfname').value,c=document.getElementById('cftext').value;
 const d=await post('/api/config',{name:n,content:c});document.getElementById('cfmsg').textContent=d.ok||d.error;}
async function loadOutcomes(){const d=await j('/api/outcomes');document.getElementById('outrate').textContent='· overall interview rate '+d.interview_rate+'%';
 const e=Object.entries(d.by_ats).sort((a,b)=>b[1].total-a[1].total);
 document.getElementById('outbody').innerHTML=e.map(([a,v])=>'<tr><td>'+esc(a)+'</td><td>'+v.total+'</td><td>'+v.interview+'</td><td>'+v.offer+'</td><td>'+Math.round(100*v.interview/v.total)+'%</td></tr>').join('')||'<tr><td colspan=5 class=muted>no data</td></tr>';}
tick();liveTick();agentName();setInterval(tick,4000);setInterval(liveTick,2500);
</script></body></html>
"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, ctype, body):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        u = urlparse(self.path)
        if u.path == "/":
            return self._send(200, "text/html; charset=utf-8", INDEX.replace("__TOKEN__", SESSION_TOKEN).encode())
        if u.path == "/api/state":
            return self._send(200, "application/json", json.dumps(gather_state()).encode())
        if u.path == "/api/runs":
            return self._send(200, "application/json", json.dumps(gather_runs()).encode())
        if u.path == "/api/tasks":
            return self._send(200, "application/json", json.dumps(task_logs()).encode())
        if u.path == "/api/live":
            return self._send(200, "application/json", json.dumps(gather_live()).encode())
        if u.path == "/api/log":
            name = parse_qs(u.query).get("task", [""])[0]
            return self._send(200, "application/json", json.dumps(read_task_log(name)).encode())
        if u.path == "/api/agent":
            return self._send(200, "application/json", json.dumps({"agent": chat_agent()}).encode())
        if u.path == "/api/chat/tail":
            since = parse_qs(u.query).get("since", ["0"])[0]
            return self._send(200, "application/json", json.dumps(chat_tail(since)).encode())
        if u.path == "/api/register":
            qs = parse_qs(u.query)
            res = register_api(qs.get("q", [""])[0], qs.get("status", [""])[0],
                               qs.get("limit", ["60"])[0], qs.get("offset", ["0"])[0])
            return self._send(200, "application/json", json.dumps(res).encode())
        if u.path == "/api/jobs":
            return self._send(200, "application/json", json.dumps(jobs_list()).encode())
        if u.path == "/api/job":
            return self._send(200, "application/json",
                              json.dumps(job_detail(parse_qs(u.query).get("key", [""])[0])).encode())
        if u.path == "/api/match":
            return self._send(200, "application/json",
                              json.dumps(match_score(parse_qs(u.query).get("key", [""])[0])).encode())
        if u.path == "/api/config":
            return self._send(200, "application/json",
                              json.dumps(config_get(parse_qs(u.query).get("name", [""])[0])).encode())
        if u.path == "/api/outcomes":
            return self._send(200, "application/json", json.dumps(outcomes()).encode())
        self._send(404, "text/plain", b"not found")

    def do_POST(self):
        u = urlparse(self.path)
        n = int(self.headers.get("Content-Length", "0") or 0)
        try:
            data = json.loads(self.rfile.read(n).decode() or "{}")
        except ValueError:
            data = {}
        # anti-CSRF: only our own page holds the session token
        if self.headers.get("X-Session") != SESSION_TOKEN:
            return self._send(403, "application/json", json.dumps({"error": "bad session token"}).encode())
        if u.path == "/api/action":
            return self._send(200, "application/json", json.dumps(start_action(data.get("action", ""))).encode())
        if u.path == "/api/chat":
            return self._send(200, "application/json", json.dumps(chat_start(data.get("message", ""))).encode())
        if u.path == "/api/row":
            return self._send(200, "application/json", json.dumps(update_row(
                data.get("company", ""), data.get("role", ""), data.get("status", ""),
                data.get("note", ""))).encode())
        if u.path == "/api/config":
            return self._send(200, "application/json", json.dumps(config_save(
                data.get("name", ""), data.get("content", ""))).encode())
        self._send(404, "text/plain", b"not found")


def main():
    ap = argparse.ArgumentParser(description="Squirrel Dashboard - read-only web UI over the pipeline.")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--open", action="store_true", help="open the browser")
    args = ap.parse_args()
    url = f"http://{args.host}:{args.port}/"
    srv = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"🐿️  Squirrel Dashboard  ->  {url}   (Ctrl-C to stop)")
    if args.open:
        threading.Timer(0.7, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nbye")


if __name__ == "__main__":
    main()
