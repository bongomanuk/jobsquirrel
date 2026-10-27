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
import glob
from functools import lru_cache
import html as _html
import json
import mimetypes
import os
import re
import secrets
import signal
import subprocess
import sys
import threading
import time
import urllib.request
import uuid
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs, quote

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATE = os.environ.get("DASHBOARD_STATE", os.path.join(ROOT, "state"))
LOGS = os.path.join(STATE, "logs")
WEB = os.path.join(ROOT, "tools", "web")
SESSION_TOKEN = secrets.token_urlsafe(24)
BOOT_ID = secrets.token_urlsafe(8)          # changes on every restart; lets open tabs reload

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
                    "action": (r.get("action") or "").strip(),
                    "cv_file": r.get("cv_file"), "cv_sha256": r.get("cv_sha256"),
                    "letter_file": r.get("letter_file"), "letter_sha256": r.get("letter_sha256"),
                    "evidence": r.get("evidence"),"snapshot_dir": snap, "screenshots": shots}
    return {}


def update_row(company, role, status, note, employment=None, action=None,
               work_model=None, salary=None, key=""):
    if not (company and role):
        return {"error": "company and role required"}
    sys.path.insert(0, os.path.join(ROOT, "tools"))
    import register as REG
    REG.set_row(company, role, status=(status or "").upper(), note=note or "",
                employment=employment, action=action)
    if work_model is not None or salary is not None:
        set_role_meta(key or _slug(f"{company}-{role}"),
                      work_model=work_model, salary=salary)
    return {"ok": f"updated {company} / {role}"}


# ---------------------------------------------------------------- drafted replies
def drafts_list(company="", role=""):
    sys.path.insert(0, os.path.join(ROOT, "tools"))
    import draft_email as DE
    return {"drafts": DE.list_drafts(company, role)}


def draft_get(path):
    sys.path.insert(0, os.path.join(ROOT, "tools"))
    import draft_email as DE
    try:
        return {"draft": DE.load_draft(path)}
    except (OSError, ValueError) as e:
        return {"error": str(e)}


def draft_save(data):
    sys.path.insert(0, os.path.join(ROOT, "tools"))
    import draft_email as DE
    path = data.get("path") or ""
    try:
        if path:
            saved = DE.update_draft(path, data.get("to", ""), data.get("cc", ""),
                                    data.get("subject", ""), data.get("body", ""),
                                    data.get("attachments") or [], data.get("company", ""),
                                    data.get("role", ""))
        else:
            if not (data.get("company") and data.get("role")):
                return {"error": "company and role required"}
            saved = DE.save_draft(data.get("company", ""), data.get("role", ""),
                                  data.get("to", ""), data.get("cc", ""),
                                  data.get("subject", ""), data.get("body", ""),
                                  data.get("attachments") or [])
        return {"ok": "saved", "path": saved, "draft": DE.load_draft(saved)}
    except (OSError, ValueError) as e:
        return {"error": str(e)}


def draft_delete(path):
    sys.path.insert(0, os.path.join(ROOT, "tools"))
    import draft_email as DE
    return {"ok": "deleted"} if DE.delete_draft(path) else {"error": "draft not found"}


def _apply_draft_edits(d, edits, validate=True):
    """Apply edits from the approval dialog to the saved draft (headers sanitised)."""
    def pick(key, default, header=False, limit=200000):
        v = edits.get(key)
        if v is None:
            return default
        v = str(v)
        if header:
            v = re.sub(r"[\r\n]+", " ", v).strip()
        return v[:limit]
    to = pick("to", d.get("to", ""), header=True, limit=2000)
    cc = pick("cc", d.get("cc", ""), header=True, limit=2000)
    subject = pick("subject", d.get("subject", ""), header=True, limit=500)
    body = pick("body", d.get("body", ""))
    if validate:
        if not to.strip():
            return {"error": "add a recipient before sending"}
        if not subject.strip():
            return {"error": "add a subject before sending"}
        if not body.strip():
            return {"error": "the email body is empty — not sent"}
    try:
        import draft_email as DE
        DE.update_draft(d["path"], to=to, cc=cc, subject=subject, body=body,
                        attachments=d.get("attachments") or [],
                        company=d.get("company") or "", role=d.get("role") or "")
    except (OSError, ValueError) as e:
        return {"error": f"could not save the edited draft: {e}"}
    return {}


def draft_send(path, clear_action=False):
    """Send exactly one saved draft, after a human approves (and may edit) it."""
    sys.path.insert(0, os.path.join(ROOT, "tools"))
    import draft_email as DE
    try:
        d = DE.load_draft(path)
    except (OSError, ValueError) as e:
        return {"error": str(e)}
    # A human must approve this exact draft, every time. The dialog shows the
    # whole email and can edit it; the receipt is issued AFTER those edits.
    who = d.get("to") or "(no recipient)"
    purpose = f"sending draft to {who} — {d.get('subject') or '(no subject)'}"
    email = {"to": d.get("to", ""), "cc": d.get("cc", ""), "subject": d.get("subject", ""),
             "body": d.get("body", ""), "attachments": d.get("attachments") or []}
    res = consent_request(purpose, "SEND-EMAIL", timeout=900, email=email)
    edits = res.get("edits") or {}
    if res.get("decision") != "allow":
        if res.get("save") and edits:
            problem = _apply_draft_edits(d, edits, validate=False)
            if problem:
                return problem
            return {"ok": "changes saved — email not sent"}
        return {"error": "refused: the email was not approved"}
    if edits:
        problem = _apply_draft_edits(d, edits, validate=True)
        if problem:
            return problem
        d = DE.load_draft(d["path"])
    sys.path.insert(0, os.path.join(ROOT, "tools"))
    import send_receipt as SRE
    SRE.issue(d["path"], "dashboard")
    env = agent_env()
    env.pop("APPROVE_SEND_EMAIL", None)
    try:
        r = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "gmail_send.py"),
                            "--draft", d["path"]],
                           cwd=ROOT, env=env, capture_output=True, text=True, timeout=380)
    except subprocess.TimeoutExpired:
        return {"error": "timed out (approval unanswered?)"}
    out = (r.stdout + "\n" + r.stderr).strip()
    if r.returncode != 0 or "sent " not in out:
        return {"error": out or f"gmail_send exited {r.returncode}", "output": out}
    mid = out.split("sent ", 1)[1].split()[0]
    DE.mark_sent(d["path"], mid)
    if clear_action and d.get("company") and d.get("role"):
        try:
            sys.path.insert(0, os.path.join(ROOT, "tools"))
            import register as REG
            REG.set_row(d["company"], d["role"], action="")
        except Exception:
            pass
    return {"ok": f"sent {mid}", "message_id": mid, "output": out}


# ---------------------------------------------------------------- queue
def _queue_rows(path):
    out = []
    for ln in _lines(path):
        p = (ln.split("\t") + [""] * 6)[:6]
        # Some queues (queue-human.tsv) put a reason in the 6th column rather
        # than a key; never mistake that for the key -- derive the slug instead.
        key = p[5]
        reason = ""
        if not re.fullmatch(r"[a-z0-9._-]{3,}", key or ""):
            reason, key = key, _slug(f"{p[0]}-{p[1]}")
        ats, letter = p[4], ""
        if ats.lower().endswith((".docx", ".pdf")):     # human queue carries the letter here
            letter, ats = ats, ""
        out.append({"company": p[0], "role": p[1], "url": p[2], "cv": p[3], "ats": ats,
                    "key": key, "reason": reason, "letter": letter})
    return out


def queue_files():
    return {"pending": _queue_rows(os.path.join(STATE, "queue.tsv")),
            "human": _queue_rows(os.path.join(STATE, "queue-human.tsv")),
            "retry": _queue_rows(os.path.join(STATE, "queue.retry")),
            "done": [l.replace("|", " — ") for l in _lines(os.path.join(STATE, "queue.done"))]}


def _drop_key(path, key):
    keep, n = [], 0
    for ln in _read(path).splitlines():
        p = (ln.split("\t") + [""] * 6)[:6]
        if (p[0] + "|" + p[1]).lower() == key.lower():
            n += 1
            continue
        keep.append(ln)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(keep).rstrip("\n") + ("\n" if keep else ""))
    return n


def _queue_fields(company, role):
    """Recover url/cv/ats/key so a re-queued row is complete."""
    for path in ("queue.tsv", "queue-human.tsv", "queue.retry",
                 "queue-prepared-linkedin.tsv", "queue-linkedin.tsv"):
        for r in _queue_rows(os.path.join(STATE, path)):
            if r["company"].lower() == company.lower() and r["role"].lower() == role.lower():
                if r["url"] or r["key"]:
                    return r["url"], r["cv"], r["ats"], r["key"]
    for r in _rows(os.path.join(STATE, "submissions.csv")):
        if r["company"].lower() == company.lower() and r["role"].lower() == role.lower():
            return r.get("apply_url", ""), r.get("cv_file", ""), r.get("ats", ""), _slug(f"{company}-{role}")
    return "", "", "", _slug(f"{company}-{role}")


def _row_note(company, role):
    for r in _rows(os.path.join(STATE, "applications.csv")):
        if r["company"].lower() == company.lower() and r["role"].lower() == role.lower():
            return r.get("notes", "")
    return ""


def _prepared_letter(company, role, key):
    """The cover letter recorded/prepared for this row, if any."""
    m = re.search(r"documents/[^\s|;]*_Motivation_[^\s|;]*\.docx", _row_note(company, role))
    if m and os.path.exists(os.path.join(ROOT, m.group(0))):
        return m.group(0)
    hits = sorted(glob.glob(os.path.join(ROOT, "documents", "applications", f"*_Motivation_{key}.docx")))
    return os.path.relpath(hits[-1], ROOT) if hits else ""


def _prepared_cv(company, role, key):
    """The targeted CV prepared for this row (falls back to the queue's archetype)."""
    return _prepared_cv_note(_row_note(company, role), key)


def _prepared_cv_note(note, key, cv_index=None):
    """The targeted CV from a register note, or the key index (cheap, no CSV read)."""
    m = re.search(r"documents/[^\s|;]*_CV_[^\s|;]*\.docx", note or "")
    if m and os.path.exists(os.path.join(ROOT, m.group(0))):
        return m.group(0)
    if cv_index is not None:
        return cv_index.get(key, "")
    hits = sorted(glob.glob(os.path.join(ROOT, "documents", "applications", f"*_CV_{key}.docx")))
    return os.path.relpath(hits[-1], ROOT) if hits else ""


def queue_action(action, company, role):
    if not (company and role):
        return {"error": "company and role required"}
    key = f"{company}|{role}"
    q = os.path.join(STATE, "queue.tsv")
    if action == "delete":
        n = sum(_drop_key(os.path.join(STATE, f), key) for f in ("queue.tsv", "queue-human.tsv", "queue.retry"))
        return {"ok": f"removed {n} row(s)"}
    if action in ("retry", "unblock"):
        url, cv, ats, k = _queue_fields(company, role)
        for f in ("queue.tsv", "queue-human.tsv", "queue.retry", "queue.done"):
            _drop_key(os.path.join(STATE, f), key)
        with open(q, "a", encoding="utf-8") as fh:
            fh.write("\t".join([company, role, url, cv, ats, k]) + "\n")
        try:
            sys.path.insert(0, os.path.join(ROOT, "tools"))
            import register as REG
            REG.set_row(company, role, status="QUEUED",
                        note=("unblocked via dashboard" if action == "unblock" else "retry via dashboard"))
        except Exception:
            pass
        return {"ok": f"{'unblocked' if action == 'unblock' else 're-queued'} {company} / {role}"}
    if action == "human":
        # One role, one visible browser, everything pre-filled: the human only has
        # to clear the challenge and press Submit. The queue row carries the exact
        # cv/letter/reason so the assist agent uploads the prepared documents.
        url, cv, ats, k = _queue_fields(company, role)
        cv = _prepared_cv(company, role, k) or cv
        letter = _prepared_letter(company, role, k)
        reason = (_row_note(company, role).split("|")[0].strip() or "human step")[:200]
        os.makedirs(LOGS, exist_ok=True)
        tmp = os.path.join(LOGS, "queue-human-ui.tsv")
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write("\t".join([company, role, url, cv, letter, reason]) + "\n")
        tmp_done = os.path.join(LOGS, "queue-human-ui.done")     # empty: never skip this row
        with open(tmp_done, "w", encoding="utf-8"):
            pass
        _spawn(f"human assist: {company} / {role}",
               ["bash", os.path.join(ROOT, "tools", "human_assist.sh")],
               {"QUEUE": tmp, "DONE": tmp_done})
        return {"ok": f"opening a VISIBLE browser for {company} / {role} — it pre-fills everything, "
                      f"then you solve the challenge and submit"}
    return {"error": "unknown action"}


def open_apply(company, role):
    """Open the employer's apply page in the operator's own browser."""
    import shutil
    url, _, _, _ = _queue_fields(company, role)
    if not url:
        return {"error": "no apply URL recorded for this row"}
    opener = "open" if sys.platform == "darwin" else "xdg-open"
    if not shutil.which(opener):
        return {"error": f"{opener} not available"}
    subprocess.Popen([opener, url], start_new_session=True)
    return {"ok": f"opened {url}"}


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

# Coverage (ATS-keyword hit %) is cheap to compute, so the grid can show it for
# every row; alignment runs a subprocess and stays on-demand. Both are persisted
# here, keyed by a signature of the inputs so restarts don't recompute.
MATCH_FILE = os.path.join(LOGS, "dashboard-match.json")
_COV, _cov_loaded, _cov_dirty = {}, False, False
_arch_text = {}


def _load_cov():
    global _cov_loaded
    if _cov_loaded:
        return
    _cov_loaded = True
    try:
        with open(MATCH_FILE, encoding="utf-8") as fh:
            _COV.update(json.load(fh))
    except (OSError, ValueError):
        pass


def _save_cov():
    global _cov_dirty
    if not _cov_dirty:
        return
    try:
        os.makedirs(LOGS, exist_ok=True)
        tmp = MATCH_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(_COV, fh)
        os.replace(tmp, MATCH_FILE)
        _cov_dirty = False
    except OSError:
        pass


# Employment/engagement type: the register field wins; otherwise guess it from
# the saved job ad. Persisted (with the JD's mtime) so the grid stays cheap.
EMP_FILE = os.path.join(LOGS, "dashboard-employment.json")
_EMP, _emp_loaded, _emp_dirty = {}, False, False
EMPLOYMENT_TYPES = ["full-time", "part-time", "contract", "consultant",
                    "freelance", "internship", "temporary"]
# Ordered checks; the first that matches wins. Deliberately conservative so a
# job title like "Senior Consultant" at a consultancy isn't mistaken for a
# consultancy engagement, and "permanent contract" reads as full-time.
_EMP_CHECKS = (
    ("freelance", lambda t: re.search(r"freelance|freelancer", t)),
    ("part-time", lambda t: re.search(r"part[- ]time", t)),
    ("internship", lambda t: re.search(r"internship|\bintern\b|\bpraktik\b", t)),
    ("temporary", lambda t: re.search(r"\btemporary\b|maternity cover|parental cover|\bvikariat\b", t)),
    ("consultant", lambda t: re.search(r"\bconsultant (contract|role|engagement|position|basis)"
                                       r"|\bas a consultant\b|independent consultant"
                                       r"|consultancy contract|freelance consultant", t)),
    ("contract", lambda t: re.search(r"fixed[- ]term|\bcontractor\b|\bb2b\b|day rate|\binterim\b"
                                     r"|outside ir35|inside ir35"
                                     r"|\b\d+[- ]?(month|year)s?[- ]contract\b"
                                     r"|\bcontract (role|position|basis|assignment|work|employment|"
                                     r"duration|length|to hire|of \d)\b|\bon a contract\b", t)),
    ("full-time", lambda t: re.search(r"full[- ]time|permanent|\bfte\b|tillsvidare|direct hire", t)),
)


