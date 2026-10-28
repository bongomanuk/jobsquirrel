#!/usr/bin/env python3
"""Discovery: find new roles from LinkedIn Job Alert emails (read-only Gmail).

The pipeline had no discovery step, so matching roles (e.g. the LinkedIn sweep)
never entered the register. This reads your LinkedIn Job Alert emails, extracts
each job (title, company, link), drops anything already in the register, and can
add the new ones as PREPARED.

Run with the venv python:
  .venv/bin/python tools/discover.py                 # show new roles (dry run)
  .venv/bin/python tools/discover.py --days 14
  .venv/bin/python tools/discover.py --apply         # add new roles as PREPARED
"""
import argparse
import html
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gmail_readonly as G
import register as R
import jd_guard

SENDER = "jobalerts-noreply@linkedin.com"
JOB = re.compile(r'href="([^"]*linkedin\.com/[^"]*jobs/view/[^"]+)"[^>]*>(.*?)</a>', re.I | re.S)
COMPANY = re.compile(r'href="[^"]*/company/([^/?"#]+)[^"]*"[^>]*>(.*?)</a>', re.I | re.S)


def clean(s):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s))).strip()


def parse_jobs(body):
    out = []
    for m in JOB.finditer(body):
        link, title_html = m.group(1), m.group(2)
        title = clean(title_html)
        if not title or len(title) < 3:
            continue
        if title.lower().startswith(("manage alerts", "see all", "unsubscribe")):
            continue
        tail = body[m.end():m.end() + 1500]
        cm = COMPANY.search(tail)
        company = clean(cm.group(2)) if cm else ""
        if not company and " at " in title:
            title, company = title.rsplit(" at ", 1)
        elif not company and " | " in title:
            title, company = title.split(" | ", 1)
        link = link.replace("/comm/jobs/view/", "/jobs/view/").split("?")[0]
        out.append({"title": title.strip(), "company": company.strip(), "link": link})
    return out


VIEW = re.compile(r"View job:\s*(https?://[^\s]+?jobs/view/[^\s]+)", re.I)


def parse_digest(body):
    """Parse a LinkedIn job-alert digest. Each block renders as:
        TITLE / COMPANY / LOCATION / "This company is actively hiring" / "View job: <url>"
    Extracts title+company+url per block (far more reliable than company-page scraping)."""
    text = html.unescape(re.sub(r"<[^>]+>", "\n", body))
    out = []
    for m in VIEW.finditer(text):
        link = m.group(1).replace("/comm/jobs/view/", "/jobs/view/").split("?")[0]
        pre = text[max(0, m.start() - 600):m.start()]
        lines = [clean(x) for x in pre.splitlines() if clean(x)]
        title = company = ""
        idx = None
        for i, ln in enumerate(lines):
            if "actively hiring" in ln.lower() or ln.lower().startswith("view job"):
                idx = i
        if idx is not None and idx >= 3:
            title, company = lines[idx - 3], lines[idx - 2]
        elif len(lines) >= 2:
            title, company = lines[-2], lines[-1]
        if title and "job alert" not in title.lower() and "job alert" not in company.lower():
            out.append({"title": title, "company": company, "link": link})
    return out


def parse_subject(subject, body):
    """LinkedIn per-job alerts use the subject 'TITLE at COMPANY' - far cleaner
    than scraping the body. Returns one job (or none) plus the first view link."""
    s = clean(subject)
    m = re.match(r"^(?P<title>.+?)\s+at\s+(?P<company>.+)$", s)
    if not m:
        return None
    link = ""
    lm = re.search(r'href="([^"]*linkedin\.com/[^"]*jobs/view/[^"]+)"', body, re.I)
    if lm:
        link = lm.group(1).replace("/comm/jobs/view/", "/jobs/view/").split("?")[0]
    return {"title": m.group("title").strip(), "company": m.group("company").strip(), "link": link}


def slug(s):
    out = []
    for ch in s.lower():
        if ch.isalnum():
            out.append(ch)
        elif out and out[-1] != "-":
            out.append("-")
    return "".join(out).strip("-")[:40]


def queue_keys(path):
    keys, urls = set(), set()
    if not os.path.isfile(path):
        return keys, urls
    for line in open(path):
        line = line.rstrip("\n")
        if not line or line.startswith("#"):
            continue
        p = line.split("\t")
        if len(p) >= 2:
            keys.add((p[0].strip().lower(), p[1].strip().lower()))
        for cell in p:
            if "linkedin.com/jobs/view/" in cell:
                urls.add(cell.strip())
    return keys, urls


def known(rows):
    # Only suppress an exact (company, role) already recorded. Matching on the
    # role alone would hide a legitimate same-titled role at a different company.
    return {(r["company"].strip().lower(), r["role"].strip().lower()) for r in rows}


