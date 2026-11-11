#!/usr/bin/env python3
"""Read the GraphRAG index for the dashboard.

The knowledge graph lives in kb/graphrag/output/*.parquet (entities, relationships,
communities, community_reports, text_units, documents). This needs pandas+pyarrow,
which live in the GraphRAG venv (.venv-graphrag), so run it with that interpreter:

    .venv-graphrag/bin/python tools/graph_explore.py stats
    .venv-graphrag/bin/python tools/graph_explore.py entities [QUERY] [LIMIT]
    .venv-graphrag/bin/python tools/graph_explore.py relationships [QUERY] [LIMIT]
    .venv-graphrag/bin/python tools/graph_explore.py communities [QUERY] [LIMIT]
    .venv-graphrag/bin/python tools/graph_explore.py documents
    .venv-graphrag/bin/python tools/graph_explore.py resolve ENTITY_IDS --docs DOC_IDS

Every command prints one JSON object on stdout.
"""
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "kb", "graphrag", "output")
EMB_URL = os.environ.get("EMBEDDINGS_URL", "http://127.0.0.1:11435")
EMB_MODEL = os.environ.get("EMBED_MODEL", "nomic-embed-text")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ontology as ONT
import sensitive as SENS
try:
    import graph_importance as GIMP
except Exception:
    GIMP = None
_IMP = None


def _importance():
    global _IMP
    if _IMP is None:
        try:
            _IMP = GIMP.scores() if GIMP else {}
        except Exception:
            _IMP = {}
    return _IMP  # noqa: E402


def _load(name):
    import pandas as pd
    path = os.path.join(OUT, name + ".parquet")
    if not os.path.exists(path):
        return None
    return pd.read_parquet(path)


def _s(v, n):
    return "" if v is None else str(v)[:n]


SKILLS_FILE = os.path.join(ROOT, "kb", "sources", "personal", "skills_evidence.md")
ENRICH_FILE = os.path.join(ROOT, "kb", "graphrag", "enrichment.json")
EDITS_FILE = os.path.join(ROOT, "kb", "graphrag", "edits.json")


def _enrichment():
    """Operator-approved, grounded additions (kb/graphrag/enrichment.json)."""
    try:
        with open(ENRICH_FILE, encoding="utf-8") as fh:
            data = json.load(fh)
        return {"nodes": data.get("nodes") or [], "links": data.get("links") or []}
    except (OSError, ValueError):
        return {"nodes": [], "links": []}


