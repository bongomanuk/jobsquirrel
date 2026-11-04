#!/usr/bin/env python3
"""Propose and apply grounded knowledge-graph additions.

The graph should already contain the obvious entities a CV implies. This tool
finds a small, conservative set of gaps that are grounded in existing evidence:

  * technologies/skills named in config/cv.json but absent from the graph;
  * certifications named in config/cv.json but absent;
  * a missing strong link from the candidate to a high-impact project/product/
    metric, when a source sentence names both;
  * a quantified metric in a high-impact description that has no METRIC node.

Nothing is invented: every proposal carries the exact evidence sentence and its
source. The operator reviews proposals in the dashboard and adds only the ones
they approve. Additions live in kb/graphrag/enrichment.json and are merged into
the graph views, the importance scores and the context builder without a
rebuild.

    .venv-graphrag/bin/python tools/graph_enrich.py propose --json
    .venv-graphrag/bin/python tools/graph_enrich.py apply --ids id1,id2
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "kb", "graphrag", "output")
OVERLAY = os.path.join(ROOT, "kb", "graphrag", "enrichment.json")
sys.path.insert(0, os.path.join(ROOT, "tools"))


def _load(name):
    import pandas as pd
    path = os.path.join(OUT, name + ".parquet")
    return pd.read_parquet(path) if os.path.exists(path) else None


def _norm(s):
    return re.sub(r"[^a-z0-9]+", " ", str(s or "").lower()).strip()


def _id(kind, key):
    return hashlib.sha1(f"{kind}|{key}".encode("utf-8")).hexdigest()[:12]


def load_overlay():
    try:
        with open(OVERLAY, encoding="utf-8") as fh:
            data = json.load(fh)
        return {"nodes": data.get("nodes") or [], "links": data.get("links") or []}
    except (OSError, ValueError):
        return {"nodes": [], "links": []}


def save_overlay(data):
    os.makedirs(os.path.dirname(OVERLAY), exist_ok=True)
    tmp = OVERLAY + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump({"updated": __import__("time").strftime("%Y-%m-%dT%H:%M:%S"),
                   "nodes": data.get("nodes") or [], "links": data.get("links") or []},
                  fh, indent=2)
    os.replace(tmp, OVERLAY)


def _sentences(text):
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n+", str(text or "")) if s.strip()]


def _article(term):
    """Return the CV line/paragraph that mentions a term."""
    for s in re.split(r"\n+|(?<=[.!?])\s+", term):
        if s.strip():
            return s.strip()[:500]
    return ""


def propose():
    import pandas as pd
    try:
        from ats_keywords import TECH_TERMS
    except Exception:
        TECH_TERMS = []
    ents = _load("entities")
    rels = _load("relationships")
    units = _load("text_units")
    docs = _load("documents")
    if ents is None or rels is None:
        return {"error": "no index"}
    try:
        import graph_importance as GI
        imp = GI.scores()
    except Exception:
        imp = {}
    overlay = load_overlay()
    existing = {_norm(t) for t in ents["title"]}
    existing |= {_norm(n.get("title")) for n in overlay["nodes"]}
    existing_tokens = [set(t.split()) for t in existing if t]
    existing_links = {(_norm(a), _norm(b)) for a, b in zip(rels["source"], rels["target"])}
    existing_links |= {(_norm(l.get("source")), _norm(l.get("target"))) for l in overlay["links"]}

    proposals = {}

    def add(p):
        if p["id"] in proposals:
            return
        proposals[p["id"]] = p

    # ---- 1. CV skills and technologies
    try:
        cv = json.load(open(os.path.join(ROOT, "config", "cv.json"), encoding="utf-8"))
    except (OSError, ValueError):
        cv = {}
    def strings(x):
        if isinstance(x, str):
            yield x
        elif isinstance(x, list):
            for y in x:
                yield from strings(y)
        elif isinstance(x, dict):
            for y in x.values():
                yield from strings(y)
    cv_text = " \n".join(strings(cv))
    for term in TECH_TERMS:
        if not re.search(r"(?<![A-Za-z0-9])" + re.escape(term) + r"(?![A-Za-z0-9])", cv_text, re.I):
            continue
        tt = set(_norm(term).split())
        if _norm(term) in existing or any(tt and tt <= s for s in existing_tokens):
            continue
        ev = _article(cv_text[cv_text.lower().find(term.lower()):]) if term.lower() in cv_text.lower() else cv_text[:300]
        add({"id": _id("node", term), "kind": "node", "title": term.upper(),
             "type": "TECHNOLOGY", "description": f"{term} is listed in the candidate's ground-truth CV.",
             "evidence": ev, "source": "config/cv.json", "related": "Peter Liam Hollas"})

    # ---- 2. certifications
    for line in (cv.get("certifications") or []):
        for part in re.split(r"[·;]", str(line)):
            name = part.strip()
            if len(name) < 3:
                continue
            short = re.sub(r"\s*\(.*?\)\s*", "", name).strip()
            if _norm(short) in existing or _norm(name) in existing:
                continue
            add({"id": _id("node", "cert:" + name), "kind": "node", "title": name.upper()[:120],
                 "type": "CERTIFICATION",
                 "description": f"{name} is listed in the candidate's certifications.",
                 "evidence": str(line)[:400], "source": "config/cv.json",
                 "related": "Peter Liam Hollas"})

    # ---- 3. strong missing links from the candidate to high-impact work
    person = None
    people = ents[ents["title"].astype(str).str.contains("HOLLAS", case=False, na=False)]
    if len(people):
        person = people.sort_values("degree", ascending=False).iloc[0]
    if person is not None:
        ptitle = str(person.title)
        unit_text = {}
        if units is not None:
            for u in units.itertuples():
                unit_text[str(u.id)] = str(u.text)
        doc_title = {}
        if docs is not None:
            doc_title = {str(i): str(t) for i, t in zip(docs["id"], docs["title"])}
        unit_doc = {}
        if units is not None:
            unit_doc = {str(i): str(d) for i, d in zip(units["id"], units["document_id"])}
        candidates = []
        for r in ents.itertuples():
            t = str(r.title)
            if t == ptitle:
                continue
            if str(r.type).upper() not in ("PROJECT", "PRODUCT", "METRIC", "ACHIEVEMENT", "TEAM"):
                continue
            if float(imp.get(t, 0)) < 0.90:
                continue
            if t.upper() in {"ASSIGNMENT", "COMPANY", "STATE", "CANDIDATE", "US", "EU"}:
                continue
            if (_norm(ptitle), _norm(t)) in existing_links or (_norm(t), _norm(ptitle)) in existing_links:
                continue
            candidates.append((float(imp.get(t, 0)), r))
        candidates.sort(reverse=True, key=lambda x: x[0])
        for score, r in candidates[:16]:
            t = str(r.title)
            evidence, source = "", ""
            sentences = _sentences(str(r.description or ""))
            for s in sentences:
                if re.search(r"\b(Peter|Hollas|candidate)\b", s, re.I) and t.lower() in s.lower():
                    evidence = s
                    break
            if not evidence and str(r.description or "") and t.lower() in str(r.description).lower():
                evidence = str(r.description)[:400]
            if not evidence:
                for uid in (r.text_unit_ids if r.text_unit_ids is not None else []):
                    text = unit_text.get(str(uid), "")
                    for s in _sentences(text):
                        if t.lower() in s.lower() and re.search(r"\b(Peter|Hollas|candidate)\b", s, re.I):
                            evidence = s
                            source = doc_title.get(unit_doc.get(str(uid), ""), "")
                            break
                    if evidence:
                        break
            if not evidence:
                continue
            add({"id": _id("link", ptitle + "->" + t), "kind": "link",
                 "source": ptitle, "target": t, "weight": max(20, round(score * 50)),
                 "title": f"{ptitle} → {t}", "type": "link",
                 "description": f"{ptitle} to {t}: {evidence[:300]}",
                 "evidence": evidence[:500], "source_doc": source,
                 "related": t, "target_type": str(r.type)})

    # ---- 4. obvious metrics not represented as METRIC nodes
    metric_titles = [_norm(t) for t in ents[ents["type"].astype(str).str.upper() == "METRIC"]["title"]]
    metric_digits = {re.sub(r"[^0-9]", "", t) for t in metric_titles}
    num_re = re.compile(r"(?<!\d)(\d[\d,\.]*\s*\+?\s*(?:pages|databases|clients|people|engineers|years|million|billion|%))", re.I)
    metric_seen = set()
    for r in ents.itertuples():
        if float(imp.get(str(r.title), 0)) < 0.90:
            continue
        for m in num_re.finditer(str(r.description or "")):
            val = re.sub(r"\s+", " ", m.group(1)).strip()
            key = re.sub(r"[^0-9a-z]+", "", val.lower())
            if not val or key in metric_seen:
                continue
            digits = re.sub(r"[^0-9]", "", val)
            if digits and digits in metric_digits:
                continue
            metric_seen.add(key)
            add({"id": _id("node", "metric:" + val), "kind": "node", "title": val.upper()[:100],
                 "type": "METRIC",
                 "description": f"Metric in the description of {r.title}: {val}",
                 "evidence": str(r.description or "")[:400], "source": "knowledge base",
                 "related": str(r.title)})

    out = sorted(proposals.values(), key=lambda p: (p["kind"] != "link", p.get("type", ""), p["title"]))
    return {"proposals": out, "overlay": {"nodes": len(overlay["nodes"]), "links": len(overlay["links"])}}


def apply(ids):
    data = propose()
    if data.get("error"):
        return data
    by_id = {p["id"]: p for p in data["proposals"]}
    overlay = load_overlay()
    have = {_norm(n.get("title")) for n in overlay["nodes"]}
    have_links = {(_norm(l.get("source")), _norm(l.get("target"))) for l in overlay["links"]}
    added = {"nodes": 0, "links": 0}
    for i in ids:
        p = by_id.get(i)
        if not p:
            continue
        if p["kind"] == "node":
            if _norm(p["title"]) in have:
                continue
            overlay["nodes"].append({"id": p["id"], "title": p["title"], "type": p["type"],
                                     "description": p["description"], "evidence": p["evidence"],
                                     "source": p["source"], "related": p.get("related", "")})
            have.add(_norm(p["title"]))
            added["nodes"] += 1
        else:
            key = (_norm(p["source"]), _norm(p["target"]))
            if key in have_links:
                continue
            overlay["links"].append({"id": p["id"], "source": p["source"], "target": p["target"],
                                     "weight": p["weight"], "description": p["description"],
                                     "evidence": p["evidence"], "source_doc": p.get("source_doc", "")})
            have_links.add(key)
            added["links"] += 1
    save_overlay(overlay)
    return {"ok": f"added {added['nodes']} node(s), {added['links']} link(s)",
            "added": added, "overlay": {"nodes": len(overlay["nodes"]), "links": len(overlay["links"])}}


def main():
    ap = argparse.ArgumentParser(description="Grounded graph enrichment")
    ap.add_argument("action", choices=["propose", "apply"])
    ap.add_argument("--ids", default="")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    if args.action == "apply":
        ids = [x.strip() for x in args.ids.split(",") if x.strip()]
        print(json.dumps(apply(ids), indent=2))
        return 0
    out = propose()
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
