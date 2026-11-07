#!/usr/bin/env python3
"""Prepare one role's document inputs in a single deterministic pass.

This replaces the agent's manual chain of ATS extraction, GraphRAG, alignment,
file discovery and pack seeding. The model then only tailors the prepared pack
and writes the letter, which cuts the number of slow model turns.

It is deliberately conservative about quality:
  - the JD and its hash are checked; ATS/GraphRAG are reused only when unchanged
  - the archetype must pass check_alignment (or the command fails)
  - the seed pack keeps every role, date and fact from an existing grounded pack
  - all the normal gates still run afterwards

Usage:
  python3 tools/prepare_role.py --key <key> [--jd path] [--cv archetype]
      [--company "Company"] [--role "Role"] [--base path] [--force]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import stateio
import scam_check

JD_DIR = os.path.join(ROOT, "state", "job-descriptions")
ATS_DIR = os.path.join(ROOT, "state", "ats")
KB_DIR = os.path.join(ROOT, "state", "kb-context")
CV_DIR = os.path.join(ROOT, "state", "cv-content")
BRIEF_DIR = os.path.join(ROOT, "state", "briefs")
LETTER_DIR = os.path.join(ROOT, "state", "letters")
ARCH_DIR = os.path.join(ROOT, "documents", "archetypes")

FAMILY_CV = {
    "ai_ml": "Senior_AI_Engineer",
    "data_science": "Senior_Data_Scientist",
    "platform_devops": "AI_Platform_Engineer",
    "systems_backend": "Systems_Backend_Engineer",
    "security": "Security_AI_Cloud",
    "leadership": "Engineering_Leadership",
    "consulting": "Senior_IT_Consultant",
}


def run(cmd, timeout=900):
    return subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=timeout)


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sidecar(path: str) -> str:
    return path + ".sha256"


def fresh(path: str, digest: str) -> bool:
    try:
        found = stateio.resolve(path) or path
        return (open(sidecar(path), encoding="utf-8").read().strip() == digest
                and os.path.exists(found))
    except OSError:
        return False


def mark(path: str, digest: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(sidecar(path), "w", encoding="utf-8") as fh:
        fh.write(digest + "\n")


def parse_role(jd_text: str, company: str, role: str):
    if company and role:
        return company, role
    first = next((l.strip() for l in jd_text.splitlines() if l.strip().startswith("#")), "")
    first = re.sub(r"^#+\s*", "", first)
    if not company:
        m = re.search(r"\*\*Company:\*\*\s*(.+)", jd_text)
        company = m.group(1).strip() if m else ""
    if not role:
        m = re.search(r"\*\*Role:\*\*\s*(.+)", jd_text)
        role = m.group(1).strip() if m else ""
    if "—" in first or " - " in first:
        bits = re.split(r"\s+—\s+|\s+-\s+", first, maxsplit=1)
        if len(bits) == 2:
            company = company or bits[0].strip()
            role = role or bits[1].strip()
    return company, role


def title_archetype(role: str) -> str:
    r = (role or "").lower()
    if re.search(r"engineering manager|head of|director|vice president|\bvp\b|chief|\bcto\b|manager", r):
        return "Engineering_Leadership"
    if "data scien" in r or "machine learning scientist" in r:
        return "Senior_Data_Scientist"
    if "security" in r or "cyber" in r:
        return "Security_AI_Cloud"
    if "consultant" in r:
        return "Senior_IT_Consultant"
    if "architect" in r:
        return "AI_Architect"
    if "platform" in r:
        return "AI_Platform_Engineer"
    if "backend" in r or "systems" in r:
        return "Systems_Backend_Engineer"
    return ""


def archetype_for(jd: str, cv_arg: str, role: str = ""):
    candidates = []
    if cv_arg:
        path = cv_arg if os.path.isabs(cv_arg) or cv_arg.endswith(".docx") else os.path.join(
            ARCH_DIR, f"Peter_Hollas_CV_{cv_arg}.docx")
        if not os.path.exists(path):
            raise SystemExit(f"no archetype CV at {path}")
        candidates = [path]
    else:
        # Prefer a title heuristic (an Engineering Manager is a leadership CV
        # even when the ad is full of AI keywords), then fall back to the gate's
        # family classification.
        hinted = title_archetype(role)
        if hinted:
            candidates = [os.path.join(ARCH_DIR, f"Peter_Hollas_CV_{hinted}.docx")]
        probe = os.path.join(ARCH_DIR, "Peter_Hollas_CV_Engineering_Leadership.docx")
        r = run([sys.executable, "tools/check_alignment.py", "--cv", probe, "--jd", jd])
        m = re.search(r"role family\s*:\s*([a-z_]+)", r.stdout + r.stderr)
        family = m.group(1) if m else ""
        key = FAMILY_CV.get(family)
        if key and not candidates:
            candidates = [os.path.join(ARCH_DIR, f"Peter_Hollas_CV_{key}.docx")]
        if not candidates:
            candidates = sorted(
                os.path.join(ARCH_DIR, f) for f in os.listdir(ARCH_DIR)
                if f.startswith("Peter_Hollas_CV_") and f.endswith(".docx"))
    good = []
    for path in candidates:
        r = run([sys.executable, "tools/check_alignment.py", "--cv", path, "--jd", jd])
        if "RESULT: PASS" in (r.stdout + r.stderr):
            good.append(path)
    if not good:
        # last resort: try every archetype once
        if not cv_arg:
            for path in sorted(
                    os.path.join(ARCH_DIR, f) for f in os.listdir(ARCH_DIR)
                    if f.startswith("Peter_Hollas_CV_") and f.endswith(".docx")):
                r = run([sys.executable, "tools/check_alignment.py", "--cv", path, "--jd", jd])
                if "RESULT: PASS" in (r.stdout + r.stderr):
                    good.append(path)
                    break
    if not good:
        raise SystemExit("no CV archetype passes check_alignment for this role")
    return good[0]


def ats_terms(path: str):
    try:
        found = stateio.resolve(path) or path
        return [t.strip().lower() for t in stateio.read_text(found).splitlines() if t.strip()]
    except OSError:
        return []


def pack_score(pack: dict, terms):
    text = json.dumps(pack).lower()
    return sum(min(3, text.count(t)) for t in terms)


def choose_base(key: str, terms):
    best = None
    for name in os.listdir(CV_DIR):
        if not name.endswith(".json") or name.startswith("_"):
            continue
        p = os.path.join(CV_DIR, name)
        if name == f"{key}.json":
            continue
        try:
            data = json.load(open(p, encoding="utf-8"))
        except Exception:
            continue
        roles = data.get("experience") or []
        bullets = sum(len(e.get("bullets") or []) for e in roles)
        bullets += sum(len(g.get("bullets") or []) for e in roles for g in (e.get("groups") or []))
        if bullets < 30 or len((data.get("profile") or "").split()) < 140:
            continue
        s = pack_score(data, terms)
        if best is None or s > best[0]:
            best = (s, p, data)
    if best:
        return best[1], best[2]
    return "", {}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--key", required=True)
    ap.add_argument("--jd", default="")
    ap.add_argument("--cv", default="")
    ap.add_argument("--company", default="")
    ap.add_argument("--role", default="")
    ap.add_argument("--base", default="")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--allow-scam", action="store_true",
                    help="continue despite a HIGH scam signal (you take the risk)")
    args = ap.parse_args()

    key = re.sub(r"[^A-Za-z0-9._-]", "-", args.key).strip("-.")
    jd_path = args.jd or os.path.join(JD_DIR, f"{key}.md")
    if not os.path.exists(jd_path):
        print(f"PREP FAIL: no job description at {jd_path}", file=sys.stderr)
        return 2
    jd_text = open(jd_path, encoding="utf-8").read()
    shelved_path = os.path.join(ROOT, "state", "shelved.json")
    try:
        with open(shelved_path, encoding="utf-8") as fh:
            shelved_now = json.load(fh)
    except (OSError, ValueError):
        shelved_now = {}
    if isinstance(shelved_now, dict) and key in shelved_now:
        print(f"PREP SKIP: {key} is shelved (unshelve it in the dashboard first)",
              file=sys.stderr)
        return 3

    # A scam advert must not become a tailored application. This runs before any
    # model/embedding work, so a HIGH signal fails fast and cheap.
    scan = scam_check.scan(jd_text, args.company, scam_check.sender_from_text(jd_text))
    scam_check.save(key, scan)
    if scan["level"] == "high" and not args.allow_scam:
        print("PREP FAIL: HIGH scam signal — " + scam_check.summary(scan), file=sys.stderr)
        for sig in scan["signals"]:
            if sig["level"] == "high":
                print(f"  {sig['key']}: {sig['why']} — {sig['advice']}", file=sys.stderr)
        print(f"  RULE: {scan['rule']}", file=sys.stderr)
        print("  If this is a false positive, re-run with --allow-scam after verifying "
              "the employer.", file=sys.stderr)
        return 3
    if scan["level"] == "medium":
        print(f"SCAM WARNING ({scan['level'].upper()}): {scam_check.summary(scan)}")
    digest = sha(jd_text)
    evidence_path = os.path.join(ROOT, "kb", "sources", "personal", "skills_evidence.md")
    try:
        evidence_text = open(evidence_path, encoding="utf-8").read()
    except OSError:
        evidence_text = ""
    # The KB context also carries the operator-provided skill evidence appended
    # by kb_graphrag.py, so new evidence must invalidate this cache too.
    company, role = parse_role(jd_text, args.company, args.role)
    leadership = bool(re.search(r"engineering manager|head of|director|vice president|\bvp\b|chief|\bcto\b|manager", role, re.I))
    kb_method = "hybrid" if leadership else "local"
    kb_level = "1" if leadership else "2"
    kb_digest = sha(jd_text + "\n\n" + evidence_text + f"\n{kb_method}:{kb_level}")

    os.makedirs(ATS_DIR, exist_ok=True)
    os.makedirs(KB_DIR, exist_ok=True)
    os.makedirs(CV_DIR, exist_ok=True)
    os.makedirs(BRIEF_DIR, exist_ok=True)
    os.makedirs(LETTER_DIR, exist_ok=True)

    ats_path = os.path.join(ATS_DIR, f"{key}.txt")
    if args.force or not fresh(ats_path, digest):
        r = run([sys.executable, "tools/ats_keywords.py", "--jd", jd_path, "--out", ats_path])
        if r.returncode:
            print((r.stdout + r.stderr).strip(), file=sys.stderr)
            return r.returncode or 2
        mark(ats_path, digest)

    kb_path = os.path.join(KB_DIR, f"{key}.md")
    if args.force or not fresh(kb_path, kb_digest):
        r = run([sys.executable, "tools/kb_graphrag.py", "--jd", jd_path, "--out", kb_path,
                 "--method", kb_method, "--community-level", kb_level])
        if r.returncode:
            print((r.stdout + r.stderr).strip(), file=sys.stderr)
            return r.returncode or 2
        mark(kb_path, kb_digest)

    cv_path = archetype_for(jd_path, args.cv, role)
    cv_key = os.path.basename(cv_path).replace("Peter_Hollas_CV_", "").replace(".docx", "")

    content_path = os.path.join(CV_DIR, f"{key}.json")
    source = ""
    if args.base:
        source = args.base
        seed = json.load(open(args.base, encoding="utf-8"))
        with open(content_path, "w", encoding="utf-8") as fh:
            json.dump(seed, fh, indent=2, ensure_ascii=False)
            fh.write("\n")
    elif os.path.exists(content_path) and not args.force:
        source = content_path
    else:
        source, seed = choose_base(key, ats_terms(ats_path))
        if source:
            seed.setdefault("key", key)
            with open(content_path, "w", encoding="utf-8") as fh:
                json.dump(seed, fh, indent=2, ensure_ascii=False)
                fh.write("\n")
        else:
            # canonical fallback from the base CV
            try:
                import cv_target as CT
                data = CT._default_data(key)
                data["company"], data["role"] = company, role
                with open(content_path, "w", encoding="utf-8") as fh:
                    json.dump(data, fh, indent=2, ensure_ascii=False)
                    fh.write("\n")
                source = "canonical"
            except Exception as exc:
                print(f"PREP FAIL: no seed pack ({exc})", file=sys.stderr)
                return 2

    data = json.load(open(content_path, encoding="utf-8"))
    data.pop("role_line", None)
    data["key"] = key
    data["company"] = company or data.get("company") or ""
    data["role"] = role or data.get("role") or ""
    with open(content_path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)
        fh.write("\n")

    brief_path = os.path.join(BRIEF_DIR, f"{key}.md")
    with open(brief_path, "w", encoding="utf-8") as fh:
        fh.write(f"# {company or 'Company'} — {role or 'Role'}\n\n")
        fh.write(f"Archetype: {cv_key}\nCV: {cv_path}\nJD: {jd_path}\n")
        fh.write(f"ATS: {ats_path}\nKB: {kb_path}\nContent: {content_path}\nBase: {source}\n\n")
        fh.write("## Job description\n\n" + jd_text.strip() + "\n\n")
        found = stateio.resolve(kb_path) or kb_path
        fh.write("## Grounded context\n\n" + stateio.read_text(found).strip() + "\n")

    roles = data.get("experience") or []
    bullets = sum(len(e.get("bullets") or []) for e in roles)
    bullets += sum(len(g.get("bullets") or []) for e in roles for g in (e.get("groups") or []))
    print(f"PREP ok key={key} archetype={cv_key}")
    print(f"CONTENT roles={len(roles)} bullets={bullets} "
          f"profile={len((data.get('profile') or '').split())}w "
          f"skills={len(data.get('skills') or [])} selected={len(data.get('selected_work') or [])}")
    print(f"BRIEF {brief_path}")
    print(f"PACK  {content_path}")
    print("NEXT edit the pack (profile, tagline, skills, selected work and role bullets), "
          "then run cv_target --require-fill and the letter.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