def _load_emp():
    global _emp_loaded
    if _emp_loaded:
        return
    _emp_loaded = True
    try:
        with open(EMP_FILE, encoding="utf-8") as fh:
            _EMP.update(json.load(fh))
    except (OSError, ValueError):
        pass


def _save_emp():
    global _emp_dirty
    if not _emp_dirty:
        return
    try:
        os.makedirs(LOGS, exist_ok=True)
        tmp = EMP_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(_EMP, fh)
        os.replace(tmp, EMP_FILE)
        _emp_dirty = False
    except OSError:
        pass


def _employment_from_jd(key):
    """Engagement type read from the saved job ad (cached by the ad's mtime)."""
    path = os.path.join(STATE, "job-descriptions", key + ".md")
    mt = _mtime(path)
    if not mt:
        return ""
    hit = _EMP.get(key) or {}
    if hit.get("mt") == mt:
        return hit.get("type", "")
    text = _read(path, 30000).lower()
    etype = ""
    for name, check in _EMP_CHECKS:
        if check(text):
            etype = name
            break
    _EMP[key] = {"mt": mt, "type": etype}
    globals()["_emp_dirty"] = True
    return etype


def _employment_from_notes(notes):
    """Engagement type guessed from the register notes (weaker signal than the ad)."""
    t = (notes or "").lower()
    if not t:
        return ""
    for name, check in _EMP_CHECKS:
        if check(t):
            return name
    return ""


# ---------------------------------------------------------------- pay + work model
# Estimated annual pay and work model, derived from the saved ad. The estimates
# are deliberately rough: they rank/filter roles, they do not replace the ad.
# Manual overrides persist in state/logs/dashboard-role-meta.json and win.
_PAY_FX = {"EUR": 1.0, "SEK": 0.090, "USD": 0.92, "GBP": 1.17,
           "CAD": 0.68, "CHF": 1.05, "DKK": 0.134, "NOK": 0.086}
_PAY_ANNUAL = {"year": 1, "month": 12, "week": 48, "day": 220, "hour": 1600}
PAY_FIT = 70                                             # default "good fit" threshold
PAY_TARGET_FALLBACK = 100000
META_VERSION = 1                                         # bump when the parser changes
META_FILE = os.path.join(LOGS, "dashboard-role-meta.json")
_META, _meta_loaded, _meta_dirty = {}, False, False
_TARGET = {"mt": 0, "eur": PAY_TARGET_FALLBACK}

_PAY_HEAD = re.compile(
    r"^\s*(?:base\s+)?(salary|compensation|pay|rate|package|remuneration)\b[^:]{0,40}:\s*(.+)$", re.I)
_PAY_HINT = re.compile(r"(salary|compensation|pay|rate|remuneration)", re.I)
_PAY_CUR = (("CAD", r"\bCA\$|\bCAD\b"), ("EUR", r"\bEUR\b|€"), ("USD", r"\bUSD\b|\bUS\$|\$"),
            ("GBP", r"\bGBP\b|£"), ("CHF", r"\bCHF\b"), ("DKK", r"\bDKK\b"),
            ("NOK", r"\bNOK\b"), ("SEK", r"\bSEK\b|\bkr\b"))
_PAY_CUR_RE = re.compile(r"(€|£|\$|\b(?:EUR|SEK|USD|GBP|CHF|DKK|NOK|CAD)\b|\bkr\b)", re.I)


def _pay_num(token):
    if re.fullmatch(r"\d{1,3}(?:[ .,]\d{3})+", token):
        return float(token.replace(" ", "").replace(",", "").replace(".", ""))
    return float(token.replace(",", "."))


_PAY_METRICS = re.compile(r"revenue|turnover|funding|raised|valuation|billion|million users|employees", re.I)


def _pay_salary_like(text):
    return bool(re.search(r"\d{1,3}(?:[ ,.]\d{3})+|\d{4,}|\d+\s*[kK]\b", text))


def _pay_line_blocks(s):
    """Sentences in one line that read like pay, not corporate metrics."""
    if len(s) <= 240:
        return [s] if _pay_salary_like(s) else []
    out = []
    for part in re.split(r"(?<=[.!?])\s+", s):
        if (len(part) <= 240 and _PAY_HINT.search(part) and _PAY_CUR_RE.search(part)
                and _pay_salary_like(part) and not _PAY_METRICS.search(part)):
            out.append(part)
    return out[:2]


def _pay_blocks(text):
    """Candidate salary/compensation lines from an ad (URLs and equity skipped)."""
    out, lines = [], (text or "").splitlines()
    for i, line in enumerate(lines):
        s = line.strip()
        if not s or re.search(r"https?://|www\.", s, re.I):
            continue
        m = _PAY_HEAD.match(s)
        if m:
            out.append(m.group(2).strip())
            for nxt in lines[i + 1:i + 3]:
                n = nxt.strip()
                if n and not re.match(r"^[A-Z][A-Za-z /&-]{2,40}:", n) and _pay_salary_like(n):
                    out.append(n)
            continue
        if _PAY_HINT.search(s) and _PAY_CUR_RE.search(s):
            out.extend(_pay_line_blocks(s))
    seen, uniq = set(), []
    for x in out:
        if x not in seen:
            seen.add(x)
            uniq.append(x[:240])
    return uniq[:8]


def _parse_pay_block(raw):
    if not raw:
        return None
    t = raw.replace("\u2013", "-").replace("\u2014", "-").replace("\u2212", "-").replace("\u00a0", " ")
    # "kr840000" / "SEK1,000,000" are common; separate the code from the amount.
    t = re.sub(r"\b(EUR|SEK|USD|GBP|CHF|DKK|NOK|CAD|kr)\s*", r"\1 ", t, flags=re.I)
    cur = next((c for c, pat in _PAY_CUR if re.search(pat, t, re.I)), None)
    if not cur:
        return None
    amounts = []
    for m in re.finditer(r"(?<![\w./])(\d{1,3}(?:[ .,]\d{3})+|\d+(?:[.,]\d+)?)\s*([kKmM])?(?![%\w])", t):
        try:
            v = _pay_num(m.group(1))
        except ValueError:
            continue
        suf = (m.group(2) or "").lower()
        if suf == "k":
            v *= 1000
        elif suf == "m":
            v *= 1000000
        if v >= 10:
            amounts.append((v, m.start()))
    if not amounts:
        return None
    low = t.lower()
    period = ""
    for name, pat in (("hour", r"per hour|/hour|hourly|/hr\b|an hour|\bhour\b"),
                      ("day", r"per day|/day|daily|day rate"),
                      ("week", r"per week|/week|weekly"),
                      ("month", r"per month|/month|monthly|a month|/mo\b"),
                      ("year", r"per year|/year|/yr\b|annually|per annum|a year")):
        if re.search(pat, low):
            period = name
            break
    vals = [a[0] for a in amounts]
    chosen = vals[0]
    if len(vals) >= 2:
        before = low[:amounts[0][1]]
        # "up to X ... exceptional Y" -> the realistic number is X
        if re.search(r"up to[^.;]{0,24}$", before) and max(vals) > 1.5 * min(vals):
            chosen = vals[0]
        else:
            chosen = (min(vals) + max(vals)) / 2
    if not period:
        if cur in ("SEK", "NOK", "DKK"):
            period = "year" if chosen >= 300000 else ("month" if chosen >= 15000 else "hour")
        else:
            period = "year" if chosen >= 30000 else ("hour" if chosen < 500 else "month")
    eur = chosen * _PAY_ANNUAL[period] * _PAY_FX[cur]
    return {"currency": cur, "period": period, "low": round(min(vals)), "high": round(max(vals)),
            "chosen": round(chosen), "eur": int(round(eur / 1000) * 1000), "raw": t[:200]}


def parse_pay(text, extract=True):
    """Best salary estimate from an ad (or from one override line)."""
    parsed = [p for p in (_parse_pay_block(b) for b in
                          (_pay_blocks(text) if extract else [text or ""])) if p]
    if not parsed:
        return None
    # Prefer EUR, then SEK, over other locations.
    for market in ("SEK", "EUR"):
        for p in parsed:
            if p["currency"] == market:
                return p
    if len({p["currency"] for p in parsed}) > 1:
        return None                                     # location-specific ranges, no EU/SEK figure
    return parsed[0]


def _salary_label(p):
    if not p:
        return ""
    k = p["eur"] / 1000
    return f"≈€{round(k)}k" if k >= 10 else f"≈€{p['eur']:,}"


def _salary_target():
    path = os.path.join(ROOT, "config", "profile.md")
    mt = _mtime(path)
    if _TARGET.get("mt") == mt:
        return _TARGET["eur"]
    eur = PAY_TARGET_FALLBACK
    m = re.search(r"salary target\s*:\s*([^\n]+)", _read(path, 20000), re.I)
    if m:
        p = parse_pay(m.group(1), extract=False)
        if p:
            eur = p["eur"]
    _TARGET.update(mt=mt, eur=eur)
    return eur


def _work_from_text(text):
    """remote / hybrid / on-site / '' from the ad's location or work-model lines."""
    if not text:
        return ""
    region = ""
    for line in text.splitlines()[:30]:
        if re.match(r"^\s*(work model|location(?:\s*/\s*work model)?|remote|workplace)\b", line, re.I):
            region += " " + line.lower()
    if not region:
        region = "\n".join(text.splitlines()[:30]).lower()
    if (re.search(r"\b(fully|100%|100 ?percent)\s+remote\b|\bremote[- ]first\b|"
                  r"\bwork from (anywhere|home)\b|\bremote \((?:eu|europe|anywhere)|\bremote\b", region)
            and not re.search(r"no remote|not remote", region)):
        return "remote"
    if re.search(r"\bhybrid\b(?!\s+cloud)|some (?:office|in-office) days|"
                 r"\b\d+\s*(?:-\s*\d+\s*)?days?\s*(?:a|per)\s*week\s*(?:in|at)\s*(?:the\s*)?office|"
                 r"partly remote|part remote", region):
        return "hybrid"
    if re.search(r"\bon-?site\b|in[- ]office|in[- ]person|office[- ]based|"
                 r"work(?:ing)? from (?:the )?office", region):
        return "on-site"
    body = text[:6000].lower()
    if re.search(r"\bfully remote\b|\b100% remote\b|\bremote[- ]first\b|work from anywhere", body):
        return "remote"
    if re.search(r"\bhybrid\b(?!\s+cloud)|some office days|days a week in (the )?office", body):
        return "hybrid"
    if re.search(r"\b(?:on-?site|in[- ]office|in[- ]person)\b", body):
        return "on-site"
    return ""


def _work_label(w):
    return {"remote": "Remote", "hybrid": "Hybrid", "on-site": "On-site"}.get(w, "—")


def _load_meta():
    global _meta_loaded
    if _meta_loaded:
        return
    _meta_loaded = True
    try:
        with open(META_FILE, encoding="utf-8") as fh:
            _META.update(json.load(fh))
    except (OSError, ValueError):
        pass


def _save_meta(force=False):
    global _meta_dirty
    if not (_meta_dirty or force):
        return
    try:
        os.makedirs(LOGS, exist_ok=True)
        tmp = META_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(_META, fh)
        os.replace(tmp, META_FILE)
        _meta_dirty = False
    except OSError:
        pass


def _role_meta(key, notes=""):
    """Effective pay/work model: JD-derived, with a manual override on top."""
    _load_meta()
    path = os.path.join(STATE, "job-descriptions", key + ".md")
    mt = _mtime(path) or 0
    e = _META.setdefault(key, {})
    if e.get("v") != META_VERSION or e.get("mt", -1) != mt or "salary" not in e:
        text = _read(path, 20000) if mt else ""
        e["mt"] = mt
        e["v"] = META_VERSION
        e["salary"] = parse_pay(text) if text else None
        e["salary_raw"] = (e["salary"] or {}).get("raw", "")
        e["work_model"] = _work_from_text(text) if text else ""
        globals()["_meta_dirty"] = True
    sal, raw = e.get("salary"), e.get("salary_raw") or ""
    if e.get("salary_override"):
        raw = e["salary_override"]
        sal = parse_pay(raw, extract=False)
    work = e.get("work_override") or e.get("work_model")
    if not work and notes:
        work = _work_from_text(notes[:4000])
    return {"salary": sal, "salary_raw": raw,
            "salary_override": bool(e.get("salary_override")),
            "work_model": work or "unknown",
            "work_detected": e.get("work_model") or "unknown",
            "work_override": bool(e.get("work_override"))}


def set_role_meta(key, work_model=None, salary=None):
    """Persist a manual pay/work-model override ('' clears it)."""
    if not key:
        return
    _load_meta()
    e = _META.setdefault(key, {})
    if work_model is not None:
        e["work_override"] = (work_model or "").strip().lower()
    if salary is not None:
        e["salary_override"] = (salary or "").strip()
    globals()["_meta_dirty"] = True
    _save_meta(force=True)


def _pay_work_fields(key, notes, status, cov, target):
    """The grid's pay/work/focus fields for one row."""
    meta = _role_meta(key, notes)
    sal = meta["salary"]
    eur = sal["eur"] if sal else None
    work = meta["work_model"]
    focus = (status not in ("CLOSED", "REJECTED") and cov is not None
             and cov >= PAY_FIT and eur is not None and eur >= target)
    focus_unknown = (status not in ("CLOSED", "REJECTED") and cov is not None
                     and cov >= PAY_FIT and eur is None)
    score = (round(0.6 * cov + 0.4 * min(100, 100 * eur / target))
             if cov is not None and eur is not None else None)
    band = ("good" if eur is not None and eur >= target else
            "mid" if eur is not None and eur >= 0.8 * target else
            "low" if eur is not None else "")
    return {"salary_eur": eur, "salary_label": _salary_label(sal),
            "salary_raw": meta["salary_raw"], "salary_band": band,
            "salary_override": meta["salary_override"],
            "work_model": work, "work_label": _work_label(work),
            "work_detected": meta.get("work_detected", work),
            "work_override": meta["work_override"],
            "focus": focus, "focus_unknown": focus_unknown, "focus_score": score}


def _doc_text(path):
    """Plain text of a CV file: .docx, .pdf (pdftotext) or .md/.txt. Cached by path+mtime."""
    if not path or not os.path.isfile(path):
        return ""
    ck = f"{path}:{_mtime(path)}"
    if ck in _arch_text:
        return _arch_text[ck]
    ext = os.path.splitext(path)[1].lower()
    t = ""
    try:
        if ext == ".docx":
            import docx
            doc = docx.Document(path)
            out = [p.text for p in doc.paragraphs]

            def walk(tbl):
                for row in tbl.rows:
                    for c in row.cells:
                        out.append(c.text)
                        for t in c.tables:
                            walk(t)
            for t in doc.tables:
                walk(t)
            t = "\n".join(x for x in out if x and x.strip())
        elif ext == ".pdf":
            import shutil
            exe = shutil.which("pdftotext")
            if exe:
                r = subprocess.run([exe, path, "-"], capture_output=True, text=True, timeout=30)
                t = r.stdout or ""
        else:
            t = _read(path)
    except Exception:
        t = ""
    _arch_text[ck] = t
    return t


def _mtime(path):
    try:
        return int(os.path.getmtime(path))
    except OSError:
        return 0


def _skills_text():
    """The candidate's recorded skills/evidence — so the fit reflects skills the moment
    they're added, without waiting for a CV to be regenerated."""
    return (_read(os.path.join(ROOT, "config", "cv.json")) + " " + _read(SKILLS_FILE)).lower()


