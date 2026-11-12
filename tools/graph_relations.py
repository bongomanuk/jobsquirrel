#!/usr/bin/env python3
"""Type the graph's relationships with the ontology vocabulary.

GraphRAG extracts edges with a description but no type, so everything in the
store is effectively RELATED_TO. That is fine for display and useless for
selection: you cannot ask "which roles did this person hold" or "what did this
project use" if every edge is the same.

This classifies each edge from its endpoints' ontology classes and the edge
description (PERSON -> ROLE is HELD_ROLE, PROJECT -> TECHNOLOGY is USES, ...) and
writes the result back as a `relation_type` column.

  python3 tools/graph_relations.py            # report only
  python3 tools/graph_relations.py --apply    # write the column (keeps a backup)
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys

import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import ontology as ONT  # noqa: E402

OUT = os.path.join(ROOT, "kb", "graphrag", "output")


def classify(entities: pd.DataFrame, rels: pd.DataFrame) -> pd.DataFrame:
    types = {}
    if "type" in entities.columns:
        types = {str(t).upper(): str(v) for t, v in zip(entities["title"], entities["type"])}
    out = []
    for r in rels.itertuples():
        s, t = str(r.source), str(r.target)
        rel = ONT.relation_for(types.get(s.upper(), ""), types.get(t.upper(), ""),
                               getattr(r, "description", ""))
        out.append(rel)
    rels = rels.copy()
    rels["relation_type"] = out
    return rels


def main() -> int:
    ap = argparse.ArgumentParser(description="Type GraphRAG relationships with the ontology.")
    ap.add_argument("--apply", action="store_true", help="write the relation_type column")
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args()

    ent_p = os.path.join(OUT, "entities.parquet")
    rel_p = os.path.join(OUT, "relationships.parquet")
    if not (os.path.exists(ent_p) and os.path.exists(rel_p)):
        print("no index: build it first (bash tools/setup_kb.sh)", file=sys.stderr)
        return 2
    entities = pd.read_parquet(ent_p)
    rels = pd.read_parquet(rel_p)
    typed = classify(entities, rels)
    counts = typed["relation_type"].value_counts().to_dict()
    total = len(typed)
    generic = counts.get("RELATED_TO", 0)

    if not a.quiet:
        print(f"{total} relationships -> {len(counts)} relation types")
        for rel, n in sorted(counts.items(), key=lambda x: -x[1]):
            label = (ONT.relations().get(rel) or {}).get("label", rel)
            print(f"  {rel:16s} {n:5d}  {label}")
        print(f"  unclassified: {generic} ({100 * generic / max(1, total):.0f}%)")

    if a.apply:
        backup = rel_p + ".bak-relations"
        if not os.path.exists(backup):
            shutil.copy2(rel_p, backup)
        typed.to_parquet(rel_p, index=False)
        if not a.quiet:
            print(f"wrote {rel_p}")
    elif not a.quiet:
        print("(dry run - pass --apply to write)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
