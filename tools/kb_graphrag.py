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
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import stateio

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GRAPHRAG = os.environ.get("GRAPHRAG_BIN") or (
    os.path.join(ROOT, ".venv-graphrag", "bin", "graphrag")
    if os.path.exists(os.path.join(ROOT, ".venv-graphrag", "bin", "graphrag")) else "graphrag")
CFG = os.path.join(ROOT, "kb", "graphrag")
EMB_URL = os.environ.get("EMBEDDINGS_URL", "http://127.0.0.1:11435")

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
    ap.add_argument("--method", default="local", choices=["local", "global", "drift", "basic"])
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
    cmd = [GRAPHRAG, "query", "--root", CFG, "--method", args.method, query]
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        print(p.stderr[-1500:], file=sys.stderr)
        return 1
    pack = _clean(p.stdout)
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