@lru_cache(maxsize=4096)
def _norm_slug(s):
    return re.sub(r"[^a-z0-9]+", "", (s or "").lower())


def _ats_key_for(company, role, key, stems=None):
    """The ATS/JD slug for a row, even when the agent resolved its own key."""
    if os.path.isfile(os.path.join(STATE, "ats", key + ".txt")):
        return key
    cn = _norm_slug(company)
    if len(cn) < 4:
        return key
    if stems is None:
        try:
            stems = [f[:-4] for f in os.listdir(os.path.join(STATE, "ats")) if f.endswith(".txt")]
        except OSError:
            return key
    role_norm = _norm_slug(role)
    best, best_score = key, 0
    for s in stems:
        sn = _norm_slug(s)
        if not sn or not (sn.startswith(cn) or cn.startswith(sn)):
            continue
        score = min(len(sn), len(cn))
        if role_norm and any(tok in role_norm for tok in re.findall(r"[a-z0-9]{4,}", s.lower())):
            score += 10
        if score > best_score:
            best, best_score = s, score
    return best


def _content_key_for(cvrel, key):
    """The cv-content/letters-content slug implied by the prepared CV filename."""
    m = re.search(r"_CV_(.+?)\.docx$", cvrel or "")
    if m and os.path.isfile(os.path.join(STATE, "cv-content", m.group(1) + ".json")):
        return m.group(1)
    return key


def _jd_key_for(ats_key, key):
    return ats_key if os.path.isfile(os.path.join(STATE, "job-descriptions", ats_key + ".md")) else key


def _cov_sig(key, cvrel, ats_key=None, content_key=None):
    ak, ck = ats_key or key, content_key or key
    cvp = cvrel if os.path.isabs(cvrel or "") else os.path.join(ROOT, cvrel or "")
    return ":".join(str(_mtime(p)) for p in (
        os.path.join(STATE, "ats", ak + ".txt"),
        os.path.join(STATE, "cv-content", ck + ".json"),
        os.path.join(STATE, "letters-content", ck + ".json"), cvp,
        os.path.join(ROOT, "config", "cv.json"), SKILLS_FILE))


def coverage_for(key, cvrel="", ats_key=None, content_key=None):
    """ATS-keyword coverage %: the tailored content packs + the candidate's recorded skills
    (and the archetype CV text as a fallback)."""
    global _cov_dirty
    ak, ck = ats_key or key, content_key or key
    kws = [l.strip() for l in _lines(os.path.join(STATE, "ats", ak + ".txt"))]
    if not kws:
        return None
    sig = _cov_sig(key, cvrel, ats_key=ak, content_key=ck)
    hit = _COV.get(key) or {}
    if hit.get("sig") == sig and "cov" in hit:
        return hit["cov"]
    hay = (_read(os.path.join(STATE, "cv-content", ck + ".json")) + " "
           + _read(os.path.join(STATE, "letters-content", ck + ".json"))).lower()
    if not hay.strip() and cvrel:
        cvp = cvrel if os.path.isabs(cvrel) else os.path.join(ROOT, cvrel)
        hay = _doc_text(cvp).lower()
    hay += " " + _skills_text()
    cov = None
    if hay.strip():
        cov = round(100 * sum(1 for k in kws if k.lower() in hay) / len(kws))
    _COV.setdefault(key, {}).update(sig=sig, cov=cov)
    _cov_dirty = True
    return cov


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
    _load_cov()
    _COV.setdefault(key, {})["align"] = res["alignment"]
    globals()["_cov_dirty"] = True
    _save_cov()
    return res


def role_docs(key):
    """The rendered documents for a role: the tailored CV (.docx/.pdf) and cover letter."""
    app = os.path.join(ROOT, "documents", "applications")
    out = {"cv": "", "cv_pdf": "", "letter": ""}

    def pick(pattern):
        hits = sorted(glob.glob(os.path.join(app, pattern.replace("{k}", glob.escape(key)))))
        return os.path.relpath(hits[0], ROOT) if hits else ""

    out["cv"] = pick("*_CV_{k}.docx")
    out["cv_pdf"] = pick("*_CV_{k}.pdf")
    out["letter"] = pick("*_Motivation_{k}.docx") or pick("*_Letter_{k}.docx")
    out["letter_pdf"] = pick("*_Motivation_{k}.pdf") or pick("*_Letter_{k}.pdf")
    return out


def _evidenced_skills():
    """Skill names that have recorded evidence in kb/sources/personal/skills_evidence.md."""
    out = set()
    for ln in _read(SKILLS_FILE).splitlines():
        m = re.match(r"- \*\*(.+?)\*\*", ln.strip())
        if m:
            out.add(m.group(1).strip().lower())
    return out


def match_info(key):
    """Cheap match for the detail drawer: keyword coverage + missing terms, no subprocess.
    (The alignment gate runs only when you explicitly prepare/recompute.)"""
    kws = [l.strip() for l in _lines(os.path.join(STATE, "ats", key + ".txt")) if l.strip()]
    content = _read(os.path.join(STATE, "cv-content", key + ".json"))
    letters = _read(os.path.join(STATE, "letters-content", key + ".json"))
    hay = (content + " " + letters).lower()
    if not hay.strip():
        cv = _archetype_for(key)
        if cv:
            hay = _doc_text(cv if os.path.isabs(cv) else os.path.join(ROOT, cv)).lower()
    hay += " " + _skills_text()                     # recorded skills count toward the fit
    cov, missing, evidenced = None, [], []
    if kws and hay.strip():
        miss = [k for k in kws if k.lower() not in hay]
        cov = round(100 * (len(kws) - len(miss)) / len(kws))
        missing = miss[:24]
        ev = _evidenced_skills()
        evidenced = [k for k in missing if k.strip().lower() in ev]
    return {"key": key, "coverage": cov, "missing": missing, "evidenced": evidenced,
            "alignment": (_COV.get(key, {}) or {}).get("align", ""),
            "archetype": os.path.basename(_archetype_for(key) or "")}


def role_detail(key):
    key = os.path.basename(key)[:120]
    return {"key": key,
            "jd": _read(os.path.join(STATE, "job-descriptions", key + ".md")),
            "ats": _read(os.path.join(STATE, "ats", key + ".txt")),
            "kb": _read(os.path.join(STATE, "kb-context", key + ".md"))[:12000],
            "tailored_cv": _read(os.path.join(STATE, "cv-content", key + ".json"))[:12000],
            "letter": _read(os.path.join(STATE, "letters-content", key + ".json"))[:12000],
            "docs": role_docs(key),
            "match": match_info(key)}


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


def _key_maps():
    km, cv = {}, {}
    for path in ("queue.tsv", "queue-human.tsv", "queue.retry"):
        for r in _queue_rows(os.path.join(STATE, path)):
            if r["key"]:
                km[(r["company"].lower(), r["role"].lower())] = r["key"]
                if r["cv"]:
                    cv[r["key"]] = r["cv"]
    return km, cv


def _hint(status, notes):
    """A plain-language 'what this means / what to do' line for a row."""
    parts = [x.strip() for x in (notes or "").split(" | ") if x.strip()]
    reason = parts[0] if parts else ""
    if status in ("BLOCKED", "MANUAL"):
        return reason or "needs you — open the row to get past the block"
    if status in ("CLOSED", "REJECTED"):
        return (parts[-1] if parts else "") or ("closed — no action" if status == "CLOSED" else "rejected — no action")
    return {
        "QUEUED": "in the apply queue — nothing done yet; applied when you run the queue",
        "DRAFTING": "in progress — ad/keywords saved, but no finished documents yet",
        "PREPARED": "documents generated and gated — ready to apply",
        "NO RESULT": "a run finished but produced nothing (no ad, no documents, no application) — re-prepare it, or remove it",
        "SUBMITTED": "applied — waiting for a reply",
        "IN_PROGRESS": "application in progress",
        "INTERVIEW": "interview held — awaiting the outcome",
        "OFFER": "offer — respond",
    }.get(status, "")


