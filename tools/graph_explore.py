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
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "kb", "graphrag", "output")


def _load(name):
    import pandas as pd
    path = os.path.join(OUT, name + ".parquet")
    if not os.path.exists(path):
        return None
    return pd.read_parquet(path)


def _s(v, n):
    return "" if v is None else str(v)[:n]


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
    return {"rows": [{"id": int(r.human_readable_id), "title": _s(r.title, 120), "type": _s(r.type, 40),
                      "degree": int(r.degree), "frequency": int(r.frequency),
                      "description": _s(r.description, 500)} for r in df.itertuples()]}


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
    return {"rows": [{"source": _s(r.source, 90), "target": _s(r.target, 90), "weight": round(float(r.weight), 1),
                      "description": _s(r.description, 400)} for r in df.itertuples()]}


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
