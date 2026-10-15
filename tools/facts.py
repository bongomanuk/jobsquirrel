#!/usr/bin/env python3
"""Authoritative, CV-backed facts — to constrain free-text answers.

Reads the structured CV in config/cv.json (falling back to
config/cv.example.json) and exposes the facts an answer may use, so an agent
writing free text (e.g. an "outlier" question) cannot invent scope, employers or
present-tense claims about past work.

Employers come from experience[].employer; the current employer is the one whose
dates contain "present"; every other employer is a past employer. Certifications
and languages are read from the CV too. Nothing about any particular person,
employer or certification is hard-coded.

Commands:
  python3 tools/facts.py --json            # machine-readable facts
  python3 tools/facts.py --show            # human-readable summary
  python3 tools/facts.py --check FILE      # validate a text file
  python3 tools/facts.py --text "..."      # validate a string
"""
import argparse
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_DIR = os.path.join(ROOT, "config")

PRESENT = re.compile(r"\b(currently|still|now|nowadays|at present|today|"
                     r"am building|am running|am leading|i run|i build|i lead|i work on)\b", re.I)
PROPER = re.compile(r"\b[A-Z][a-zA-Z]{2,}(?:\.org|\.com|\.net)?\b")

# Generic words (months, role words, common tech and frameworks) that are not
# treated as past-work proper nouns. No person-, employer- or country-specific
# entries belong here.
STOP = set("""Present Now Current Currently
Mar Oct Jan Feb Apr May Jun Jul Aug Sep Nov Dec
The And For With From This That These Those
Senior Principal Staff Founding Founder Head Lead Leader
Engineer Engineering Manager Management Company Division Team Group Department
Platform Software Systems System Technology Development Research Shared Director
Administrator Architecture Data Science Product
Azure AWS GCP Docker Linux Kafka Git Python Typescript JavaScript Java Rust SQL
Kubernetes Terraform Prometheus Grafana Postgres PostgreSQL MySQL MongoDB Redis
Claude GitHub Copilot LangChain MCP RAG LLM NLP BERT GAN GANs OWL LSID ISO GDPR
NIS2 DORA IAM IDAM SSO SAML SIEM API APIs REST GraphQL ScyllaDB Cassandra
React Svelte Node Helm ArgoCD Jenkins Ansible Bash SaaS
C# BSc MSc""".split())


def config_path(name, ext):
    """config/<name>.<ext> if present, else config/<name>.example.<ext>."""
    for fn in (f"{name}.{ext}", f"{name}.example.{ext}"):
        p = os.path.join(CONFIG_DIR, fn)
        if os.path.isfile(p):
            return p
    return ""


def load_cv():
    path = config_path("cv", "json")
    if not path:
        return {}
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _flatten(value):
    """Yield every string in a nested json structure."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for v in value.values():
            yield from _flatten(v)
    elif isinstance(value, (list, tuple)):
        for v in value:
            yield from _flatten(v)


def cv_corpus():
    """Lower-cased text of every string in the CV, for claim support checks."""
    return " ".join(_flatten(load_cv())).lower()


def _proper(text):
    return {w for w in PROPER.findall(text) if w not in STOP and len(w) >= 4}


def load():
    cv = load_cv()
    experiences = []
    past_bullets, current_bullets = [], []
    past_orgs, current_orgs = [], []

    for e in cv.get("experience", []) or []:
        if not isinstance(e, dict):
            continue
        org = str(e.get("employer") or e.get("org") or "")
        dates = str(e.get("dates", ""))
        current = "present" in dates.lower()
        experiences.append({"org": org, "dates": dates, "current": current,
                            "title": str(e.get("title", ""))})
        bullets = " ".join(str(b) for b in (e.get("bullets") or []))
        extras = e.get("extras") or {}
        if isinstance(extras, dict):
            bullets += " " + " ".join(str(v) for v in extras.values())
        (current_bullets if current else past_bullets).append(bullets)
        (current_orgs if current else past_orgs).append(org)

    past_bullets_text = " ".join(past_bullets)

    def base(ts):
        out = set()
        for t in ts:
            out.add(t)
            out.add(t.split(".")[0])
        return out

    past_org_terms = base(_proper(" ".join(o.split("|")[0] for o in past_orgs)))
    projects = cv.get("projects", []) or []
    # historical projects: named in the projects list AND referenced by a past employer
    hist_projects = {w for w in base(_proper(" ".join(str(p) for p in projects)))
                     if re.search(r"\b" + re.escape(w) + r"\b", past_bullets_text, re.I)}
    current_org_terms = base(_proper(" ".join(o.split("|")[0] for o in current_orgs)))
    past_terms = (past_org_terms | hist_projects) - current_org_terms
    current_terms = current_org_terms | base(_proper(" ".join(current_bullets)))

    corpus = (past_bullets_text + " " + " ".join(current_bullets) + " "
              + " ".join(str(p) for p in projects) + " "
              + " ".join(str(e.get("employer", "")) for e in cv.get("experience", []) or []
                         if isinstance(e, dict))).lower()
    facts = {
        "employers": experiences,
        "past_employers": [e["org"] for e in experiences if not e["current"]],
        "current_employers": [e["org"] for e in experiences if e["current"]],
        "certifications": cv.get("certifications", []) or [],
        "languages": cv.get("languages", []) or [],
        "past_terms": sorted(past_terms),
        "current_terms": sorted(current_terms),
    }
    return facts, corpus


def check_text(text, facts, corpus):
    errors, warnings = [], []
    for sent in re.split(r"(?<=[.!?;])\s+", text):
        if PRESENT.search(sent):
            hits = [t for t in facts.get("past_terms", [])
                    if re.search(r"(?<![A-Za-z])" + re.escape(t) + r"\b", sent)]
            if hits:
                errors.append(f"present-tense claim about past work ({', '.join(hits)}): "
                              f"\"{sent.strip()[:120]}\"")
    # organisations / multi-word proper nouns not present in the CV
    for phrase in set(re.findall(r"\b[A-Z][a-zA-Z]+(?:[ ][A-Z][a-zA-Z]+)+\b", text)):
        if phrase.lower() not in corpus and phrase not in STOP:
            first = phrase.split()[0]
            if first in ("I", "The", "My"):
                continue
            warnings.append(f"phrase not found in the CV (verify): \"{phrase}\"")
    return errors, warnings


def main():
    ap = argparse.ArgumentParser(description="CV-backed facts for free-text answers.")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--show", action="store_true")
    ap.add_argument("--check", metavar="FILE")
    ap.add_argument("--text", default="")
    args = ap.parse_args()
    facts, corpus = load()
    if args.json:
        print(json.dumps(facts, indent=2))
    elif args.show:
        print("current:", "; ".join(facts["current_employers"]))
        print("past:   ", "; ".join(facts["past_employers"]))
        print("certifications:", ", ".join(facts["certifications"]))
        print("languages:", ", ".join(facts["languages"]))
        print("past-only terms:", ", ".join(facts["past_terms"][:40]))
    elif args.check or args.text:
        text = open(args.check, encoding="utf-8").read() if args.check else args.text
        errors, warnings = check_text(text, facts, corpus)
        for w in warnings:
            print("WARN", w)
        for e in errors:
            print("FAIL", e)
        print("RESULT:", "FAIL" if errors else "PASS")
        sys.exit(1 if errors else 0)
    else:
        ap.print_help()


if __name__ == "__main__":
    main()
