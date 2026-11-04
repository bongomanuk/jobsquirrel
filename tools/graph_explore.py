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
