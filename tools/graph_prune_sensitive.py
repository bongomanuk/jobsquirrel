#!/usr/bin/env python3
"""Remove employment-contract material from the knowledge graph.

The graph should describe work and outcomes, not contractual machinery:
garden leave, pay in lieu of notice, notice periods, probation, grievances,
salary/bonus details and the generic parties from a contract (Company,
Employee, Agent, Supplier...). This pass removes those entities and the
relationships that depend on them, redacts remaining descriptions/reports and
drops the contract documents from the provenance tables.

It is deliberately a post-processing pass over the existing index so it can be
run immediately. Contract documents are also excluded from future ingestion in
kb/sources/.ingestignore, so a rebuild starts clean.

    .venv-graphrag/bin/python tools/graph_prune_sensitive.py --dry-run
    .venv-graphrag/bin/python tools/graph_prune_sensitive.py --apply
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import shutil
import sys
import time
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "kb", "graphrag", "output")
ENRICH = os.path.join(ROOT, "kb", "graphrag", "enrichment.json")
EDITS = os.path.join(ROOT, "kb", "graphrag", "edits.json")
sys.path.insert(0, os.path.join(ROOT, "tools"))
import sensitive as S  # noqa: E402

CONTRACT_DOC = re.compile(
    r"(contract|employment agreement|key information|digisourced|juridiska|"
    r"work finding|assignment confirmation|\bterms\b)", re.I)


def load(name):
    import pandas as pd
    path = os.path.join(OUT, name + ".parquet")
    return pd.read_parquet(path) if os.path.exists(path) else None


def redact_value(value):
    if isinstance(value, str):
        return S.redact(value)
    if isinstance(value, list):
        return [redact_value(x) for x in value]
    if isinstance(value, dict):
        return {k: redact_value(v) for k, v in value.items()}
    return value


def clean_vectors():
    """Delete vector rows whose parquet entity/unit/community no longer exists."""
    try:
        import lancedb
        db = lancedb.connect(os.path.join(OUT, "lancedb"))
    except Exception as exc:
        print(f"vector store unavailable: {type(exc).__name__}: {exc}")
        return
    for table_name, parquet in (("entity_description", "entities"),
                                ("text_unit_text", "text_units"),
                                ("community_full_content", "community_reports")):
        try:
            table = db.open_table(table_name)
            frame = table.to_pandas()
            valid_df = load(parquet)
            valid = {str(x) for x in valid_df["id"]} if valid_df is not None and "id" in valid_df.columns else set()
            bad = [str(x) for x in frame["id"] if str(x) not in valid]
            removed = 0
            for i in range(0, len(bad), 100):
                chunk = bad[i:i + 100]
                sql = "id IN (" + ",".join("'" + x.replace("'", "''") + "'" for x in chunk) + ")"
                table.delete(sql)
                removed += len(chunk)
            print(f"{table_name}: removed {removed} orphan vector row(s)")
        except Exception as exc:
            print(f"{table_name}: vector cleanup skipped ({type(exc).__name__}: {exc})")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--vectors", action="store_true",
                    help="remove vector-store rows that no longer have a parquet row")
    args = ap.parse_args()

    ents = load("entities")
    rels = load("relationships")
    comms = load("communities")
    reports = load("community_reports")
    docs = load("documents")
    units = load("text_units")
    if ents is None or rels is None:
        print("no graph index", file=sys.stderr)
        return 1

    blocked = {str(t) for t in ents["title"] if S.blocked_title(t)}
    # contract-derived metrics/products whose whole description is sensitive
    for r in ents.itertuples():
        title = str(r.title)
        if title in blocked:
            continue
        if S.sensitive(r.description) and str(r.type).upper() in ("METRIC", "PRODUCT", "CONCEPT"):
            if not S.redact(str(r.description or "")).strip():
                blocked.add(title)
    print(f"entities blocked by title/sensitive-only: {len(blocked)}")
    for t in sorted(blocked)[:30]:
        print("  -", t)
    if len(blocked) > 30:
        print(f"  ... {len(blocked)-30} more")

    # contract documents and their text units
    drop_docs = set()
    if docs is not None:
        for r in docs.itertuples():
            if CONTRACT_DOC.search(str(r.title)):
                drop_docs.add(str(r.id))
    drop_units = set()
    if units is not None:
        for r in units.itertuples():
            if str(r.document_id) in drop_docs:
                drop_units.add(str(r.id))

    if args.vectors:
        clean_vectors()
        return 0
    if not args.apply:
        empty_ents = sum(1 for ids in ents["text_unit_ids"] if len(list(ids)) == 0)
        empty_rels = sum(1 for ids in rels["text_unit_ids"] if len(list(ids)) == 0)
        print(f"contract documents to drop: {len(drop_docs)}, text units: {len(drop_units)}")
        print(f"ungrounded entities to drop: {empty_ents}; relationships without provenance: {empty_rels}")
        print("(dry run — pass --apply to write the cleaned index)")
        return 0

    stamp = time.strftime("%Y%m%d-%H%M%S")
    backup = os.path.join(OUT, f".sensitive-backup-{stamp}")
    os.makedirs(backup, exist_ok=True)
    for name in ("entities", "relationships", "communities", "community_reports",
                 "documents", "text_units"):
        src = os.path.join(OUT, name + ".parquet")
        if os.path.exists(src):
            shutil.copy2(src, os.path.join(backup, name + ".parquet"))

    # provenance first: strip the contract text units, then treat any entity
    # left without a text unit as contract residue. Such an entity has no
    # surviving evidence, so it cannot stay in a grounded graph.
    def clean_ids(ids):
        return [x for x in (list(ids) if ids is not None else [])
                if str(x) not in drop_units]

    ents = ents.copy()
    if "text_unit_ids" in ents.columns:
        ents["text_unit_ids"] = ents["text_unit_ids"].map(clean_ids)
    ungrounded = set(ents.loc[ents["text_unit_ids"].map(len) == 0, "title"].astype(str))
    drop_titles = set(blocked) | ungrounded
    print(f"entities dropped: {len(drop_titles)} "
          f"({len(blocked)} blocked by name, {len(ungrounded)} with no surviving provenance)")

    # relationships: drop either endpoint, anything whose only provenance was
    # a contract text unit, and any edge left pointing at a removed entity.
    # Recompute both degree fields afterwards.
    kept_titles = {str(t) for t in ents["title"] if str(t) not in drop_titles}
    rel = rels[~rels["source"].astype(str).isin(drop_titles) &
               ~rels["target"].astype(str).isin(drop_titles) &
               rels["source"].astype(str).isin(kept_titles) &
               rels["target"].astype(str).isin(kept_titles)].copy()
    rel["description"] = [S.redact(str(d or "")) for d in rel["description"]]
    if "text_unit_ids" in rel.columns:
        rel["text_unit_ids"] = rel["text_unit_ids"].map(clean_ids)
        rel = rel[rel["text_unit_ids"].map(len) > 0].copy()
    deg = Counter()
    for a, b in zip(rel["source"], rel["target"]):
        deg[str(a)] += 1
        deg[str(b)] += 1
    if "combined_degree" in rel.columns:
        rel["combined_degree"] = [deg[str(a)] + deg[str(b)]
                                  for a, b in zip(rel["source"], rel["target"])]
    rel.to_parquet(os.path.join(OUT, "relationships.parquet"), index=False)

    # entities (degree now reflects the surviving relationships)
    keep = ents[~ents["title"].astype(str).isin(drop_titles)].copy()
    keep["description"] = [S.redact(str(d or "")) for d in keep["description"]]
    keep["degree"] = [deg.get(str(t), 0) for t in keep["title"]]
    keep.to_parquet(os.path.join(OUT, "entities.parquet"), index=False)

    # communities: drop ungrounded communities, then remove deleted members
    # and relationships and recount. A community without a text unit has no
    # evidence behind it and is removed with its report.
    kept_ids = set(keep["id"].astype(str))
    kept_rel = set(rel["id"].astype(str))
    kept_comm = set()
    if comms is not None:
        comms = comms.copy()
        comms["entity_ids"] = comms["entity_ids"].map(
            lambda ids: [x for x in (list(ids) if ids is not None else [])
                         if str(x) in kept_ids])
        if "relationship_ids" in comms.columns:
            comms["relationship_ids"] = comms["relationship_ids"].map(
                lambda ids: [x for x in (list(ids) if ids is not None else [])
                             if str(x) in kept_rel])
        if "text_unit_ids" in comms.columns:
            comms["text_unit_ids"] = comms["text_unit_ids"].map(clean_ids)
        comms["size"] = comms["entity_ids"].map(lambda ids: len(list(ids)))
        comms = comms[comms["entity_ids"].map(len) > 0].copy()
        if "text_unit_ids" in comms.columns:
            comms = comms[comms["text_unit_ids"].map(len) > 0].copy()
        kept_comm = set(int(x) for x in comms["community"])
        comms.to_parquet(os.path.join(OUT, "communities.parquet"), index=False)

    # reports: only for surviving communities, never for a blocked/sensitive
    # title, and redact the rest.
    if reports is not None:
        rep = reports[reports["community"].isin(kept_comm)].copy()
        rep = rep[~rep["title"].astype(str).map(S.blocked_title)].copy()
        rep = rep[~rep["title"].astype(str).map(S.sensitive)].copy()
        for col in ("title", "summary", "full_content", "findings",
                    "rating_explanation", "full_content_json"):
            if col in rep.columns:
                rep[col] = rep[col].map(redact_value)
        if "full_content" in rep.columns:
            rep = rep[rep["full_content"].astype(str).str.strip() != ""].copy()
        rep.to_parquet(os.path.join(OUT, "community_reports.parquet"), index=False)

    # documents / text units
    if docs is not None:
        docs[~docs["id"].astype(str).isin(drop_docs)].to_parquet(
            os.path.join(OUT, "documents.parquet"), index=False)
    if units is not None:
        u = units[~units["id"].astype(str).isin(drop_units)].copy()
        u["text"] = [S.redact(str(t or "")) for t in u["text"]]
        if "entity_ids" in u.columns:
            u["entity_ids"] = u["entity_ids"].map(
                lambda ids: [x for x in (list(ids) if ids is not None else [])
                             if str(x) in kept_ids])
        u.to_parquet(os.path.join(OUT, "text_units.parquet"), index=False)

    # operator overlays
    for path in (ENRICH, EDITS):
        try:
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            continue
        if "nodes" in data and isinstance(data["nodes"], list):
            data["nodes"] = [n for n in data["nodes"] if not S.blocked_title(n.get("title"))]
        if "links" in data and isinstance(data["links"], list):
            data["links"] = [l for l in data["links"]
                             if not S.blocked_title(l.get("source")) and not S.blocked_title(l.get("target"))]
        if "nodes" in data and isinstance(data["nodes"], dict):
            data["nodes"] = {k: v for k, v in data["nodes"].items() if not S.blocked_title(k)}
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)

    # stale context packs: redact contract passages so they cannot feed a document
    changed = 0
    for path in glob.glob(os.path.join(ROOT, "state", "kb-context", "*.md")):
        try:
            text = open(path, encoding="utf-8", errors="ignore").read()
        except OSError:
            continue
        clean = S.redact(text)
        if clean != text:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(clean)
            changed += 1

    # importance cache is now stale
    try:
        os.remove(os.path.join(ROOT, "state", "graph-importance.json"))
    except OSError:
        pass

    log = os.path.join(ROOT, "state", "logs", "sensitive-prune.log")
    os.makedirs(os.path.dirname(log), exist_ok=True)
    with open(log, "a", encoding="utf-8") as fh:
        fh.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S')} blocked={len(blocked)} "
                 f"docs={len(drop_docs)} units={len(drop_units)} packs_redacted={changed}\n")
    clean_vectors()
    print(f"applied: entities {len(ents)} -> {len(keep)}, relationships {len(rels)} -> {len(rel)}, "
          f"documents dropped {len(drop_docs)}, context packs redacted {changed}")
    print(f"backup: {os.path.relpath(backup, ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