def main():
    ap = argparse.ArgumentParser(description="Discover roles from LinkedIn job alerts.")
    ap.add_argument("--days", type=int, default=14)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--match", default="", help="only roles whose title matches this regex (case-insensitive)")
    ap.add_argument("--queue", action="store_true",
                    help="append matched new roles to state/queue.tsv (feeds the run queue)")
    ap.add_argument("--cv", default=os.environ.get("CV_ARCHETYPE", "documents/archetypes/CV.docx"),
                    help="CV archetype to put in queued rows (override with CV_ARCHETYPE)")
    ap.add_argument("--fetch-jd", action="store_true",
                    help="fetch and save each new role's job description before queueing it")
    ap.add_argument("--browser-server", default=os.environ.get("CAMOUFOX_SERVER", ""),
                    help="optional Camoufox server for login-gated job pages")
    args = ap.parse_args()
    matcher = re.compile(args.match, re.I) if args.match else None

    svc = G.authenticate()
    q = f"from:{SENDER} newer_than:{args.days}d"
    msgs = G._retry(lambda: svc.users().messages().list(userId="me", q=q, maxResults=50).execute()).get("messages", [])
    print(f"{len(msgs)} alert emails in the last {args.days} days\n")

    seen, jobs = set(), []
    for m in msgs:
        msg = G._retry(lambda: svc.users().messages().get(userId="me", id=m["id"], format="full").execute())
        payload = msg["payload"]
        headers = {h["name"].lower(): h["value"] for h in payload.get("headers", [])}
        body = G._decode(payload)
        batch = parse_digest(body) + list(parse_jobs(body))
        subj_job = parse_subject(headers.get("subject", ""), body)
        if subj_job and subj_job["title"]:
            batch.insert(0, subj_job)
        for j in batch:
            key = j["link"] or (j["company"].lower(), j["title"].lower())
            if key in seen:
                continue
            seen.add(key)
            jobs.append(j)

    reg = known(R.load())
    qkeys, qurls = queue_keys(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                           "state", "queue.tsv"))
    new = []
    for j in jobs:
        t = j["title"].strip().lower()
        if matcher and not matcher.search(j["title"]):
            continue
        if (j["company"].lower(), t) in reg:
            continue
        if (j["company"].lower(), t) in qkeys or (j["link"] and j["link"] in qurls):
            continue
        new.append(j)

    def qkey(j):
        co = j["company"] or "(LinkedIn)"
        return co, slug(f"{co} {j['title']}") or slug(j["title"]) or slug(j["link"])

    ready, skipped = [], []
    for j in new:
        co, key = qkey(j)
        if jd_guard.has_jd(key):
            ready.append(j)
            continue
        if not args.fetch_jd:
            skipped.append((j, "no job description (pass --fetch-jd)"))
            continue
        try:
            text = ""
            if args.browser_server:
                try:
                    text = jd_guard.fetch_browser(j["link"], args.browser_server)
                except Exception:
                    text = ""
            if not text:
                text = jd_guard.fetch_http(j["link"])
            jd_guard.write_jd(key, co, j["title"], j["link"], text)
            ready.append(j)
        except Exception as e:
            skipped.append((j, str(e)[:100]))

    print(f"{len(jobs)} unique jobs, {len(new)} new (matching) not already in the register/queue")
    print(f"  {len(ready)} have a job description; {len(skipped)} skipped\n")
    for j in ready:
        print(f"  READY {j['title'][:50]:50} | {(j['company'] or '?')[:20]:20} | {j['link']}")
    for j, why in skipped:
        print(f"  SKIP  {j['title'][:50]:50} | {(j['company'] or '?')[:20]:20} | {why}")

    if args.apply and ready:
        for j in ready:
            co = j["company"] or "(LinkedIn)"
            R.upsert(co, j["title"], "PREPARED", day=__import__("datetime").date.today().isoformat(),
                     notes=f"source: LinkedIn job alert; {j['link']}")
        print(f"\nadded {len(ready)} roles as PREPARED")

    if args.queue and ready:
        qpath = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "state", "queue.tsv")
        n = 0
        with open(qpath, "a") as fh:
            for j in ready:
                co, key = qkey(j)
                fh.write(f"{co}\t{j['title']}\t{j['link']}\t{args.cv}\tTBD\t{key}\n")
                n += 1
        print(f"queued {n} roles into state/queue.tsv (run tools/run_queue.sh to apply)")
    elif ready and not args.apply:
        print("\n(dry run - use --apply and/or --queue)")
    if skipped:
        print(f"\n{len(skipped)} role(s) were not queued because they have no job description; save one first.")


if __name__ == "__main__":
    main()