_MONTHS = {m: i for i, m in enumerate(
    ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"), 1)}
# A segment counts as interview-related if it says any of these; "booked" and
# "confirmed" catch the terse "Booked: Thu 15 Oct …" / "Confirmed: …" notes.
_INTERVIEW_WORDS = ("interview", "screen", "intro call", "first chat", "call with",
                    "booked", "confirmed", "invit")
# No date yet, but clearly still being arranged -> INVITED rather than held.
_INVITED_WORDS = ("invit", "schedul", "availabil", "await", "reschedul", "book at",
                  "asked", "reply", "follow", "still interested")


def _interview_time(notes):
    """Latest interview datetime mentioned in the notes (epoch seconds, 0 if none).

    Only '|'-separated segments that talk about an interview/screen/call are
    scanned, so application dates or start dates don't flip the label."""
    best = 0.0
    for seg in re.split(r"\s*\|\s*", notes or ""):
        sl = seg.strip().lower()
        if sl.startswith("gmail:"):                     # reconciler metadata: the email's date, not the interview's
            continue
        if any(w in sl for w in ("email sent to", "message id", "outbound", "sent:")):
            continue                                     # outbound note: the send date, not an interview
        if any(w in sl for w in ("asked", "followed up", "follow-up", "still interested",
                                 "reply", "not booked", "availability")):
            continue                                     # correspondence, not a booked interview
        if not any(w in seg.lower() for w in _INTERVIEW_WORDS):
            continue
        for m in re.finditer(r"\b(20\d{2})-(\d{2})-(\d{2})(?:[ T](\d{1,2}):(\d{2}))?", seg):
            try:
                best = max(best, time.mktime((int(m.group(1)), int(m.group(2)), int(m.group(3)),
                                              int(m.group(4) or 0), int(m.group(5) or 0),
                                              0, 0, 0, -1)))
            except (OverflowError, ValueError):
                pass
        for m in re.finditer(r"\b(\d{1,2})\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)"
                             r"[a-z]*\.?\s+(20\d{2})(?:[ ,]+(\d{1,2}):(\d{2}))?", seg, re.I):
            try:
                best = max(best, time.mktime((int(m.group(3)), _MONTHS[m.group(2).lower()[:3]],
                                              int(m.group(1)), int(m.group(4) or 0),
                                              int(m.group(5) or 0), 0, 0, 0, -1)))
            except (OverflowError, ValueError):
                pass
    return best


def _interview_label(status, notes):
    """Distinguish the interview sub-states for the grid.

      SCHEDULED  a future interview is booked
      INVITED     being arranged (no confirmed date yet)
      INTERVIEW   held — awaiting the outcome

    Returns (display_label, 'YYYY-MM-DD HH:MM' or '')."""
    if status != "INTERVIEW":
        return status, ""
    iv = _interview_time(notes)
    if iv > time.time():
        return "SCHEDULED", time.strftime("%Y-%m-%d %H:%M", time.localtime(iv))
    if iv:
        return "INTERVIEW", time.strftime("%Y-%m-%d %H:%M", time.localtime(iv))
    if any(w in (notes or "").lower() for w in _INVITED_WORDS):
        return "INVITED", ""
    return "INTERVIEW", ""



def grid():
    """One row per application: register ⋈ queue ⋈ in-flight running tasks ⋈ provenance."""
    apps = _rows(os.path.join(STATE, "applications.csv"))
    _load_cov(); _load_emp()
    target = _salary_target()
    km, cvmap = _key_maps()
    qstate, qrow = {}, {}
    for st, path in (("pending", "queue.tsv"), ("human", "queue-human.tsv"), ("retry", "queue.retry")):
        for r in _queue_rows(os.path.join(STATE, path)):
            ck = (r["company"].lower(), r["role"].lower())
            qstate[ck] = st
            qrow.setdefault(ck, r)
    done = set(l.strip() for l in _lines(os.path.join(STATE, "queue.done")))
    subm = {(r["company"].lower(), r["role"].lower())
            for r in _rows(os.path.join(STATE, "submissions.csv"))}
    subm_cv = {(r["company"].lower(), r["role"].lower()): r.get("cv_file", "")
               for r in _rows(os.path.join(STATE, "submissions.csv")) if r.get("cv_file")}
    subm_url = {(r["company"].lower(), r["role"].lower()): r.get("apply_url", "")
                for r in _rows(os.path.join(STATE, "submissions.csv")) if r.get("apply_url")}
    try:
        specs = {f[:-3] for f in os.listdir(os.path.join(STATE, "job-descriptions")) if f.endswith(".md")}
    except OSError:
        specs = set()

    def _keyset(folder, ext):
        try:
            return {f[:-len(ext)] for f in os.listdir(os.path.join(STATE, folder)) if f.endswith(ext)}
        except OSError:
            return set()
    ats_set, kb_set, cv_set = _keyset("ats", ".txt"), _keyset("kb-context", ".md"), _keyset("cv-content", ".json")
    ats_stems = sorted(ats_set)
    cv_index = {}
    try:
        app_dir = os.path.join(ROOT, "documents", "applications")
        for f in os.listdir(app_dir):
            m = re.match(r".*_CV_(.+?)\.docx$", f)
            if not m:
                continue
            k = m.group(1)
            rel = os.path.join("documents", "applications", f)
            mt = _mtime(os.path.join(app_dir, f)) or 0
            if k not in cv_index or mt >= cv_index[k][0]:
                cv_index[k] = (mt, rel)
    except OSError:
        pass
    cv_index = {k: v[1] for k, v in cv_index.items()}

    def stages_for(key, applied, jd_key=None, ats_key=None, content_key=None):
        """What has actually happened to this job so far (artifact slugs may differ)."""
        jk, ak, ck = jd_key or key, ats_key or key, content_key or key
        return {"ad": jk in specs, "keywords": ak in ats_set,
                "grounding": jk in kb_set or ak in kb_set,
                "documents": ck in cv_set or key in cv_set, "applied": bool(applied)}
    running = set()
    if WQ:
        try:
            for k in WQ.live_tasks():
                co, _, role = k.partition("|")
                running.add((co.strip().lower(), role.strip().lower()))
        except Exception:
            running = set()
    out = []
    seen = set()
    for r in apps:
        co, role = r["company"], r["role"]
        ck = (co.lower(), role.lower())
        seen.add(ck)
        key = km.get(ck) or _slug(f"{co}-{role}")
        notes = r.get("notes", "")
        cvrel = _prepared_cv_note(notes, key, cv_index) or cvmap.get(key, "") or subm_cv.get(ck, "")
        ats_key = _ats_key_for(co, role, key, stems=ats_stems)
        content_key = _content_key_for(cvrel, key)
        jd_key = _jd_key_for(ats_key, key)
        m = _MATCH_CACHE.get(key, {})
        cov = m.get("coverage")
        if cov is None:
            cov = coverage_for(key, cvrel, ats_key=ats_key, content_key=content_key)
        align = m.get("alignment") or (_COV.get(key, {}) or {}).get("align", "")
        status = (r.get("status") or "").upper()
        label, interview_at = _interview_label(status, notes)
        hint = _hint(status, notes)
        if status == "INTERVIEW":
            hint = {"SCHEDULED": f"interview booked {interview_at} — prepare",
                    "INVITED": "interview requested — reply and get a time booked"}.get(
                        label, (f"interview held {interview_at} — awaiting the outcome" if interview_at
                                else "interview held — awaiting the outcome"))
        employment = ((r.get("employment") or "").strip().lower()
                      or _employment_from_jd(jd_key) or _employment_from_notes(notes))
        out.append({"date": r.get("date", ""), "company": co, "role": role, "ats": r.get("ats", ""),
                    "status": status, "label": label, "interview_at": interview_at, "key": key,
                    "employment": employment,
                    "queue": "finished" if f"{co}|{role}" in done else qstate.get(ck, ""),
                    "spec": jd_key in specs, "applied": ck in subm,
                    "match": cov, "alignment": align, "running": ck in running,
                    "notes": notes, "letter": r.get("letter", ""), "action": (r.get("action") or "").strip(),
                    "url": qrow.get(ck, {}).get("url", "") or subm_url.get(ck, ""),
                    "stages": stages_for(key, ck in subm, jd_key=jd_key,
                                         ats_key=ats_key, content_key=content_key),
                    **_pay_work_fields(jd_key, notes, status, cov, target),
                    "hint": hint})
    # queued but not yet in the register — show the work that's waiting / in flight
    for ck, r in qrow.items():
        if ck in seen:
            continue
        co, role = r["company"], r["role"]
        key = r["key"] or _slug(f"{co}-{role}")
        m = _MATCH_CACHE.get(key, {})
        cov = m.get("coverage")
        if cov is None:
            cov = coverage_for(key, r.get("cv", ""))
        jd = os.path.join(STATE, "job-descriptions", key + ".md")
        stamp = _mtime(jd) or _mtime(os.path.join(STATE, "queue.tsv"))
        qdate = time.strftime("%Y-%m-%d", time.localtime(stamp)) if stamp else ""
        st = stages_for(key, ck in subm)
        if st["applied"]:
            stg = "SUBMITTED"
        elif st["documents"]:
            stg = "PREPARED"
        elif st["ad"] or st["keywords"] or st["grounding"]:
            stg = "DRAFTING"
        elif f"{co}|{role}" in done:
            stg = "NO RESULT"
        else:
            stg = "QUEUED"
        out.append({"date": qdate, "company": co, "role": role, "ats": r.get("ats", ""),
                    "status": stg, "label": stg, "interview_at": "", "key": key,
                    "employment": r.get("employment", "") or _employment_from_jd(key),
                    "queue": "finished" if f"{co}|{role}" in done else qstate.get(ck, "pending"),
                    "spec": key in specs, "applied": ck in subm,
                    "match": cov, "alignment": m.get("alignment", ""), "running": ck in running,
                    "notes": "", "letter": "", "action": "", "url": r.get("url", ""), "stages": st,
                    **_pay_work_fields(key, "", stg, cov, target),
                    "hint": _hint(stg, "")})
    _save_cov(); _save_emp(); _save_meta()
    out.sort(key=lambda x: (x["date"] or ""), reverse=True)
    out.sort(key=lambda x: 0 if x["running"] else (1 if x["status"] == "QUEUED" else 2))
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
    path = os.path.join(LOGS, name + ".log")
    try:
        st = os.stat(path)
        size, age = st.st_size, int(time.time() - st.st_mtime)
    except OSError:
        size, age = 0, None
    text = ANSI.sub("", _read(path, cap=400_000))
    return {"name": name, "curated": curate(text),
            "raw": text.splitlines()[-400:], "size": size, "age": age}


def _web_build():
    """Restart + static-frontend fingerprint, so an open tab reloads itself."""
    try:
        static = "|".join(
            f"{st.st_mtime_ns}:{st.st_size}"
            for st in (os.stat(os.path.join(WEB, f)) for f in ("index.html", "app.css", "app.js"))
        )
    except OSError:
        static = ""
    return f"{BOOT_ID}|{static}"


def live():
    _act_load()
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
    proc = _ACT.get("proc")
    act_running = bool(proc and proc.poll() is None)
    act_lines = action_log(4000)
    act_log = act_lines[-400:]
    act_name = _ACT.get("name", "")
    def _running_task(k):
        co, _, role = k.partition("|")
        name = f"{co}-{role}".translate(str.maketrans(" /|", "___"))
        try:
            st = os.stat(os.path.join(LOGS, name + ".log"))
            age, size = int(time.time() - st.st_mtime), st.st_size
        except OSError:
            age, size = None, 0
        return {"label": k.replace("|", " — "), "log": name, "age": age, "size": size}
    return {"active": active, "running": [k.replace("|", " — ") for k in running],
            "running_tasks": [_running_task(k) for k in running],
            "tail_name": tail_name, "tail": tail,
            "paused": os.path.exists(PAUSE_FILE),
            "stopping": os.path.exists(STOP_FILE),
            "build": _web_build(),
            "action": {"name": act_name, "running": act_running,
                       "summary": summarize_action(act_name, act_log, act_running),
                       "overview": action_overview(act_name, act_lines, act_running),
                       "log": act_log}}


ACT_NOISE = re.compile(r"^\s*(?:[─═\-_=]{4,}|[.|·•]\s*$|\d+%?\s*\|)")


def summarize_action(name, lines, running):
    """Compress an action log into a headline + the few lines that matter."""
    clean = [l.rstrip() for l in lines if l.strip() and not ACT_NOISE.match(l)]
    wanted = re.compile(r"(error|fail|warn|refus|denied|traceback|⇒|→|nothing to|no changes|"
                        r"proposed|verification|unmatched|ambiguous|summary|"
                        r"\bwrote\b|\bwritten\b|\bsaved\b|prepared|submitted|applied|created|"
                        r"proposal|\b[1-9]\d*\b\s*(?:new|found|queued|sent|updated|skipped|matched))", re.I)
    notable, seen = [], set()
    for l in clean:
        if wanted.search(l) and l not in seen:
            notable.append(l.strip()[:200]); seen.add(l)
    notable = notable[-8:]
    return {"headline": (clean[-1][:200] if clean else ("running…" if running else "no output")),
            "notable": notable, "lines": len(clean)}


RECON_SUMMARY = re.compile(
    r"summary \((dry run|applied)\): (\d+) inspected · (\d+) proposed · "
    r"(\d+) outbound · (\d+) verification · (\d+) unmatched · (\d+) ambiguous")


def action_overview(name, lines, running):
    """A short 'where we are / what's new' summary after a reconcile."""
    if "reconcile" not in (name or "").lower():
        return []
    apps = _rows(os.path.join(STATE, "applications.csv"))
    counts = {}
    for r in apps:
        k = (r.get("status") or "").upper()
        counts[k] = counts.get(k, 0) + 1
    live = sum(counts.get(k, 0) for k in ("SUBMITTED", "IN_PROGRESS", "INTERVIEW", "OFFER"))
    live_parts = " · ".join(f"{s} {counts[s]}" for s in
                            ("SUBMITTED", "IN_PROGRESS", "INTERVIEW", "OFFER") if counts.get(s))
    flagged = sum(1 for r in apps if (r.get("action") or "").strip())
    blocked = counts.get("BLOCKED", 0) + counts.get("MANUAL", 0)
    human = _count(os.path.join(STATE, "queue-human.tsv"))
    out = [f"live {live}" + (f" — {live_parts}" if live_parts else "")]
    needs = " · ".join(x for x in (
        f"{human} waiting on you" if human else "",
        f"{flagged} flagged" if flagged else "",
        f"{blocked} blocked/manual" if blocked else "") if x)
    out.append("needs you " + (needs or "nothing"))
    out.append(f"queue {_count(os.path.join(STATE, 'queue.tsv'))} · "
               f"prepared {counts.get('PREPARED', 0)} · "
               f"closed {counts.get('CLOSED', 0)} (hidden by default) · "
               f"rejected {counts.get('REJECTED', 0)}")
    hit = None
    for line in reversed(lines):
        hit = RECON_SUMMARY.search(line)
        if hit:
            break
    if hit:
        mode, _insp, proposed, _out, verification, unmatched, ambiguous = hit.groups()
        out.append(f"new this run ({mode}): {proposed} proposed · {verification} verification · "
                   f"{unmatched} unmatched · {ambiguous} ambiguous")
    elif running:
        tail = [l.strip() for l in lines if l.strip()]
        out.append("new this run: reconciling…" + (f" ({tail[-1][:100]})" if tail else ""))
    changes, in_sec = [], False
    for line in lines:
        s = line.strip()
        if s.startswith("== proposed register changes"):
            in_sec = True
            continue
        if in_sec:
            if s.startswith("=="):
                break
            if s and s != "(none)":
                changes.append("new: " + " ".join(s.split())[:140])
    if changes:
        out.extend(changes[:5])
        if len(changes) > 5:
            out.append(f"new: … and {len(changes) - 5} more")
    return out


def logs_tail(lines=100):
    p = os.path.join(LOGS, "run_queue.out")
    return {"logs": ANSI.sub("", _read(p, cap=200_000)).splitlines()[-int(lines or 100):]}


# ---------------------------------------------------------------- file viewer
SAFE_DIRS = ("documents", "state", "config", "kb", "answers", "docs")


def _safe_path(rel):
    """Resolve a viewable path: inside the repo (allow-listed top dir) or under $HOME
    (recorded CVs/letters can be absolute paths outside the repo). Secrets always blocked."""
    rel = (rel or "").strip()
    root = os.path.realpath(ROOT)
    home = os.path.realpath(os.path.expanduser("~"))
    p = os.path.realpath(rel if os.path.isabs(rel) else os.path.join(ROOT, rel.lstrip("/")))
    if p.startswith(root + os.sep):
        top = p[len(root) + 1:].split(os.sep)[0]
        if top not in SAFE_DIRS:
            return None
    elif not p.startswith(home + os.sep):
        return None
    if any(x in p.lower() for x in ("token", "credential", ".env", "accounts.json", ".ssh", ".gnupg")):
        return None
    return p


def file_view(rel):
    p = _safe_path(rel)
    if not p or not os.path.isfile(p):
        return {"error": "not found or not allowed"}
    ext = os.path.splitext(p)[1].lower()
    if ext == ".docx":
        try:
            import docx
            doc = docx.Document(p)
            out = []
            for para in doc.paragraphs:
                if para.text.strip():
                    out.append(f"<p>{_html.escape(para.text)}</p>")
            for t in doc.tables:
                for row in t.rows:
                    out.append("<p>" + " | ".join(_html.escape(c.text) for c in row.cells) + "</p>")
            return {"kind": "docx", "html": "".join(out), "name": os.path.basename(p)}
        except Exception as e:
            return {"error": f"could not read docx: {e}"}
    if ext in (".md", ".txt", ".csv", ".json", ".log"):
        return {"kind": "text", "text": _read(p), "name": os.path.basename(p)}
    if ext == ".pdf":
        return {"kind": "pdf", "url": "/raw?path=" + quote(rel), "name": os.path.basename(p)}
    if ext in (".png", ".jpg", ".jpeg", ".gif", ".webp"):
        return {"kind": "image", "url": "/raw?path=" + quote(rel), "name": os.path.basename(p)}
    return {"kind": "other", "url": "/raw?path=" + quote(rel), "name": os.path.basename(p)}


def raw_file(rel):
    p = _safe_path(rel)
    if not p or not os.path.isfile(p):
        return None, None, None
    try:
        with open(p, "rb") as fh:
            return fh.read(), (mimetypes.guess_type(p)[0] or "application/octet-stream"), os.path.basename(p)
    except OSError:
        return None, None, None


# ---------------------------------------------------------------- chat
CHAT_LOG = os.path.join(LOGS, "dashboard-chat.log")
CHAT_SESSION = os.path.join(LOGS, "dashboard-chat.session")
_CHAT = {"proc": None, "queue": []}
CHAT_PID = os.path.join(LOGS, "dashboard-chat.pid")


def _chat_pid_write(pid):
    try:
        os.makedirs(LOGS, exist_ok=True)
        with open(CHAT_PID, "w") as fh:
            fh.write(str(pid))
    except OSError:
        pass


def _chat_pid_read():
    """pid of the running chat turn, even if this dashboard process didn't spawn it."""
    try:
        pid = int(open(CHAT_PID).read().strip())
    except (OSError, ValueError):
        return 0
    try:
        os.kill(pid, 0)
    except OSError:
        return 0
    return pid


def _chat_running():
    p = _CHAT.get("proc")
    if p is not None:
        return p.poll() is None
    return bool(_chat_pid_read())


def chat_agent():
    try:
        r = subprocess.run(["bash", os.path.join(ROOT, "tools", "agent_run.sh"), "--which"],
                           cwd=ROOT, capture_output=True, text=True, timeout=10)
        return (r.stdout or "").strip() or "?"
    except (OSError, subprocess.SubprocessError):
        return "?"


def _chat_session():
    try:
        with open(CHAT_SESSION, encoding="utf-8") as fh:
            return fh.read().strip()
    except OSError:
        return ""


def _record_chat_session(text):
    """Remember the agent's session id so the next message continues the same conversation."""
    sid = ""
    for ln in text.splitlines():
        i = ln.find('"sessionID"')
        if i != -1:
            j = ln.find(':"', i + 11)
            if j != -1:
                sid = ln[j + 2:].split('"', 1)[0]
    if sid and sid != _chat_session():
        try:
            with open(CHAT_SESSION, "w", encoding="utf-8") as fh:
                fh.write(sid)
        except OSError:
            pass


def chat_stop():
    """Stop the current turn (and drop queued messages) but KEEP the transcript."""
    _CHAT["queue"] = []
    pid = (_CHAT["proc"].pid if _CHAT.get("proc") and _CHAT["proc"].poll() is None
           else _chat_pid_read())
    killed = False
    if pid:
        try:
            os.killpg(os.getpgid(pid), signal.SIGTERM)
            killed = True
        except OSError:
            try:
                os.kill(pid, signal.SIGTERM)
                killed = True
            except OSError:
                pass
    _CHAT["proc"] = None
    try:
        os.remove(CHAT_PID)
    except OSError:
        pass
    return {"ok": "stopped the current turn" if killed else "nothing was running"}


def chat_new():
    """Clear the chat history: stop any running turn, drop the queue, transcript + session."""
    _CHAT["queue"] = []
    pid = (_CHAT["proc"].pid if _CHAT.get("proc") and _CHAT["proc"].poll() is None
           else _chat_pid_read())
    if pid:
        try:
            os.killpg(os.getpgid(pid), signal.SIGTERM)
        except OSError:
            pass
        _CHAT["proc"] = None
    try:
        os.remove(CHAT_PID)
    except OSError:
        pass
    for path in (CHAT_LOG, CHAT_SESSION):
        try:
            os.remove(path)
        except OSError:
            pass
    return {"ok": "history cleared"}


# ---------------------------------------------------------------- per-role chat (drawer → Discuss)
ROLE_CHAT_DIR = os.path.join(LOGS, "role-chat")
_ROLE = {}                      # key -> {"proc": Popen, "queue": [(message, company, role)]}


def _role_key(key):
    k = re.sub(r"[^a-z0-9._-]+", "-", (key or "").lower()).strip("-")[:120]
    if not k:
        raise ValueError("role key required")
    os.makedirs(ROLE_CHAT_DIR, exist_ok=True)
    return k


def _role_paths(key):
    k = _role_key(key)
    return (os.path.join(ROLE_CHAT_DIR, k + ".log"),
            os.path.join(ROLE_CHAT_DIR, k + ".session"),
            os.path.join(ROLE_CHAT_DIR, k + ".pid"))


def _role_pid(key):
    _, _, pidf = _role_paths(key)
    try:
        pid = int(open(pidf).read().strip())
    except (OSError, ValueError):
        return 0
    try:
        os.kill(pid, 0)
    except OSError:
        return 0
    return pid


def _role_running(key):
    k = _role_key(key)
    st = _ROLE.get(k) or {}
    p = st.get("proc")
    if p is not None:
        return p.poll() is None
    return bool(_role_pid(k))


def _role_session(key):
    _, sess, _ = _role_paths(key)
    try:
        with open(sess, encoding="utf-8") as fh:
            return fh.read().strip()
    except OSError:
        return ""


def _role_find_session(text):
    sid = ""
    for ln in text.splitlines():
        i = ln.find('"sessionID"')
        if i != -1:
            j = ln.find(':"', i + 11)
            if j != -1:
                sid = ln[j + 2:].split('"', 1)[0]
    return sid


def _role_record_session(key, text):
    _, sess, _ = _role_paths(key)
    sid = _role_find_session(text)
    if sid and sid != _role_session(key):
        try:
            with open(sess, "w", encoding="utf-8") as fh:
                fh.write(sid)
        except OSError:
            pass


def _role_echo(key, message):
    log, _, _ = _role_paths(key)
    os.makedirs(LOGS, exist_ok=True)
    with open(log, "a", encoding="utf-8") as fh:
        fh.write(f"\n> {message}\n")


def _role_context(company, role, key):
    import register as REG
    row = None
    for r in REG.load():
        if r["company"].strip().lower() == company.strip().lower() and \
                r["role"].strip().lower() == role.strip().lower():
            row = r
            break
    bits = [f"- Company: {company}", f"- Role: {role}"]
    if row:
        bits += [f"- Status: {row.get('status','')}",
                 f"- Follow-up flag: {row.get('action','') or '(none)'}",
                 f"- Engagement: {row.get('employment','') or '(unknown)'}"]
        notes = (row.get("notes") or "").strip()
        if notes:
            bits.append(f"- Notes: {notes[:1400]}")
        if row.get("letter"):
            bits.append(f"- Cover letter: {row['letter']}")
    jd = os.path.join(STATE, "job-descriptions", key + ".md")
    if os.path.isfile(jd):
        bits.append(f"- Job ad file: {os.path.relpath(jd, ROOT)}")
    cv = os.path.join(STATE, "cv-content", key + ".json")
    if os.path.isfile(cv):
        bits.append(f"- Tailored CV content: {os.path.relpath(cv, ROOT)}")
    return ("You are discussing ONE application with the candidate. Stay on this role.\n"
            + "\n".join(bits) + "\n\n"
            "Answer questions about this role and help with next steps: reply wording, interview "
            "preparation, follow-ups, gaps and positioning. Be concise and practical. If email is "
            "needed, save a draft with tools/draft_email.py and ask the candidate to press Send with "
            "approval in the drawer (never send; gmail_send.py refuses unapproved drafts). Never submit an application "
            "or change the register without explicit approval. Read the job ad/CV files above when useful.")


def _role_spawn(key, message, company, role):
    log, _, pidf = _role_paths(key)
    sid = _role_session(key)
    base = message if sid else (CHAT_PREAMBLE + "\n\n" + _role_context(company, role, key) + "\n\n---\n" + message)
    prompt = GATE_NOTE + "\n\n" + base
    f = open(log, "a", encoding="utf-8")
    env = agent_env(AGENT_JSON="1")
    if sid:
        env["AGENT_SESSION"] = sid
    p = subprocess.Popen(["bash", os.path.join(ROOT, "tools", "agent_run.sh"), prompt],
                         cwd=ROOT, env=env, stdout=f, stderr=subprocess.STDOUT,
                         start_new_session=True)
    st = _ROLE.setdefault(_role_key(key), {"proc": None, "queue": []})
    st["proc"] = p
    try:
        with open(pidf, "w") as fh:
            fh.write(str(p.pid))
    except OSError:
        pass


def _role_pump(key):
    k = _role_key(key)
    if _role_running(k):
        return
    q = _ROLE.get(k, {}).get("queue") or []
    if q:
        message, company, role = q.pop(0)
        _role_spawn(k, message, company, role)


def role_chat_start(key, company, role, message):
    message = (message or "").strip()[:6000]
    if not message:
        return {"error": "empty message"}
    k = _role_key(key)
    if _role_running(k):
        _ROLE.setdefault(k, {"proc": None, "queue": []})["queue"].append((message, company, role))
        _role_echo(k, message)
        return {"status": "queued", "queued": True}
    _role_echo(k, message)
    _role_spawn(k, message, company, role)
    return {"status": "started"}


def role_chat_stream(key):
    k = _role_key(key)
    _role_pump(k)
    log, _, _ = _role_paths(k)
    try:
        text = ANSI.sub("", open(log, encoding="utf-8", errors="ignore").read())
    except OSError:
        text = ""
    _role_record_session(k, text)
    kind = _json_kind(text)
    if kind == "opencode":
        segs = chat_parse_json(text)
    elif kind == "claude":
        segs = chat_parse_claude(text)
    else:
        segs = chat_parse(text)
    if len(segs) > 300:
        segs = segs[-300:]
    q = _ROLE.get(k, {}).get("queue") or []
    return {"segments": segs, "running": _role_running(k), "pending": len(q),
            "done": not _role_running(k) and not q}


def role_chat_stop(key):
    k = _role_key(key)
    _ROLE.setdefault(k, {"proc": None, "queue": []})["queue"] = []
    pid = (_ROLE.get(k, {}).get("proc").pid if _ROLE.get(k, {}).get("proc")
           and _ROLE[k]["proc"].poll() is None else _role_pid(k))
    killed = False
    if pid:
        try:
            os.killpg(os.getpgid(pid), signal.SIGTERM)
            killed = True
        except OSError:
            try:
                os.kill(pid, signal.SIGTERM)
                killed = True
            except OSError:
                pass
    _ROLE.setdefault(k, {"proc": None, "queue": []})["proc"] = None
    try:
        os.remove(_role_paths(k)[2])
    except OSError:
        pass
    return {"ok": "stopped this role's turn" if killed else "nothing was running"}


def role_chat_new(key):
    k = _role_key(key)
    role_chat_stop(k)
    for path in (_role_paths(k)[0], _role_paths(k)[1]):
        try:
            os.remove(path)
        except OSError:
            pass
    return {"ok": "role chat cleared"}


CHAT_PREAMBLE = (
    "You are the operator assistant for THIS repository: the Jobsquirrel job-search pipeline. "
    "The repo root is your cwd. Read AGENTS.md at the repo root first; it is your operating manual, "
    "and the human in the chat is the candidate whose job search this pipeline runs. "
    "Answer questions about the job search from the pipeline's own state, NOT from git history: "
    "the canonical register is state/applications.csv with counts from `python3 tools/register.py --stats` "
    "(also written to state/counts.md); the apply queue is state/queue*.tsv; what was sent to whom is "
    "state/submissions.csv; conversion is `python3 tools/outcomes.py`. Treat 'updates', 'status' and "
    "'how's it going' as job-search progress (applications, interviews, replies, queue) unless the "
    "operator explicitly asks about the code. Be concise; use the repo's tools; never take an "
    "irreversible action (submitting applications, sending email, deleting mail) without explicit approval. "
    "NEVER send email yourself: save a draft with tools/draft_email.py and ask the candidate to press "
    "Send with approval in the role drawer. gmail_send.py refuses non-draft sends and drafts without a "
    "human dashboard receipt; do not try to set APPROVE_SEND_EMAIL, call the Gmail API directly, "
    "or work around it. "
    "IMPORTANT, this is a job-search tool: when the operator says 'skills', 'my experience', 'my background' "
    "or 'add what I did at X', they mean their JOB/CAREER skills (technologies, competencies, roles, "
    "achievements) for their CV — capture those in the knowledge base (kb/sources/*.md, grounded and "
    "attributed) and config/cv.json so they flow into the tailored CVs and cover letters. They do NOT mean "
    "coding-agent tooling (opencode skill packages, plugins, MCP servers, IDE extensions). If a request "
    "could be read either way, assume career/job skills and ask only if still unclear. ")


def _chat_echo(message):
    os.makedirs(LOGS, exist_ok=True)
    with open(CHAT_LOG, "a", encoding="utf-8") as fh:
        fh.write(f"\n> {message}\n")


# The agent reaches outside the repo only through the gate (tools/agent_access.py),
# which asks the operator; native external access is denied so it can't bypass it.
AGENT_PERMISSIONS = {"permission": {"external_directory": {"*": "deny"}, "task": "allow"}}
GATE_NOTE = ("Before reading files outside this repo, writing files, or running shell commands, use the "
             "gate so the operator can approve: `python3 tools/agent_access.py read|write|run ...`. "
             "It asks the operator and only proceeds if they allow it.")


DASH = {"url": ""}          # set in main(); handed to the embedded agent so it can ask for approval


# ---------------------------------------------------------------- agent / LLM config
AGENT_CFG_FILE = os.path.join(os.path.expanduser("~"), ".config", "job-search", "agent.json")
GRAPHRAG_ENV = os.path.join(ROOT, "kb", "graphrag", ".env")


def load_agent_cfg():
    try:
        with open(AGENT_CFG_FILE, encoding="utf-8") as fh:
            d = json.load(fh)
        models = d.get("models") if isinstance(d.get("models"), dict) else {}
        models = {str(k)[:200]: str(v)[:200] for k, v in models.items() if v}
        agent = d.get("agent", "") or ""
        model = (d.get("model", "") or "").strip() or models.get(agent, "")
        return {"agent": agent, "model": model, "models": models,
                "env": d.get("env", {}) or {}}
    except (OSError, ValueError):
        return {"agent": "", "model": "", "models": {}, "env": {}}


def save_agent_cfg(d):
    prev = load_agent_cfg()
    agent = str(d.get("agent", prev["agent"]) or "").strip()[:200]
    models = dict(prev.get("models") or {})
    if isinstance(d.get("models"), dict):
        for k, v in d["models"].items():
            k, v = str(k).strip()[:200], str(v).strip()[:200]
            if k and v:
                models[k] = v
    if "model" in d:
        model = str(d.get("model") or "").strip()[:200]
        if agent:
            if model:
                models[agent] = model
            else:
                models.pop(agent, None)
    else:
        model = prev["model"]
        if agent and not model:
            model = models.get(agent, "")
    env = dict(prev["env"])
    for k, v in (d.get("env") or {}).items():
        k = re.sub(r"[^A-Za-z0-9_]", "", str(k))[:80]
        if not k:
            continue
        if v in ("", None):
            env.pop(k, None)                      # blank clears
        else:
            env[k] = str(v)[:1000]
    out = {"agent": agent, "model": model, "models": models, "env": env}
    os.makedirs(os.path.dirname(AGENT_CFG_FILE), exist_ok=True)
    fd = os.open(AGENT_CFG_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=2)
    return out


def _mask(v):
    v = v or ""
    return ("…" + v[-4:]) if len(v) > 4 else ("set" if v else "")


_MODEL_CACHE = {"t": 0.0, "key": "", "data": {}}


def agent_models(agent=""):
    """Models the chosen CLI can run, when it can tell us (opencode models)."""
    import shutil
    agent = (agent or "").strip()
    if not agent:
        try:
            r = subprocess.run(["bash", os.path.join(ROOT, "tools", "agent_run.sh"), "--which"],
                               cwd=ROOT, capture_output=True, text=True, timeout=10)
            agent = (r.stdout or "").strip()
        except (OSError, subprocess.SubprocessError):
            agent = ""
    base = (agent.split() or [""])[0]
    now = time.time()
    cache = _MODEL_CACHE
    if cache["key"] == base and now - cache["t"] < 300:
        return cache["data"]
    models, source = [], ""
    if base == "opencode" and shutil.which("opencode"):
        try:
            r = subprocess.run(["opencode", "models"], capture_output=True, text=True, timeout=40)
            models = [ln.strip() for ln in ANSI.sub("", r.stdout or "").splitlines()
                      if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/-]*", ln.strip() or "")]
            source = "opencode models"
        except (OSError, subprocess.SubprocessError):
            models, source = [], "opencode models (failed)"
    elif base == "claude" and shutil.which("claude"):
        models = ["sonnet", "opus", "haiku", "sonnet[1m]", "opus[1m]"]
        source = "Claude Code aliases"
    models = list(dict.fromkeys(models))
    groups = _model_groups(base, models)
    cfg = load_agent_cfg()
    data = {"agent": agent or base, "models": models, "groups": groups, "source": source,
            "current": cfg.get("model", ""), "saved": (cfg.get("models") or {}).get(base, "")}
    _MODEL_CACHE.update(t=now, key=base, data=data)
    return data


def _model_groups(base, models):
    """Group model ids for the pickers: Free, products (Zen/Go/...), contributor."""
    def short(m):
        return m.split("/", 1)[1] if "/" in m else m
    free = [m for m in models if short(m).lower().endswith("-free")]
    contributor = [m for m in models if short(m).lower().endswith("-contributor")]
    rest = [m for m in models if m not in free and m not in contributor]
    groups = []
    if free:
        groups.append({"label": "Free models", "models": free})
    by_product = {}
    for m in rest:
        key = m.split("/", 1)[0] if "/" in m else (base or "other")
        by_product.setdefault(key, []).append(m)
    labels = {"opencode": "OpenCode Zen", "opencode-go": "OpenCode Go",
              "claude": "Claude Code", "anthropic": "Anthropic"}
    for key in sorted(by_product):
        groups.append({"label": labels.get(key, key.replace("-", " ").title() or "Other"),
                       "models": by_product[key]})
    if contributor:
        groups.append({"label": "Contributor / preview", "models": contributor})
    return groups


def agent_config():
    import shutil
    cfg = load_agent_cfg()
    detected = [a for a in ("opencode", "claude") if shutil.which(a)]
    which = ""
    try:
        r = subprocess.run(["bash", os.path.join(ROOT, "tools", "agent_run.sh"), "--which"],
                           cwd=ROOT, capture_output=True, text=True, timeout=10)
        which = (r.stdout or "").strip()
    except (OSError, subprocess.SubprocessError):
        pass
    return {"agent": cfg["agent"], "model": cfg["model"], "models": cfg.get("models", {}),
            "env": {k: _mask(v) for k, v in cfg["env"].items()},
            "env_keys": sorted(cfg["env"]), "detected": detected, "which": which,
            "config_path": AGENT_CFG_FILE,
            "known_keys": ["OPENCODE_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY"]}


def graphrag_env():
    vars_, order = {}, []
    for ln in _read(GRAPHRAG_ENV).splitlines():
        s = ln.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, v = s.split("=", 1)
        k, v = k.strip(), v.strip()
        order.append(k)
        secret = bool(re.search(r"KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL", k, re.I))
        vars_[k] = _mask(v) if secret else v
    return {"path": GRAPHRAG_ENV, "vars": vars_, "keys": order, "exists": os.path.isfile(GRAPHRAG_ENV)}


def save_graphrag_env(updates):
    lines = _read(GRAPHRAG_ENV).splitlines()
    updates = {re.sub(r"[^A-Za-z0-9_]", "", str(k))[:80]: str(v)[:1000]
               for k, v in (updates or {}).items()}
    seen, out = set(), []
    for ln in lines:
        s = ln.strip()
        if s and not s.startswith("#") and "=" in s:
            k = s.split("=", 1)[0].strip()
            if k in updates:
                seen.add(k)
                if updates[k] != "":
                    out.append(f"{k}={updates[k]}")
                continue
        out.append(ln)
    for k, v in updates.items():
        if k not in seen and v != "":
            out.append(f"{k}={v}")
    os.makedirs(os.path.dirname(GRAPHRAG_ENV), exist_ok=True)
    with open(GRAPHRAG_ENV, "w", encoding="utf-8") as fh:
        fh.write("\n".join(out).rstrip("\n") + "\n")
    return graphrag_env()


def agent_env(**extra):
    env = dict(os.environ)
    env.update(extra)
    env.setdefault("OPENCODE_CONFIG_CONTENT", json.dumps(AGENT_PERMISSIONS))
    if DASH["url"]:
        env.setdefault("JOBSQUIRREL_URL", DASH["url"])
    env.setdefault("JOBSQUIRREL_TOKEN", SESSION_TOKEN)
    cfg = load_agent_cfg()                        # user-configured agent/model/token
    if cfg.get("agent"):
        env["AGENT"] = cfg["agent"]               # the dashboard choice wins over a stray AGENT=1
    if cfg.get("model"):
        env["MODEL"] = cfg["model"]               # chat + role chats use the selected model
    for k, v in cfg.get("env", {}).items():
        env.setdefault(k, v)
    return env


# ---------------------------------------------------------------- updates
VERSION_FILE = os.path.join(ROOT, "VERSION")
GITHUB_REPO = os.environ.get("JOBSQUIRREL_REPO", "bongomanuk/jobsquirrel")
_UPDATE = {"t": 0.0, "data": {}}


def current_version():
    try:
        with open(VERSION_FILE, encoding="utf-8") as fh:
            return fh.read().strip() or "0"
    except OSError:
        return "0"


def _vtup(v):
    return tuple(int(x) for x in re.findall(r"\d+", v or "")[:3]) or (0,)


def check_update(refresh=False):
    """Latest GitHub release vs the VERSION file (cached an hour)."""
    if not refresh and _UPDATE["data"] and time.time() - _UPDATE["t"] < 3600:
        return _UPDATE["data"]
    cur = current_version()
    d = {"current": cur, "latest": "", "available": False, "name": "", "notes": "", "error": "",
         "url": f"https://github.com/{GITHUB_REPO}/releases"}
    try:
        req = urllib.request.Request(f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest",
                                     headers={"Accept": "application/vnd.github+json",
                                              "User-Agent": "jobsquirrel"})
        with urllib.request.urlopen(req, timeout=12) as r:
            rel = json.load(r)
        tag = (rel.get("tag_name") or "").strip()
        d.update(latest=tag, name=rel.get("name", ""), notes=(rel.get("body") or "")[:4000],
                 url=rel.get("html_url") or d["url"], available=_vtup(tag) > _vtup(cur))
    except Exception as e:
        d["error"] = f"{type(e).__name__}: {e}"
    _UPDATE.update(t=time.time(), data=d)
    return d


def apply_update(approval_token=""):
    if approval_token != "APPROVE_UPDATE":
        return {"error": "refused: confirm to update"}
    _spawn("update (git pull)", ["git", "-C", ROOT, "pull", "--ff-only"])
    return {"ok": "updating — watch the Activity pane, then restart the dashboard"}


# ---------------------------------------------------------------- Google accounts (Gmail + Calendar)
def google_info():
    sys.path.insert(0, os.path.join(ROOT, "tools"))
    import google_config as GC
    st = GC.status()

    def mask(v):
        v = v or ""
        return v if len(v) < 14 else v[:8] + "\u2026" + v[-6:]

    return {"config_file": st["config_file"], "config_dir": st["config_dir"],
            "credentials": st["credentials"], "token": st["token"],
            "credentials_exists": st["credentials_exists"], "token_exists": st["token_exists"],
            "client_id": mask(st["client_id"]), "has_client_secret": st["has_client_secret"],
            "account": st["account"], "scopes": st["scopes"]}


def google_save(data):
    sys.path.insert(0, os.path.join(ROOT, "tools"))
    import google_config as GC
    upd = {}
    for k in ("config_dir", "credentials", "token", "client_id", "client_secret"):
        v = data.get(k)
        if isinstance(v, str) and v.strip():
            upd[k] = v.strip()
    if not upd:
        return {"error": "nothing to save"}
    GC.save(upd)
    msg = "saved config/google.json"
    if GC.load().get("client_id") and GC.load().get("client_secret"):
        written = GC.write_credentials()
        if written:
            msg += f"; wrote {written}"
    return {"ok": msg}


# ---------------------------------------------------------------- agent permissions
PERMS_FILE = os.path.join(ROOT, "config", "agent-permissions.json")
DEFAULT_PERMS = {
    "read_repo": "allow", "write_repo": "allow",      # its normal work in this repo
    "read_external": "ask", "write_external": "ask",  # outside the repo -> ask
    "bash": "ask", "web": "allow", "task": "ask",
}
_PERM_LOCK = threading.Lock()
_PERM = {}                  # request id -> {category, detail, event, decision, ts}


def load_perms():
    try:
        with open(PERMS_FILE, encoding="utf-8") as fh:
            return {**DEFAULT_PERMS, **json.load(fh)}
    except (OSError, ValueError):
        return dict(DEFAULT_PERMS)


def save_perms(d):
    d = {k: v for k, v in d.items() if k in DEFAULT_PERMS and v in ("allow", "ask", "deny")}
    merged = {**DEFAULT_PERMS, **d}
    os.makedirs(os.path.dirname(PERMS_FILE), exist_ok=True)
    with open(PERMS_FILE, "w", encoding="utf-8") as fh:
        json.dump(merged, fh, indent=2)
    return merged


def permission_request(category, detail, timeout=300):
    """The agent asks to do something; honour allow/deny, or block until the operator answers."""
    pol = load_perms().get(category, "ask")
    if pol in ("allow", "deny"):
        return {"decision": pol, "category": category}
    rid = uuid.uuid4().hex
    ev = threading.Event()
    with _PERM_LOCK:
        _PERM[rid] = {"id": rid, "category": category, "detail": detail, "event": ev, "decision": None, "ts": time.time()}
    ev.wait(timeout)
    with _PERM_LOCK:
        rec = _PERM.pop(rid, {})
    return {"decision": rec.get("decision") or "deny", "id": rid, "category": category}


def consent_request(purpose, token, timeout=300, email=None):
    """A one-off approval (send mail, write the calendar): always asks, never remembered.

    `email` (optional) is the full message shown in the approval dialog, where the
    human can edit To/Cc/Subject/body. Edits come back only with their decision.
    """
    rid = uuid.uuid4().hex
    ev = threading.Event()
    with _PERM_LOCK:
        _PERM[rid] = {"id": rid, "category": token, "detail": purpose, "event": ev,
                      "decision": None, "ts": time.time(), "rememberable": False,
                      "email": email, "edits": None, "save": False}
    ev.wait(timeout)
    with _PERM_LOCK:
        rec = _PERM.pop(rid, {})
    return {"decision": rec.get("decision") or "deny", "id": rid,
            "edits": rec.get("edits") or {}, "save": bool(rec.get("save"))}


def _log_approval(msg):
    try:
        os.makedirs(LOGS, exist_ok=True)
        with open(os.path.join(LOGS, "approval.log"), "a", encoding="utf-8") as fh:
            fh.write(time.strftime("%Y-%m-%d %H:%M:%S ") + msg + "\n")
    except OSError:
        pass


def permission_pending():
    with _PERM_LOCK:
        return [{"id": r["id"], "category": r["category"], "detail": r["detail"],
                 "rememberable": r.get("rememberable", True),
                 "email": r.get("email")}
                for r in _PERM.values() if r["decision"] is None]


def permission_decide(rid, decision, remember=False, edits=None, save=False):
    with _PERM_LOCK:
        r = _PERM.get(rid)
    if not r:
        return {"error": "unknown or expired request"}
    r["decision"] = "allow" if decision == "allow" else "deny"
    r["edits"] = edits
    r["save"] = bool(save)
    if remember and r.get("rememberable", True):
        p = load_perms()
        p[r["category"]] = r["decision"]
        save_perms(p)
    r["event"].set()
    return {"ok": f"{r['decision']} {r['category']}"}


def _chat_spawn(message):
    """Run one turn for `message` (the echo is written by the caller)."""
    sid = _chat_session()
    if not os.path.exists(CHAT_LOG):
        sid = ""                                    # transcript gone -> start fresh
    base = message if sid else (CHAT_PREAMBLE + "\n\n---\n" + message)
    prompt = GATE_NOTE + "\n\n" + base
    f = open(CHAT_LOG, "a", encoding="utf-8")
    env = agent_env(AGENT_JSON="1")
    if sid:
        env["AGENT_SESSION"] = sid                  # continue the same agent session
    p = subprocess.Popen(["bash", os.path.join(ROOT, "tools", "agent_run.sh"), prompt],
                         cwd=ROOT, env=env, stdout=f, stderr=subprocess.STDOUT,
                         start_new_session=True)
    _CHAT["proc"] = p
    _chat_pid_write(p.pid)


def _chat_pump():
    """Start the next queued message if the agent is free."""
    if _chat_running():
        return
    q = _CHAT.get("queue") or []
    if q:
        _chat_spawn(q.pop(0))


def chat_start(message):
    message = (message or "").strip()[:8000]
    if not message:
        return {"error": "empty message"}
    if _chat_running():
        _CHAT.setdefault("queue", []).append(message)      # queue it — never lose the message
        _chat_echo(message)
        return {"status": "queued", "queued": True, "pending": len(_CHAT["queue"])}
    _chat_echo(message)
    _chat_spawn(message)
    return {"status": "queued", "run_id": "chat", "agent": chat_agent(), "pending": 0}


CHAT_USER = re.compile(r"^>\s?(.*)$")
CHAT_TOOL = re.compile(r"^\$\s?(.*)$")
CHAT_STATUS = re.compile(r"^>\s*build\b.*$", re.I)


CHAT_TOOL_BODY_MAX = 900        # tool output kept per step (the UI collapses it; keep the payload small)
CHAT_TOOL_CMD_MAX = 400


def _compress_tool(seg):
    """Keep tool segments small so the chat never fills with scripts and raw output."""
    cmd = str(seg.get("cmd") or "")
    if len(cmd) > CHAT_TOOL_CMD_MAX:
        seg["cmd"] = cmd[:CHAT_TOOL_CMD_MAX].rstrip() + "\n… (command truncated)"
    body = str(seg.get("body") or "")
    if len(body) > CHAT_TOOL_BODY_MAX:
        seg["body"] = body[:CHAT_TOOL_BODY_MAX].rstrip() + f"\n… ({len(body) - CHAT_TOOL_BODY_MAX} more chars)"
    return seg


def chat_parse(text):
    """Split an agent transcript into typed segments so the UI can collapse tool noise."""
    segs, cur, fence = [], None, False

    def push(seg):
        if seg and (seg.get("body", "").strip() or seg["t"] == "tool"):
            segs.append(seg)

    for ln in text.splitlines():
        if ln.strip().startswith("```"):
            fence = not fence
            cur = cur or {"t": "text", "body": ""}
            cur["body"] += ("\n" if cur["body"] else "") + ln
            continue
        if not fence:
            if CHAT_STATUS.match(ln):
                push(cur); cur = None
                push({"t": "status", "body": ln.lstrip("> ").strip()}); continue
            m_user = CHAT_USER.match(ln)
            if m_user:
                push(cur); cur = None
                push({"t": "user", "body": m_user.group(1)}); continue
            m_tool = CHAT_TOOL.match(ln)
            if m_tool:
                push(cur); cur = None
                cur = {"t": "tool", "cmd": m_tool.group(1), "body": ""}
                continue
        cur = cur or {"t": "text", "body": ""}
        cur["body"] += ("\n" if cur["body"] else "") + ln
    push(cur)
    for s in segs:
        s["body"] = s.get("body", "").strip("\n")
        if s["t"] == "tool":
            _compress_tool(s)
    return segs


def chat_parse_json(text):
    """Parse opencode `--format json` events into typed segments."""
    segs, tokens, cost = [], None, None
    for ln in text.splitlines():
        s = ln.strip()
        if s.startswith(">") and not CHAT_STATUS.match(s):
            segs.append({"t": "user", "body": s[1:].strip()})
            continue
        if not s.startswith("{"):
            continue
        try:
            e = json.loads(s)
        except ValueError:
            continue
        t, p = e.get("type"), (e.get("part") or {})
        if t == "text" and p.get("text"):
            segs.append({"t": "text", "body": p["text"]})
        elif t == "tool_use":
            st = p.get("state") or {}
            inp = st.get("input") or {}
            cmd = inp.get("command") or inp.get("filePath") or inp.get("pattern") or st.get("title") or p.get("tool")
            out = st.get("output")
            if out in (None, ""):
                out = st.get("metadata") or ""
            if isinstance(out, (dict, list)):
                out = json.dumps(out, indent=2)
            segs.append({"t": "tool", "tool": p.get("tool", ""), "cmd": str(cmd), "body": str(out)})
        elif t == "step_finish":
            tk = p.get("tokens") or {}
            tokens = tk.get("total", tokens)
            if p.get("cost") is not None:
                cost = p.get("cost")
    if tokens is not None:
        segs.append({"t": "status", "body": f"{tokens} tokens" + (f" · ${cost:.4f}" if isinstance(cost, (int, float)) else "")})
    for s in segs:
        if s["t"] == "tool":
            _compress_tool(s)
    return segs


def chat_parse_claude(text):
    """Parse Claude Code `--output-format stream-json` events into typed segments."""
    segs, tokens, cost = [], None, None
    for ln in text.splitlines():
        s = ln.strip()
        if s.startswith(">") and not CHAT_STATUS.match(s):
            segs.append({"t": "user", "body": s[1:].strip()})
            continue
        if not s.startswith("{"):
            continue
        try:
            e = json.loads(s)
        except ValueError:
            continue
        t = e.get("type")
        blocks = ((e.get("message") or {}).get("content") or [])
        if t == "assistant":
            for blk in blocks:
                if blk.get("type") == "text" and blk.get("text"):
                    segs.append({"t": "text", "body": blk["text"]})
                elif blk.get("type") == "tool_use":
                    inp = blk.get("input") or {}
                    cmd = inp.get("command") or inp.get("file_path") or inp.get("pattern") or blk.get("name", "")
                    segs.append({"t": "tool", "tool": blk.get("name", ""), "cmd": str(cmd), "body": ""})
        elif t == "user":
            for blk in blocks:
                if blk.get("type") == "tool_result":
                    c = blk.get("content")
                    if isinstance(c, list):
                        c = "\n".join(x.get("text", "") for x in c if isinstance(x, dict))
                    if segs and segs[-1]["t"] == "tool" and not segs[-1]["body"]:
                        segs[-1]["body"] = str(c or "")
        elif t == "result":
            u = e.get("usage") or {}
            if u.get("input_tokens") is not None or u.get("output_tokens") is not None:
                tokens = (u.get("input_tokens") or 0) + (u.get("output_tokens") or 0)
            if e.get("total_cost_usd") is not None:
                cost = e.get("total_cost_usd")
    if tokens is not None or cost is not None:
        parts = ([f"{tokens} tokens"] if tokens else []) + ([f"${cost:.4f}"] if isinstance(cost, (int, float)) else [])
        if parts:
            segs.append({"t": "status", "body": " · ".join(parts)})
    for s in segs:
        if s["t"] == "tool":
            _compress_tool(s)
    return segs


def _json_kind(text):
    """Best-effort: is this an opencode or Claude Code JSON stream?

    Skip runner diagnostics (e.g. "agent_run: ... falling back") instead of
    treating them as proof of a plain-text transcript: otherwise the raw JSON
    events leak into the chat as text.
    """
    for ln in text.splitlines()[:200]:
        s = ln.strip()
        if not s or s.startswith(">") or s.startswith("build "):
            continue
        if not s.startswith("{"):
            continue
        try:
            e = json.loads(s)
        except ValueError:
            continue
        if "part" in e:
            return "opencode"
        if "message" in e or e.get("type") in ("system", "assistant", "user", "result"):
            return "claude"
    return None


def chat_stream(run_id, since):
    _chat_pump()                                    # start the next queued message if the agent is free
    try:
        size = os.path.getsize(CHAT_LOG)
        with open(CHAT_LOG, encoding="utf-8", errors="ignore") as fh:
            text = ANSI.sub("", fh.read())
    except OSError:
        size, text = 0, ""                          # transcript cleared/not created yet
    _record_chat_session(text)
    running = _chat_running()
    kind = _json_kind(text)
    if kind == "opencode":
        segs = chat_parse_json(text)
    elif kind == "claude":
        segs = chat_parse_claude(text)
    else:
        segs = chat_parse(text)
    if len(segs) > 400:
        segs = segs[-400:]
    pending = len(_CHAT.get("queue") or [])
    return {"segments": segs, "offset": size, "running": running, "pending": pending,
            "done": not running and not pending}


# ---------------------------------------------------------------- actions
ACTIONS = {
    "prepare": {"argv": ["bash", "tools/run_queue.sh"], "env": {"REVIEW": "1", "PARALLEL": "1"},
                "purpose": "prepare documents (review run)", "token": None},
    "submit_queue": {"argv": ["bash", "tools/run_queue.sh"], "env": {},
                     "purpose": "run the apply queue (submits applications)", "token": "APPROVE_RUN_QUEUE"},
    "reconcile": {"argv": [sys.executable, "tools/gmail_reconcile.py"],
                  "env": {"PYTHONUNBUFFERED": "1"},
                  "purpose": "reconcile the register with Gmail", "token": None},
    "build_archetypes": {"argv": [sys.executable, "tools/build_archetypes.py"], "env": {},
                         "purpose": "regenerate archetype CVs", "token": None},
    "kb_update": {"argv": ["bash", "tools/kb_update.sh"], "env": {},
                  "purpose": "update the knowledge graph (incremental)", "token": None},
}


_ACT = {"name": "", "proc": None, "offset": 0, "t0": 0}
ACT_FILE = os.path.join(LOGS, "dashboard-activity.json")


def _act_save():
    try:
        json.dump({k: _ACT.get(k) for k in ("name", "offset", "t0")}, open(ACT_FILE, "w"))
    except OSError:
        pass


def _act_load():
    """Restore the last action so the Activity pane survives a server restart."""
    if _ACT.get("name") or _ACT.get("proc"):
        return
    try:
        with open(ACT_FILE, encoding="utf-8") as fh:
            d = json.load(fh)
        for k in ("name", "offset", "t0"):
            _ACT[k] = d.get(k, _ACT.get(k))
    except (OSError, ValueError):
        pass


def action_log(n=100):
    p = os.path.join(LOGS, "dashboard-action.log")
    start = _ACT.get("offset", 0)
    try:
        with open(p, encoding="utf-8", errors="ignore") as fh:
            fh.seek(min(start, os.path.getsize(p)))
            txt = ANSI.sub("", fh.read())
    except OSError:
        txt = ""
    return txt.splitlines()[-int(n or 100):]


def _spawn(purpose, argv, env=None):
    """Run a command detached, logged to the activity pane (state/logs/dashboard-action.log)."""
    os.makedirs(LOGS, exist_ok=True)
    logf = open(os.path.join(LOGS, "dashboard-action.log"), "a", encoding="utf-8")
    logf.write(f"\n=== {time.strftime('%Y-%m-%dT%H:%M:%S')} {purpose} ===\n")
    logf.flush()
    proc = subprocess.Popen(argv, cwd=ROOT, env=agent_env(ROOT=ROOT, **(env or {})),
                            stdout=logf, stderr=subprocess.STDOUT, start_new_session=True)
    _ACT.update(name=purpose, proc=proc, offset=logf.tell(), t0=time.time())
    _act_save()
    return proc


STOP_FILE = os.path.join(STATE, "queue.stop")
PAUSE_FILE = os.path.join(STATE, "queue.pause")


def process_running():
    p = _ACT.get("proc")
    return bool(p and p.poll() is None)


def stop_action():
    """Stop everything: no new tasks, and terminate the running action + queue runner."""
    try:
        os.makedirs(STATE, exist_ok=True)
        with open(STOP_FILE, "w") as fh:
            fh.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S')} stop requested via dashboard\n")
    except OSError:
        pass
    stopped = False
    p = _ACT.get("proc")
    if p and p.poll() is None:
        try:
            os.killpg(os.getpgid(p.pid), signal.SIGTERM)
            stopped = True
        except OSError:
            pass
    _ACT["proc"] = None
    return {"ok": "stopped" + (" (terminated the running action)" if stopped else "") +
            " — no new tasks will start. Pause stays off; re-run when ready."}


def pause_action(on):
    try:
        os.makedirs(STATE, exist_ok=True)
        if on:
            with open(PAUSE_FILE, "w") as fh:
                fh.write("paused via dashboard\n")
        else:
            try:
                os.remove(PAUSE_FILE)
            except OSError:
                pass
    except OSError as e:
        return {"error": str(e)}
    return {"ok": "paused — workers will finish the current task, then wait" if on else "resumed"}


def _resolve_roles(keys):
    """Resolve register/queue keys to complete queue rows (company, role, url, cv, ats, key).

    Queued rows are taken from the queue files; other keys are rebuilt from the
    register / submissions, so a role you opened (e.g. a prepared or blocked one)
    can still be acted on."""
    want = {str(k).strip() for k in (keys or []) if str(k).strip()}
    rows, found = [], set()
    for path in ("queue.tsv", "queue-human.tsv", "queue.retry"):
        for r in _queue_rows(os.path.join(STATE, path)):
            if r["key"] in want and r["key"] not in found:
                rows.append(r)
                found.add(r["key"])
    if want - found:                                   # not in a queue -> rebuild from the register
        km, _ = _key_maps()
        for r in _rows(os.path.join(STATE, "applications.csv")):
            co, role = r["company"], r["role"]
            k = km.get((co.lower(), role.lower())) or _slug(f"{co}-{role}")
            if k in (want - found) and k not in found:
                url, cv, ats, _ = _queue_fields(co, role)
                rows.append({"company": co, "role": role, "url": url, "cv": cv, "ats": ats, "key": k})
                found.add(k)
    return rows


def _queue_only_roles(rows):
    """Write rows to a private queue (and an empty DONE file) so a scoped run
    processes exactly those roles and never skips them as already done."""
    os.makedirs(LOGS, exist_ok=True)
    tmp = os.path.join(LOGS, "queue-ui.tsv")
    with open(tmp, "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write("\t".join([r["company"], r["role"], r.get("url", ""), r.get("cv", ""),
                                r.get("ats", ""), r["key"]]) + "\n")
    tmp_done = os.path.join(LOGS, "queue-ui.done")
    with open(tmp_done, "w", encoding="utf-8"):
        pass
    return tmp, tmp_done


