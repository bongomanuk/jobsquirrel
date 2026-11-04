#!/usr/bin/env python3
"""The small, explicit ontology behind the knowledge graph and applications.

GraphRAG emits a bag of typed entities and untyped relationships. This module
turns that into a stable vocabulary the UI can show and the application layer
can use:

  classes   Person, Organisation, Role, Skill, Technology, Project, ...
  relations Held role, At organisation, Requires, Satisfies, ...

`config/ontology.json` overrides the shipped example; unknown GraphRAG types
fall back to Concept. The graph view, the class view and the side panel all read
their labels and colours from here.
"""
from __future__ import annotations

import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXAMPLE = os.path.join(ROOT, "config", "ontology.example.json")
LOCAL = os.path.join(ROOT, "config", "ontology.json")

FALLBACK = {"classes": {"CONCEPT": {"label": "Concept", "color": "#94a3b8",
                                    "description": "Anything not in a more specific class."}},
            "relations": {}}

ALIASES = {
    "COMPANY": "ORGANIZATION", "EMPLOYER": "ORGANIZATION", "CLIENT": "ORGANIZATION",
    "JOB": "ROLE", "POSITION": "ROLE", "TITLE": "ROLE",
    "TOOL": "TECHNOLOGY", "FRAMEWORK": "TECHNOLOGY",
    "OUTCOME": "ACHIEVEMENT", "RESULT": "METRIC", "NUMBER": "METRIC",
    "DEGREE": "EDUCATION", "COURSE": "EDUCATION", "CERTIFICATE": "CERTIFICATION",
    "PLACE": "LOCATION", "COUNTRY": "LOCATION", "CITY": "LOCATION",
    "DEPARTMENT": "TEAM", "GROUP": "TEAM", "SQUAD": "TEAM",
}


def _load(path):
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def load() -> dict:
    base = _load(EXAMPLE)
    if not base:
        base = json.loads(json.dumps(FALLBACK))
    local = _load(LOCAL)
    for section in ("classes", "relations"):
        if isinstance(local.get(section), dict):
            for key, value in local[section].items():
                merged = dict(base.get(section, {}).get(key, {}))
                if isinstance(value, dict):
                    merged.update(value)
                else:
                    merged["label"] = str(value)
                base.setdefault(section, {})[key] = merged
    return base


def class_for(graph_type: str) -> str:
    t = str(graph_type or "").strip().upper()
    t = ALIASES.get(t, t)
    return t if t in load().get("classes", {}) else "CONCEPT"


def class_meta(graph_type: str) -> dict:
    c = class_for(graph_type)
    meta = dict(load().get("classes", {}).get(c, {}))
    meta.setdefault("label", c.title())
    meta.setdefault("color", "#94a3b8")
    meta.setdefault("description", "")
    meta["id"] = c
    return meta


def summary(entities=None) -> dict:
    """The ontology plus per-class counts from an entities dataframe."""
    data = load()
    counts = {}
    if entities is not None and "type" in entities.columns:
        for t in entities["type"].tolist():
            c = class_for(t)
            counts[c] = counts.get(c, 0) + 1
    classes = []
    for cid, meta in data.get("classes", {}).items():
        row = dict(meta)
        row["id"] = cid
        row["count"] = counts.get(cid, 0)
        classes.append(row)
    classes.sort(key=lambda x: (-x["count"], x["label"]))
    relations = [{"id": k, **v} for k, v in data.get("relations", {}).items()]
    return {"classes": classes, "relations": relations, "total": sum(counts.values()),
            "note": "GraphRAG edges are generic RELATED_TO links; the application "
                    "layer adds REQUIRES and SATISFIES when a job is assessed."}
