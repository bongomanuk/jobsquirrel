#!/usr/bin/env python3
"""A small message-passing importance score for the knowledge graph.

The graph is a weighted network. An entity matters when it is connected to
important things with strong relationships, and when its own description
carries impact language or a high-value type (a delivered project, a product,
a metric, a first-of-its-kind achievement).

This is the graph equivalent of one forward pass of a neural network:

    h_i <- (1-d) * prior_i + d * sum_j (w_ji / sum_k w_jk) * h_j

run for a few iterations, then normalised to a percentile. The result is
stored as `importance` (0..1) on every entity and used by the graph views and
the context builder. It is deliberately deterministic and offline: no LLM,
no invented facts.

    .venv-graphrag/bin/python tools/graph_importance.py --top 20
    .venv-graphrag/bin/python tools/graph_importance.py --json
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "kb", "graphrag", "output")
CACHE = os.path.join(ROOT, "state", "graph-importance.json")
OVERLAY = os.path.join(ROOT, "kb", "graphrag", "enrichment.json")
EDITS = os.path.join(ROOT, "kb", "graphrag", "edits.json")

TYPE_WEIGHT = {
    "PERSON": 1.10, "ORGANIZATION": 1.00, "TEAM": 1.05, "ROLE": 1.10,
    "SKILL": 1.00, "TECHNOLOGY": 1.00, "PROJECT": 1.35, "PRODUCT": 1.25,
    "PLATFORM": 1.10, "METRIC": 1.25, "CERTIFICATION": 1.05,
    "EDUCATION": 1.00, "ACHIEVEMENT": 1.60, "CONCEPT": 0.85,
}
# language that marks a delivered, first-of-its-kind or measured outcome
IMPACT = (
    "first", "world", "worlds", "largest", "official", "founded", "created",
    "built", "delivered", "architected", "launched", "invented", "patent",
    "record", "pioneering", "landmark", "award", "registered", "digitised",
    "digitized", "scaled", "transformation", "turnaround", "revenue",
    "multi-tenant", "enterprise", "platform", "led", "chief", "founding",
    "register", "architect", "pioneering",
)

# whole phrases that mark a landmark outcome, not just a word
PHRASE_BONUS = (
    ("first ever", 0.55), ("world register", 0.50), ("world's largest", 0.50),
    ("worlds largest", 0.50), ("official world", 0.40), ("first official", 0.35),
    ("largest database", 0.35), ("largest ... database", 0.0), ("record", 0.20),
)


def _load(name):
    import pandas as pd
    path = os.path.join(OUT, name + ".parquet")
    return pd.read_parquet(path) if os.path.exists(path) else None


def _norm(s):
    return re.sub(r"[^a-z0-9]+", " ", str(s or "").lower()).strip()


def _mtime(path):
    try:
        return os.path.getmtime(path)
    except OSError:
        return 0


def _cache_stamp():
    return [round(_mtime(os.path.join(OUT, n + ".parquet")), 2)
            for n in ("entities", "relationships")] + [round(_mtime(OVERLAY), 2), round(_mtime(EDITS), 2)]


def _cached():
    try:
        with open(CACHE, encoding="utf-8") as fh:
            data = json.load(fh)
        if data.get("stamp") == _cache_stamp():
            return data.get("scores") or {}
    except (OSError, ValueError):
        pass
    return None


def _write(scores):
    os.makedirs(os.path.dirname(CACHE), exist_ok=True)
    tmp = CACHE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump({"stamp": _cache_stamp(), "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                   "scores": scores}, fh)
    os.replace(tmp, CACHE)


def scores(force=False):
    """title -> importance percentile (0..1)."""
    if not force:
        hit = _cached()
        if hit:
            return hit
    ents, rels = _load("entities"), _load("relationships")
    if ents is None or rels is None:
        return {}
    import math

    nodes = [(str(r.title), str(r.type), int(r.frequency), str(r.description or ""))
             for r in ents.itertuples()]
    edges = [(str(r.source), str(r.target), float(r.weight)) for r in rels.itertuples()]
    try:
        with open(EDITS, encoding="utf-8") as fh:
            edits = json.load(fh)
        overrides = edits.get("nodes") or {}
    except (OSError, ValueError):
        overrides = {}
    nodes = [(t, (overrides.get(t) or {}).get("type") or ty,
              f, (overrides.get(t) or {}).get("description") or d)
             for t, ty, f, d in nodes]
    try:
        with open(OVERLAY, encoding="utf-8") as fh:
            ov = json.load(fh)
        have = {_norm(t) for t, _ty, _f, _d in nodes}
        for x in (ov.get("nodes") or []):
            t = str(x.get("title") or "")
            if t and _norm(t) not in have:
                nodes.append((t, str(x.get("type") or "CONCEPT"), 1, str(x.get("description") or "")))
                have.add(_norm(t))
        for x in (ov.get("links") or []):
            if x.get("source") and x.get("target"):
                edges.append((str(x["source"]), str(x["target"]), float(x.get("weight") or 1)))
    except (OSError, ValueError):
        pass

    titles = [t for t, _ty, _f, _d in nodes]
    idx = {t: i for i, t in enumerate(titles)}
    n = len(titles)
    prior = [1.0] * n
    max_w = {}
    for title, ntype, freq, desc in nodes:
        i = idx[title]
        base = TYPE_WEIGHT.get(ntype.upper(), 1.0)
        base *= 1.0 + min(0.55, math.log1p(freq) * 0.14)
        text = (title + " " + desc).lower()
        cues = sum(1 for w in IMPACT if re.search(r"\b" + re.escape(w) + r"\b", text))
        base *= 1.0 + min(0.85, cues * 0.10)
        for phrase, bonus in PHRASE_BONUS:
            if bonus and phrase in text:
                base *= 1.0 + bonus
        prior[i] = base

    adj = [dict() for _ in range(n)]
    for source, target, weight in edges:
        a, b = idx.get(source), idx.get(target)
        if a is None or b is None:
            continue
        w = max(0.1, weight)
        adj[a][b] = adj[a].get(b, 0.0) + w
        adj[b][a] = adj[b].get(a, 0.0) + w * 0.45   # a relationship is evidence both ways
        max_w[a] = max(max_w.get(a, 0), w)
        max_w[b] = max(max_w.get(b, 0), w)

    for i, w in max_w.items():
        prior[i] *= 1.0 + min(0.30, w / 100.0)

    out_sum = [sum(d.values()) or 1.0 for d in adj]
    h = list(prior)
    damp = 0.85
    for _ in range(30):
        new = [0.0] * n
        for i, row in enumerate(adj):
            if not row:
                continue
            factor = damp * h[i] / out_sum[i]
            for j, w in row.items():
                new[j] += factor * w
        h = [(1 - damp) * prior[i] + new[i] for i in range(n)]
        total = sum(h) or 1.0
        h = [x / total for x in h]

    order = sorted(range(n), key=lambda i: h[i])
    pct = [0.0] * n
    for rank, i in enumerate(order):
        pct[i] = rank / max(1, n - 1)
    result = {titles[i]: round(pct[i], 4) for i in range(n)}
    _write(result)
    return result


def main():
    ap = argparse.ArgumentParser(description="Weighted entity importance")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--top", type=int, default=15)
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()
    sc = scores(force=args.force)
    if args.json:
        print(json.dumps(sc, indent=2))
        return 0
    for title, score in sorted(sc.items(), key=lambda kv: kv[1], reverse=True)[:args.top]:
        print(f"{score:.3f}  {title}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