def prepare_roles(keys):
    """Run a REVIEW pass (generate + gate documents, never submit) over the given roles."""
    rows = _resolve_roles(keys)
    if not rows:
        return {"error": "couldn't resolve those roles to a company/role"}
    tmp, tmp_done = _queue_only_roles(rows)
    _spawn(f"prepare {len(rows)} role(s) (review)",
           ["bash", os.path.join(ROOT, "tools", "run_queue.sh")],
           {"REVIEW": "1", "PARALLEL": "1", "QUEUE": tmp, "DONE": tmp_done})
    return {"ok": f"generating documents for {len(rows)} role(s) — watch the Activity pane (nothing is submitted)"}


def submit_roles(keys, approval_token=""):
    """Submit the selected roles with the documents already prepared for them.

    The runner reuses the existing artifacts (step 0d: job ad, keywords, grounding,
    content pack, CV and letter), re-runs the gates and applies through the browser.
    Irreversible: requires the APPROVE_RUN_QUEUE approval token."""
    rows = _resolve_roles(keys)
    if not rows:
        return {"error": "couldn't resolve those roles to a company/role"}
    if WQ and WQ.runner_active():
        return {"error": "a queue run is already active"}
    sys.path.insert(0, os.path.join(ROOT, "tools"))
    import approval
    if approval_token != "APPROVE_RUN_QUEUE":
        approval._record(f"submit {len(rows)} prepared role(s) via dashboard", "REFUSED (no approval token)")
        return {"error": "refused: submitting applications is irreversible; confirm to send APPROVE_RUN_QUEUE"}
    approval._record(f"submit {len(rows)} prepared role(s) via dashboard", "ui-token:APPROVE_RUN_QUEUE")
    tmp, tmp_done = _queue_only_roles(rows)
    try:
        import register as REG
        for r in rows:
            REG.set_row(r["company"], r["role"], status="QUEUED",
                        note="submitting prepared documents via dashboard")
    except Exception:
        pass
    _spawn(f"submit {len(rows)} prepared role(s)",
           ["bash", os.path.join(ROOT, "tools", "run_queue.sh")],
           {"PARALLEL": "1", "QUEUE": tmp, "DONE": tmp_done, "PREPARED": "1"})
    return {"ok": f"submitting {len(rows)} application(s) — watch the Activity pane (this sends them)"}



