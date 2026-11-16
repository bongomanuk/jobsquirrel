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
    for section in ("classes", "relations", "profiles"):
        if isinstance(local.get(section), dict):
            for key, value in local[section].items():
                merged = dict(base.get(section, {}).get(key, {}))
                if isinstance(value, dict):
                    merged.update(value)
                else:
                    merged["label"] = str(value)
                base.setdefault(section, {})[key] = merged
    return base


RELATION_RULES = (
    # (source classes, target classes, relation, keyword hint in the description)
    ({"PERSON"}, {"ROLE"}, "HELD_ROLE", ""),
    ({"ROLE"}, {"PERSON"}, "HELD_ROLE", ""),
    ({"PERSON"}, {"ORGANIZATION", "TEAM"}, "AT_ORGANIZATION", ""),
    ({"ORGANIZATION", "TEAM"}, {"PERSON"}, "AT_ORGANIZATION", ""),
    ({"PERSON"}, {"PROJECT", "PRODUCT", "ACHIEVEMENT"}, "DELIVERED", ""),
    ({"PERSON"}, {"METRIC"}, "DELIVERED", ""),
    ({"PERSON"}, {"CERTIFICATION"}, "CERTIFIED_IN", ""),
    ({"CERTIFICATION"}, {"PERSON"}, "CERTIFIED_IN", ""),
    ({"PERSON"}, {"EDUCATION"}, "STUDIED_AT", ""),
    ({"EDUCATION"}, {"PERSON"}, "STUDIED_AT", ""),
    ({"PERSON"}, {"LANGUAGE"}, "SPEAKS", ""),
    ({"LANGUAGE"}, {"PERSON"}, "SPEAKS", ""),
    ({"PERSON"}, {"SKILL", "TECHNOLOGY", "PLATFORM"}, "USES", ""),
    ({"ROLE"}, {"ORGANIZATION", "TEAM"}, "AT_ORGANIZATION", ""),
    ({"ORGANIZATION", "TEAM"}, {"TEAM", "ORGANIZATION"}, "AT_ORGANIZATION", ""),
    # things built with things
    ({"PROJECT", "PRODUCT", "ROLE", "TEAM", "ORGANIZATION"},
     {"TECHNOLOGY", "PLATFORM", "SKILL"}, "USES", ""),
    ({"TECHNOLOGY", "PLATFORM", "SKILL"},
     {"PROJECT", "PRODUCT", "ROLE", "TEAM", "ORGANIZATION"}, "USES", ""),
    ({"TECHNOLOGY", "PLATFORM", "SKILL"},
     {"TECHNOLOGY", "PLATFORM", "SKILL"}, "RELATED_TO", ""),
    # what produced a number
    ({"TECHNOLOGY", "PLATFORM", "SKILL", "ORGANIZATION", "TEAM", "PROJECT", "PRODUCT"},
     {"METRIC"}, "DELIVERED", ""),
    ({"SKILL", "METRIC", "CERTIFICATION", "ACHIEVEMENT"},
     {"PROJECT", "PRODUCT", "ORGANIZATION", "TEAM"}, "EVIDENCED_BY", ""),
)
# Default weighting per class, per kind of role. This is what makes the same
# graph yield different cuts: a leadership CV leans on roles, teams and
# organisations; an AI engineering CV leans on technology, projects and metrics.
DEFAULT_PROFILES = {
    "leadership": {"ROLE": 2.0, "ORGANIZATION": 1.8, "TEAM": 1.7, "METRIC": 1.5,
                   "PROJECT": 1.2, "SKILL": 1.0, "TECHNOLOGY": 0.8, "PRODUCT": 1.0},
    "ai": {"TECHNOLOGY": 1.8, "SKILL": 1.7, "PROJECT": 1.6, "PLATFORM": 1.4,
           "METRIC": 1.3, "ROLE": 1.0, "ORGANIZATION": 0.9},
    "data": {"METRIC": 1.7, "TECHNOLOGY": 1.6, "SKILL": 1.5, "PROJECT": 1.4, "PLATFORM": 1.2},
    "security": {"CERTIFICATION": 1.8, "TECHNOLOGY": 1.5, "SKILL": 1.4, "PROJECT": 1.3},
    "architecture": {"TECHNOLOGY": 1.6, "PLATFORM": 1.5, "PROJECT": 1.4, "SKILL": 1.3,
                     "ORGANIZATION": 1.1},
    "default": {},
}

PROFILE_HINTS = (
    ("leadership", r"\b(head of|director|cto|cio|chief|vp|vice president|manager|chef|ledare)\b"),
    ("security", r"\b(security|säkerhet|cyber|soc|iam|identity)\b"),
    ("data", r"\b(data scientist|data engineer|analytics|machine learning engineer)\b"),
    ("architecture", r"\b(architect|arkitekt)\b"),
    ("ai", r"\b(ai|ml|llm|agent|genai|generative)\b"),
)


def relations() -> dict:
    return load().get("relations", {})


def relation_for(source_type: str, target_type: str, description: str = "") -> str:
    """Classify an untyped GraphRAG edge into the ontology's relation vocabulary."""
    s, t = class_for(source_type), class_for(target_type)
    low = " " + str(description or "").lower() + " "
    for srcs, dsts, rel, hint in RELATION_RULES:
        if s in srcs and t in dsts:
            if hint and rel == "AT_ORGANIZATION" and not __import__("re").search(hint, low):
                continue
            return rel
    return "RELATED_TO"


def weights_for(text: str) -> tuple:
    """(profile name, {CLASS: weight}) for the kind of role described by `text`."""
    low = " " + str(text or "").lower() + " "
    import re
    profiles = dict(DEFAULT_PROFILES)
    local = load().get("profiles") or {}
    for name, weights in local.items():
        base = dict(profiles.get(name) or {})
        if isinstance(weights, dict):
            base.update({str(k).upper(): float(v) for k, v in weights.items()})
        profiles[name] = base
    for name, pat in PROFILE_HINTS:
        if re.search(pat, low):
            return name, dict(profiles.get(name) or profiles.get("default") or {})
    return "default", dict(profiles.get("default") or {})


def weight_of(weights: dict, graph_type: str) -> float:
    return float((weights or {}).get(class_for(graph_type), 1.0))


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
