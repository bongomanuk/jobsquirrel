#!/usr/bin/env python3
"""GraphRAG context builder — the single retrieval path for document generation.

Thin wrapper around Microsoft GraphRAG's query engine (no bespoke retrieval):
it runs `graphrag query --method local|global|drift` against kb/graphrag and
returns a grounded, cited context pack for a role. Generation must draw claims
only from this output (plus the profile), so every statement is traceable.

Usage:
  python3 tools/kb_graphrag.py --jd state/job-descriptions/<key>.md [--out state/kb-context/<key>.md]
  python3 tools/kb_graphrag.py --text "Staff Rust engineer, LLM agents, EU AI Act"
  python3 tools/kb_graphrag.py --jd <jd> --method drift     # deep pass (slow)
  python3 tools/kb_graphrag.py --check                      # is the index + embeddings backend up?
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import stateio

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# The graphrag query subprocess needs the provider key. Prefer the environment
# (the runners inject it); fall back to the encrypted store without printing it.
try:
    if not os.environ.get("OPENCODE_API_KEY"):
        import secrets_store as _SS
        _key = _SS.get("graphrag", "OPENCODE_API_KEY")
        if _key:
            os.environ["OPENCODE_API_KEY"] = _key
except Exception:
    pass

GRAPHRAG = os.environ.get("GRAPHRAG_BIN") or (
    os.path.join(ROOT, ".venv-graphrag", "bin", "graphrag")
    if os.path.exists(os.path.join(ROOT, ".venv-graphrag", "bin", "graphrag")) else "graphrag")
CFG = os.path.join(ROOT, "kb", "graphrag")
EMB_URL = os.environ.get("EMBEDDINGS_URL", "http://127.0.0.1:11435")

STOP = set("""a an and are as at be by for from has have in into is it its of on or that the their this to was were will with you your we our role job description candidate experience work working strong able etc using use used across within including include""".split())


def _tokens(text):
    return {w for w in re.findall(r"[a-z0-9+#.]+", str(text).lower())
            if len(w) >= 3 and w not in STOP}


def weighted_highlights(jd, limit=12):
    """High-impact entities ranked by graph importance and role relevance."""
    import pandas as pd
    try:
        ents = pd.read_parquet(os.path.join(CFG, "output", "entities.parquet"))
        units = pd.read_parquet(os.path.join(CFG, "output", "text_units.parquet"))
        docs = pd.read_parquet(os.path.join(CFG, "output", "documents.parquet"))
        comms = pd.read_parquet(os.path.join(CFG, "output", "communities.parquet"))
        import graph_importance as GI
        imp = GI.scores()
    except Exception:
        return ""
    cmap = {}
    for c in comms[comms["level"] == 0].itertuples():
        for uid in c.entity_ids:
            cmap.setdefault(str(uid), int(c.community))
    doc_title = {str(i): str(t) for i, t in zip(docs["id"], docs["title"])}
    unit_doc = {str(i): str(d) for i, d in zip(units["id"], units["document_id"])}
    jd_tokens = _tokens(jd)
    picked = []
    for r in ents.itertuples():
        title = str(r.title)
        importance = float(imp.get(title, 0.0))
        body = (title + " " + str(r.description or "")).lower()
        overlap = len(jd_tokens & _tokens(body))
        rel = min(1.0, overlap / 8.0)
        if importance < 0.80 and rel < 0.25:
            continue
        text = (title + " " + str(r.description or "")).lower()
        landmark = 0.0
        if rel >= 0.10:
            for phrase, bonus in (("world register", 0.12), ("first ever", 0.10),
                                  ("world's first", 0.08), ("worlds first", 0.08),
                                  ("official world", 0.06), ("world's largest", 0.05),
                                  ("worlds largest", 0.05)):
                if phrase in text:
                    landmark += bonus
        score = 0.70 * importance + 0.30 * rel + min(0.12, landmark)
        sources = []
        for uid in (r.text_unit_ids if r.text_unit_ids is not None else []):
            d = doc_title.get(unit_doc.get(str(uid), ""), "")
            if d and d not in sources:
                sources.append(d)
        picked.append((score, importance, rel, title, str(r.type or ""),
                       str(r.description or "")[:340], sources[:2], cmap.get(str(r.id))))
    picked.sort(reverse=True)
    out, seen, per_comm = [], [], {}
    for row in picked:
        t = _tokens(row[3])
        if any((len(t & s) / max(1, len(t | s))) >= 0.82 for s in seen):
            continue
        c = row[7]
        if c is not None and per_comm.get(c, 0) >= 3:
            continue
        seen.append(t)
        out.append(row)
        if c is not None:
            per_comm[c] = per_comm.get(c, 0) + 1
        if len(out) >= limit:
            break
    if not out:
        return ""
    lines = ["## Weighted graph highlights (high impact; grounded)",
             "These are the strongest facts by graph importance and role relevance. "
             "Attribute each to the named employer/project; do not inflate the level.\n"]
    for score, importance, rel, title, typ, desc, sources, _c in out:
        src = f"; source: {', '.join(sources)}" if sources else ""
        lines.append(f"- **{title}** [{typ or 'entity'}, impact {importance:.2f}, "
                     f"relevance {rel:.2f}{src}]: {desc}")
    return "\n".join(lines)


def edits_context():
    """Operator edits to existing nodes (grounded overrides)."""
    try:
        with open(os.path.join(CFG, "edits.json"), encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return ""
    nodes = data.get("nodes") or {}
    if not nodes:
        return ""
    lines = ["## Operator edits (grounded overrides; prefer these)",
             "These descriptions were reviewed and corrected by the operator. Use them instead of the raw extracted description.\n"]
    for title, rec in list(nodes.items())[:60]:
        desc = (rec or {}).get("description") or ""
        typ = (rec or {}).get("type") or ""
        if desc:
            lines.append(f"- **{title}** [{typ or 'entity'}]: {desc[:700]}")
    return "\n".join(lines)


def overlay_context():
    """Operator-approved additions, each with its exact evidence sentence."""
    try:
        with open(os.path.join(CFG, "enrichment.json"), encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return ""
    nodes = data.get("nodes") or []
    links = data.get("links") or []
    if not nodes and not links:
        return ""
    lines = ["## Grounded additions (operator-approved, cite the evidence)",
             "Use these only when relevant; they were added because the source text supports them.\n"]
    for n in nodes[:40]:
        src = n.get("source") or n.get("source_doc") or "operator-approved"
        lines.append(f"- **{n.get('title')}** [{n.get('type','entity')}; source: {src}]: "
                     f"{n.get('description','')} Evidence: {n.get('evidence','')[:300]}")
    for l in links[:40]:
        src = l.get("source_doc") or "operator-approved"
        lines.append(f"- **{l.get('source')} -> {l.get('target')}** [link; source: {src}]: "
                     f"{l.get('description') or l.get('evidence','')[:300]}")
    return "\n".join(lines)


INSTR = (
    "Using only the knowledge base, extract the candidate's most relevant, verifiable "
    "experience, achievements, skills, certifications, technologies and quantified outcomes "
    "for the role below. Prefer specifics and metrics. Keep source citations. If something "
    "the role needs is not evidenced, say so explicitly (do not invent it)."
)


def _clean(text: str) -> str:
    text = re.sub(r"\x1b\[[0-9;]*m", "", text)
    text = text.replace("\r", "\n")
    out = []
    for ln in text.splitlines():
        s = ln.strip()
        if re.fullmatch(r"\d+\s*/\s*\d+", s):     # tqdm progress tokens
            continue
        if s.startswith(("0%|", "5%|", "10%|")):  # tqdm bars
            continue
        out.append(ln)
    return "\n".join(out).strip()


def check_backends() -> int:
    ok = True
    if not os.path.exists(os.path.join(CFG, "settings.yaml")):
        print("MISSING kb/graphrag/settings.yaml"); ok = False
    if not os.path.exists(os.path.join(CFG, "output", "entities.parquet")):
        print("MISSING index (run: .venv-graphrag/bin/graphrag index --root kb/graphrag)"); ok = False
    try:
        import urllib.request
        urllib.request.urlopen(EMB_URL + "/health", timeout=4)
        print(f"embeddings backend OK ({EMB_URL})")
    except Exception as e:
        print(f"embeddings backend DOWN ({EMB_URL}): {e}"); ok = False
    try:
        r = subprocess.run([GRAPHRAG, "--help"], capture_output=True, text=True, timeout=30)
        print("graphrag CLI OK" if r.returncode == 0 else "graphrag CLI problem")
    except Exception as e:
        print(f"graphrag CLI missing: {e}"); ok = False
    return 0 if ok else 1


def ensure_embeddings() -> None:
    """GraphRAG needs the embeddings backend; start it (Vulkan) if it is down."""
    import urllib.request
    try:
        urllib.request.urlopen(EMB_URL + "/health", timeout=3)
        return
    except Exception:
        pass
    script = os.path.join(ROOT, "tools", "embeddings.sh")
    if os.path.exists(script):
        subprocess.run(["bash", script], capture_output=True, text=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--jd", help="path to a job description")
    ap.add_argument("--text", help="raw role/query text")
    ap.add_argument("--method", default=os.environ.get("KB_QUERY_METHOD", "local"),
                    choices=["local", "global", "drift", "basic", "hybrid"])
    ap.add_argument("--community-level", type=int, default=None,
                    help="Leiden community level for reports (GraphRAG default 2)")
    ap.add_argument("--out", help="write the context pack here")
    ap.add_argument("--check", action="store_true", help="verify index + embeddings backend")
    args = ap.parse_args()

    if args.check:
        return check_backends()

    stateio.ensure_paths(args.jd, args.out)
    jd = open(args.jd).read() if args.jd else (args.text or "")
    if not jd.strip():
        print("provide --jd or --text", file=sys.stderr)
        return 2

    ensure_embeddings()

    # The embeddings backend has a hard token cap (2048 by default). A full JD
    # used to exceed it and GraphRAG would fail - and the traceback was written
    # into the context pack as if it were evidence. Keep the head (context) and
    # the tail (requirements) within a safe character budget.
    budget = max(1200, int(os.environ.get("KB_QUERY_CHARS", "5200")))
    if len(jd) > budget:
        head = int(budget * 0.6)
        tail = budget - head - 5
        jd_query = jd[:head] + "\n...\n" + jd[-tail:]
    else:
        jd_query = jd
    query = f"{INSTR}\n\n---\nROLE / JOB DESCRIPTION:\n{jd_query}"

    def run_method(method):
        cmd = [GRAPHRAG, "query", "--root", CFG, "--method", method, query]
        if args.community_level is not None:
            cmd[cmd.index("--method") + 2:cmd.index("--method") + 2] = ["--community-level", str(args.community_level)]
        p = subprocess.run(cmd, capture_output=True, text=True)
        if p.returncode != 0:
            return "", (p.stderr or "query failed")[-1500:]
        return _clean(p.stdout), ""

    if args.method == "hybrid":
        local, err1 = run_method("local")
        glob, err2 = run_method("global")
        if not local and not glob:
            print(err1 or err2, file=sys.stderr)
            return 1
        pack = ""
        if local:
            pack += "## Local facts and evidence\n" + local + "\n\n"
        if glob:
            pack += "## Global career themes\n" + glob
    else:
        pack, err = run_method(args.method)
        if not pack:
            print(err, file=sys.stderr)
            return 1
    highlights = weighted_highlights(jd)
    if highlights:
        pack += "\n\n" + highlights
    edited = edits_context()
    if edited:
        pack += "\n\n" + edited
    extra = overlay_context()
    if extra:
        pack += "\n\n" + extra
    if not pack.strip():
        print("GraphRAG returned no context (nothing written)", file=sys.stderr)
        return 1

    # Always include operator-recorded skill evidence (dashboard "add evidence"),
    # so a newly-evidenced skill is grounded immediately, without a graph rebuild.
    ev = os.path.join(ROOT, "kb", "sources", "personal", "skills_evidence.md")
    try:
        evidence = open(ev, encoding="utf-8").read().strip()
    except OSError:
        evidence = ""
    if evidence:
        pack += ("\n\n## Supplementary skill evidence (operator-provided; grounded)\n"
                 "Attribute each of these to the named employer/project; use them when the role asks.\n\n"
                 + evidence)

    header = f"<!-- GraphRAG {args.method} context; index: kb/graphrag. Grounding only. -->\n"
    if args.out:
        os.makedirs(os.path.dirname(args.out), exist_ok=True)
        tmp = args.out + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(header + pack + "\n")
        os.replace(tmp, args.out)
        print(f"wrote {args.out} ({len(pack)} chars)")
    else:
        print(header + pack)
    return 0


if __name__ == "__main__":
    sys.exit(main())