def recompute_match(keys=None):
    keys = [str(k).strip() for k in (keys or []) if str(k).strip()]
    if keys:
        for k in keys:
            _COV.pop(k, None)
            _MATCH_CACHE.pop(k, None)
        msg = f"recomputing match for {len(keys)} role(s)"
    else:
        _COV.clear()
        _MATCH_CACHE.clear()
        msg = "recomputing match for all roles"
    globals()["_cov_dirty"] = True
    _save_cov()
    return {"ok": msg}


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
    _spawn(f"action={command} ({spec['purpose']})", spec["argv"], spec["env"])
    return {"ok": f"started: {spec['purpose']}"}


# ---------------------------------------------------------------- knowledge base + graph
GRAPH_PY = os.path.join(ROOT, ".venv-graphrag", "bin", "python")
GRAPH_TOOL = os.path.join(ROOT, "tools", "graph_explore.py")
KB_SOURCES = os.path.join(ROOT, "kb", "sources")
_gcache = {}


def graph_query(*args):
    key = "|".join(str(a) for a in args)
    if key in _gcache:
        return _gcache[key]
    py = GRAPH_PY if os.path.exists(GRAPH_PY) else sys.executable
    try:
        r = subprocess.run([py, GRAPH_TOOL, *[str(a) for a in args]], cwd=ROOT,
                           capture_output=True, text=True, timeout=90)
        data = json.loads((r.stdout or "").strip() or "{}")
        if r.returncode != 0 and "error" not in data:
            data = {"error": (r.stderr or "graph read failed").strip()[-300:]}
    except (OSError, subprocess.SubprocessError, ValueError) as e:
        data = {"error": f"{type(e).__name__}: {e}"}
    _gcache[key] = data
    return data


