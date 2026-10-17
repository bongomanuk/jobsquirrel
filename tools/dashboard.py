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
ACTIONS = {
    # safe: prepares documents (REVIEW=1) and never submits or emails
    "review": {"argv": ["bash", "tools/run_queue.sh"], "env": {"REVIEW": "1", "PARALLEL": "1"},
               "purpose": "prepare documents (review run)", "token": "RUN-REVIEW", "gated": False},
    # risky: actually applies to roles (submits). Gated by approval.
    "queue": {"argv": ["bash", "tools/run_queue.sh"], "env": {},
              "purpose": "run the apply queue (submits applications)", "token": "RUN-QUEUE", "gated": True},
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
header{display:flex;align-items:center;gap:14px;padding:16px 22px;border-bottom:1px solid var(--line);
background:linear-gradient(180deg,#12161c,#0e1116)}
.sq{font-size:34px;animation:bob 2.4s ease-in-out infinite}@keyframes bob{50%{transform:translateY(-5px) rotate(-6deg)}}
h1{font-size:18px;margin:0}.sub{color:var(--dim);font-size:12px}
.wrap{padding:18px 22px;max-width:1200px;margin:0 auto}
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
.log{background:#0b0e12;border:1px solid var(--line);border-radius:12px;padding:14px;max-height:52vh;overflow:auto;
font:12px/1.6 ui-monospace,SFMono-Regular,Menlo,monospace;white-space:pre-wrap}
.log .p{color:var(--accent);font-weight:700}.log .e{color:var(--bad)}.log .g{color:var(--good)}
.muted{color:var(--dim)}a{color:var(--info);text-decoration:none}
.tools{display:flex;align-items:center;gap:8px}
button{background:var(--panel2);color:var(--fg);border:1px solid var(--line);border-radius:8px;padding:7px 12px;
font:600 13px inherit;cursor:pointer}button:hover{border-color:var(--accent)}
button.risky{border-color:#6e2b2b;color:#ffb4b4}button:disabled{opacity:.5;cursor:default}
#live .r{color:var(--accent);font-weight:700}
.hint{cursor:help;border-bottom:1px dotted var(--dim)}
button.help{padding:7px 12px;font-weight:800}
#help{display:none;position:fixed;inset:0;background:rgba(2,4,8,.66);z-index:50;padding:40px 18px;overflow:auto}
#help.on{display:block}
#help .box{max-width:780px;margin:0 auto;background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:24px}
#help h3{margin:16px 0 2px;font-size:14px;color:var(--fg)}#help p{margin:0 0 2px;color:var(--dim);font-size:13px}
</style></head><body>
<header><div class="sq">🐿️</div>
<div style="flex:1"><h1>Jobsquirrel <span class="muted" style="font-size:12px">· dashboard</span></h1>
<div class="sub" id="ts">loading…</div></div>
<div class="tools">
<button id="b-review" onclick="act('review')" class="hint"
 title="Safe: builds a tailored CV + cover letter for each queued role and runs the pre-submit gate. Records PREPARED. Never submits or emails.">Prepare (review)</button>
<button id="b-queue" class="risky hint" onclick="act('queue')"
 title="Applies to queued roles for real (submits applications). Gated: start the dashboard with APPROVE_RUN_QUEUE=1, and it confirms first.">Apply queue</button>
<button class="help hint" onclick="toggleHelp()" title="Help: what everything means">?</button>
<span id="amsg" class="sub"></span>
</div></header>
<div class="wrap">
<div class="cards" id="cards"></div>
<div class="card"><div class="l">Queue progress</div><div id="qbar" class="bar"><i style="width:0%"></i></div>
<div class="sub" id="qtext" style="margin-top:6px"></div></div>
<h2>Chat <span class="muted" id="agentname" style="text-transform:none;letter-spacing:0"></span></h2>
<div class="card" title="Talk to the coding agent the pipeline uses to do work.">
<div class="log" id="chat" style="max-height:34vh">ask the agent anything about your pipeline…</div>
<div style="display:flex;gap:8px;margin-top:10px">
<input id="chatmsg" placeholder="e.g. which interviews are coming up?"
 style="flex:1;background:#0b0e12;border:1px solid var(--line);border-radius:8px;color:var(--fg);padding:8px 10px;font:13px ui-monospace,monospace"
 onkeydown="if(event.key==='Enter')chatSend()">
<button onclick="chatSend()">Send</button>
</div>
<div class="sub" id="chatst"></div>
</div>
<h2 class="hint" title="Whether a runner is active, the tasks running now, and a curated tail of the newest task log.">Live</h2>
<div class="card" id="live"><span class="muted">idle — no run active</span></div>
<h2 class="hint" title="One row per finished task (state/logs/runs.jsonl). Click a row to see its curated log.">Recent runs</h2>
<table><thead><tr><th>When</th><th>Company</th><th>Role</th><th>Outcome</th><th>Detail</th></tr></thead>
<tbody id="runs"></tbody></table>
<h2 class="hint" title="Roles currently at the interview stage (status INTERVIEW).">Interviews</h2>
<div id="int" class="muted">—</div>
<h2 class="hint" title="Curated view of a task's opencode log: phases, gate PASS/FAIL, commands, submissions, errors — not the tool noise. Full logs are in state/logs/*.log.">Task log</h2><div class="log" id="log">click a run to see its curated log</div>
</div>
<div id="help" onclick="if(event.target.id==='help')toggleHelp()"><div class="box">
<h2 style="margin-top:0">What everything means</h2>
<h3>In process</h3><p>Applications you've sent and are still awaiting an outcome on: SUBMITTED + IN_PROGRESS + INTERVIEW + OFFER. The number that actually matters.</p>
<h3>Interviews / Rejected / Blocked / Human queue / Total</h3><p>Counts by status. <b>Blocked</b> = needs a manual step (CAPTCHA / login). <b>Human queue</b> = roles only a person can finish. <b>Total</b> = every row in the register.</p>
<h3>Queue progress</h3><p>How many queued roles the runners have processed (state/queue.done ÷ queue.tsv).</p>
<h3>Prepare (review)</h3><p><b>Safe.</b> Builds a tailored CV + cover letter per queued role and runs the pre-submit gate; records PREPARED. Nothing is submitted and no email is sent.</p>
<h3>Apply queue</h3><p><b>Submits applications.</b> Gated: start the dashboard with <code>APPROVE_RUN_QUEUE=1</code> and confirm the dialog. It never runs the same company+role twice (duplicate guard).</p>
<h3>Chat</h3><p>Talk to the coding agent the pipeline uses. It's <b>agent-agnostic</b> — whatever <code>tools/agent_run.sh</code> resolves (opencode, Claude Code, hermes, pi, or your <code>AGENT=</code>). It can use the repo's tools; irreversible actions still hit their own approval gates.</p>
<h3>Live</h3><p>Whether a runner is active, which tasks are running right now, and a curated tail of the newest task log.</p>
<h3>Recent runs &amp; Task log</h3><p>One row per finished task from <code>state/logs/runs.jsonl</code>. Click a row for a <b>curated</b> log — only the meaningful lines (phases, gate PASS/FAIL, commands, submissions, errors). Raw logs live in <code>state/logs/*.log</code>.</p>
<h3>Approvals</h3><p>Anything irreversible — sending email, deleting mail, applying — is approval-gated (see <code>tools/approval.py</code>). The dashboard is localhost-only and actions need a per-session token (anti-CSRF).</p>
<p style="margin-top:18px"><button onclick="toggleHelp()">close</button></p>
</div></div>
<script>
const TOKEN="__TOKEN__";
async function j(u){const r=await fetch(u);return r.json()}
function chip(s){return '<span class="chip s-'+s+'">'+s+'</span>'}
async function tick(){
 const s=await j('/api/state');
 document.getElementById('ts').textContent='updated '+new Date().toLocaleTimeString()+
   '  ·  '+s.total+' applications  ·  '+s.submissions+' recorded submissions';
 const c=s.counts||{};
 document.getElementById('cards').innerHTML=
  card('hero','In process',s.in_process)+
  card('','Interviews',(c.INTERVIEW||0))+card('','Rejected',(c.REJECTED||0))+
  card('','Blocked',s.blocked)+card('','Human queue',s.human)+card('','Total',s.total);
 const pct=s.queue.total?Math.round(100*s.queue.done/s.queue.total):0;
 document.querySelector('#qbar>i').style.width=pct+'%';
 document.getElementById('qtext').textContent=s.queue.done+' / '+s.queue.total+' done ('+pct+'%)';
 document.getElementById('int').innerHTML=s.interviews.length?s.interviews.map(x=>'· '+esc(x.company)+' — '+esc(x.role)).join('<br>'):'<span class=muted>none yet</span>';
 const runs=await j('/api/runs');
 document.getElementById('runs').innerHTML=runs.map(r=>'<tr onclick="loadlog(\''+esc(r.company+'-'+r.role).replace(/\//g,'_')+'\')"><td class=muted>'+esc((r.ts||'').slice(11,19))+'</td><td>'+esc(r.company)+'</td><td>'+esc(r.role)+'</td><td>'+chip(r.outcome||'?')+'</td><td class=muted>'+esc(r.reason||'')+'</td></tr>').join('')||'<tr><td colspan=5 class=muted>no runs recorded yet (they appear once run_queue.sh runs)</td></tr>';
}
function card(c,l,n){return '<div class="card '+c+' hint" title="'+esc(CARDHELP[l]||'')+'"><div class="n">'+n+'</div><div class="l">'+l+'</div></div>'}
const CARDHELP={
 'In process':'Sent, still awaiting an outcome: SUBMITTED + IN_PROGRESS + INTERVIEW + OFFER.',
 'Interviews':'Roles currently at the interview stage.',
 'Rejected':'Applications that came back as a no.',
 'Blocked':'Applications that need a manual step (CAPTCHA / login).',
 'Human queue':'Roles only a human can finish (see state/queue-human.tsv).',
 'Total':'Every row in the register (state/applications.csv).'};
function toggleHelp(){document.getElementById('help').classList.toggle('on')}
function esc(s){return (s+'').replace(/[&<>"]/g,x=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[x]))}
async function loadlog(name){
 const d=await j('/api/log?task='+encodeURIComponent(name));
 const el=document.getElementById('log');
 el.innerHTML='<div class=muted>'+esc(d.name)+'</div>'+(d.curated||[]).map(x=>x.k=='phase'?'<span class=p>▶ '+esc(x.t)+'</span>':'  '+esc(x.t)).join('\n');
}
async function act(name){
 const b=document.getElementById('b-'+name), msg=document.getElementById('amsg');
 if(name==='queue' && !confirm('Apply queue will submit applications on your behalf. Continue?')) return;
 b.disabled=true; msg.textContent='starting…';
 try{
  const r=await fetch('/api/action',{method:'POST',headers:{'Content-Type':'application/json','X-Session':TOKEN},
    body:JSON.stringify({action:name})});
  const d=await r.json(); msg.textContent=d.ok||d.error||'done';
 }catch(e){msg.textContent='error: '+e}
 setTimeout(function(){b.disabled=false;liveTick();},1500);
}
async function liveTick(){
 const d=await j('/api/live'), el=document.getElementById('live'), running=d.running||[];
 if(!d.active && !running.length){el.innerHTML='<span class=muted>idle — no run active</span>';return}
 let h='<div class=sub>'+(d.active?'● runner active':'○ runner idle')+'</div>';
 if(running.length) h+='<div>'+running.map(r=>'<div class=r>▶ '+esc(r)+'</div>').join('')+'</div>';
 if(d.tail&&d.tail.length) h+='<div class=log style="margin-top:10px;max-height:30vh">'+
   d.tail.map(x=>x.k=='phase'?'<span class=p>▶ '+esc(x.t)+'</span>':'  '+esc(x.t)).join('\n')+'</div>';
 el.innerHTML=h;
}
tick();liveTick();agentName();setInterval(tick,3000);setInterval(liveTick,2000);
let chatOffset=0, chatTimer=null;
async function agentName(){try{const d=await j('/api/agent');document.getElementById('agentname').textContent='· via '+d.agent}catch(e){}}
async function chatSend(){
 const inp=document.getElementById('chatmsg'), msg=inp.value.trim(); if(!msg)return;
 inp.value=''; document.getElementById('chatst').textContent='thinking…';
 try{
  const r=await fetch('/api/chat',{method:'POST',headers:{'Content-Type':'application/json','X-Session':TOKEN},
    body:JSON.stringify({message:msg})});
  const d=await r.json();
  if(d.error){document.getElementById('chatst').textContent=d.error;return}
 }catch(e){document.getElementById('chatst').textContent='error: '+e;return}
 chatOffset=0; document.getElementById('chat').textContent='';
 if(!chatTimer) chatTimer=setInterval(chatPoll,1200);
 chatPoll();
}
async function chatPoll(){
 const d=await j('/api/chat/tail?since='+chatOffset);
 if(d.text){const el=document.getElementById('chat'); el.textContent+=d.text; el.scrollTop=el.scrollHeight}
 chatOffset=d.offset; document.getElementById('chatst').textContent=d.running?'running…':'';
 if(!d.running && chatTimer){clearInterval(chatTimer);chatTimer=null}
}
</script></body></html>"""


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
