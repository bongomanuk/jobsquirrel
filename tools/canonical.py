#!/usr/bin/env python3
"""Canonical wording for facts that must survive graph and document generation.

A small, configurable set of replacements and forbidden variants. The knowledge
base ingest normalises source text before indexing, the CV/letter renderers
normalise content packs before rendering, and the document gate fails if a
generated file still contains a forbidden variant.

Rules live in config/canonical-facts.json (falling back to the public example).
"""
from __future__ import annotations

import json
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_DIR = os.path.join(ROOT, "config")


def _load():
    for name in ("canonical-facts.json", "canonical-facts.example.json"):
        path = os.path.join(CONFIG_DIR, name)
        if os.path.isfile(path):
            try:
                with open(path, encoding="utf-8") as fh:
                    data = json.load(fh)
                return data if isinstance(data, dict) else {}
            except (OSError, ValueError):
                pass
    return {}


RULES = _load()


def normalize(text):
    """Apply the canonical replacements to a string (idempotent)."""
    text = str(text or "")
    for rule in RULES.get("replace", []) or []:
        wrong, right = str(rule.get("wrong") or ""), str(rule.get("right") or "")
        if wrong and right:
            text = re.sub(wrong, right, text)
    return text


def normalize_data(value):
    """Recursively normalize every string in a JSON-like structure."""
    if isinstance(value, str):
        return normalize(value)
    if isinstance(value, list):
        return [normalize_data(v) for v in value]
    if isinstance(value, dict):
        return {k: normalize_data(v) for k, v in value.items()}
    return value


def explain(text):
    """Return (found, canonical) pairs for forbidden variants in text."""
    text = str(text or "")
    out = []
    for rule in RULES.get("replace", []) or []:
        wrong, right = str(rule.get("wrong") or ""), str(rule.get("right") or "")
        if not wrong or not right:
            continue
        for m in re.finditer(wrong, text):
            pair = (m.group(0), right)
            if pair not in out:
                out.append(pair)
    return out


def violations(text):
    """The forbidden variants still present in text."""
    return [found for found, _ in explain(text)]