def kb_sources():
    groups = {}
    if os.path.isdir(KB_SOURCES):
        for g in sorted(os.listdir(KB_SOURCES)):
            d = os.path.join(KB_SOURCES, g)
            if os.path.isdir(d):
                groups[g] = sorted(({"name": f, "size": os.path.getsize(os.path.join(d, f))}
                                    for f in os.listdir(d) if os.path.isfile(os.path.join(d, f))),
                                   key=lambda x: x["name"])
        groups["(root)"] = sorted(({"name": f, "size": os.path.getsize(os.path.join(KB_SOURCES, f))}
                                   for f in os.listdir(KB_SOURCES) if os.path.isfile(os.path.join(KB_SOURCES, f))),
                                  key=lambda x: x["name"])
    return groups


_kb_check = {"t": 0.0, "text": ""}


def kb_info():
    if time.time() - _kb_check["t"] > 30:
        try:
            r = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "kb_graphrag.py"), "--check"],
                               cwd=ROOT, capture_output=True, text=True, timeout=60)
            _kb_check.update(t=time.time(), text=ANSI.sub("", (r.stdout or "") + (r.stderr or "")).strip())
        except (OSError, subprocess.SubprocessError) as e:
            _kb_check.update(t=time.time(), text=f"check failed: {e}")
    return {"sources": kb_sources(), "stats": graph_query("stats"), "check": _kb_check["text"]}


def _safe_kb_path(rel):
    base = os.path.realpath(KB_SOURCES)
    p = os.path.realpath(os.path.join(ROOT, rel))
    return p if p.startswith(base + os.sep) else None


def kb_delete(rel):
    p = _safe_kb_path(rel)
    if not p or not os.path.isfile(p):
        return {"error": "not found"}
    try:
        os.remove(p)
        return {"ok": f"removed {os.path.relpath(p, ROOT)}"}
    except OSError as e:
        return {"error": str(e)}


def kb_upload(group, files):
    """files: list of (filename, bytes). Saves into kb/sources/<group>/."""
    group = re.sub(r"[^a-zA-Z0-9._-]", "_", (group or "imported").strip()) or "imported"
    if group.startswith("."):
        group = "imported"
    dest = os.path.join(KB_SOURCES, group)
    os.makedirs(dest, exist_ok=True)
    saved = []
    for name, data in files:
        name = os.path.basename(name or "").replace("/", "_").strip()
        if not name or not data:
            continue
        with open(os.path.join(dest, name), "wb") as fh:
            fh.write(data)
        saved.append(f"{group}/{name}")
    return {"ok": f"uploaded {len(saved)} file(s) to kb/sources/{group}/", "files": saved} if saved \
        else {"error": "no files"}


def kb_rebuild():
    if WQ and WQ.runner_active():
        return {"error": "a queue run is active"}
    _spawn("rebuild knowledge graph (setup_kb.sh)", ["bash", os.path.join(ROOT, "tools", "setup_kb.sh")])
    return {"ok": "rebuilding knowledge graph - watch the Activity pane"}


def accounts():
    try:
        r = subprocess.run(["bash", os.path.join(ROOT, "tools", "setup_accounts.sh"), "--check"],
                           cwd=ROOT, capture_output=True, text=True, timeout=60)
        text = ANSI.sub("", (r.stdout or "") + (r.stderr or "")).strip()
    except (OSError, subprocess.SubprocessError) as e:
        text = f"check failed: {e}"
    n = 0
    acc = os.path.join(ROOT, "config", "accounts.json")
    if os.path.isfile(acc):
        try:
            n = len(json.load(open(acc, encoding="utf-8")))
        except (OSError, ValueError):
            n = 0
    return {"text": text, "sites": n}


def account_auth(kind):
    argv = {"gmail": [sys.executable, os.path.join(ROOT, "tools", "gmail_readonly.py"), "--auth"],
            "calendar": [sys.executable, os.path.join(ROOT, "tools", "gmail_calendar_auth.py")]}.get(kind)
    if not argv:
        return {"error": "unknown account"}
    _spawn(f"authorise {kind}",
           argv, {"PYTHONUNBUFFERED": "1"})
    return {"ok": f"started {kind} authorisation - finish it in the browser / Activity pane"}


SKILLS_FILE = os.path.join(ROOT, "kb", "sources", "personal", "skills_evidence.md")


def add_skill_evidence(skill, source="", detail="", key=""):
    """Record evidence that the candidate has a skill (for a missing ATS keyword),
    as a grounded knowledge-base source so it flows into future tailored documents."""
    skill = (skill or "").strip()[:160]
    source = (source or "").strip()[:200]
    detail = (detail or "").strip()[:1000]
    if not skill:
        return {"error": "skill is required"}
    os.makedirs(os.path.dirname(SKILLS_FILE), exist_ok=True)
    if not os.path.isfile(SKILLS_FILE):
        with open(SKILLS_FILE, "w", encoding="utf-8") as fh:
            fh.write("# Skill evidence (added via the dashboard)\n\n"
                     "Provenance: first-hand account provided by the candidate. Attribute each fact to the\n"
                     "named employer/project; do not inflate level.\n")
    where = f" — {source}" if source else ""
    extra = f": {detail}" if detail else ""
    role = f" [for {key}]" if key else ""
    line = f"- **{skill}**{where}{extra} (added {time.strftime('%Y-%m-%d')}{role})"
    with open(SKILLS_FILE, "a", encoding="utf-8") as fh:
        fh.write(line + "\n")
    return {"ok": f"evidence recorded for “{skill}”", "file": os.path.relpath(SKILLS_FILE, ROOT),
            "hint": "Rebuild the knowledge graph (Settings → Knowledge base → Rebuild) to fold it into CVs."}


