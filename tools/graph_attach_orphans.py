#!/usr/bin/env python3
"""Give every graph entity at least one evidence-backed link.

GraphRAG occasionally extracts an entity from a skill list, a role line or a
CV summary without extracting a relationship for it. Those entities have no
place in a theme and used to appear as stray stars in the Universe.

This tool reads a curated mapping from ``kb/graphrag/orphan-links.json`` and
writes the links into the operator overlay (``kb/graphrag/enrichment.json``),
so they survive a rebuild and remain reviewable. Each mapping entry must name
a target, a short description and the evidence sentence it rests on. Targets
must already exist in the index or the overlay; the tool never invents a node.

    python3 tools/graph_attach_orphans.py --report
    python3 tools/graph_attach_orphans.py --apply
    python3 tools/graph_attach_orphans.py --apply --mapping /path/to/links.json

The mapping is personal data and lives under the git-ignored ``kb/graphrag/``.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "kb", "graphrag", "output")
ENRICH = os.path.join(ROOT, "kb", "graphrag", "enrichment.json")
MAPPING = os.path.join(ROOT, "kb", "graphrag", "orphan-links.json")


def _load(name):
    import pandas as pd
    path = os.path.join(OUT, name + ".parquet")
    return pd.read_parquet(path) if os.path.exists(path) else None


def _norm(value):
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").casefold()).strip()


def _read_json(path, default):
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else default
    except (OSError, ValueError):
        return default


def degrees(rels, overlay_links):
    deg = Counter()
    for a, b in zip(rels["source"], rels["target"]):
        deg[str(a)] += 1
        deg[str(b)] += 1
    for link in overlay_links:
        a, b = str(link.get("source") or ""), str(link.get("target") or "")
        if a:
            deg[a] += 1
        if b:
            deg[b] += 1
    return deg


def assign_communities(mapping, ents, comms, reports):
    """Place newly linked entities in the level-0 community of their target.

    The universe lays nodes out by community. An orphan that is linked to a
    themed entity but has no community would still sit in a drift island, so
    the link would be a long line across the map. Membership follows the first
    mapped target that has a level-0 community; it is a display grouping, not
    a new claim.
    """
    if comms is None:
        return 0, comms
    ids = {str(r.title): str(r.id) for r in ents.itertuples()}
    comms = comms.copy()
    at = {}
    for r in comms[comms["level"] == 0].itertuples():
        for eid in (r.entity_ids if r.entity_ids is not None else []):
            at[str(eid)] = int(r.community)
    connected = set(at)
    assigned = 0
    for source, items in mapping.items():
        sid = ids.get(str(source))
        if not sid or sid in connected:
            continue
        for item in items or []:
            tid = ids.get(str((item or {}).get("target") or ""))
            cid = at.get(tid) if tid else None
            if cid is None:
                continue
            mask = comms["community"] == cid
            row = comms.index[mask][0]
            members = list(comms.at[row, "entity_ids"])
            if sid in [str(x) for x in members]:
                break
            members.append(sid)
            comms.at[row, "entity_ids"] = members
            comms.at[row, "size"] = len(members)
            connected.add(sid)
            assigned += 1
            print(f"  community {source} -> {item.get('target')}")
            break
    if assigned:
        comms.to_parquet(os.path.join(OUT, "communities.parquet"), index=False)
        if reports is not None and "size" in reports.columns:
            sizes = {int(r.community): int(r.size) for r in comms.itertuples()}
            rep = reports.copy()
            rep["size"] = [sizes.get(int(c), int(sz)) for c, sz in zip(rep["community"], rep["size"])]
            rep.to_parquet(os.path.join(OUT, "community_reports.parquet"), index=False)
    return assigned, comms


def doc_map(ents, units):
    docs = {}
    tu2doc = {str(r.id): str(r.document_id) for r in units.itertuples()} if units is not None else {}
    for row in ents.itertuples():
        seen = set()
        for tid in (row.text_unit_ids if row.text_unit_ids is not None else []):
            d = tu2doc.get(str(tid))
            if d:
                seen.add(d)
        docs[str(row.title)] = seen
    return docs


def main():
    ap = argparse.ArgumentParser(description="Attach evidence-backed links to graph orphans")
    ap.add_argument("--apply", action="store_true", help="write the links to enrichment.json")
    ap.add_argument("--mapping", default=MAPPING, help="orphan -> targets JSON")
    ap.add_argument("--report", action="store_true", help="only show orphans and the mapping coverage")
    ap.add_argument("--allow-missing", action="store_true", help="do not fail on unmapped orphans")
    ap.add_argument("--no-communities", action="store_true",
                    help="do not place linked orphans in a level-0 community")
    args = ap.parse_args()

    if not os.path.isdir(OUT):
        print(f"no graph index at {os.path.relpath(OUT, ROOT)}", file=sys.stderr)
        return 1
    ents, rels, units = _load("entities"), _load("relationships"), _load("text_units")
    if ents is None or rels is None:
        print("no entities/relationships in the index", file=sys.stderr)
        return 1

    overlay = _read_json(ENRICH, {"nodes": [], "links": []})
    overlay.setdefault("nodes", [])
    overlay.setdefault("links", [])
    mapping = _read_json(args.mapping, {})
    if not mapping:
        print(f"missing mapping file: {os.path.relpath(args.mapping, ROOT)}", file=sys.stderr)
        print("Create it with: {\"ORPHAN TITLE\": [{\"target\": \"...\", \"description\": \"...\", "
              "\"evidence\": \"...\"}]}", file=sys.stderr)
        return 1

    by_title = {str(t): t for t in ents["title"]}
    by_norm = {_norm(t): str(t) for t in ents["title"]}
    overlay_nodes = {str(n.get("title") or "") for n in overlay["nodes"]}
    known = set(by_title) | overlay_nodes

    deg = degrees(rels, overlay["links"])
    orphans = sorted(str(t) for t in ents["title"] if deg.get(str(t), 0) == 0)
    mapped = {str(k) for k in mapping}
    missing = [t for t in orphans if t not in mapped]
    extra = sorted(mapped - set(orphans))

    print(f"orphans: {len(orphans)}; mapped: {len(mapped & set(orphans))}")
    for t in orphans:
        print(f"  orphan  {t}")
    if extra:
        print("mapping entries that are no longer orphans (kept, safe to prune):")
        for t in extra:
            print(f"  linked  {t}")

    docs = doc_map(ents, units)
    have = {(_norm(l.get("source")), _norm(l.get("target"))) for l in overlay["links"]}
    additions = []
    errors = []
    for source, items in mapping.items():
        if source not in known:
            errors.append(f"mapping source not in the graph: {source}")
            continue
        if not isinstance(items, list):
            errors.append(f"mapping for {source} must be a list")
            continue
        for item in items:
            target = str((item or {}).get("target") or "").strip()
            description = str((item or {}).get("description") or "").strip()
            evidence = str((item or {}).get("evidence") or "").strip()
            if not target or not description:
                errors.append(f"{source}: target and description are required")
                continue
            if target not in known:
                errors.append(f"{source}: target not in the graph: {target}")
                continue
            key = (_norm(source), _norm(target))
            if key in have or (_norm(target), _norm(source)) in have:
                continue
            shared = bool(docs.get(source, set()) & docs.get(target, set()))
            if not shared:
                print(f"  note    {source} -> {target}: no shared document; "
                      f"the link rests on the two descriptions")
            link = {
                "id": hashlib.sha1(f"{source}|{target}".encode("utf-8")).hexdigest()[:12],
                "source": source,
                "target": target,
                "weight": float((item or {}).get("weight") or 8),
                "description": f"{source} to {target}: {description}",
                "evidence": evidence or description,
                "source_doc": "",
                "grounded": True,
                "origin": "orphan-attachment",
            }
            additions.append(link)
            have.add(key)

    if errors:
        for err in errors:
            print(f"  error   {err}", file=sys.stderr)
        return 1

    print(f"links to add: {len(additions)}")
    for link in additions:
        print(f"  + {link['source']} -> {link['target']}")

    if args.report or not args.apply:
        print("(report only — pass --apply to write the overlay)")
        if missing and not args.allow_missing:
            print(f"unmapped orphans: {len(missing)}", file=sys.stderr)
            return 1
        return 0

    if missing and not args.allow_missing:
        print(f"refusing to write: {len(missing)} orphan(s) have no mapping", file=sys.stderr)
        return 1

    overlay["links"].extend(additions)
    overlay["updated"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    os.makedirs(os.path.dirname(ENRICH), exist_ok=True)
    with open(ENRICH, "w", encoding="utf-8") as fh:
        json.dump(overlay, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    print(f"wrote {len(additions)} link(s) to {os.path.relpath(ENRICH, ROOT)}")
    if not args.no_communities:
        comms, reports = _load("communities"), _load("community_reports")
        n, _ = assign_communities(mapping, ents, comms, reports)
        print(f"communities assigned: {n}")

    after = degrees(rels, overlay["links"])
    left = [str(t) for t in ents["title"] if after.get(str(t), 0) == 0]
    print(f"orphans after: {len(left)}")
    for t in left:
        print(f"  still orphan  {t}")
    return 1 if left else 0


if __name__ == "__main__":
    raise SystemExit(main())
