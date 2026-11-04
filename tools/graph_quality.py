#!/usr/bin/env python3
"""Report the quality of the GraphRAG knowledge graph.

This is the gate to run after a rebuild, so "is the graph better?" is a
measurement rather than an impression. It never changes the index.

    .venv-graphrag/bin/python tools/graph_quality.py
    .venv-graphrag/bin/python tools/graph_quality.py --json
    .venv-graphrag/bin/python tools/graph_quality.py --top 15

It reports:
  * corpus duplication (from kb/graphrag/input/.ingest.json)
  * entity, relationship, text-unit and community counts
  * degree distribution and isolated entities (the long tail)
  * exact and near-duplicate entity titles
  * team entities spread across the wrong ontology classes
  * community levels and the largest communities
  * relationship self-loops and duplicate pairs
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'tools'))
import sensitive as SENS

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "kb", "graphrag", "output")
INPUT = os.path.join(ROOT, "kb", "graphrag", "input")


def load(name):
    import pandas as pd
    path = os.path.join(OUT, name + ".parquet")
    if not os.path.exists(path):
        return None
    return pd.read_parquet(path)


def norm_title(s):
    s = re.sub(r"[^a-z0-9 ]", " ", str(s).lower())
    return re.sub(r"\s+", " ", s).strip()


def tokens(s):
    return set(norm_title(s).split())


def jaccard(a, b):
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def near_duplicate_groups(titles, threshold=0.86):
    """Blocked token-set matching so 2,800 titles stay cheap."""
    blocks = defaultdict(list)
    for title in titles:
        t = tokens(title)
        if t:
            blocks[min(t)].append(title)
    parent = {t: t for t in titles}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    for group in blocks.values():
        if len(group) < 2 or len(group) > 400:
            continue
        sets = [(t, tokens(t)) for t in group]
        for i in range(len(sets)):
            for j in range(i + 1, len(sets)):
                if jaccard(sets[i][1], sets[j][1]) >= threshold:
                    union(sets[i][0], sets[j][0])
    groups = defaultdict(list)
    for t in titles:
        groups[find(t)].append(t)
    return [sorted(v) for v in groups.values() if len(v) > 1]


def main():
    ap = argparse.ArgumentParser(description="Knowledge-graph quality report")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--top", type=int, default=10)
    ap.add_argument("--fail-sensitive", action="store_true",
                    help="exit non-zero if sensitive employment-contract terms remain")
    args = ap.parse_args()

    ents = load("entities")
    rels = load("relationships")
    units = load("text_units")
    comms = load("communities")
    if ents is None or rels is None:
        print("no graph index at kb/graphrag/output", file=sys.stderr)
        return 1

    report = {"entities": len(ents), "relationships": len(rels),
              "text_units": len(units) if units is not None else 0,
              "communities": len(comms) if comms is not None else 0}

    # corpus duplication from the ingest manifest
    manifest = {}
    try:
        with open(os.path.join(INPUT, ".ingest.json"), encoding="utf-8") as fh:
            manifest = json.load(fh)
    except (OSError, ValueError):
        pass
    report["input"] = manifest.get("summary", {})
    report["input_files"] = len([f for f in os.listdir(INPUT)
                                 if os.path.isfile(os.path.join(INPUT, f))
                                 and not f.startswith(".")]) if os.path.isdir(INPUT) else 0

    # grounding: every entity should still point at a surviving text unit
    report["grounding"] = {
        "entities_without_text_units": int(ents["text_unit_ids"].apply(lambda x: len(list(x)) == 0).sum())
        if "text_unit_ids" in ents.columns else 0,
    }

    # degree + type distribution
    deg = [int(x) for x in ents["degree"]]
    report["degree"] = {"zero": sum(1 for x in deg if x == 0),
                        "one": sum(1 for x in deg if x == 1),
                        "le_two": sum(1 for x in deg if x <= 2),
                        "max": max(deg) if deg else 0}
    report["types"] = {str(k): int(v) for k, v in ents["type"].value_counts().items()}

    # duplicate titles
    normed = Counter(norm_title(x) for x in ents["title"])
    exact = {k: v for k, v in normed.items() if v > 1}
    near = near_duplicate_groups(list(ents["title"]))
    report["duplicate_titles"] = {
        "exact_groups": len(exact),
        "exact_entities": sum(exact.values()),
        "near_groups": len(near),
        "near_entities": sum(len(g) for g in near),
        "examples": [g for g in sorted(near, key=len, reverse=True)[:args.top]],
    }

    # teams in the wrong class
    team_like = ents[ents["title"].astype(str).str.contains(r"\bteams?\b", case=False, na=False)]
    report["team_like"] = {
        "total": len(team_like),
        "by_type": {str(k): int(v) for k, v in team_like["type"].value_counts().items()},
    }

    # communities
    if comms is not None:
        levels = {}
        for lvl, grp in comms.groupby("level"):
            levels[str(int(lvl))] = {"count": len(grp),
                                     "min": int(grp["size"].min()),
                                     "median": int(grp["size"].median()),
                                     "max": int(grp["size"].max())}
        report["community_levels"] = levels
        report["largest_communities"] = [
            {"id": int(r.community), "level": int(r.level), "size": int(r.size)}
            for r in comms.sort_values("size", ascending=False).head(args.top).itertuples()]

    # relationships
    pairs = Counter((str(a), str(b)) for a, b in zip(rels["source"], rels["target"]))
    report["sensitive"] = {
        "blocked_titles": sum(1 for t in ents["title"] if SENS.blocked_title(t)),
        "sensitive_descriptions": sum(1 for d in ents["description"] if SENS.sensitive(d)),
        "sensitive_reports": 0,
    }
    reports = load("community_reports")
    if reports is not None:
        report["sensitive"]["sensitive_reports"] = sum(
            1 for r in reports.itertuples()
            if SENS.sensitive(str(r.title)) or SENS.sensitive(str(r.summary)))
    report["relationships_quality"] = {
        "self_loops": sum(1 for a, b in zip(rels["source"], rels["target"]) if str(a) == str(b)),
        "duplicate_pairs": sum(1 for v in pairs.values() if v > 1),
    }

    if args.json:
        print(json.dumps(report, indent=2))
        return 0

    print(f"entities        {report['entities']:,}")
    print(f"relationships   {report['relationships']:,}")
    print(f"text units      {report['text_units']:,}")
    print(f"communities     {report['communities']:,}")
    if report["input"]:
        s = report["input"]
        print(f"input files     {report['input_files']}  "
              f"(kept {s.get('kept', '?')}, exact dup {s.get('exact_duplicates', '?')}, "
              f"near dup {s.get('near_duplicates', '?')})")
    d = report["degree"]
    print(f"degree          0:{d['zero']}  1:{d['one']}  ≤2:{d['le_two']}  max:{d['max']}")
    print("types           " + ", ".join(f"{k}:{v}" for k, v in report["types"].items()))
    t = report["duplicate_titles"]
    print(f"duplicate names {t['exact_groups']} exact groups / {t['exact_entities']} entities; "
          f"{t['near_groups']} near groups / {t['near_entities']} entities")
    tl = report["team_like"]
    print(f"team-like       {tl['total']} entities; " +
          ", ".join(f"{k}:{v}" for k, v in tl["by_type"].items()))
    if report.get("community_levels"):
        print("community levels " + "  ".join(
            f"{k}:{v['count']}" for k, v in report["community_levels"].items()))
    rq = report["relationships_quality"]
    print(f"relationships   self-loops:{rq['self_loops']}  duplicate pairs:{rq['duplicate_pairs']}")
    se = report["sensitive"]
    print(f"sensitive       blocked titles:{se['blocked_titles']}  "
          f"descriptions:{se['sensitive_descriptions']}  reports:{se['sensitive_reports']}")
    gr = report["grounding"]
    print(f"grounding       entities without a text unit: {gr['entities_without_text_units']}")
    if args.fail_sensitive and (any(report["sensitive"].values()) or
                                gr["entities_without_text_units"]):
        print("\nFAIL: sensitive or ungrounded material remains", file=sys.stderr)
        return 2
    if t["examples"]:
        print("\nlargest near-duplicate title groups:")
        for g in t["examples"][:args.top]:
            print("  - " + " | ".join(g[:6]) + (f"  (+{len(g)-6})" if len(g) > 6 else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