def role_grounding(key):
    """The GraphRAG context pack for a role + the entities/sources it cites, resolved."""
    key = os.path.basename(key)[:120]
    pack = _read(os.path.join(STATE, "kb-context", key + ".md"))[:20000]
    ents, docs = [], []
    for m in re.finditer(r"Entities \(([^)]*)\)", pack):
        ents += re.findall(r"\d+", m.group(1))
    for m in re.finditer(r"Sources \(([^)]*)\)", pack):
        docs += re.findall(r"\d+", m.group(1))
    ents, docs = sorted(set(ents), key=int)[:60], sorted(set(docs), key=int)[:40]
    resolved = graph_query("resolve", ",".join(ents), "--docs", ",".join(docs)) if (ents or docs) else {}
    return {"key": key, "pack": pack, "entities": resolved.get("entities", []),
            "documents": resolved.get("documents", []),
            "cited_entities": len(ents), "cited_sources": len(docs)}


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
            body = body.replace(b"{{ASSET}}", quote(_web_build(), safe="").encode())
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _page(self, title, body, refresh=0):
        meta = f"<meta http-equiv='refresh' content='{int(refresh)}'>" if refresh else ""
        html = ("<!doctype html><html><head><meta charset='utf-8'>" + meta +
                "<meta name='viewport' content='width=device-width,initial-scale=1'>"
                f"<title>{_html.escape(title)}</title>"
                "<style>body{font:14px/1.5 system-ui,-apple-system,sans-serif;background:#0c0e12;color:#f3f4f6;margin:20px}"
                "a{color:#f59e0b}pre{background:#07090c;border:1px solid #232838;border-radius:8px;padding:12px;"
                "white-space:pre-wrap;overflow:auto;max-height:75vh;font:12px/1.5 ui-monospace,monospace}"
                ".muted{color:#9ca3af}.bad{color:#ffb4b4}h2,h3{margin:.4em 0}li{margin:4px 0}</style></head><body>"
                + body + "</body></html>")
        data = html.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _task_names(self):
        out = {}
        if WQ:
            try:
                for k in WQ.live_tasks():
                    co, _, role = k.partition("|")
                    out[f"{co}-{role}".translate(str.maketrans(" /|", "___"))] = k.replace("|", " — ")
            except Exception:
                pass
        return out

    def _logs_page(self):
        running = self._task_names()
        try:
            files = [f for f in os.listdir(LOGS) if f.endswith(".log")]
        except OSError:
            files = []
        files.sort(key=lambda f: os.path.getmtime(os.path.join(LOGS, f)), reverse=True)
        rows = []
        for f in files[:80]:
            name = f[:-4]
            try:
                st = os.stat(os.path.join(LOGS, f))
                age, size = int(time.time() - st.st_mtime), st.st_size
            except OSError:
                age, size = 0, 0
            tag = ' <b class="bad">running</b>' if name in running else ''
            rows.append(f"<li><a href='/tasklog?task={quote(name)}'>{_html.escape(name)}</a>{tag} "
                        f"<span class='muted'>· {size} bytes · {age}s ago</span></li>")
        body = (f"<h2>Task logs</h2><p class='muted'>{time.strftime('%Y-%m-%d %H:%M:%S')} · "
                "auto-refresh 3s · <a href='/'>dashboard</a></p>")
        if running:
            body += "<h3>Running</h3><ul>" + "".join(
                f"<li><a href='/tasklog?task={quote(n)}'>{_html.escape(n)}</a> "
                f"<span class='muted'>· {_html.escape(label)}</span></li>" for n, label in running.items()) + "</ul>"
        else:
            body += "<p class='muted'>No task running.</p>"
        body += "<h3>Recent</h3><ul>" + ("".join(rows) or "<li class='muted'>no logs yet</li>") + "</ul>"
        return self._page("Jobsquirrel task logs", body, refresh=3)

    def _tasklog_page(self, task):
        name = os.path.basename(task or "")[:120]
        if not name:
            return self._logs_page()
        path = os.path.join(LOGS, name + ".log")
        try:
            st = os.stat(path)
            size, age = st.st_size, int(time.time() - st.st_mtime)
        except OSError:
            size, age = 0, None
        raw = ANSI.sub("", _read(path, cap=400_000)).splitlines()[-400:]
        running = name in self._task_names()
        status = "running" if running else ("not running" if age is not None else "no log file")
        meta = f"{size} bytes · " + (f"last output {age}s ago" if age is not None else "no output yet")
        if age is not None and age > 90:
            meta += f" · quiet for {age // 60}m — the model may be stalled"
        text = "\n".join(raw) or "No output yet."
        body = (f"<p><a href='/logs'>← all logs</a> · <a href='/'>dashboard</a></p>"
                f"<h2>{_html.escape(name)}</h2><p class='muted'>{_html.escape(meta)} · {status}</p>"
                f"<pre>{_html.escape(text)}</pre>")
        return self._page(name + " · log", body, refresh=2)

    def do_GET(self):
        u = urlparse(self.path)
        p, qs = u.path, parse_qs(u.query)
        static = {"/": ("index.html", "text/html; charset=utf-8"),
                  "/app.css": ("app.css", "text/css; charset=utf-8"),
                  "/app.js": ("app.js", "application/javascript; charset=utf-8")}
        if p in static:
            return self._file(os.path.join(WEB, static[p][0]), static[p][1])
        if p == "/logs":
            return self._logs_page()
        if p == "/tasklog":
            return self._tasklog_page(qs.get("task", [""])[0])
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
        if p == "/api/accounts":
            return self._json(accounts())
        if p == "/api/google":
            return self._json(google_info())
        if p == "/api/drafts":
            return self._json(drafts_list(qs.get("company", [""])[0], qs.get("role", [""])[0]))
        if p == "/api/draft":
            return self._json(draft_get(qs.get("path", [""])[0]))
        if p == "/api/role-chat":
            return self._json(role_chat_stream(qs.get("key", [""])[0]))
        if p == "/api/permissions":
            return self._json({"policy": load_perms(), "defaults": DEFAULT_PERMS})
        if p == "/api/agent/config":
            return self._json(agent_config())
        if p == "/api/agent/models":
            return self._json(agent_models(qs.get("agent", [""])[0]))
        if p == "/api/graphrag/env":
            return self._json(graphrag_env())
        if p == "/api/agent/pending":
            return self._json({"pending": permission_pending()})
        if p == "/api/update":
            return self._json(check_update(refresh=qs.get("refresh", ["0"])[0] in ("1", "true")))
        if p == "/api/kb":
            return self._json(kb_info())
        if p == "/api/graph":
            return self._json(graph_query(qs.get("kind", ["entities"])[0], qs.get("q", [""])[0],
                                          qs.get("limit", ["200"])[0]))
        if p == "/api/grounding":
            return self._json(role_grounding(qs.get("key", [""])[0]))
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
        if p == "/api/file":
            return self._json(file_view(qs.get("path", [""])[0]))
        if p == "/raw":
            data, ctype, name = raw_file(qs.get("path", [""])[0])
            if data is None:
                return self._json({"error": "not found or not allowed"}, 404)
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Disposition", f'inline; filename="{name}"')
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            return self.wfile.write(data)
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

    def _upload(self):
        n = int(self.headers.get("Content-Length", "0") or 0)
        raw = self.rfile.read(n)
        m = re.search(r"boundary=([^;]+)", self.headers.get("Content-Type", ""))
        if not m:
            return {"error": "expected multipart/form-data"}
        b = m.group(1).strip('"').encode()
        group, files = "imported", []
        for part in raw.split(b"--" + b):
            if part.strip() in (b"", b"--", b"--\r\n"):
                continue
            head, _, body = part.partition(b"\r\n\r\n")
            if body.endswith(b"\r\n"):
                body = body[:-2]
            hs = head.decode("utf-8", "ignore")
            fm = re.search(r'filename="([^"]*)"', hs)
            nm = re.search(r'name="([^"]*)"', hs)
            if fm and fm.group(1):
                files.append((fm.group(1), body))
            elif nm and nm.group(1) == "group":
                group = body.decode("utf-8", "ignore").strip() or group
        return kb_upload(group, files)

    def do_POST(self):
        p = urlparse(self.path).path
        if p == "/api/agent/decide":
            # The pending id is the one-time secret the approval dialog holds.
            # Do not also require the session token: a tab opened before a
            # dashboard restart must still be able to approve its pending mail.
            # No Origin allow-list here: the dashboard may be opened by hostname
            # or LAN name, and a 128-bit id is already the unguessable secret.
            origin = self.headers.get("Origin") or ""
            host = self.headers.get("Host") or ""
            data = self._body()
            rid = str(data.get("id", ""))
            decision = str(data.get("decision", "deny"))
            res = permission_decide(rid, decision, bool(data.get("remember")),
                                    data.get("edits") or {}, bool(data.get("save")))
            _log_approval(f"id={rid[:8]}... decision={decision} origin={origin!r} host={host!r} -> {res}")
            return self._json(res)
        if not self._authed():
            return
        if p == "/api/kb/upload":
            return self._json(self._upload())
        data = self._body()
        if p == "/api/register/row":
            return self._json(update_row(data.get("company", ""), data.get("role", ""),
                                         data.get("status", ""), data.get("notes", ""),
                                         data.get("employment"), data.get("action"),
                                         data.get("work_model"), data.get("salary"),
                                         data.get("key", "")))
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
        if p == "/api/chat/stop":
            return self._json(chat_stop())
        if p == "/api/chat/new":
            return self._json(chat_new())
        if p == "/api/kb/delete":
            return self._json(kb_delete(data.get("path", "")))
        if p == "/api/kb/rebuild":
            return self._json(kb_rebuild())
        if p == "/api/accounts/auth":
            return self._json(account_auth(data.get("kind", "")))
        if p == "/api/google":
            return self._json(google_save(data))
        if p == "/api/draft/save":
            return self._json(draft_save(data))
        if p == "/api/draft/delete":
            return self._json(draft_delete(data.get("path", "")))
        if p == "/api/draft/send":
            return self._json(draft_send(data.get("path", ""), bool(data.get("clear_action"))))
        if p == "/api/role-chat":
            return self._json(role_chat_start(data.get("key", ""), data.get("company", ""),
                                              data.get("role", ""), data.get("message", "")))
        if p == "/api/role-chat/stop":
            return self._json(role_chat_stop(data.get("key", "")))
        if p == "/api/role-chat/new":
            return self._json(role_chat_new(data.get("key", "")))
        if p == "/api/permissions":
            return self._json({"policy": save_perms(data.get("policy") or {})})
        if p == "/api/agent/config":
            return self._json({"ok": "saved", "config": save_agent_cfg(data)})
        if p == "/api/graphrag/env":
            return self._json({"ok": "saved", "env": save_graphrag_env(data.get("vars") or {})})
        if p == "/api/approval/ask":
            return self._json(consent_request(str(data.get("purpose", "risky action"))[:500],
                                              str(data.get("token", "ACTION"))[:40],
                                              email=data.get("email") or None))
        if p == "/api/agent/permission":
            return self._json(permission_request(str(data.get("category", "?"))[:60],
                                                 str(data.get("detail", ""))[:400]))
        if p == "/api/update/apply":
            return self._json(apply_update(str(data.get("approval_token", ""))))
        if p == "/api/prepare":
            return self._json(prepare_roles(data.get("keys") or []))
        if p == "/api/submit":
            return self._json(submit_roles(data.get("keys") or [], data.get("approval_token", "")))
        if p == "/api/match/recompute":
            return self._json(recompute_match(data.get("keys")))
        if p == "/api/open":
            return self._json(open_apply(data.get("company", ""), data.get("role", "")))
        if p == "/api/action/stop":
            return self._json(stop_action())
        if p == "/api/action/pause":
            return self._json(pause_action(bool(data.get("on"))))
        if p == "/api/skills/evidence":
            return self._json(add_skill_evidence(data.get("skill", ""), data.get("source", ""),
                                                 data.get("detail", ""), data.get("key", "")))
        self._json({"error": "not found"}, 404)


def _source_stamp():
    """Fingerprint of the Python sources the server imports."""
    here = os.path.dirname(os.path.abspath(__file__))
    out = []
    for path in glob.glob(os.path.join(here, "*.py")):
        try:
            st = os.stat(path)
        except OSError:
            continue
        out.append((path, st.st_mtime_ns, st.st_size))
    return tuple(sorted(out))


def _supervise(host, port, open_browser):
    """Run the server in a child process; restart it when a source file changes."""
    child = [sys.executable, os.path.abspath(__file__), "--serve",
             "--host", host, "--port", str(port)]
    url = f"http://{host}:{port}/"
    print(f"🐿️  Jobsquirrel WebUI  ->  {url}   (Ctrl-C to stop · auto-reload on)", flush=True)
    stamp = _source_stamp()
    runs, proc = 0, None

    def _stop(_signum, _frame):
        raise KeyboardInterrupt                       # clean up the child on kill/TERM
    try:
        signal.signal(signal.SIGTERM, _stop)
    except (ValueError, OSError):
        pass
    try:
        while True:
            proc = subprocess.Popen(child)
            runs += 1
            if runs == 1 and open_browser:
                threading.Timer(0.8, lambda p=proc: p.poll() is None and webbrowser.open(url)).start()
            changed = False
            while proc.poll() is None:
                time.sleep(0.7)
                now = _source_stamp()
                if now != stamp:
                    changed = True
                    time.sleep(0.25)                    # coalesce a multi-file save
                    stamp = _source_stamp()
                    print("↻ source changed — restarting the WebUI…", flush=True)
                    proc.terminate()
                    try:
                        proc.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                        proc.wait(timeout=3)
                    break
            if changed:
                continue
            if runs == 1:
                return proc.returncode or 1             # e.g. port already in use
            print("server exited — fix the error and save; waiting for the next change…", flush=True)
            while _source_stamp() == stamp:
                time.sleep(0.7)
            stamp = _source_stamp()
    except KeyboardInterrupt:
        print("\nbye")
    finally:
        if proc and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()
    return 0


def main():
    ap = argparse.ArgumentParser(description="Jobsquirrel WebUI server.")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--open", action="store_true")
    ap.add_argument("--serve", action="store_true", help=argparse.SUPPRESS)
    ap.add_argument("--no-reload", action="store_true", help="run in-process (no auto-reload)")
    args = ap.parse_args()
    if not os.path.isfile(os.path.join(WEB, "index.html")):
        print(f"missing frontend: {WEB}/index.html", file=sys.stderr)
        return 2
    if not args.serve and not args.no_reload and os.environ.get("JOBSQUIRREL_NO_RELOAD") != "1":
        return _supervise(args.host, args.port, args.open)
    url = f"http://{args.host}:{args.port}/"
    DASH["url"] = f"http://{args.host}:{args.port}"       # handed to the agent so it can ask for approval
    srv = ThreadingHTTPServer((args.host, args.port), H)
    if not args.serve:
        print(f"🐿️  Jobsquirrel WebUI  ->  {url}   (Ctrl-C to stop)", flush=True)
    if args.open:
        threading.Timer(0.7, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        if not args.serve:
            print("\nbye")
    return 0


if __name__ == "__main__":
    sys.exit(main())