def _edits():
    """Operator edits: field overrides for existing nodes."""
    try:
        with open(EDITS_FILE, encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _override(title):
    return (_edits().get("nodes") or {}).get(str(title), {})


def _skill_overlay():
    """Skill evidence added from the dashboard, shown live without a graph rebuild."""
    rows = []
    try:
        lines = open(SKILLS_FILE, encoding="utf-8", errors="ignore").read().splitlines()
    except OSError:
        return rows
    for line in lines:
        line = line.strip()
        m = re.match(r"^-\s+\*\*(.+?)\*\*\s*(?:—\s*(.*))?$", line)
        if not m:
            continue
        title = m.group(1).strip()[:140]
        detail = (m.group(2) or "").strip()[:700]
        if title:
            rows.append({"title": title, "description": detail or "operator-recorded skill evidence",
                         "type": "SKILL", "degree": 1, "frequency": 1})
    return rows


def _overlay_nodes(q="", limit=12):
    rows = _skill_overlay()
    if q:
        rows = [r for r in rows if q in (r["title"] + " " + r["description"]).lower()]
    return rows[:max(1, min(int(limit or 12), 40))]


def _norm(s):
    return re.sub(r"[^a-z0-9]+", " ", str(s or "").lower()).strip()


def _candidate_name():
    """Best available display name for the candidate, without hard-coding one."""
    try:
        with open(os.path.join(ROOT, "config", "cv.json"), encoding="utf-8") as fh:
            data = json.load(fh)
        name = str((data.get("name") or data.get("basics", {}).get("name") or "")).strip()
        if name:
            return name
    except (OSError, ValueError):
        pass
    return "Candidate"


def _add_skill_links(nodes, links, rows):
    if not rows:
        return
    titles = {_norm(n.get("title", "")) for n in nodes}
    # Attach operator-recorded skills to the person already in the graph. If
    # there is no person node, add one using the configured candidate name.
    person_node = max((n for n in nodes if str(n.get("type", "")).upper() == "PERSON"),
                      key=lambda n: int(n.get("degree") or 0), default=None)
    person = person_node["title"] if person_node else _candidate_name()
    if person.lower() not in titles:
        nodes.append({"id": person, "title": person, "type": "PERSON", "degree": len(rows),
                      "frequency": len(rows), "description": "Candidate"})
    for i, r in enumerate(rows):
        if _norm(r["title"]) in titles:
            continue
        nodes.append({"id": r["title"], "title": r["title"], "type": "SKILL",
                      "degree": 1, "frequency": 1, "description": r["description"]})
        links.append({"source": person, "target": r["title"], "weight": 1,
                      "description": r["description"][:400]})


def stats():
    out = {"index": os.path.exists(OUT)}
    for name in ("entities", "relationships", "communities", "community_reports", "documents", "text_units"):
        df = _load(name)
        out[name] = 0 if df is None else int(len(df))
    try:
        with open(os.path.join(OUT, "stats.json"), encoding="utf-8") as fh:
            out["runtime_s"] = round(json.load(fh).get("total_runtime", 0))
    except (OSError, ValueError):
        pass
    out["skills_overlay"] = len(_skill_overlay())
    ov = _enrichment()
    out["enrichment"] = {"nodes": len(ov["nodes"]), "links": len(ov["links"])}
    return out


def entities(q, limit):
    df = _load("entities")
    if df is None:
        return {"error": "no index"}
    if q:
        m = df["title"].str.lower().str.contains(q, regex=False) | \
            df["description"].str.lower().str.contains(q, regex=False) | \
            df["type"].str.lower().str.contains(q, regex=False)
        df = df[m]
    df = df.sort_values("degree", ascending=False).head(limit)
    rows = [{"id": int(r.human_readable_id), "title": _s(r.title, 120), "type": _s(r.type, 40),
             "degree": int(r.degree), "frequency": int(r.frequency),
             "description": _s(r.description, 500)} for r in df.itertuples()]
    seen = {_norm(r["title"]) for r in rows}
    for i, r in enumerate(_overlay_nodes(q, 20)):
        if _norm(r["title"]) not in seen:
            rows.append({"id": -1000 - i, **r, "description": r["description"][:500]})
    return {"rows": rows[:limit]}


def relationships(q, limit):
    df = _load("relationships")
    if df is None:
        return {"error": "no index"}
    if q:
        m = df["source"].str.lower().str.contains(q, regex=False) | \
            df["target"].str.lower().str.contains(q, regex=False) | \
            df["description"].str.lower().str.contains(q, regex=False)
        df = df[m]
    df = df.sort_values("weight", ascending=False).head(limit)
    rows = [{"source": _s(r.source, 90), "target": _s(r.target, 90), "weight": round(float(r.weight), 1),
             "description": _s(r.description, 400)} for r in df.itertuples()]
    for r in _overlay_nodes(q, 20):
        rows.append({"source": "Peter Hollas", "target": r["title"], "weight": 1,
                     "description": r["description"][:400]})
    return {"rows": rows[:limit]}


def communities(q, limit):
    df = _load("communities")
    rep = _load("community_reports")
    if df is None:
        return {"error": "no index"}
    summ = {}
    if rep is not None:
        summ = {int(r.community): _s(r.summary, 500) for r in rep.itertuples()}
    if q:
        df = df[df["title"].str.lower().str.contains(q, regex=False)]
    df = df.sort_values("level").head(limit)
    return {"rows": [{"community": int(r.community), "level": int(r.level), "title": _s(r.title, 120),
                      "size": int(r.size), "summary": summ.get(int(r.community), "")} for r in df.itertuples()]}


_DOC_MAP = None


def _doc_map():
    """entity uuid -> source document titles (from the text units)."""
    global _DOC_MAP
    if _DOC_MAP is not None:
        return _DOC_MAP
    tus, docs = _load("text_units"), _load("documents")
    out = {}
    if tus is not None and docs is not None:
        titles = {str(r.id): _s(r.title, 160) for r in docs.itertuples()}
        for r in tus.itertuples():
            title = titles.get(str(r.document_id))
            if not title:
                continue
            for eid in r.entity_ids:
                out.setdefault(str(eid), set()).add(title)
        out = {k: sorted(v)[:8] for k, v in out.items()}
    _DOC_MAP = out
    return out


def _clean_label(title, entity_titles=()):
    import re
    t = re.sub(r"\bPeter\s+(Liam\s+)?Hollas\b", " ", title or "", flags=re.I)
    t = re.sub(r"\b(community|and)\b", " ", t, flags=re.I)
    t = re.sub(r"[,;:]+", " ", t)
    t = re.sub(r"\s+", " ", t).strip(" -.")
    if len(t) < 4:
        t = " · ".join([x for x in entity_titles if x][:2]) or (title or "Community")
    return _s(t, 76)


def _community_meta(comms, ents, docs, row):
    uids = {str(x) for x in row.entity_ids}
    sub = ents[ents["id"].isin(uids)]
    if "degree" in sub.columns and len(sub):
        sub = sub.sort_values("degree", ascending=False)
    names = [str(t) for t in sub["title"].tolist() if "HOLLAS" not in str(t).upper()]
    sources = sorted({s for uid in uids for s in docs.get(uid, [])})[:10]
    return _clean_label(reports_title(int(row.community)), names[:3]), names[:3], sources


def _reports():
    rep = _load("community_reports")
    if rep is None:
        return {}
    out = {}
    for r in rep.itertuples():
        out[int(r.community)] = {"title": _s(SENS.redact(str(r.title or "")), 120), "summary": _s(SENS.redact(str(r.summary or "")), 700)}
    return out


def _breadcrumb(comms, community):
    by = {int(r.community): r for r in comms.itertuples()}
    out, seen, n = [], set(), int(community)
    while n in by and n not in seen:
        seen.add(n)
        r = by[n]
        out.append({"community": n, "title": _s(reports_title(n), 90)})
        n = int(r.parent)
    return list(reversed(out))


def reports_title(n):
    global _REPORTS
    if not _REPORTS:
        _REPORTS = _reports()
    return _REPORTS.get(int(n), {}).get("title") or f"Community {int(n)}"


_REPORTS = {}


def _deepest_community(comms, ents):
    """entity uuid -> the smallest/deepest community that contains it."""
    out = {}
    for r in comms.sort_values("level", ascending=False).itertuples():
        for uid in r.entity_ids:
            out.setdefault(str(uid), int(r.community))
    return out


def _community_at_level(comms, level):
    """entity uuid -> its community at one level of the hierarchy."""
    out = {}
    for r in comms[comms["level"] == level].itertuples():
        for uid in r.entity_ids:
            out.setdefault(str(uid), int(r.community))
    return out


def _entity_node(r, community=None, docs=None):
    ed = _override(r.title)
    gtype = ed.get("type") or r.type
    desc = ed.get("description") or r.description
    meta = ONT.class_meta(gtype)
    return {"id": _s(r.title, 140), "title": _s(r.title, 140), "kind": "entity",
            "type": _s(gtype, 40), "class": meta["id"], "class_label": meta["label"],
            "color": meta["color"],
            "degree": int(r.degree), "frequency": int(r.frequency),
            "importance": round(float(_importance().get(_s(r.title, 140), 0.0)), 3),
            "description": _s(SENS.redact(str(desc or "")), 700), "community": community,
            "sources": (docs or {}).get(str(r.id), [])[:6]}


def _overlay_entity_node(x, community=None):
    title = _s(x.get("title"), 140)
    meta = ONT.class_meta(x.get("type") or "CONCEPT")
    return {"id": title, "title": title, "kind": "entity",
            "type": _s(x.get("type") or "CONCEPT", 40), "class": meta["id"],
            "class_label": meta["label"], "color": meta["color"],
            "degree": 1, "frequency": 1,
            "importance": round(float(_importance().get(title, 0.0)), 3),
            "description": _s(x.get("description") or x.get("evidence"), 700),
            "community": community,
            "community_title": reports_title(community) if community is not None else "",
            "sources": [x.get("source") or x.get("source_doc")] if (x.get("source") or x.get("source_doc")) else [],
            "grounded": True, "evidence": _s(x.get("evidence"), 500)}


def overview(parent=None, limit=60):
    global _REPORTS
    comms, ents, rels = _load("communities"), _load("entities"), _load("relationships")
    if comms is None or ents is None or rels is None:
        return {"error": "no index"}
    _REPORTS = _reports()
    limit = max(8, min(int(limit or 60), 100))
    if parent is not None:
        row = comms[comms["community"] == int(parent)]
        if row.empty:
            return {"error": f"unknown community {parent}"}
        row = row.iloc[0]
        if len(row["children"]) == 0:
            return community_view(int(parent), limit)
        kids = comms[comms["community"].isin(row["children"])]
    else:
        kids = comms[comms["parent"] == -1]
    total = len(kids)
    kids = kids.sort_values("size", ascending=False).head(limit)
    selected = {int(r.community): r for r in kids.itertuples()}
    uuid_comm, title_comm = {}, {}
    for r in kids.itertuples():
        for uid in r.entity_ids:
            uuid_comm[str(uid)] = int(r.community)
    if uuid_comm:
        sub = ents[ents["id"].isin(uuid_comm.keys())]
        title_comm = {str(r.title): uuid_comm[str(r.id)] for r in sub.itertuples() if str(r.id) in uuid_comm}
    agg = {}
    for r in rels.itertuples():
        a = title_comm.get(str(r.source))
        b = title_comm.get(str(r.target))
        if a is None or b is None or a == b:
            continue
        key = (min(a, b), max(a, b))
        rec = agg.setdefault(key, {"weight": 0.0, "count": 0})
        rec["weight"] += float(r.weight)
        rec["count"] += 1
    links = [{"source": f"c:{a}", "target": f"c:{b}", "weight": round(v["weight"], 1),
              "count": v["count"]} for (a, b), v in
             sorted(agg.items(), key=lambda kv: kv[1]["weight"], reverse=True)[:limit * 3]]
    docs = _doc_map()
    nodes = []
    for n, r in selected.items():
        rep = _REPORTS.get(n, {})
        label, keywords, sources = _community_meta(comms, ents, docs, r)
        nodes.append({"id": f"c:{n}", "community": n, "kind": "community",
                      "title": rep.get("title") or f"Community {n}",
                      "label": label, "keywords": keywords, "sources": sources,
                      "level": int(r.level), "size": int(r.size),
                      "has_children": len(r.children) > 0,
                      "description": rep.get("summary", "")})
    nodes.sort(key=lambda x: -x["size"])
    return {"mode": "communities", "parent": parent, "level": int(kids.iloc[0].level) if len(kids) else None,
            "breadcrumb": _breadcrumb(comms, parent) if parent is not None else [],
            "nodes": nodes, "links": links, "total": total}


def _connected_subgraph(sub_all, rel_all, limit):
    """The largest connected component, then a BFS subset up to `limit`.

    A top-degree cut can include entities whose only neighbours fell outside the
    cut; this keeps the picture honest and avoids floating, disconnected nodes.
    """
    if sub_all.empty:
        return sub_all, rel_all.iloc[0:0], 0
    titles = set(str(t) for t in sub_all["title"])
    adj = {}
    for r in rel_all.itertuples():
        a, b = str(r.source), str(r.target)
        if a in titles and b in titles:
            adj.setdefault(a, set()).add(b)
            adj.setdefault(b, set()).add(a)
    if not adj:
        return sub_all.head(limit), rel_all, 0
    seen, comps = set(), []
    for t in sub_all.sort_values("degree", ascending=False)["title"]:
        t = str(t)
        if t in seen:
            continue
        stack, comp = [t], []
        seen.add(t)
        while stack:
            x = stack.pop()
            comp.append(x)
            for y in adj.get(x, ()):
                if y not in seen:
                    seen.add(y)
                    stack.append(y)
        comps.append(comp)
    comps.sort(key=len, reverse=True)
    best = set(comps[0])
    start = next(str(t) for t in sub_all.sort_values("degree", ascending=False)["title"]
                 if str(t) in best)
    order, queue, seen2 = [], [start], set()
    while queue and len(order) < limit:
        x = queue.pop(0)
        if x in seen2:
            continue
        seen2.add(x)
        order.append(x)
        nxt = sorted((y for y in adj.get(x, ()) if y in best and y not in seen2),
                     key=lambda y: -len(adj.get(y, ())))
        queue.extend(nxt)
    nodes = sub_all[sub_all["title"].isin(order)]
    links = rel_all[rel_all["source"].isin(order) & rel_all["target"].isin(order)]
    return nodes, links, len(best)


def community_view(community, limit=90):
    global _REPORTS
    comms, ents, rels = _load("communities"), _load("entities"), _load("relationships")
    if comms is None or ents is None or rels is None:
        return {"error": "no index"}
    _REPORTS = _reports()
    row = comms[comms["community"] == int(community)]
    if row.empty:
        return {"error": f"unknown community {community}"}
    row = row.iloc[0]
    if len(row["children"]) > 0:
        return overview(int(community), limit)
    limit = max(10, min(int(limit or 90), 160))
    uuids = {str(x) for x in row.entity_ids}
    sub_all = ents[ents["id"].isin(uuids)]
    titles_all = set(str(t) for t in sub_all["title"])
    rel_all = rels[rels["source"].isin(titles_all) & rels["target"].isin(titles_all)]
    sub, rel, connected = _connected_subgraph(sub_all, rel_all, limit)
    rel = rel.sort_values("weight", ascending=False).head(limit * 2)
    docs = _doc_map()
    nodes = [_entity_node(r, int(community), docs) for r in sub.itertuples()]
    links = [{"source": _s(r.source, 140), "target": _s(r.target, 140),
              "weight": round(float(r.weight), 1)} for r in rel.itertuples()]
    return {"mode": "entities", "community": int(community), "level": int(row.level),
            "breadcrumb": _breadcrumb(comms, int(community)),
            "nodes": nodes, "links": links, "total": len(uuids),
            "connected": connected, "shown": len(nodes)}


def types_overview(limit=24):
    ents, rels = _load("entities"), _load("relationships")
    if ents is None or rels is None:
        return {"error": "no index"}
    limit = max(6, min(int(limit or 24), 40))
    classes = ents["type"].map(ONT.class_for)
    counts = classes.value_counts()
    total = len(counts)
    counts = counts.head(limit)
    selected = {str(t) for t in counts.index}
    type_by_title = {}
    for r in ents.itertuples():
        c = ONT.class_for(r.type)
        if c in selected:
            type_by_title[str(r.title)] = c
    agg = {}
    for r in rels.itertuples():
        a, b = type_by_title.get(str(r.source)), type_by_title.get(str(r.target))
        if not a or not b or a == b:
            continue
        key = (min(a, b), max(a, b))
        rec = agg.setdefault(key, {"weight": 0.0, "count": 0})
        rec["weight"] += float(r.weight)
        rec["count"] += 1
    links = [{"source": f"t:{a}", "target": f"t:{b}", "weight": round(v["weight"], 1),
              "count": v["count"]} for (a, b), v in
             sorted(agg.items(), key=lambda kv: kv[1]["weight"], reverse=True)[:limit * 3]]
    nodes = []
    for t, n in counts.items():
        meta = ONT.class_meta(t)
        nodes.append({"id": f"t:{t}", "kind": "type", "type": str(t),
                      "label": meta["label"], "title": meta["label"], "size": int(n),
                      "color": meta["color"],
                      "description": meta["description"] or f"{int(n)} entities of type {meta['label']}."})
    return {"mode": "types", "nodes": nodes, "links": links, "total": total}


def type_entities(type_name, limit=90):
    ents, rels = _load("entities"), _load("relationships")
    if ents is None or rels is None:
        return {"error": "no index"}
    t = ONT.class_for(type_name)
    sub_all = ents[ents["type"].map(ONT.class_for) == t]
    if sub_all.empty:
        return {"error": f"no entities of type {type_name}"}
    limit = max(10, min(int(limit or 90), 160))
    comms = _load("communities")
    comm_of = _community_at_level(comms, 0) if comms is not None else {}
    titles_all = set(str(x) for x in sub_all["title"])
    rel_all = rels[rels["source"].isin(titles_all) & rels["target"].isin(titles_all)]
    imp = _importance()
    ordered = sub_all.assign(_imp=[imp.get(str(t), 0.0) for t in sub_all["title"]])
    ordered = ordered.sort_values(["_imp", "degree", "frequency"], ascending=False)
    if len(ordered) > limit:
        # do not hand the whole topic to whichever employer has the largest
        # connected blob: take the strongest entities with a per-theme cap
        cap = max(5, limit // 8)
        picked, per = [], {}
        for r in ordered.itertuples():
            c = comm_of.get(str(r.id))
            if c is not None and per.get(c, 0) >= cap:
                continue
            picked.append(str(r.title))
            if c is not None:
                per[c] = per.get(c, 0) + 1
            if len(picked) >= limit:
                break
        sub = ordered[ordered["title"].astype(str).isin(set(picked))]
    else:
        sub = ordered
    titles = set(str(x) for x in sub["title"])
    rel = rel_all[rel_all["source"].isin(titles) & rel_all["target"].isin(titles)]
    rel = rel.sort_values("weight", ascending=False).head(limit * 2)
    docs = _doc_map()
    nodes = []
    for r in sub.itertuples():
        n = _entity_node(r, comm_of.get(str(r.id)), docs)
        n["community_title"] = reports_title(n.get("community")) if n.get("community") is not None else ""
        nodes.append(n)
    links = [{"source": _s(r.source, 140), "target": _s(r.target, 140),
              "weight": round(float(r.weight), 1)} for r in rel.itertuples()]
    ov = _enrichment()
    if ov["nodes"]:
        seen = {n["title"] for n in nodes}
        for x in ov["nodes"]:
            if ONT.class_for(x.get("type") or "CONCEPT") != t:
                continue
            title = _s(x.get("title"), 140)
            if not title or title in seen:
                continue
            meta_x = ONT.class_meta(x.get("type") or t)
            nodes.append({"id": title, "title": title, "type": _s(x.get("type") or t, 40),
                          "class": meta_x["id"], "class_label": meta_x["label"],
                          "color": meta_x["color"], "degree": 1, "frequency": 1,
                          "importance": round(float(_importance().get(title, 0.0)), 3),
                          "description": _s(x.get("description") or x.get("evidence"), 700),
                          "community": None, "community_title": "",
                          "grounded": True, "evidence": _s(x.get("evidence"), 500),
                          "source": _s(x.get("source") or x.get("source_doc"), 200)})
            seen.add(title)
        have = {(_norm(l.get("source")), _norm(l.get("target"))) for l in links}
        for x in ov["links"]:
            a, b = _s(x.get("source"), 140), _s(x.get("target"), 140)
            if a in seen and b in seen and (_norm(a), _norm(b)) not in have:
                links.append({"source": a, "target": b, "weight": round(float(x.get("weight") or 1), 1),
                              "description": _s(x.get("description"), 400), "grounded": True})
                have.add((_norm(a), _norm(b)))
    meta = ONT.class_meta(t)
    return {"mode": "entities", "type": t, "label": meta["label"], "color": meta["color"],
            "nodes": nodes, "links": links, "total": len(sub_all),
            "shown": len(nodes)}


def ontology_view():
    ents = _load("entities")
    out = ONT.summary(ents)
    out["mode"] = "ontology"
    return out


def _embed(text):
    import json as _json
    import urllib.request
    body = _json.dumps({"model": EMB_MODEL, "input": [str(text)[:4000]]}).encode()
    req = urllib.request.Request(EMB_URL.rstrip("/") + "/v1/embeddings", data=body,
                                 headers={"Content-Type": "application/json",
                                          "Authorization": "Bearer vulkan"})
    with urllib.request.urlopen(req, timeout=30) as r:
        data = _json.loads(r.read().decode())
    return data["data"][0]["embedding"]


def _job_meta(key):
    """Company/role for a saved job key, from the queue or the register."""
    import csv
    key = str(key or "").strip()
    if not key:
        return {}, ""
    for name in ("queue.tsv", "queue.done"):
        path = os.path.join(ROOT, "state", name)
        try:
            for line in open(path, encoding="utf-8", errors="ignore"):
                if not line.strip() or line.startswith("#"):
                    continue
                f = (line.rstrip("\n").split("\t") + [""] * 6)[:6]
                if len(f) >= 6 and f[5].strip() == key:
                    return {"company": f[0].strip(), "role": f[1].strip()}, key
        except OSError:
            pass
    try:
        with open(os.path.join(ROOT, "state", "applications.csv"), encoding="utf-8",
                  errors="ignore") as fh:
            for row in csv.DictReader(fh):
                if (row.get("key") or "").strip() == key:
                    return {"company": (row.get("company") or "").strip(),
                            "role": (row.get("role") or "").strip()}, key
    except OSError:
        pass
    return {}, key


def _keywords_for(jd, ats_path=""):
    """Requirements from the saved ATS file, else frequent terms + tech names."""
    keywords = []
    if ats_path:
        try:
            for line in open(ats_path, encoding="utf-8", errors="ignore"):
                line = line.strip()
                if line and not line.startswith("#") and len(line) > 1:
                    keywords.append(line)
        except OSError:
            pass
    if not keywords:
        import re as _re
        from collections import Counter
        stop = set("the and for with you your are our will have has this that from they their "
                   "role job work experience team teams including etc able strong good years "
                   "across within using about who what when where which while would could should "
                   "into more than other such only also been being were was are is it its".split())
        words = [w for w in _re.findall(r"[a-z][a-z0-9+#.-]{2,}", str(jd).lower())
                 if w not in stop]
        keywords = [w for w, _n in Counter(words).most_common(28)]
        try:
            from ats_keywords import TECH_TERMS
            low = str(jd).lower()
            seen = {k.lower() for k in keywords}
            for term in TECH_TERMS:
                t = str(term).strip()
                if len(t) > 1 and t.lower() in low and t.lower() not in seen:
                    keywords.append(t)
                    seen.add(t.lower())
        except Exception:
            pass
    out, seen = [], set()
    for k in keywords:
        k = str(k).strip().strip(" .,;:()[]")
        if k and k.lower() not in seen:
            out.append(k[:60])
            seen.add(k.lower())
    return out[:40]


def _cv_data():
    try:
        with open(os.path.join(ROOT, "config", "cv.json"), encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _identity():
    out = {}
    try:
        for line in open(os.path.join(ROOT, "config", "profile.md"),
                         encoding="utf-8", errors="ignore"):
            m = re.match(r"^\s*-\s*([^:]+):\s*(.+?)\s*$", line)
            if m:
                out[m.group(1).strip().lower()] = m.group(2).strip()
    except OSError:
        pass
    return out


def _nice_skill(s):
    special = {
        "JAVASCRIPT": "JavaScript", "TYPESCRIPT": "TypeScript", "KUBERNETES": "Kubernetes",
        "TERRAFORM": "Terraform", "PYTHON": "Python", "JAVA": "Java", "RUST": "Rust",
        "POSTGRES": "PostgreSQL", "REACT": "React", "SPRING": "Spring",
        "KEYCLOAK": "Keycloak", "SCYLLADB": "ScyllaDB", "PROMETHEUS": "Prometheus",
        "KAFKA": "Kafka", "DOCKER": "Docker", "LINUX": "Linux", "GRAPHQL": "GraphQL",
        "REDIS": "Redis", "MICROSERVICES": "Microservices", "NODE.JS": "Node.js",
        "AWS": "AWS", "GCP": "GCP", "JVM": "JVM", "SQL": "SQL", "API": "API",
        "RAG": "RAG", "MCP": "MCP", "CI/CD": "CI/CD", "LLM": "LLM", "NLP": "NLP",
        "ETL": "ETL", "IAM": "IAM", "OIDC": "OIDC", "SAML": "SAML", "SSO": "SSO",
        "SAAS": "SaaS",
    }
    words = []
    for w in str(s or "").split():
        key = w.upper()
        if key in special:
            words.append(special[key])
        elif w.isupper() and len(w) <= 4:
            words.append(w)
        elif w.isupper():
            words.append(w[:1].upper() + w[1:].lower())
        else:
            words.append(w)
    return " ".join(words)


def _verb_bullet(bullets):
    verbs = {"created", "delivered", "led", "built", "designed", "developed",
             "implemented", "managed", "scaled", "owned", "reduced", "improved",
             "established", "worked", "ran", "drove", "launched", "shipped"}
    for b in bullets or []:
        first = re.split(r"\s+", str(b).strip(), 1)[0].strip(".,;:").lower()
        if first in verbs:
            return str(b).strip()
    return ""


def playground(key="", text="", hops=2, kind="cv"):
    """A deterministic, animated evidence build from a job spec.

    The UI 'plays' the returned steps: each one names the entity and connection
    the recursive query just used, and the document bullets become visible as
    their supporting step arrives.
    """
    key = str(key or "").strip()
    jd = str(text or "")
    if not jd and key:
        try:
            jd = open(os.path.join(ROOT, "state", "job-descriptions", key + ".md"),
                      encoding="utf-8", errors="ignore").read()
        except OSError:
            return {"error": f"no saved job description for {key}"}
    jd = jd.strip()
    if not jd:
        return {"error": "paste a job spec or choose a saved one"}
    ats_path = os.path.join(ROOT, "state", "ats", key + ".txt") if key else ""
    keywords = _keywords_for(jd, ats_path)
    meta, _ = _job_meta(key)
    if not meta.get("role"):
        # a heading or the first non-empty line is a decent demo title
        for line in jd.splitlines():
            s = line.strip().lstrip("#").strip()
            if not s or s.lower().startswith(("http", "company:", "role:", "location:", "about", "apply")):
                continue
            first = re.split(r"(?<=[.!?])\s+", s)[0].strip().rstrip(".")
            if 3 <= len(first) <= 120:
                meta["role"] = first
            break
    company, role = meta.get("company", ""), meta.get("role", "")
    ents, rels = _load("entities"), _load("relationships")
    if ents is None or rels is None:
        return {"error": "no index"}
    imp = _importance()
    by_title = {str(r.title): r for r in ents.itertuples()}

    def _rel(t):
        r = by_title.get(t)
        text = (str(t) + " " + str(getattr(r, "description", "") or "")).lower()
        hits = sum(1 for kw in keywords
                   if re.search(r"\b" + re.escape(kw) + r"\b", text, re.I))
        typ = str(getattr(r, "type", "") or "").upper()
        bonus = {"METRIC": 3, "SKILL": 2, "TECHNOLOGY": 2, "PROJECT": 2,
                 "CERTIFICATION": 2, "ROLE": 1}.get(typ, 0)
        return hits, bonus

    def _hits_text(text):
        s = str(text or "").lower()
        return sum(1 for kw in keywords
                   if re.search(r"\b" + re.escape(kw) + r"\b", s, re.I))

    def _rel_title(t):
        s = str(t or "").lower()
        return sum(1 for kw in keywords if kw.lower() in s)

    # keyword -> matching entities
    matched, seed_score = {}, {}
    for kw in keywords:
        pat = r"\b" + re.escape(kw) + r"\b"
        m = (ents["title"].str.contains(pat, case=False, regex=True) |
             ents["description"].str.contains(pat, case=False, regex=True))
        rows = ents[m].copy()
        titles = []
        for r in rows.itertuples():
            t = str(r.title)
            titles.append(t)
            seed_score[t] = seed_score.get(t, 0) + 1
        matched[kw] = titles[:6]
    seeds = sorted(seed_score, key=lambda t: (-seed_score[t], -float(imp.get(t, 0)),
                                              -int(by_title[t].degree if t in by_title else 0)))[:8]
    if not seeds:
        seeds = [str(r.title) for r in ents.assign(_i=[float(imp.get(str(t), 0))
                                                       for t in ents["title"]])
                 .sort_values(["_i", "degree"], ascending=False).head(6).itertuples()]

    # adjacency, strongest first
    adj = {}
    link_desc = {}
    for r in rels.itertuples():
        s, t = str(r.source), str(r.target)
        w = float(r.weight)
        d = _s(SENS.redact(str(r.description or "")), 400)
        adj.setdefault(s, []).append((w, t, d))
        adj.setdefault(t, []).append((w, s, d))
        link_desc[(s, t)] = d
    for s in adj:
        adj[s].sort(key=lambda x: (-_rel(x[1])[0], -_rel(x[1])[1], -x[0]))

    steps = []
    sentences = []
    visited = set(seeds)
    used_links = set()
    cap_titles = []
    cap_links = []
    parent_of = {t: "" for t in seeds}

    def trace_to(parent, child, desc):
        """The recursive path that reached this fact."""
        chain, x, seen = [], parent, set()
        while x and x not in seeds and x not in seen:
            seen.add(x)
            p = parent_of.get(x)
            if not p:
                break
            d = link_desc.get((p, x)) or link_desc.get((x, p)) or ""
            chain.append({"from": p, "to": x, "desc": d})
            x = p
        chain.reverse()
        chain.append({"from": parent, "to": child, "desc": desc or ""})
        return chain

    def add_sentence(text, cites, section="Selected experience",
                     group="Selected experience", trace=None):
        text = " ".join(str(text or "").split())
        text = re.sub(r"\b[Tt]he author\b", display_name, text)
        if len(text) < 24:
            return
        if not text.endswith((".", "!", "?")):
            text += "."
        text = text[:520]
        if any(s["text"] == text for s in sentences):
            return
        sentences.append({"text": text, "cites": [c for c in cites if c],
                          "step": 0, "section": section, "group": group,
                          "trace": trace or []})

    def org_of(*titles):
        for t in titles:
            r = by_title.get(t)
            if r is not None and str(getattr(r, "type", "")).upper() == "ORGANIZATION":
                return str(t)
        return ""

    covered = [k for k in keywords if matched.get(k)]
    gaps = [k for k in keywords if not matched.get(k)]
    top_seed = seeds[0] if seeds else ""
    person = next((t for t in by_title if "HOLLAS" in str(t).upper()
                   and str(getattr(by_title[t], "type", "")).upper() == "PERSON"), "")
    if not person:
        person = next((t for t in by_title
                       if str(getattr(by_title[t], "type", "")).upper() == "PERSON"), "")
    display_name = person.title() if person and person.isupper() else (person or "The candidate")
    skills = []
    for t in seeds:
        typ = str(getattr(by_title.get(t), "type", "") or "").upper()
        if typ in ("SKILL", "TECHNOLOGY", "CERTIFICATION", "PROJECT") and t not in skills:
            skills.append(str(t))
    target = role or "this role"
    if company:
        target = f"{target} at {company}" if role else company

    hop, frontier = 0, list(seeds)
    max_hops = 45
    exp_count = 0
    hop_log = []
    for depth in range(1, max(1, min(int(hops or 2), 3)) + 1):
        nxt = []
        found, edges_h = [], []
        for parent in frontier:
            if hop >= max_hops:
                break
            used = 0
            for w, child, desc in adj.get(parent, []):
                if child in visited or child not in by_title:
                    continue
                visited.add(child)
                used_links.add((parent, child))
                parent_of[child] = parent
                hop += 1
                found.append(str(child))
                edges_h.append((str(parent), str(child), desc or ""))
                r = by_title.get(child)
                typ = str(getattr(r, "type", "") or "").upper() if r is not None else ""
                pt = str(getattr(by_title.get(parent), "type", "") or "").upper()
                if pt == "ORGANIZATION" and desc and exp_count < 7:
                    add_sentence(desc, [parent, child], "Selected experience",
                                 str(parent), trace_to(parent, child, desc))
                    exp_count += 1
                if typ in ("SKILL", "TECHNOLOGY", "CERTIFICATION", "PROJECT"):
                    if _rel_title(child) > 0 and str(child) not in cap_titles:
                        cap_titles.append(str(child))
                        cap_links.append({"from": parent, "to": child, "desc": desc or ""})
                elif desc and exp_count < 7:
                    if _hits_text(desc) > 0 or _rel_title(child) > 0:
                        org = org_of(child, parent)
                        add_sentence(desc, [parent, child], "Selected experience",
                                     org or "Selected experience",
                                     trace_to(parent, child, desc))
                        exp_count += 1
                nxt.append(child)
                used += 1
                if used >= 2:
                    break
            if hop >= max_hops:
                break
        hop_log.append({"depth": depth, "found": found, "edges": edges_h,
                        "frontier": len(frontier),
                        "frontier_nodes": [str(x) for x in frontier]})
        frontier = nxt
        if not frontier:
            break

    orgs = []
    for t in sorted(visited, key=lambda t: -float(imp.get(t, 0))):
        if str(getattr(by_title.get(t), "type", "") or "").upper() == "ORGANIZATION" and str(t) not in orgs:
            orgs.append(str(t))
    doc_orgs = []
    for s in sentences:
        g = s.get("group") or ""
        if s["section"] == "Selected experience" and g and g != "Selected experience" and g not in doc_orgs:
            doc_orgs.append(g)
    if doc_orgs:
        orgs = doc_orgs
    profile_skills = skills[:6] or cap_titles[:6]
    if orgs:
        add_sentence(f"{display_name} is a senior engineering leader with experience at "
                     + ", ".join(orgs[:3]) + ".",
                     [person] + orgs[:3], "Profile", "")
    else:
        add_sentence(f"{display_name} is a senior engineering leader with a connected record "
                     f"across engineering organisations.", [person], "Profile", "")
    add_sentence(f"Targeting {target}, with evidence in "
                 + (", ".join(profile_skills) if profile_skills else "the connected record") + ".",
                 seeds, "Profile", "")

    if not any(s["section"] == "Selected experience" for s in sentences):
        for t in seeds:
            if str(getattr(by_title.get(t), "type", "") or "").upper() != "ORGANIZATION":
                continue
            for w, child, desc in adj.get(t, []):
                if desc:
                    add_sentence(desc, [t, child], "Selected experience", str(t),
                                 trace_to(t, child, desc))
                    break
            if any(s["section"] == "Selected experience" for s in sentences):
                break

    if cap_titles:
        add_sentence("Relevant capabilities: " + ", ".join(cap_titles[:10]) + ".",
                     cap_titles[:10], "Relevant capabilities", "", cap_links[:10])

    prof = [s for s in sentences if s["section"] == "Profile"]
    exp = [s for s in sentences if s["section"] == "Selected experience"]
    caps = [s for s in sentences if s["section"] == "Relevant capabilities"]
    ordered = prof + exp + caps
    steps = [{"n": 0, "kind": "read", "query": "Read the job spec",
              "label": "Read the job spec", "write": "",
              "nodes": [], "links": [], "trace": []}]
    profile_i = 0
    for i, s in enumerate(ordered, 1):
        s["step"] = i
        if s["section"] == "Profile":
            profile_i += 1
            q = ("Who is the candidate?" if profile_i == 1
                 else "What is the target role and which evidence matches?")
        elif s["section"] == "Relevant capabilities":
            q = "Which capabilities match the requirements?"
        else:
            tr = s.get("trace") or []
            q = (f"Trace {tr[0]['from']} → {tr[-1]['to']}" if tr
                 else f"What evidence supports {s.get('group') or 'the role'}?")
        steps.append({"n": i, "kind": "write", "query": q, "label": s["section"],
                      "write": s["text"], "nodes": s["cites"],
                      "links": [{"from": t["from"], "to": t["to"]} for t in (s.get("trace") or [])],
                      "trace": s.get("trace") or [], "section": s["section"]})

    used_titles = sorted(visited)
    nodes = []
    for t in used_titles:
        r = by_title.get(t)
        if r is None:
            continue
        nodes.append({"id": _s(t, 140), "title": _s(t, 140), "type": _s(r.type, 40),
                      "degree": int(r.degree), "frequency": int(r.frequency),
                      "importance": round(float(imp.get(t, 0)), 3),
                      "description": _s(SENS.redact(str(r.description or "")), 400)})
    node_ids = {n["id"] for n in nodes}
    links = []
    for (s, t) in used_links:
        if s in node_ids and t in node_ids:
            links.append({"source": s, "target": t,
                          "weight": 30, "description": link_desc.get((s, t), "")})
    # keep the seed-to-seed structure if it exists, without exploding the payload
    for r in rels.itertuples():
        s, t = str(r.source), str(r.target)
        if s in node_ids and t in node_ids and (s, t) not in used_links and len(links) < 60:
            links.append({"source": s, "target": t, "weight": round(float(r.weight), 1),
                          "description": link_desc.get((s, t), "")})

    def _build_cv(kind):
        cv = _cv_data()
        ident = _identity()
        name_ = cv.get("name") or ident.get("full name") or display_name
        contact = [ident.get(k) for k in ("email", "phone", "location (city, country)",
                                          "linkedin", "github / portfolio / website")
                   if ident.get(k)]

        # Employers named in the CV become visible hubs even when the expansion
        # never reached them, so a role step can light up the organisation itself.
        for e in (cv.get("experience") or []):
            if not isinstance(e, dict):
                continue
            emp = str(e.get("employer") or "")
            key = emp
            r = by_title.get(key)
            if r is None and emp:
                head = re.split(r"[,(&/–—-]", emp)[0].strip().lower()
                cands = [(len(str(t)), str(t)) for t in by_title
                         if str(t).lower() == head or str(t).lower().startswith(head)]
                if not cands and " " in head:
                    word = head.split()[0]
                    cands = [(len(str(t)), str(t)) for t in by_title
                             if str(t).lower() == word or str(t).lower().startswith(word + " ")]
                if cands:
                    key = min(cands)[1]
                    r = by_title[key]
            if not key or key in node_ids or r is None:
                continue
            nodes.append({"id": _s(key, 140), "title": _s(key, 140), "type": _s(r.type, 40),
                          "degree": int(r.degree), "frequency": int(r.frequency),
                          "importance": round(float(imp.get(key, 0)), 3),
                          "description": _s(SENS.redact(str(r.description or "")), 400)})
            node_ids.add(key)

        def hits(text):
            low = str(text or "").lower()
            return sum(1 for kw in keywords
                       if re.search(r"\b" + re.escape(kw) + r"\b", low, re.I))

        def terms_of(text):
            low = str(text or "").lower()
            return [kw for kw in keywords
                    if re.search(r"\b" + re.escape(kw) + r"\b", low, re.I)][:10]

        # ---- traversal trace: the actual path the recursive query walked on
        # the graph returned to the UI, so the demo can animate it hop by hop.
        id_adj = {}
        for l in links:
            a, b = l["source"], l["target"]
            id_adj.setdefault(a, []).append(b)
            id_adj.setdefault(b, []).append(a)

        def as_id(t):
            s = str(t or "").strip()[:140]
            if not s:
                return ""
            if s in node_ids:
                return s
            low = s.lower()
            best = ""
            for n in nodes:
                tl = n["title"].lower()
                if tl == low or tl.startswith(low) or low.startswith(tl):
                    if not best or len(n["title"]) < len(best):
                        best = n["id"]
            if best:
                return best
            for tok in re.split(r"[,()&/–—-]", s):
                tok = tok.strip().lower()
                if len(tok) < 4:
                    continue
                hit = [n["id"] for n in nodes if n["title"].lower() == tok]
                if len(hit) == 1:
                    return hit[0]
            for word in re.split(r"[^a-z0-9]+", low):
                if len(word) < 4:
                    continue
                hit = [n["id"] for n in nodes if n["title"].lower() == word]
                if len(hit) == 1:
                    return hit[0]
            return ""

        def _path(src_id, dst_id, max_len=4):
            if not src_id or not dst_id or src_id == dst_id:
                return []
            prev = {src_id: None}
            q = [src_id]
            while q:
                x = q.pop(0)
                if x == dst_id:
                    break
                for y in id_adj.get(x, []):
                    if y not in prev:
                        prev[y] = x
                        q.append(y)
            if dst_id not in prev:
                return []
            chain, x = [], dst_id
            while x != src_id and len(chain) < max_len:
                p = prev[x]
                if p is None:
                    break
                d = link_desc.get((p, x)) or link_desc.get((x, p)) or ""
                chain.append({"from": p, "to": x, "desc": d})
                x = p
            chain.reverse()
            return chain

        root_id = as_id(person) or as_id(top_seed) or (nodes[0]["id"] if nodes else "")
        edge_pairs = set()
        for l in links:
            edge_pairs.add((l["source"], l["target"]))
            edge_pairs.add((l["target"], l["source"]))

        def trace_for(targets, roots=None, limit=4):
            """The most direct evidence path, not a random tour of the graph."""
            rids = [as_id(r) for r in (roots or [root_id])]
            rids = [r for r in rids if r]
            out, seen = [], set()
            tids = [t for t in (as_id(x) for x in (targets or [])) if t]
            # prefer a direct edge from the role/person the sentence is about
            for tid in tids:
                for rid in rids:
                    if rid == tid or (rid, tid) not in edge_pairs:
                        continue
                    key = (rid, tid)
                    if key in seen:
                        continue
                    seen.add(key)
                    desc = link_desc.get((rid, tid)) or link_desc.get((tid, rid)) or ""
                    out.append({"from": rid, "to": tid, "desc": desc})
                if len(out) >= limit:
                    break
            if out:
                return out[:limit]
            for tid in tids:
                for rid in rids:
                    hop = _path(rid, tid)
                    if hop:
                        pair = (hop[0]["from"], hop[-1]["to"])
                        if pair not in seen:
                            seen.add(pair)
                            out.extend(hop)
                        break
                if len(out) >= limit:
                    break
            return out[:limit]

        def cites(text, n=4, types=None):
            low = str(text or "").lower()
            out = []
            for t, r in by_title.items():
                if len(str(t)) < 4:
                    continue
                if not re.search(r"\b" + re.escape(str(t).lower()) + r"\b", low):
                    continue
                typ = str(getattr(r, "type", "")).upper()
                if types:
                    if typ not in types:
                        continue
                elif typ not in ("SKILL", "TECHNOLOGY", "PROJECT", "ORGANIZATION",
                                 "CERTIFICATION", "METRIC", "PLATFORM", "ROLE"):
                    continue
                out.append(str(t))
            return list(dict.fromkeys(out))[:n]

        skill_titles = []
        for t in (cap_titles + skills + [t for t in visited
                  if str(getattr(by_title.get(t), "type", "") or "").upper()
                  in ("SKILL", "TECHNOLOGY", "CERTIFICATION", "PLATFORM")]):
            t = str(t)
            if (not t or t in skill_titles or len(t) > 40 or "," in t
                    or _rel_title(t) <= 0):
                continue
            skill_titles.append(t)
        if not skill_titles:
            skill_titles = [str(t) for t in cap_titles[:10]]
        skill_text = "Core skills: " + " · ".join(_nice_skill(t) for t in skill_titles[:10]) + "."

        exp = [e for e in (cv.get("experience") or []) if isinstance(e, dict)]
        ranked = sorted(exp, key=lambda e: -hits(
            f"{e.get('employer', '')} {e.get('title', '')} {' '.join(e.get('bullets') or [])}"))
        roles = ranked[:3] or exp[:3]
        role_blocks, role_steps = [], []
        for e in roles:
            bullets = [str(b) for b in (e.get("bullets") or [])]
            br = sorted(enumerate(bullets), key=lambda ib: -hits(ib[1]))
            keep = sorted(i for i, _ in br[:3])
            chosen = [bullets[i] for i in keep] or bullets[:2]
            sentences, all_cites = [], []
            emp = str(e.get("employer") or "")
            for b in chosen:
                b = b.strip()
                if not b:
                    continue
                if not b.endswith((".", "!", "?")):
                    b += "."
                c = ([emp] if emp in by_title else []) + cites(b)
                c = list(dict.fromkeys(c))[:5]
                all_cites += c
                sentences.append({"text": b, "cites": c, "step": 0,
                                  "section": "Selected experience", "group": emp, "trace": []})
            if sentences:
                role_blocks.append({"heading": f"{emp} — {e.get('title', '')}",
                                    "sub": " · ".join(x for x in (e.get("dates"), e.get("location")) if x),
                                    "sentences": sentences})
                role_steps.append((emp, sentences, list(dict.fromkeys(all_cites))))

        org_full = [e.get("employer", "") for e in roles if e.get("employer")] or orgs[:3]
        org_names = [str(x).split(",")[0].strip() for x in org_full]
        top_skills = skill_titles[:5] or ["the connected record"]
        summary1 = (f"{name_} is a senior engineering leader with experience at "
                    f"{', '.join(org_names[:3])} and core strengths in "
                    f"{', '.join(_nice_skill(t) for t in top_skills)}.")
        summary2 = (f"Targeting {target}, with evidence across "
                    f"{', '.join(covered[:6]) if covered else 'the requirements'}.")
        sum_cites = ([person] if person in by_title else []) + \
                    [o for o in org_full if o in by_title] + skill_titles[:5]
        sum_cites = list(dict.fromkeys(sum_cites))[:7]
        summary = [
            {"text": summary1, "cites": sum_cites, "step": 0,
             "section": "Profile", "group": "", "trace": []},
            {"text": summary2, "cites": skill_titles[:5], "step": 0,
             "section": "Profile", "group": "", "trace": []},
        ]
        skill_sentence = {"text": skill_text, "cites": skill_titles[:10], "step": 0,
                          "section": "Core skills", "group": "", "trace": []}
        skill_lines = [str(line).strip() for line in (cv.get("skills") or [])
                       if line and hits(line) > 0][:2]
        if not skill_lines:
            skill_lines = [str(line).strip() for line in (cv.get("skills") or []) if line][:2]
        skill_sentences = [skill_sentence]
        for line in skill_lines:
            text = line.rstrip('.') + '.'
            if ':' not in text:
                text = f"Core strengths: {text}"
            skill_sentences.append({"text": text, "cites": cites(text, 5), "step": 0,
                                    "section": "Core skills", "group": "", "trace": []})

        edu = [str(x) for x in (cv.get("education") or []) if x]
        certs = [str(x) for x in (cv.get("certifications") or []) if x]
        edu_sentences = []
        for label, lines in (("Education", edu), ("Certifications", certs)):
            if lines:
                text = f"{label}: " + " · ".join(lines)
                edu_sentences.append({"text": text,
                                      "cites": cites(text, 5, ("EDUCATION", "CERTIFICATION")),
                                      "step": 0,
                                      "section": "Education & certifications", "group": "", "trace": []})

        steps_ = [{"n": 0, "kind": "read", "query": "Read the job spec",
                   "label": "Read the job spec", "write": "",
                   "nodes": [], "links": [], "trace": []}]
        n = 0

        def add_step(query, sentences_, nodes_, trace_=None, terms=None, explain="", hub=None):
            nonlocal n
            n += 1
            for s_ in sentences_:
                s_["step"] = n
            base = hub or root_id
            ids_ = []
            for x in (nodes_ or []):
                xid = as_id(x) or str(x or "")
                if xid and xid not in ids_:
                    ids_.append(xid)
            tr = [h for h in (trace_ or []) if h.get("from") != h.get("to")]
            if not tr and sentences_:
                tr = trace_for([c for s_ in sentences_ for c in (s_.get("cites") or [])])
            # every document line cites the nodes it was built from; draw those
            # citation links so the audience can see which evidence fed the line
            have = {(h["from"], h["to"]) for h in tr}
            for cid in ids_:
                if len(tr) >= 5:
                    break
                if cid and cid != base and (base, cid) not in have:
                    tr.append({"from": base, "to": cid,
                               "desc": "cited by this line", "citation": True})
                    have.add((base, cid))
            for hop in tr:
                if (hop["from"], hop["to"]) not in edge_pairs:
                    links.append({"source": hop["from"], "target": hop["to"],
                                  "weight": 24.0, "description": hop.get("desc") or ""})
                    edge_pairs.add((hop["from"], hop["to"]))
                    edge_pairs.add((hop["to"], hop["from"]))
            steps_.append({"n": n, "kind": "write", "query": query,
                           "label": sentences_[0]["section"] if sentences_ else "Document",
                           "write": " ".join(s_["text"] for s_ in sentences_)[:700],
                           "nodes": ids_, "focus": ids_,
                           "links": [{"from": x["from"], "to": x["to"]} for x in tr],
                           "trace": tr,
                           "terms": terms if terms is not None else terms_of(
                               " ".join(s_["text"] for s_ in sentences_)),
                           "explain": explain})
            return n

        def add_query(query, explain, nodes=None, trace_=None, terms=None, label="Query", focus=None):
            nonlocal n
            n += 1
            ids_, focus_ids = [], []
            for x in (nodes or []):
                xid = as_id(x) or str(x or "")
                if xid and xid not in ids_:
                    ids_.append(xid)
            for x in (focus if focus is not None else (nodes or [])):
                xid = as_id(x) or str(x or "")
                if xid and xid not in focus_ids:
                    focus_ids.append(xid)
            tr = [h for h in (trace_ or []) if h.get("from") != h.get("to")][:8]
            for hop in tr:
                if (hop["from"], hop["to"]) not in edge_pairs:
                    links.append({"source": hop["from"], "target": hop["to"],
                                  "weight": 24.0, "description": hop.get("desc") or ""})
                    edge_pairs.add((hop["from"], hop["to"]))
                    edge_pairs.add((hop["to"], hop["from"]))
            steps_.append({"n": n, "kind": "query", "query": query, "label": label,
                           "write": "", "nodes": ids_,
                           "links": [{"from": x["from"], "to": x["to"]} for x in tr],
                           "trace": tr, "terms": terms or [],
                           "focus": focus_ids,
                           "explain": explain, "returned": len(focus_ids)})
            return n

        # ---- the recursive query itself, before anything is written
        seed_nodes = []
        for kw in covered:
            for t in matched.get(kw, [])[:2]:
                if t not in seed_nodes:
                    seed_nodes.append(t)
        add_query(
            f"MATCH requirement → entity · {len(covered)}/{len(keywords)} requirements hit the graph",
            (f"Each requirement was looked up against entity titles and descriptions. "
             f"{len(covered)} of {len(keywords)} matched, giving {len(seed_nodes)} seed entities "
             f"to walk out from."),
            nodes=seed_nodes[:16], focus=seed_nodes[:8], terms=covered[:8], label="Seed match")
        for entry in hop_log:
            depth = entry.get("depth", 1)
            raw_edges = entry.get("edges") or []
            hop_edges = []
            for a, b, d in raw_edges:
                aid, bid = as_id(a), as_id(b)
                if aid and bid:
                    hop_edges.append({"from": aid, "to": bid, "desc": d})
            add_query(
                f"EXPAND hop {depth}/{max(1, len(hop_log))} · {entry.get('frontier', 0)} frontier nodes "
                f"→ {len(entry.get('found') or [])} new entities",
                (f"Walked {len(raw_edges)} edges out of {entry.get('frontier', 0)} frontier nodes, "
                 f"discarding anything already seen. That adds {len(entry.get('found') or [])} nodes "
                 f"to the evidence subgraph this document is built from."),
                nodes=((entry.get("frontier_nodes") or []) +
                       (entry.get("found") or []))[:22],
                focus=(entry.get("found") or [])[:16],
                trace_=hop_edges[:8], terms=[],
                label=f"Hop {depth}")

        if kind == "letter":
            opening = {"text": f"I am applying for {target}. I have led engineering at "
                              f"{', '.join(org_names[:3])} and my core strengths are "
                              f"{', '.join(_nice_skill(t) for t in top_skills)}.",
                       "cites": sum_cites,
                       "step": 0, "section": "Opening", "group": "", "trace": []}
            background = {"text": f"My background includes {', '.join(org_names[:3])} and "
                                  f"{', '.join(_nice_skill(t) for t in top_skills)}.",
                          "cites": sum_cites, "step": 0, "section": "Background", "group": "", "trace": []}
            evidence = None
            if role_steps:
                emp, sentences_, cites_ = role_steps[0]
                b = _verb_bullet([s["text"] for s in sentences_])
                if b:
                    evidence = {"text": f"At {emp}, I {b[0].lower() + b[1:].rstrip('.')}.",
                                "cites": cites_, "step": 0,
                                "section": "Evidence", "group": emp, "trace": []}
            close = {"text": f"I would welcome the chance to discuss how I can help "
                              f"{company or 'your team'}.", "cites": [], "step": 0,
                     "section": "Close", "group": "", "trace": []}
            add_step("Anchor the letter in the target role and the strongest cited evidence",
                     [opening], sum_cites, terms=covered[:6],
                     explain=f"The advert names {len(covered)} requirements the graph can evidence; "
                             f"the opening names the role and the candidate's strongest matches.")
            add_step("Connect the career record to those requirements", [background],
                     sum_cites, terms=covered[:6],
                     explain=f"Two-hop traversal collected {len(nodes)} evidence nodes across "
                             f"{len(org_names[:3])} organisations.")
            if evidence:
                add_step(f"Pull the strongest cited achievement from {evidence['group']}",
                         [evidence], evidence["cites"], terms=terms_of(evidence["text"]),
                         explain=f"Selected the highest-matching achievement at {evidence['group']} "
                                 f"and traced it back to the graph.")
            add_step("Close without inventing a claim", [close], [], terms=[],
                     explain="A standard application close. No new fact, number or promise is added.")
            n += 1
            steps_.append({"n": n, "kind": "gate",
                           "query": "Gate the letter: every claim is grounded",
                           "label": "Gate", "write": "", "nodes": [],
                           "links": [], "trace": [], "terms": [],
                           "explain": "Coherence gate: every sentence maps to a saved CV fact and a "
                                      "graph citation; the letter adds no unsupported claim."})
            doc = {
                "title": "Cover letter",
                "subtitle": f"Tailored cover letter · {len(nodes)} evidence nodes and {len(links)} connections",
                "name": name_, "target": target, "contact": contact,
                "prologue": ["Dear Hiring Team,"],
                "blocks": [
                    {"heading": "", "type": "letter", "sentences": [opening]},
                    {"heading": "", "type": "letter", "sentences": [background]},
                    *([{"heading": "", "type": "letter", "sentences": [evidence]}] if evidence else []),
                    {"heading": "", "type": "letter", "sentences": [close]},
                ],
                "note": "Every claim is drawn from config/cv.json; the graph supplies the ranking "
                        "and citations. The closing is a standard application sentence, not a new claim.",
                "note_step": n,
            }
        else:
            add_step("Rank the career record against the advert and write the summary",
                     summary, sum_cites, terms=covered[:6],
                     explain=f"Scored all {len(exp)} roles in the saved CV by how many of the "
                             f"{len(keywords)} advert requirements they evidence. "
                             f"{len(sum_cites)} nodes are cited in the summary.")
            add_step("Keep only skills the graph can evidence",
                     skill_sentences, skill_titles[:10], terms=covered[:6],
                     explain=f"The recursive query returned {len(skill_titles)} matching skills; "
                             f"{min(10, len(skill_titles))} are written, strongest first.")
            for emp, sentences_, cites_ in role_steps:
                hub = as_id(emp) or root_id
                trace = []
                for c in cites_:
                    cid = as_id(c)
                    if not cid or cid == hub:
                        continue
                    d = link_desc.get((hub, cid)) or link_desc.get((cid, hub)) or ""
                    trace.append({"from": hub, "to": cid, "desc": d, "citation": not d})
                    if len(trace) >= 4:
                        break
                role_terms = terms_of(" ".join(s["text"] for s in sentences_))
                add_step(f"Expand {emp} and keep the achievements that match",
                         sentences_, cites_, trace_=trace, terms=role_terms, hub=hub,
                         explain=f"{len(sentences_)} achievements cited for {emp}; each line keeps "
                                 f"its graph edge, so the claim can be traced back.")
            if edu_sentences:
                add_step("Attach education and certifications from the saved CV",
                         edu_sentences, [c for s_ in edu_sentences for c in s_["cites"]][:8],
                         terms=[],
                         explain="Education and certifications come from the saved CV, not from the advert; "
                                 "they are included only where the record supports them.")
            n += 1
            steps_.append({"n": n, "kind": "gate",
                           "query": "Gate the CV: every line is grounded and cited",
                           "label": "Gate", "write": "", "nodes": [],
                           "links": [], "trace": [], "terms": [],
                           "explain": "Coherence gate: every included line maps to a saved CV fact and "
                                      "a graph node. Missing requirements are left out, not invented."})
            doc = {
                "title": "Curriculum Vitae",
                "subtitle": f"Tailored CV · {len(nodes)} evidence nodes and {len(links)} connections",
                "name": name_, "target": target, "contact": contact,
                "blocks": [
                    {"heading": "Professional summary", "type": "p", "sentences": summary},
                    {"heading": "Core skills", "type": "p", "sentences": skill_sentences},
                    {"heading": "Experience", "type": "experience", "roles": role_blocks},
                    {"heading": "Education & certifications", "type": "p",
                     "sentences": edu_sentences},
                ],
                "note": "Every line is drawn from config/cv.json; the graph supplies the ranking "
                        "and citations. Coherence gate: included claims are grounded in the saved CV.",
                "note_step": n,
            }
        found_terms = [k for k in keywords if matched.get(k)]
        missing_terms = [k for k in keywords if not matched.get(k)]
        steps_[0].update({
            "terms": found_terms[:14],
            "nodes": [root_id] if root_id else [],
            "explain": (f"Parsed the advert into {len(keywords)} requirements; "
                        f"{len(found_terms)} are evidenced in the knowledge graph and "
                        f"{len(missing_terms)} are not. Only evidenced requirements are used."),
        })
        spec_lines = []
        budget = 0
        noise = (
            "linkedin respects your privacy", "linkedin and 3rd parties",
            "select accept to consent", "accept reject", "skip to main content",
            "clear text", "sign in", "join now", "see who ", "be among the first",
            "no longer accepting applications", "report this job", "easy apply",
            "set alert", "am i a good fit", "job details", "seniority level",
            "employment type", "job function", "industries", "referrals increase",
            "show more", "show less", "message the job poster", "upload your cv",
            "get notified about new", "use ai to assess", "see more jobs",
            "linkedin", "jobs", "companies", "people", "learning", "games",
        )
        for raw in jd.splitlines():
            s = raw.strip()
            if not s:
                continue
            low = s.lower()
            if (len(s) < 4 or low.startswith(("#", "source:", "fetched:", "---"))
                    or low.startswith(noise) or low.endswith(noise)
                    or low == "unknown company — unknown role"):
                continue
            s = s[:240]
            spec_lines.append({"text": s, "terms": terms_of(s)})
            budget += len(s)
            if len(spec_lines) >= 46 or budget > 4600:
                break
        return {"mode": "playground",
                "job": {"key": key, "company": company, "role": role,
                        "keywords": keywords[:20], "found": found_terms[:20],
                        "missing": missing_terms[:10], "hops": hops,
                        "coverage": round(100 * len(covered) / max(1, len(keywords))),
                        "lines": spec_lines, "text": jd[:4600]},
                "steps": steps_, "doc": doc,
                "graph": {"nodes": nodes, "links": links, "center": top_seed}}

    if kind in ("cv", "letter"):
        return _build_cv(kind)

    blocks = []
    if prof:
        blocks.append({"heading": "Profile", "type": "p", "sentences": prof})
    if exp:
        order, groups = [], {}
        for s in exp:
            g = s.get("group") or "Selected experience"
            if g not in groups:
                groups[g] = []
                order.append(g)
            groups[g].append(s)
        blocks.append({"heading": "Selected experience", "type": "experience",
                       "roles": [{"heading": g, "sentences": groups[g]} for g in order]})
    if caps:
        blocks.append({"heading": "Relevant capabilities", "type": "p", "sentences": caps})
    name = display_name
    doc = {
        "title": "Tailored profile",
        "subtitle": f"{target} · built from {len(nodes)} evidence nodes and {len(links)} connections",
        "name": name,
        "target": target,
        "blocks": blocks,
        "note": (f"Grounded in the knowledge graph. {len(covered)} of {len(keywords)} requirements "
                 f"have evidence." + (f" Not evidenced: {', '.join(gaps[:10])}." if gaps else "")),
        "note_step": len(ordered),
    }
    return {"mode": "playground", "job": {"key": key, "company": company, "role": role,
                                          "keywords": keywords, "coverage": round(100 * len(covered) / max(1, len(keywords)))},
            "steps": steps, "doc": doc,
            "graph": {"nodes": nodes, "links": links, "center": top_seed}}


def role_evidence(key):
    """JD keywords -> grounded graph evidence, with explicit gaps."""
    key = str(key or "").strip()
    jd_path = os.path.join(ROOT, "state", "job-descriptions", key + ".md")
    ats_path = os.path.join(ROOT, "state", "ats", key + ".txt")
    keywords = []
    try:
        for line in open(ats_path, encoding="utf-8", errors="ignore"):
            line = line.strip()
            if line and not line.startswith("#") and len(line) > 1:
                keywords.append(line)
    except OSError:
        pass
    if not keywords:
        try:
            jd = open(jd_path, encoding="utf-8", errors="ignore").read().lower()
        except OSError:
            return {"error": f"no saved job description for {key}"}
        import re as _re
        from collections import Counter
        stop = set("the and for with you your are our will have has this that from they their role job work experience team teams including etc able strong good years across within using".split())
        words = [w for w in _re.findall(r"[a-z][a-z0-9+#.-]{2,}", jd) if w not in stop]
        keywords = [w for w, _n in Counter(words).most_common(24)]
    keywords = keywords[:40]
    ents = _load("entities")
    if ents is None:
        return {"error": "no index"}
    imp = _importance()
    docs = _doc_map()
    cmap = _community_at_level(_load("communities"), 0) if _load("communities") is not None else {}
    matched = {}
    evidence = {}
    for kw in keywords:
        pat = r"\b" + re.escape(kw) + r"\b"
        m = (ents["title"].str.contains(pat, case=False, regex=True) |
             ents["description"].str.contains(pat, case=False, regex=True))
        rows = ents[m].copy()
        if rows.empty:
            matched[kw] = []
            continue
        rows["_imp"] = [float(imp.get(str(t), 0)) for t in rows["title"]]
        rows = rows.sort_values(["_imp", "degree"], ascending=False).head(3)
        matched[kw] = []
        for r in rows.itertuples():
            title = str(r.title)
            matched[kw].append(title)
            rec = evidence.setdefault(title, {
                "title": title, "type": str(r.type), "importance": round(float(imp.get(title, 0)), 3),
                "description": _s(SENS.redact(str(r.description or "")), 400),
                "sources": docs.get(str(r.id), [])[:3],
                "community": cmap.get(str(r.id)), "keywords": [],
            })
            rec["keywords"].append(kw)
    ev = sorted(evidence.values(), key=lambda x: (-len(x["keywords"]), -x["importance"]))[:14]
    gaps = [k for k in keywords if not matched.get(k)]
    return {"key": key, "keywords": keywords, "matched": matched,
            "evidence": ev, "gaps": gaps,
            "coverage": round(100 * (len(keywords) - len(gaps)) / max(1, len(keywords)))}


def semantic(q, limit=14):
    """Natural-language entity search over the GraphRAG entity embeddings."""
    q = str(q or "").strip()
    if not q:
        return {"mode": "semantic", "entities": [], "query": ""}
    try:
        import lancedb
        ents, comms = _load("entities"), _load("communities")
        if ents is None:
            return {"error": "no index"}
        db = lancedb.connect(os.path.join(OUT, "lancedb"))
        table = db.open_table("entity_description")
        vec = _embed(q)
        rows = table.search(vec).limit(max(limit * 3, 40)).to_list()
    except Exception as exc:
        return {"error": f"semantic search unavailable: {type(exc).__name__}: {exc}"}
    by_id = {str(r.id): r for r in ents.itertuples()}
    cmap = _community_at_level(comms, 0) if comms is not None else {}
    imp = _importance()
    out, seen = [], set()
    for row in rows:
        r = by_id.get(str(row.get("id")))
        if r is None:
            continue
        title = str(r.title)
        key = _norm(title)
        if key in seen:
            continue
        seen.add(key)
        ed = _override(title)
        gtype = ed.get("type") or r.type
        meta = ONT.class_meta(gtype)
        c = cmap.get(str(r.id))
        out.append({"id": _s(title, 140), "title": _s(title, 140),
                    "type": _s(gtype, 40), "class": meta["id"], "class_label": meta["label"],
                    "importance": round(float(imp.get(title, 0)), 3),
                    "score": round(1.0 - float(row.get("_distance") or 1.0), 4),
                    "degree": int(r.degree),
                    "description": _s(SENS.redact(str(ed.get("description") or r.description or "")), 500),
                    "community": c,
                    "community_title": reports_title(c) if c is not None else ""})
        if len(out) >= limit:
            break
    return {"mode": "semantic", "entities": out, "query": q}


def node_details(title):
    """Full node + reachable-subgraph details for the right-hand pane."""
    global _REPORTS
    _REPORTS = _reports()
    ents, rels, comms = _load("entities"), _load("relationships"), _load("communities")
    if ents is None or rels is None:
        return {"error": "no index"}
    title = str(title or "").strip()
    if not title:
        return {"error": "no node title"}
    ov = _enrichment()
    by_title = {str(r.title): r for r in ents.itertuples()}
    ov_by = {str(x.get("title") or ""): x for x in ov["nodes"]}
    row = by_title.get(title)
    if row is None:
        row = next((r for t, r in by_title.items() if t.lower() == title.lower()), None)
    ov_node = ov_by.get(title) or next((x for t, x in ov_by.items() if t.lower() == title.lower()), None)
    if row is None and ov_node is None:
        return {"error": f"no entity matching {title}"}
    base = str(row.title) if row is not None else str(ov_node.get("title"))
    ed = _override(base)
    gtype = ed.get("type") or (row.type if row is not None else ov_node.get("type") or "CONCEPT")
    desc = ed.get("description") or (row.description if row is not None else ov_node.get("description") or "")
    meta = ONT.class_meta(gtype)
    docs = _doc_map()
    sources = docs.get(str(row.id), []) if row is not None else []
    if not sources:
        src = (ov_node or {}).get("source") or (ov_node or {}).get("source_doc")
        if src:
            sources = [src]

    adj = {}
    def add_edge(a, b, w, d=""):
        a, b = str(a), str(b)
        adj.setdefault(a, []).append((b, float(w or 1), str(d or "")))
        adj.setdefault(b, []).append((a, float(w or 1), str(d or "")))

    for r in rels.itertuples():
        add_edge(r.source, r.target, r.weight, r.description)
    for l in ov["links"]:
        add_edge(l.get("source"), l.get("target"), l.get("weight") or 1, l.get("description"))

    dist = {base: 0}
    q = [base]
    while q:
        x = q.pop(0)
        for y, _w, _d in adj.get(x, []):
            if y not in dist:
                dist[y] = dist[x] + 1
                q.append(y)
    layers = {}
    for d in dist.values():
        layers[d] = layers.get(d, 0) + 1
    links_in = 0
    seen_pairs = set()
    for a, neighbours in adj.items():
        if a not in dist:
            continue
        for b, w, d in neighbours:
            if b in dist:
                key = tuple(sorted((a, b)))
                if key not in seen_pairs:
                    seen_pairs.add(key)
                    links_in += 1

    cmap = _community_at_level(comms, 0) if comms is not None else {}
    c = cmap.get(str(row.id)) if row is not None else None
    imp = _importance()
    degree = len(adj.get(base, []))
    neighbours = []
    for b, w, d in adj.get(base, []):
        nr = by_title.get(b)
        nx = ov_by.get(b)
        ntype = (ed.get("type") if nr is not None and b == base else
                 (nr.type if nr is not None else (nx or {}).get("type") or "CONCEPT"))
        neighbours.append({"title": b, "type": str(ntype), "weight": round(w, 1),
                          "distance": 1,
                          "importance": round(float(imp.get(b, 0)), 3),
                          "description": _s(SENS.redact(str(nr.description if nr is not None else (nx or {}).get("description") or "")), 300)})
    neighbours.sort(key=lambda x: (-x["weight"], -x["importance"]))
    connections = []
    seen = set()
    for a, ns in adj.items():
        if a not in dist:
            continue
        for b, w, d in ns:
            if b not in dist:
                continue
            if min(dist.get(a, 99), dist.get(b, 99)) > 2:
                continue
            key = tuple(sorted((a, b)))
            if key in seen:
                continue
            seen.add(key)
            connections.append({"source": a, "target": b, "weight": round(w, 1),
                                "description": _s(SENS.redact(str(d or "")), 300)})
    connections.sort(key=lambda x: -x["weight"])

    return {
        "title": base, "type": _s(gtype, 40), "class": meta["id"],
        "class_label": meta["label"], "color": meta["color"],
        "importance": round(float(imp.get(base, 0)), 3),
        "degree": degree,
        "frequency": int(row.frequency) if row is not None else 1,
        "community": c,
        "community_title": reports_title(c) if c is not None else "",
        "description": _s(SENS.redact(str(desc or "")), 1200),
        "sources": sources[:8],
        "grounded": bool((ov_node or {}).get("grounded") or row is None),
        "evidence": _s(SENS.redact(str((ov_node or {}).get("evidence") or "")), 700),
        "edited": bool(ed),
        "subgraph": {
            "nodes": len(dist),
            "links": links_in,
            "max_depth": max(dist.values()) if dist else 0,
            "layers": [{"distance": d, "nodes": layers[d]} for d in sorted(layers)],
        },
        "neighbours": neighbours[:14],
        "connections": connections[:12],
    }


def search(q, limit=12):

    global _REPORTS
    q = (q or "").strip().lower()
    if not q:
        return {"communities": [], "entities": [], "query": ""}
    comms, ents, rels = _load("communities"), _load("entities"), _load("relationships")
    if comms is None or ents is None:
        return {"error": "no index"}
    _REPORTS = _reports()
    cmap = _deepest_community(comms, ents)
    communities = []
    for r in comms.itertuples():
        rep = _REPORTS.get(int(r.community), {})
        hay = f"{rep.get('title','')} {rep.get('summary','')} community {r.community}".lower()
        if q in hay:
            communities.append({"community": int(r.community), "title": rep.get("title") or f"Community {r.community}",
                                "level": int(r.level), "size": int(r.size),
                                "description": rep.get("summary", ""),
                                "path": _breadcrumb(comms, int(r.community))})
    communities.sort(key=lambda x: -x["size"])
    communities = communities[:limit]
    m = (ents["title"].str.lower().str.contains(q, regex=False) |
         ents["type"].str.lower().str.contains(q, regex=False) |
         ents["description"].str.lower().str.contains(q, regex=False))
    imp = _importance()
    sub = ents[m].assign(_imp=[imp.get(str(t), 0.0) for t in ents[m]["title"]])
    sub = sub.sort_values(["_imp", "degree"], ascending=False).head(limit)
    entities = []
    for r in sub.itertuples():
        c = cmap.get(str(r.id))
        ed = _override(r.title)
        gtype = ed.get("type") or r.type
        meta = ONT.class_meta(gtype)
        entities.append({"id": _s(r.title, 140), "title": _s(r.title, 140), "type": _s(gtype, 40),
                         "class": meta["id"], "class_label": meta["label"],
                         "degree": int(r.degree), "importance": round(float(_importance().get(_s(r.title, 140), 0.0)), 3),
                         "description": _s(SENS.redact(str(ed.get("description") or r.description or "")), 400),
                         "community": c,
                         "community_title": reports_title(c) if c is not None else ""})
    seen = {_norm(e.get("title", "")) for e in entities}
    for r in _overlay_nodes(q, limit):
        if _norm(r["title"]) in seen:
            continue
        entities.append({"id": r["title"], "title": r["title"], "type": "SKILL",
                         "class": "SKILL", "class_label": "Skill", "degree": 1,
                         "description": r["description"][:400], "community": None,
                         "community_title": ""})
    for x in _enrichment()["nodes"]:
        title = _s(x.get("title"), 140)
        if not title or _norm(title) in seen:
            continue
        hay = (title + " " + str(x.get("description") or "") + " " + str(x.get("evidence") or "")).lower()
        if q not in hay:
            continue
        meta = ONT.class_meta(x.get("type") or "CONCEPT")
        entities.append({"id": title, "title": title, "type": _s(x.get("type"), 40),
                         "class": meta["id"], "class_label": meta["label"], "degree": 1,
                         "importance": round(float(_importance().get(title, 0.0)), 3),
                         "description": _s(x.get("description") or x.get("evidence"), 400),
                         "community": None, "community_title": "",
                         "grounded": True})
        seen.add(_norm(title))
    return {"communities": communities, "entities": entities[:limit], "query": q}


def ego(q, limit=50):
    global _REPORTS
    q = (q or "").strip()
    if not q:
        return {"error": "no entity"}
    comms, ents, rels = _load("communities"), _load("entities"), _load("relationships")
    if comms is None or ents is None or rels is None:
        return {"error": "no index"}
    _REPORTS = _reports()
    ov = _enrichment()
    ov_by = {str(x.get("title") or "").lower(): x for x in ov["nodes"]}
    exact = ents[ents["title"].str.lower() == q.lower()]
    row = exact.iloc[0] if len(exact) else None
    if row is None:
        m = ents["title"].str.lower().str.contains(q.lower(), regex=False)
        if m.any():
            row = ents[m].sort_values("degree", ascending=False).iloc[0]
        elif q.lower() in ov_by:
            x = ov_by[q.lower()]
            title = str(x["title"])
            edges = rels[(rels["source"] == title) | (rels["target"] == title)]
            neigh = set(edges["source"]) | set(edges["target"])
            ov_neigh = set()
            for l in ov["links"]:
                if l.get("source") == title:
                    ov_neigh.add(str(l.get("target")))
                elif l.get("target") == title:
                    ov_neigh.add(str(l.get("source")))
            titles = {title} | neigh | ov_neigh
            sub = ents[ents["title"].isin(neigh)].sort_values("degree", ascending=False).head(max(1, limit - 1))
            nodes = [_overlay_entity_node(x)] + [_entity_node(r, None, _doc_map()) for r in sub.itertuples()]
            for t in ov_neigh:
                if t in ov_by and not any(n["title"] == t for n in nodes):
                    nodes.append(_overlay_entity_node(ov_by[t]))
            links = [{"source": _s(r.source, 140), "target": _s(r.target, 140),
                      "weight": round(float(r.weight), 1)} for r in edges.itertuples()]
            for l in ov["links"]:
                if l.get("source") in titles and l.get("target") in titles:
                    links.append({"source": _s(l.get("source"), 140), "target": _s(l.get("target"), 140),
                                  "weight": round(float(l.get("weight") or 1), 1),
                                  "description": _s(l.get("description"), 400), "grounded": True})
            return {"mode": "ego", "center": title, "community": None,
                    "breadcrumb": [], "nodes": nodes[:limit], "links": links[:limit * 2],
                    "total": len(nodes)}
        else:
            return {"error": f"no entity matching {q}"}
    title = str(row.title)
    edges = rels[(rels["source"] == title) | (rels["target"] == title)]
    neigh = set(edges["source"]) | set(edges["target"])
    neigh.discard(title)
    imp = _importance()
    ne = ents[ents["title"].isin(neigh)].assign(_imp=[imp.get(str(t), 0.0) for t in ents[ents["title"].isin(neigh)]["title"]])
    sub = ne.sort_values(["_imp", "degree"], ascending=False).head(limit - 1)
    titles = set(sub["title"]) | {title}
    links_df = rels[rels["source"].isin(titles) & rels["target"].isin(titles)]
    links_df = links_df.sort_values("weight", ascending=False).head(limit * 3)
    center_c = _deepest_community(comms, ents).get(str(row.id))
    docs = _doc_map()
    nodes = [_entity_node(row, center_c, docs)]
    nodes += [_entity_node(r, center_c, docs) for r in sub.itertuples()]
    links = [{"source": _s(r.source, 140), "target": _s(r.target, 140),
              "weight": round(float(r.weight), 1)} for r in links_df.itertuples()]
    seen_titles = {n["title"] for n in nodes}
    for l in ov["links"]:
        if l.get("source") == title or l.get("target") == title:
            add = str(l.get("target") if l.get("source") == title else l.get("source"))
            if add and add not in seen_titles and add.lower() in ov_by:
                nodes.append(_overlay_entity_node(ov_by[add.lower()], center_c))
                seen_titles.add(add)
            links.append({"source": _s(l.get("source"), 140), "target": _s(l.get("target"), 140),
                          "weight": round(float(l.get("weight") or 1), 1),
                          "description": _s(l.get("description"), 400), "grounded": True})
    return {"mode": "ego", "center": title, "community": center_c,
            "breadcrumb": ([{"community": center_c, "title": reports_title(center_c)}] if center_c is not None else []),
            "nodes": nodes, "links": links, "total": len(nodes)}


def graph(q, limit):
    """A navigable subgraph: top entities, or a query plus its one-hop neighbourhood."""
    ents = _load("entities")
    rels = _load("relationships")
    if ents is None or rels is None:
        return {"error": "no index"}
    limit = max(10, min(int(limit or 90), 160))
    if q:
        m = (ents["title"].str.lower().str.contains(q, regex=False) |
             ents["description"].str.lower().str.contains(q, regex=False) |
             ents["type"].str.lower().str.contains(q, regex=False))
        imp = _importance()
        seed = ents[m].assign(_imp=[imp.get(str(t), 0.0) for t in ents[m]["title"]]).sort_values(["_imp", "degree"], ascending=False)
        if seed.empty:
            return {"nodes": [], "links": [], "query": q, "total": 0}
        seeds = set(seed["title"].head(max(6, limit // 6)))
        rel = rels[rels["source"].isin(seeds) | rels["target"].isin(seeds)]
        rel = rel.sort_values("weight", ascending=False).head(limit * 2)
        titles = seeds | set(rel["source"]) | set(rel["target"])
        nodes_df = ents[ents["title"].isin(titles)].assign(_imp=[_importance().get(str(t), 0.0) for t in ents[ents["title"].isin(titles)]["title"]]).sort_values(["_imp", "degree"], ascending=False).head(limit)
        titles = set(nodes_df["title"])
        rel = rel[rel["source"].isin(titles) & rel["target"].isin(titles)].head(limit * 2)
    else:
        nodes_df = ents.assign(_imp=[_importance().get(str(t), 0.0) for t in ents["title"]]).sort_values(["_imp", "degree"], ascending=False).head(limit)
        titles = set(nodes_df["title"])
        rel = rels[rels["source"].isin(titles) & rels["target"].isin(titles)]
        rel = rel.sort_values("weight", ascending=False).head(limit * 2)
    nodes = [{"id": _s(r.title, 140), "title": _s(r.title, 140), "type": _s(r.type, 40),
              "degree": int(r.degree), "frequency": int(r.frequency),
              "importance": round(float(_importance().get(_s(r.title, 140), 0.0)), 3),
              "description": _s(r.description, 700)} for r in nodes_df.itertuples()]
    links = [{"source": _s(r.source, 140), "target": _s(r.target, 140),
              "weight": round(float(r.weight), 1), "description": _s(r.description, 400)}
             for r in rel.itertuples()]
    _add_skill_links(nodes, links, _overlay_nodes(q, 10))
    return {"nodes": nodes, "links": links, "query": q, "total": len(ents) + len(_skill_overlay())}


def universe():
    """The whole indexed graph, for the space-view explorer."""
    global _REPORTS
    _REPORTS = _reports()
    ents, rels = _load("entities"), _load("relationships")
    comms = _load("communities")
    if ents is None or rels is None:
        return {"error": "no index"}
    # Level 0 is the theme/employer level (Anaplan, Telia, Thomson Reuters,
    # HAUD, EuroCompliant...). Using the deepest community fragmented the map
    # into hundreds of tiny islands and hid that structure.
    cmap = _community_at_level(comms, 0) if comms is not None else {}
    nodes = []
    for r in ents.itertuples():
        ed = _override(r.title)
        gtype = ed.get("type") or r.type
        meta = ONT.class_meta(gtype)
        c = cmap.get(str(r.id))
        nodes.append({"id": _s(r.title, 140), "title": _s(r.title, 140),
                      "type": _s(gtype, 40), "class": meta["id"],
                      "color": meta["color"], "degree": int(r.degree),
                      "frequency": int(r.frequency),
                      "importance": round(float(_importance().get(_s(r.title, 140), 0.0)), 3),
                      "community": c,
                      "community_title": reports_title(c) if c is not None else "",
                      "description": _s(SENS.redact(str(ed.get("description") or r.description or "")), 260)})
    links = [{"source": _s(r.source, 140), "target": _s(r.target, 140),
              "weight": round(float(r.weight), 1)} for r in rels.itertuples()]
    _add_skill_links(nodes, links, _overlay_nodes("", 60))
    ov = _enrichment()
    if ov["nodes"] or ov["links"]:
        by_title = {n["title"]: n for n in nodes}
        imp = _importance()
        for x in ov["nodes"]:
            title = _s(x.get("title"), 140)
            if not title or title in by_title:
                continue
            meta = ONT.class_meta(x.get("type") or "CONCEPT")
            rel = by_title.get(_s(x.get("related"), 140))
            c = rel.get("community") if rel else None
            ct = rel.get("community_title") if rel else ""
            node = {"id": title, "title": title, "type": _s(x.get("type") or "CONCEPT", 40),
                    "class": meta["id"], "color": meta["color"],
                    "degree": 1, "frequency": 1,
                    "importance": round(float(imp.get(title, 0.0)), 3),
                    "community": c, "community_title": ct or "",
                    "description": _s(x.get("description"), 260),
                    "grounded": True, "evidence": _s(x.get("evidence"), 500),
                    "source": _s(x.get("source") or x.get("source_doc"), 200)}
            nodes.append(node); by_title[title] = node
        have = {(_norm(l.get("source")), _norm(l.get("target"))) for l in links}
        for x in ov["links"]:
            a, b = _s(x.get("source"), 140), _s(x.get("target"), 140)
            if not a or not b or a not in by_title or b not in by_title:
                continue
            key = (_norm(a), _norm(b))
            if key in have:
                continue
            links.append({"source": a, "target": b, "weight": round(float(x.get("weight") or 1), 1),
                          "description": _s(x.get("description"), 400), "grounded": True})
            if x.get("origin") == "orphan-attachment" and a in by_title:
                by_title[a]["attached"] = True
            have.add(key)
        deg = {n["id"]: int(n.get("degree") or 0) for n in nodes}
        for l in ov["links"]:
            a, b = l.get("source"), l.get("target")
            if a in deg and b in deg:
                deg[a] += 1
                deg[b] += 1
        for n in nodes:
            if n["id"] in deg:
                n["degree"] = deg[n["id"]]
    return {"nodes": nodes, "links": links, "total": len(nodes)}


def documents():
    df = _load("documents")
    if df is None:
        return {"error": "no index"}
    return {"rows": [{"id": int(r.human_readable_id), "title": _s(r.title, 120),
                      "chars": len(str(r.text or ""))} for r in df.itertuples()]}


def resolve(entity_ids, doc_ids):
    ents = _load("entities")
    docs = _load("documents")
    out = {"entities": [], "documents": []}
    if ents is not None and entity_ids:
        m = ents["human_readable_id"].isin(entity_ids)
        out["entities"] = [{"id": int(r.human_readable_id), "title": _s(r.title, 120), "type": _s(r.type, 40),
                            "description": _s(r.description, 400)} for r in ents[m].itertuples()]
    if docs is not None and doc_ids:
        m = docs["human_readable_id"].isin(doc_ids)
        out["documents"] = [{"id": int(r.human_readable_id), "title": _s(r.title, 140),
                             "chars": len(str(r.text or ""))} for r in docs[m].itertuples()]
    return out


def main():
    if len(sys.argv) < 2:
        print(json.dumps({"error": "usage: graph_explore.py <cmd> [args]"}))
        return 0
    cmd, a = sys.argv[1], sys.argv[2:]
    try:
        if cmd == "stats":
            res = stats()
        elif cmd == "entities":
            res = entities((a[0] if a else "").lower(), int(a[1]) if len(a) > 1 else 200)
        elif cmd == "relationships":
            res = relationships((a[0] if a else "").lower(), int(a[1]) if len(a) > 1 else 200)
        elif cmd == "communities":
            res = communities((a[0] if a else "").lower(), int(a[1]) if len(a) > 1 else 200)
        elif cmd == "universe":
            res = universe()
        elif cmd == "documents":
            res = documents()
        elif cmd == "graph":
            res = graph((a[0] if a else "").lower(),
                        int(a[1]) if len(a) > 1 else 90)
        elif cmd == "overview":
            res = overview((int(a[0]) if a and a[0] else None),
                           int(a[1]) if len(a) > 1 else 60)
        elif cmd == "community":
            res = community_view(int(a[0]) if a else 0,
                                 int(a[1]) if len(a) > 1 else 90)
        elif cmd == "ontology":
            res = ontology_view()
        elif cmd == "types":
            res = types_overview(int(a[0]) if a else 24)
        elif cmd == "type":
            res = type_entities(a[0] if a else "",
                                int(a[1]) if len(a) > 1 else 90)
        elif cmd == "evidence":
            res = role_evidence(a[0] if a else "")
        elif cmd == "playground":
            text = "" if sys.stdin.isatty() else sys.stdin.read()
            res = playground(a[0] if a else "", text,
                             int(a[1]) if len(a) > 1 else 2,
                             a[2] if len(a) > 2 else "cv")
        elif cmd == "semantic":
            res = semantic(a[0] if a else "", int(a[1]) if len(a) > 1 else 14)
        elif cmd == "node":
            res = node_details(a[0] if a else "")
        elif cmd == "search":
            res = search(a[0] if a else "",
                         int(a[1]) if len(a) > 1 else 12)
        elif cmd == "ego":
            res = ego(a[0] if a else "",
                      int(a[1]) if len(a) > 1 else 50)
        elif cmd == "resolve":
            eids = [int(x) for x in (a[0] if a else "").split(",") if x.strip().isdigit()]
            dids = []
            if "--docs" in a:
                dids = [int(x) for x in a[a.index("--docs") + 1].split(",") if x.strip().isdigit()]
            res = resolve(eids, dids)
        else:
            res = {"error": f"unknown command {cmd}"}
    except Exception as e:  # never break the dashboard on a graph read
        res = {"error": f"{type(e).__name__}: {e}"}
    print(json.dumps(res))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
