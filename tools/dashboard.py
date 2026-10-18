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
        url, cv, ats, k = _queue_fields(company, role)
        os.makedirs(LOGS, exist_ok=True)
        tmp = os.path.join(LOGS, "queue-human-ui.tsv")
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write("\t".join([company, role, url, cv, ats, k]) + "\n")
        _spawn(f"human assist: {company} / {role}",
               ["bash", os.path.join(ROOT, "tools", "human_assist.sh")], {"QUEUE": tmp})
        return {"ok": f"opening a visible Camoufox browser for {company} / {role} — solve the block there, then submit"}
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


def _cov_sig(key, cvrel):
    cvp = cvrel if os.path.isabs(cvrel or "") else os.path.join(ROOT, cvrel or "")
    return ":".join(str(_mtime(p)) for p in (
        os.path.join(STATE, "ats", key + ".txt"),
        os.path.join(STATE, "cv-content", key + ".json"),
        os.path.join(STATE, "letters-content", key + ".json"), cvp))


def coverage_for(key, cvrel=""):
    """ATS-keyword coverage %: the tailored content packs if present, else the archetype CV text."""
    global _cov_dirty
    kws = [l.strip() for l in _lines(os.path.join(STATE, "ats", key + ".txt"))]
    if not kws:
        return None
    sig = _cov_sig(key, cvrel)
    hit = _COV.get(key) or {}
    if hit.get("sig") == sig and "cov" in hit:
        return hit["cov"]
    hay = (_read(os.path.join(STATE, "cv-content", key + ".json")) + " "
           + _read(os.path.join(STATE, "letters-content", key + ".json"))).lower()
    if not hay.strip() and cvrel:
        cvp = cvrel if os.path.isabs(cvrel) else os.path.join(ROOT, cvrel)
        hay = _doc_text(cvp).lower()
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
    cov, missing = None, []
    if kws and hay.strip():
        miss = [k for k in kws if k.lower() not in hay]
        cov = round(100 * (len(kws) - len(miss)) / len(kws))
        missing = miss[:24]
    return {"key": key, "coverage": cov, "missing": missing,
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


def grid():
    """One row per application: register ⋈ queue ⋈ in-flight running tasks ⋈ provenance."""
    apps = _rows(os.path.join(STATE, "applications.csv"))
    _load_cov()
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
        m = _MATCH_CACHE.get(key, {})
        cov = m.get("coverage")
        if cov is None:
            cov = coverage_for(key, cvmap.get(key, "") or subm_cv.get(ck, ""))
        align = m.get("alignment") or (_COV.get(key, {}) or {}).get("align", "")
        out.append({"date": r.get("date", ""), "company": co, "role": role, "ats": r.get("ats", ""),
                    "status": (r.get("status") or "").upper(), "key": key,
                    "queue": "done" if f"{co}|{role}" in done else qstate.get(ck, ""),
                    "spec": key in specs, "applied": ck in subm,
                    "match": cov, "alignment": align, "running": ck in running,
                    "notes": r.get("notes", ""), "letter": r.get("letter", ""),
                    "url": qrow.get(ck, {}).get("url", "") or subm_url.get(ck, "")})
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
        out.append({"date": qdate, "company": co, "role": role, "ats": r.get("ats", ""),
                    "status": "DONE" if f"{co}|{role}" in done else "QUEUED", "key": key,
                    "queue": "done" if f"{co}|{role}" in done else qstate.get(ck, "pending"),
                    "spec": key in specs, "applied": ck in subm,
                    "match": cov, "alignment": m.get("alignment", ""), "running": ck in running,
                    "notes": "", "letter": "", "url": r.get("url", "")})
    _save_cov()
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
    return {"name": name, "curated": curate(_read(os.path.join(LOGS, name + ".log"), cap=200_000))}


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
    act_log = action_log(400)
    return {"active": active, "running": [k.replace("|", " — ") for k in running],
            "tail_name": tail_name, "tail": tail,
            "paused": os.path.exists(PAUSE_FILE),
            "stopping": os.path.exists(STOP_FILE),
            "action": {"name": _ACT.get("name", ""), "running": act_running,
                       "summary": summarize_action(_ACT.get("name", ""), act_log, act_running),
                       "log": act_log}}


ACT_NOISE = re.compile(r"^\s*(?:[─═\-_=]{4,}|[.|·•]\s*$|\d+%?\s*\|)")


def summarize_action(name, lines, running):
    """Compress an action log into a headline + the few lines that matter."""
    clean = [l.rstrip() for l in lines if l.strip() and not ACT_NOISE.match(l)]
    wanted = re.compile(r"(error|fail|warn|refus|denied|traceback|⇒|→|nothing to|no changes|"
                        r"\bwrote\b|\bwritten\b|\bsaved\b|prepared|submitted|applied|created|"
                        r"proposal|\b[1-9]\d*\b\s*(?:new|found|queued|sent|updated|skipped|matched))", re.I)
    notable, seen = [], set()
    for l in clean:
        if wanted.search(l) and l not in seen:
            notable.append(l.strip()[:200]); seen.add(l)
    notable = notable[-8:]
    return {"headline": (clean[-1][:200] if clean else ("running…" if running else "no output")),
            "notable": notable, "lines": len(clean)}


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


def chat_new():
    """Clear the chat history: stop any running turn, drop the queue, transcript + session."""
    _CHAT["queue"] = []
    p = _CHAT.get("proc")
    if p and p.poll() is None:
        try:
            os.killpg(os.getpgid(p.pid), signal.SIGTERM)
        except OSError:
            pass
        _CHAT["proc"] = None
    for path in (CHAT_LOG, CHAT_SESSION):
        try:
            os.remove(path)
        except OSError:
            pass
    return {"ok": "history cleared"}


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
        return {"agent": d.get("agent", "") or "", "model": d.get("model", "") or "",
                "env": d.get("env", {}) or {}}
    except (OSError, ValueError):
        return {"agent": "", "model": "", "env": {}}


def save_agent_cfg(d):
    prev = load_agent_cfg()
    agent = str(d.get("agent", prev["agent"]) or "").strip()[:200]
    model = str(d.get("model", prev["model"]) or "").strip()[:200]
    env = dict(prev["env"])
    for k, v in (d.get("env") or {}).items():
        k = re.sub(r"[^A-Za-z0-9_]", "", str(k))[:80]
        if not k:
            continue
        if v in ("", None):
            env.pop(k, None)                      # blank clears
        else:
            env[k] = str(v)[:1000]
    out = {"agent": agent, "model": model, "env": env}
    os.makedirs(os.path.dirname(AGENT_CFG_FILE), exist_ok=True)
    fd = os.open(AGENT_CFG_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=2)
    return out


def _mask(v):
    v = v or ""
    return ("…" + v[-4:]) if len(v) > 4 else ("set" if v else "")


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
    return {"agent": cfg["agent"], "model": cfg["model"],
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
        env.setdefault("AGENT", cfg["agent"])
    if cfg.get("model"):
        env.setdefault("MODEL", cfg["model"])
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
    rid = uuid.uuid4().hex[:8]
    ev = threading.Event()
    with _PERM_LOCK:
        _PERM[rid] = {"id": rid, "category": category, "detail": detail, "event": ev, "decision": None, "ts": time.time()}
    ev.wait(timeout)
    with _PERM_LOCK:
        rec = _PERM.pop(rid, {})
    return {"decision": rec.get("decision") or "deny", "id": rid, "category": category}


def permission_pending():
    with _PERM_LOCK:
        return [{"id": r["id"], "category": r["category"], "detail": r["detail"]}
                for r in _PERM.values() if r["decision"] is None]


def permission_decide(rid, decision, remember=False):
    with _PERM_LOCK:
        r = _PERM.get(rid)
    if not r:
        return {"error": "unknown or expired request"}
    r["decision"] = "allow" if decision == "allow" else "deny"
    if remember:
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
    _CHAT["proc"] = subprocess.Popen(["bash", os.path.join(ROOT, "tools", "agent_run.sh"), prompt],
                                     cwd=ROOT, env=env, stdout=f, stderr=subprocess.STDOUT,
                                     start_new_session=True)


def _chat_pump():
    """Start the next queued message if the agent is free."""
    proc = _CHAT.get("proc")
    if proc and proc.poll() is None:
        return
    q = _CHAT.get("queue") or []
    if q:
        _chat_spawn(q.pop(0))


def chat_start(message):
    message = (message or "").strip()[:8000]
    if not message:
        return {"error": "empty message"}
    if _CHAT.get("proc") and _CHAT["proc"].poll() is None:
        _CHAT.setdefault("queue", []).append(message)      # queue it — never lose the message
        _chat_echo(message)
        return {"status": "queued", "queued": True, "pending": len(_CHAT["queue"])}
    _chat_echo(message)
    _chat_spawn(message)
    return {"status": "queued", "run_id": "chat", "agent": chat_agent(), "pending": 0}


CHAT_USER = re.compile(r"^>\s?(.*)$")
CHAT_TOOL = re.compile(r"^\$\s?(.*)$")
CHAT_STATUS = re.compile(r"^>\s*build\b.*$", re.I)


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
        if s["t"] == "tool" and len(s["body"]) > 6000:
            s["body"] = s["body"][:6000] + "\n… (truncated)"
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
        if s["t"] == "tool" and len(s.get("body", "")) > 6000:
            s["body"] = s["body"][:6000] + "\n… (truncated)"
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
        if s["t"] == "tool" and len(s.get("body", "")) > 6000:
            s["body"] = s["body"][:6000] + "\n… (truncated)"
    return segs


def _json_kind(text):
    for ln in text.splitlines():
        s = ln.strip()
        if not s or s.startswith(">") or s.startswith("build "):
            continue
        if not s.startswith("{"):
            return None
        try:
            e = json.loads(s)
        except ValueError:
            return None
        if "part" in e:
            return "opencode"
        if "message" in e or e.get("type") in ("system", "assistant", "user", "result"):
            return "claude"
        return None
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
    running = bool(_CHAT["proc"] and _CHAT["proc"].poll() is None)
    kind = _json_kind(text)
    if kind == "opencode":
        segs = chat_parse_json(text)
    elif kind == "claude":
        segs = chat_parse_claude(text)
    else:
        segs = chat_parse(text)
    pending = len(_CHAT.get("queue") or [])
    return {"segments": segs, "offset": size, "running": running, "pending": pending,
            "done": not running and not pending}


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


def prepare_roles(keys):
    """Run a REVIEW pass (generate + gate documents, never submit) over the given roles,
    by handing run_queue.sh a temporary queue containing just those rows.

    Works for any role: queued rows are taken from the queue files; others are rebuilt
    from the register / submissions so a role you opened (e.g. a done or blocked one) can
    still be (re)prepared."""
    keys = [str(k).strip() for k in (keys or []) if str(k).strip()]
    if not keys:
        return {"error": "no roles selected"}
    want = set(keys)
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
    if not rows:
        return {"error": "couldn't resolve those roles to a company/role"}
    os.makedirs(LOGS, exist_ok=True)
    tmp = os.path.join(LOGS, "queue-ui.tsv")
    with open(tmp, "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write("\t".join([r["company"], r["role"], r.get("url", ""), r.get("cv", ""),
                                r.get("ats", ""), r["key"]]) + "\n")
    # a scoped run must NOT skip rows already marked done in the shared queue.done
    tmp_done = os.path.join(LOGS, "queue-ui.done")
    with open(tmp_done, "w", encoding="utf-8"):
        pass
    _spawn(f"prepare {len(rows)} role(s) (review)",
           ["bash", os.path.join(ROOT, "tools", "run_queue.sh")],
           {"REVIEW": "1", "PARALLEL": "1", "QUEUE": tmp, "DONE": tmp_done})
    return {"ok": f"generating documents for {len(rows)} role(s) — watch the Activity pane (nothing is submitted)"}


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
        if p == "/api/accounts":
            return self._json(accounts())
        if p == "/api/permissions":
            return self._json({"policy": load_perms(), "defaults": DEFAULT_PERMS})
        if p == "/api/agent/config":
            return self._json(agent_config())
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
        if not self._authed():
            return
        if p == "/api/kb/upload":
            return self._json(self._upload())
        data = self._body()
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
        if p == "/api/chat/new":
            return self._json(chat_new())
        if p == "/api/kb/delete":
            return self._json(kb_delete(data.get("path", "")))
        if p == "/api/kb/rebuild":
            return self._json(kb_rebuild())
        if p == "/api/accounts/auth":
            return self._json(account_auth(data.get("kind", "")))
        if p == "/api/permissions":
            return self._json({"policy": save_perms(data.get("policy") or {})})
        if p == "/api/agent/config":
            return self._json({"ok": "saved", "config": save_agent_cfg(data)})
        if p == "/api/graphrag/env":
            return self._json({"ok": "saved", "env": save_graphrag_env(data.get("vars") or {})})
        if p == "/api/agent/permission":
            return self._json(permission_request(str(data.get("category", "?"))[:60],
                                                 str(data.get("detail", ""))[:400]))
        if p == "/api/agent/decide":
            return self._json(permission_decide(str(data.get("id", "")), str(data.get("decision", "deny")),
                                                bool(data.get("remember"))))
        if p == "/api/update/apply":
            return self._json(apply_update(str(data.get("approval_token", ""))))
        if p == "/api/prepare":
            return self._json(prepare_roles(data.get("keys") or []))
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
    DASH["url"] = f"http://{args.host}:{args.port}"       # handed to the agent so it can ask for approval
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
