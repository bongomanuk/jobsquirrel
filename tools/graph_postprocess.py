#!/usr/bin/env python3
"""Conservatively merge near-duplicate entities in the GraphRAG output.

GraphRAG's extractor keeps "BSS TEAM" and "BSS TEAMS" as separate nodes, and
the same happens with hyphenation ("SHARED-TECHNOLOGY TEAM" vs "SHARED
TECHNOLOGY TEAM"). That fragments the graph and inflates the communities.

This pass is deliberately narrow. It merges:
  * titles that differ only in case, spacing, hyphens, slashes, commas or
    ampersands (so C, C#, C++ and C/C++ stay separate);
  * a plural team title when the singular team exists and neither is a metric;
  * a small curated alias list.

It never changes descriptions into claims, never merges different
organisations, and always writes a backup first.

    .venv-graphrag/bin/python tools/graph_postprocess.py --dry-run
    .venv-graphrag/bin/python tools/graph_postprocess.py --apply
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import sys
import time
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "kb", "graphrag", "output")
sys.path.insert(0, os.path.join(ROOT, "tools"))
try:
    import ontology as ONT
except Exception:  # pragma: no cover - the report must still run
    ONT = None

ALIASES = {
    "SHARED-TECHNOLOGY TEAM": "SHARED TECHNOLOGY TEAM",
    "DIVX API TEAM": "DIVISION X API TEAM",
    "BSS TEAMS": "BSS TEAM",
    "IOT TEAMS": "IOT TEAM",
}


def load(name):
    import pandas as pd
    path = os.path.join(OUT, name + ".parquet")
    return pd.read_parquet(path) if os.path.exists(path) else None


def safe_key(title):
    """Punctuation-insensitive, but symbols that carry meaning are kept."""
    t = str(title or "").strip().lower()
    t = t.replace("&", " and ")
    t = re.sub(r"[\u2013\u2014]", "-", t)
    t = t.replace("-", " ").replace("_", " ").replace("/", " ")
    t = re.sub(r"[,;:()\[\]]", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def class_of(t):
    return ONT.class_for(t) if ONT else str(t).upper()


def pick_survivor(rows):
    return sorted(rows, key=lambda r: (-int(r.degree), -len(str(r.description or ""))))[0]


def merge_groups(ents):
    """Return title -> survivor row, plus a human-readable merge report."""
    by_key = defaultdict(list)
    for r in ents.itertuples():
        by_key[safe_key(r.title)].append(r)
    mapping = {}
    merges = []
    for key, rows in by_key.items():
        if len(rows) < 2:
            continue
        classes = {class_of(r.type) for r in rows}
        if len(classes) > 1:
            continue        # a metric and an organisation with the same name are not the same thing
        survivor = pick_survivor(rows)
        for r in rows:
            if r.title != survivor.title:
                mapping[r.title] = survivor
        merges.append((survivor.title, sorted({r.title for r in rows})))

    # plural team variants, only when the singular exists and neither is a metric
    by_title = {str(r.title).upper(): r for r in ents.itertuples()}
    for title, r in list(by_title.items()):
        if not title.endswith("S") or class_of(r.type) == "METRIC":
            continue
        singular = by_title.get(title[:-1])
        if not singular or class_of(singular.type) == "METRIC":
            continue
        if "TEAM" not in title:
            continue
        if title in mapping:
            continue
        mapping[r.title] = singular
        merges.append((singular.title, [r.title]))

    # explicit aliases win over fuzzy choices
    for title, target in ALIASES.items():
        src = by_title.get(title)
        dst = by_title.get(target)
        if src and dst and src.title != dst.title:
            mapping[src.title] = dst
            merges.append((dst.title, [src.title]))
    return mapping, merges


def main():
    ap = argparse.ArgumentParser(description="Merge conservative entity aliases in the graph")
    ap.add_argument("--apply", action="store_true", help="write the merged parquet files")
    ap.add_argument("--dry-run", action="store_true", help="only report (default)")
    args = ap.parse_args()

    ents = load("entities")
    rels = load("relationships")
    comms = load("communities")
    units = load("text_units")
    if ents is None or rels is None:
        print("no graph index", file=sys.stderr)
        return 1

    mapping, merges = merge_groups(ents)
    if not mapping:
        print("no conservative merges found")
        return 0

    print(f"{len(mapping)} title(s) would merge into {len({id(v) for v in mapping.values()})} survivor(s):")
    for target, sources in merges[:30]:
        print("  " + " | ".join(sources) + f"  ->  {target}")
    if len(merges) > 30:
        print(f"  ... {len(merges)-30} more")

    if not args.apply:
        print("\n(dry run — pass --apply to write the merged index)")
        return 0

    import pandas as pd

    stamp = time.strftime("%Y%m%d-%H%M%S")
    backup = os.path.join(OUT, f".postprocess-backup-{stamp}")
    os.makedirs(backup, exist_ok=True)
    for name in ("entities", "relationships", "communities", "text_units"):
        src = os.path.join(OUT, name + ".parquet")
        if os.path.exists(src):
            shutil.copy2(src, os.path.join(backup, name + ".parquet"))

    # survivor UUID and title for each mapped row
    uuid_map, title_map = {}, {}
    survivors = {}
    for r in ents.itertuples():
        target = mapping.get(r.title)
        if target is not None:
            uuid_map[str(r.id)] = str(target.id)
            title_map[str(r.title)] = str(target.title)
            survivors.setdefault(str(target.id), target)
        else:
            survivors.setdefault(str(r.id), r)

    # merge descriptions and provenance into the survivor rows
    merged_rows = {}
    for r in ents.itertuples():
        sid = uuid_map.get(str(r.id), str(r.id))
        base = merged_rows.get(sid)
        if base is None:
            merged_rows[sid] = {
                "id": sid, "title": str(r.title), "type": str(r.type),
                "description": str(r.description or ""),
                "text_unit_ids": list(r.text_unit_ids or []),
                "frequency": int(r.frequency),
            }
        else:
            if len(str(r.description or "")) > len(base["description"]):
                base["description"] = str(r.description or "")
                base["title"] = str(r.title)
                base["type"] = str(r.type)
            base["text_unit_ids"] = list(dict.fromkeys(base["text_unit_ids"] + list(r.text_unit_ids or [])))
            base["frequency"] = max(base["frequency"], int(r.frequency))

    rows = []
    for rec in merged_rows.values():
        rows.append({
            "id": rec["id"], "human_readable_id": 0, "title": rec["title"],
            "type": rec["type"], "description": rec["description"],
            "text_unit_ids": rec["text_unit_ids"], "frequency": rec["frequency"],
            "degree": 0,
        })
    new_ents = pd.DataFrame(rows)

    # relationships: remap titles, drop self-loops, merge duplicate pairs
    recs = {}
    for r in rels.itertuples():
        s = title_map.get(str(r.source), str(r.source))
        t = title_map.get(str(r.target), str(r.target))
        if s == t:
            continue
        key = (s, t)
        if key not in recs or float(r.weight) > float(recs[key]["weight"]):
            recs[key] = {"source": s, "target": t, "description": str(r.description or ""),
                         "weight": float(r.weight), "text_unit_ids": list(r.text_unit_ids or [])}
    new_rels = pd.DataFrame(list(recs.values()))

    # recompute degree from the merged relationships
    deg = defaultdict(int)
    for s, t in zip(new_rels["source"], new_rels["target"]):
        deg[str(s)] += 1
        deg[str(t)] += 1
    new_ents["degree"] = [deg.get(str(t), 0) for t in new_ents["title"]]

    # remap UUID references in communities and text units
    if comms is not None:
        def remap_ids(ids):
            return list(dict.fromkeys(uuid_map.get(str(x), str(x)) for x in (ids or [])))
        comms = comms.copy()
        comms["entity_ids"] = comms["entity_ids"].map(remap_ids)
    if units is not None:
        units = units.copy()
        units["entity_ids"] = units["entity_ids"].map(
            lambda ids: list(dict.fromkeys(uuid_map.get(str(x), str(x)) for x in (ids or []))))

    new_ents.to_parquet(os.path.join(OUT, "entities.parquet"), index=False)
    new_rels.to_parquet(os.path.join(OUT, "relationships.parquet"), index=False)
    if comms is not None:
        comms.to_parquet(os.path.join(OUT, "communities.parquet"), index=False)
    if units is not None:
        units.to_parquet(os.path.join(OUT, "text_units.parquet"), index=False)

    print(f"\napplied: {len(ents)} -> {len(new_ents)} entities, "
          f"{len(rels)} -> {len(new_rels)} relationships")
    print(f"backup: {os.path.relpath(backup, ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
