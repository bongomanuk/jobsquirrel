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
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ontology as ONT  # noqa: E402


def _load(name):
    import pandas as pd
    path = os.path.join(OUT, name + ".parquet")
    if not os.path.exists(path):
        return None
    return pd.read_parquet(path)


def _s(v, n):
    return "" if v is None else str(v)[:n]


SKILLS_FILE = os.path.join(ROOT, "kb", "sources", "personal", "skills_evidence.md")


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


def _add_skill_links(nodes, links, rows):
    titles = {_norm(n.get("title", "")) for n in nodes}
    person = "Peter Hollas"
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
        out[int(r.community)] = {"title": _s(r.title, 120), "summary": _s(r.summary, 700)}
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
    return _REPORTS.get(int(n), {}).get("title") or f"Community {int(n)}"


_REPORTS = {}


def _deepest_community(comms, ents):
    """entity uuid -> the smallest/deepest community that contains it."""
    out = {}
    for r in comms.sort_values("level", ascending=False).itertuples():
        for uid in r.entity_ids:
            out.setdefault(str(uid), int(r.community))
    return out


def _entity_node(r, community=None, docs=None):
    meta = ONT.class_meta(r.type)
    return {"id": _s(r.title, 140), "title": _s(r.title, 140), "kind": "entity",
            "type": _s(r.type, 40), "class": meta["id"], "class_label": meta["label"],
            "color": meta["color"],
            "degree": int(r.degree), "frequency": int(r.frequency),
            "description": _s(r.description, 700), "community": community,
            "sources": (docs or {}).get(str(r.id), [])[:6]}


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
    titles_all = set(str(x) for x in sub_all["title"])
    rel_all = rels[rels["source"].isin(titles_all) & rels["target"].isin(titles_all)]
    sub, rel, connected = _connected_subgraph(sub_all, rel_all, limit)
    rel = rel.sort_values("weight", ascending=False).head(limit * 2)
    docs = _doc_map()
    nodes = [_entity_node(r, None, docs) for r in sub.itertuples()]
    links = [{"source": _s(r.source, 140), "target": _s(r.target, 140),
              "weight": round(float(r.weight), 1)} for r in rel.itertuples()]
    meta = ONT.class_meta(t)
    return {"mode": "entities", "type": t, "label": meta["label"], "color": meta["color"],
            "nodes": nodes, "links": links, "total": len(sub_all),
            "connected": connected, "shown": len(nodes)}


def ontology_view():
    ents = _load("entities")
    out = ONT.summary(ents)
    out["mode"] = "ontology"
    return out


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
    sub = ents[m].sort_values("degree", ascending=False).head(limit)
    entities = []
    for r in sub.itertuples():
        c = cmap.get(str(r.id))
        entities.append({"id": _s(r.title, 140), "title": _s(r.title, 140), "type": _s(r.type, 40),
                         "class": ONT.class_for(r.type), "class_label": ONT.class_meta(r.type)["label"],
                         "degree": int(r.degree), "description": _s(r.description, 400),
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
    exact = ents[ents["title"].str.lower() == q.lower()]
    row = exact.iloc[0] if len(exact) else None
    if row is None:
        m = ents["title"].str.lower().str.contains(q.lower(), regex=False)
        if not m.any():
            return {"error": f"no entity matching {q}"}
        row = ents[m].sort_values("degree", ascending=False).iloc[0]
    title = str(row.title)
    edges = rels[(rels["source"] == title) | (rels["target"] == title)]
    neigh = set(edges["source"]) | set(edges["target"])
    neigh.discard(title)
    sub = ents[ents["title"].isin(neigh)].sort_values("degree", ascending=False).head(limit - 1)
    titles = set(sub["title"]) | {title}
    links_df = rels[rels["source"].isin(titles) & rels["target"].isin(titles)]
    links_df = links_df.sort_values("weight", ascending=False).head(limit * 3)
    center_c = _deepest_community(comms, ents).get(str(row.id))
    docs = _doc_map()
    nodes = [_entity_node(row, center_c, docs)]
    nodes += [_entity_node(r, center_c, docs) for r in sub.itertuples()]
    links = [{"source": _s(r.source, 140), "target": _s(r.target, 140),
              "weight": round(float(r.weight), 1)} for r in links_df.itertuples()]
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
        seed = ents[m].sort_values("degree", ascending=False)
        if seed.empty:
            return {"nodes": [], "links": [], "query": q, "total": 0}
        seeds = set(seed["title"].head(max(6, limit // 6)))
        rel = rels[rels["source"].isin(seeds) | rels["target"].isin(seeds)]
        rel = rel.sort_values("weight", ascending=False).head(limit * 2)
        titles = seeds | set(rel["source"]) | set(rel["target"])
        nodes_df = ents[ents["title"].isin(titles)].sort_values("degree", ascending=False).head(limit)
        titles = set(nodes_df["title"])
        rel = rel[rel["source"].isin(titles) & rel["target"].isin(titles)].head(limit * 2)
    else:
        nodes_df = ents.sort_values("degree", ascending=False).head(limit)
        titles = set(nodes_df["title"])
        rel = rels[rels["source"].isin(titles) & rels["target"].isin(titles)]
        rel = rel.sort_values("weight", ascending=False).head(limit * 2)
    nodes = [{"id": _s(r.title, 140), "title": _s(r.title, 140), "type": _s(r.type, 40),
              "degree": int(r.degree), "frequency": int(r.frequency),
              "description": _s(r.description, 700)} for r in nodes_df.itertuples()]
    links = [{"source": _s(r.source, 140), "target": _s(r.target, 140),
              "weight": round(float(r.weight), 1), "description": _s(r.description, 400)}
             for r in rel.itertuples()]
    _add_skill_links(nodes, links, _overlay_nodes(q, 10))
    return {"nodes": nodes, "links": links, "query": q, "total": len(ents) + len(_skill_overlay())}


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
