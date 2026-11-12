#!/usr/bin/env python3
"""Merge duplicate entities in the knowledge graph index.

GraphRAG extracts the same thing more than once: "ANA PLAN" and "ANAPLAN", or
an employer and its legal entities ("ANAPLAN", "ANAPLAN UK", "ANAPLAN UK LTD",
"ANAPLAN SINGAPORE PTE LTD", "ANAPLAN APAC HQ"). The graph then shows several
nodes for one real thing, which reads as duplication.

This tool merges, in the built index:

  * entities whose titles normalise to the same string within the same type
    (case, punctuation and spacing only);
  * organisation variants that reduce to an existing organisation once legal
    suffixes (Ltd, Pte Ltd, Inc, AB, GmbH, ...) and office qualifiers (UK,
    Singapore, APAC, HQ, ...) are stripped.

Aliases are recorded in the surviving entity's description, text units are
unioned, and relationships are rewritten to the survivor; duplicate edges are
summed and self-loops dropped. A timestamped backup of the parquet files is
written under state/backups/ before anything changes.

    python3 tools/graph_dedupe.py                 # dry run, list the merges
    python3 tools/graph_dedupe.py --apply         # write the merged index
    python3 tools/graph_dedupe.py --apply --near  # also merge near-duplicates

Run it after a graph rebuild. The dashboard caches graph reads for a minute.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "kb", "graphrag", "output")

LEGAL = {"ltd", "limited", "pte", "plc", "inc", "llc", "gmbh", "ab", "oy", "as",
         "sa", "ag", "bv", "nv", "corp", "corporation", "company", "co"}
OFFICE = {"uk", "us", "usa", "singapore", "apac", "emea", "amer", "hq", "office",
          "group", "holdings", "international", "global"}


def norm(title: str) -> str:
    """Lowercase and collapse spacing, but keep +, # and / so C, C# and C++ stay apart."""
    t = str(title or "").strip().lower()
    t = re.sub(r"[^a-z0-9+#/]+", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def symbolic(title: str) -> bool:
    """Titles like C++, C# or Spring/Camel must never be merged by punctuation."""
    t = str(title or "")
    return any(c in t for c in "+#/")


def base_org(title: str) -> str:
    """Strip legal suffixes and office qualifiers: 'ANAPLAN UK LTD' -> 'anaplan'."""
    words = norm(title).split()
    changed = True
    while words and changed:
        changed = False
        while words and words[-1] in LEGAL | OFFICE:
            words.pop()
            changed = True
    base = " ".join(words)
    if len(base) < 3 or base in LEGAL | OFFICE or symbolic(title):
        return ""
    return base


def load(name):
    import pandas as pd
    path = os.path.join(OUT, name + ".parquet")
    return pd.read_parquet(path) if os.path.exists(path) else None


def save(name, df):
    df.to_parquet(os.path.join(OUT, name + ".parquet"), index=False)


ALIAS_FILE = os.path.join(ROOT, "kb", "graphrag", "aliases.json")


def load_aliases():
    """Curated alias -> canonical overrides (kb/graphrag/aliases.json)."""
    try:
        with open(ALIAS_FILE, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return {}
    return {str(k): str(v) for k, v in (data or {}).items() if k and v}


def person_map(titles, types):
    """PETER HOLLAS -> PETER LIAM HOLLAS: token-subset, same surname, PERSON only.

    GraphRAG emits the same person under a fuller and a shorter name. Merging into
    the *longer* name keeps the operative node (the one relationships and the UI
    already use) without a curated list for every variant.
    """
    people = [t for t in titles if types.get(t, "").upper() == "PERSON"]
    out = {}
    for a in people:
        ta = norm(a).split()
        if len(ta) < 2:
            continue
        for b in people:
            if a == b or a in out:
                continue
            tb = norm(b).split()
            if len(tb) <= len(ta) or ta[-1] != tb[-1]:
                continue
            if set(ta) <= set(tb):
                out[a] = b
                break
    return out


def build_map(ents, near=False):
    """canonical title -> survivor title for every entity that should merge."""
    import pandas as pd

    titles = [str(t) for t in ents["title"]]
    types = {str(r["title"]): str(r.get("type") or "") for _, r in ents.iterrows()}
    # Which node is the one the graph actually uses? Connections first, then
    # mentions, then the more descriptive title. Merging into the busiest node
    # keeps the operative one (PETER LIAM HOLLAS, HAUD AB, TELIA COMPANY) instead
    # of an abbreviation that happens to normalise the same.
    rank = {}
    for _, r in ents.iterrows():
        t = str(r["title"])
        try:
            rank[t] = (int(r.get("degree") or 0), int(r.get("frequency") or 0), len(t))
        except (TypeError, ValueError):
            rank[t] = (0, 0, len(t))
    by_norm, by_org = {}, {}
    for t in titles:
        if len(norm(t)) >= 4 and not symbolic(t):
            # group by normalised title regardless of type: "CALLER-FRAUD
            # DETECTION PIPELINE" filed once as TECHNOLOGY and once as PROJECT is
            # the same thing, and the survivor keeps the busier node's type.
            by_norm.setdefault(norm(t), []).append(t)
        if types[t].upper() == "ORGANIZATION":
            base = base_org(t)
            if base:
                by_org.setdefault(base, []).append(t)

    merge = {}
    # exact duplicates within a type: keep the longest title (most descriptive)
    for group in by_norm.values():
        if len(group) < 2:
            continue
        keep = max(group, key=lambda t: rank.get(t, (0, 0, len(t))))
        for t in group:
            if t != keep:
                merge[t] = keep
    # organisation variants: keep the shortest base title if it is itself a node
    for base, group in by_org.items():
        if len(group) < 2:
            continue
        exact = next((t for t in group if norm(t) == base), None)
        keep = max(group, key=lambda t: rank.get(t, (0, 0, len(t))))
        for t in group:
            if t != keep:
                merge.setdefault(t, keep)

    # curated overrides win, when both ends exist
    known = set(titles)
    for alias, canonical in load_aliases().items():
        if alias in known and canonical in known and alias != canonical:
            merge.setdefault(alias, canonical)
    # one person, two names
    for alias, canonical in person_map(titles, types).items():
        merge.setdefault(alias, canonical)

    if near:
        # conservative near-duplicates: same type, one title is the other plus a
        # qualifier ("fraud detection" / "caller fraud detection" is not merged;
        # only token-subset with >= 2 shared words and a length ratio > 0.8)
        for i, a in enumerate(titles):
            for b in titles[i + 1:]:
                if types[a] != types[b] or a in merge or b in merge:
                    continue
                ta, tb = set(norm(a).split()), set(norm(b).split())
                if not ta or not tb:
                    continue
                shared = len(ta & tb)
                if shared >= 2 and shared / max(len(ta), len(tb)) >= 0.8:
                    long_, short = (a, b) if len(a) >= len(b) else (b, a)
                    merge.setdefault(short, long_)
    return _break_cycles(merge, rank)


def _break_cycles(merge, rank):
    """A -> B -> C -> A must collapse to one survivor, not loop."""
    for start in list(merge):
        path, cur = [], start
        while cur in merge and cur not in path:
            path.append(cur)
            cur = merge[cur]
        if cur in path:                       # found a cycle
            members = set(path[path.index(cur):]) | {cur}
            best = max(members, key=lambda t: rank.get(t, (0, 0, 0)))
            for m in members:
                if m != best:
                    merge[m] = best
            merge.pop(best, None)
    return merge


def apply_merge(ents, rels, merge, apply=False):
    import pandas as pd

    if not merge:
        return ents, rels, []

    # resolve chains (a->b, b->c)
    def canon(t):
        seen = set()
        while t in merge and t not in seen:
            seen.add(t)
            t = merge[t]
        return t

    aliases = {}
    for old, new in merge.items():
        aliases.setdefault(canon(new), []).append(old)

    ents = ents.copy()
    ents["title"] = [canon(str(t)) for t in ents["title"]]

    # merge rows that now share a title
    rows = []
    for title, g in ents.groupby("title", sort=False):
        r = g.iloc[0].copy()
        if len(g) > 1:
            units = set()
            for u in g["text_unit_ids"]:
                try:
                    units.update(list(u))
                except TypeError:
                    pass
            if "text_unit_ids" in g.columns:
                r["text_unit_ids"] = list(units)
            for col in ("frequency", "degree"):
                if col in g.columns:
                    r[col] = int(pd.to_numeric(g[col], errors="coerce").fillna(0).sum())
        al = aliases.get(title)
        if al:
            note = "Also known as: " + ", ".join(sorted(set(al))) + "."
            desc = str(r.get("description") or "")
            if note not in desc:
                r["description"] = (desc.rstrip() + " " + note).strip()
        rows.append(r)
    ents = pd.DataFrame(rows).reset_index(drop=True)

    rels = rels.copy()
    rels["source"] = [canon(str(t)) for t in rels["source"]]
    rels["target"] = [canon(str(t)) for t in rels["target"]]
    rels = rels[rels["source"] != rels["target"]]

    # collapse duplicate pairs (either direction) by summing weight
    def pair(r):
        a, b = str(r["source"]), str(r["target"])
        return (a, b) if a <= b else (b, a)

    rels["_pair"] = [pair(r) for _, r in rels.iterrows()]
    out = []
    for _, g in rels.groupby("_pair", sort=False):
        r = g.iloc[0].copy()
        if "weight" in g.columns:
            r["weight"] = float(pd.to_numeric(g["weight"], errors="coerce").fillna(0).sum())
        units = set()
        for u in g.get("text_unit_ids", []):
            try:
                units.update(list(u))
            except TypeError:
                pass
        if "text_unit_ids" in g.columns:
            r["text_unit_ids"] = list(units)
        out.append(r)
    rels = pd.DataFrame(out).drop(columns=["_pair"], errors="ignore").reset_index(drop=True)
    return ents, rels, sorted(aliases)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true", help="write the merged index")
    ap.add_argument("--near", action="store_true", help="also merge near-duplicate titles")
    args = ap.parse_args()

    ents, rels = load("entities"), load("relationships")
    if ents is None or rels is None:
        print("no graph index under kb/graphrag/output", file=sys.stderr)
        return 2

    merge = build_map(ents, near=args.near)
    if not merge:
        print("no duplicate entities found")
        return 0
    for old, new in sorted(merge.items()):
        print(f"merge  {old}  ->  {new}")

    new_ents, new_rels, _ = apply_merge(ents, rels, merge, apply=args.apply)
    print(f"{len(merge)} entities merged: {len(ents)} -> {len(new_ents)} entities, "
          f"{len(rels)} -> {len(new_rels)} relationships")

    if not args.apply:
        print("(dry run - pass --apply to write the index)")
        return 0

    backup = os.path.join(ROOT, "state", "backups", "graph-dedupe-" + time.strftime("%Y%m%d-%H%M%S"))
    os.makedirs(backup, exist_ok=True)
    for name in ("entities", "relationships"):
        shutil.copy2(os.path.join(OUT, name + ".parquet"), os.path.join(backup, name + ".parquet"))
    save("entities", new_ents)
    save("relationships", new_rels)
    print(f"backup: {os.path.relpath(backup, ROOT)}")
    print("done; the dashboard caches graph reads for a minute, or reload the page")
    return 0


if __name__ == "__main__":
    sys.exit(main())
