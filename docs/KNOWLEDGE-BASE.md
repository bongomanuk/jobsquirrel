# Knowledge base (GraphRAG)

The knowledge base is the retrieval layer that keeps generated documents
**truthful**. It is a Microsoft [GraphRAG](https://microsoft.github.io/graphrag/)
index over your own documents. `tools/kb_graphrag.py` is the single retrieval
path: given a job description it returns a **cited context pack** of your most
relevant achievements, skills, metrics and certifications, which the agent then
uses as the only source of claims.

It is **required**: the agent builds a targeted CV and cover letter for each role **from the cited context pack** this produces. (Grounding can fall back to `config/cv.json` only if you truly cannot run GraphRAG, but targeted document generation depends on it.)

## How it fits the pipeline

```
kb/sources/*.txt  --graphrag index-->  kb/graphrag/output/ (graph + vectors)
                                             │
  a job description  --tools/kb_graphrag.py--> state/kb-context/<key>.md  (cited pack)
                                             │
                     agent writes CV/letter ONLY from this pack + config/cv.json
```

`tools/kb_graphrag.py --jd <ad> --out state/kb-context/<key>.md` runs a GraphRAG
local search (`--method local|global|drift`) and writes the pack. `--check`
verifies the index and the embeddings backend are up.

## 1. Curate sources — the more, the better

The knowledge base is only as rich as the corpus you feed it. **Do not stop at
your CV.** Dump everything truthful and specific you have into `kb/sources/` — a
larger corpus directly produces sharper, more targeted, more honest documents,
because retrieval can find the *exact right* fact for each ad, **with a citation**.

Put plain text/markdown (`.txt` / `.md`) there:

- **Every version of your CV** — a master plus each old/role-specific one.
  Different versions hold different bullets; the graph merges them.
- **A "brag document"** — every project with *numbers*: scale, users, revenue,
  latency, uptime, team sizes, budgets, outcomes.
- **Project / design / architecture notes**, RFCs, postmortems, talks, blog and
  README excerpts.
- **Performance reviews / feedback**, awards, publications.
- **Your LinkedIn export** (positions, skills, recommendations, certifications).
- **Anything else truthful** that evidences what you've done.

Rules:

- Keep **every fact traceable to a real experience** — this corpus is the ground
  truth the gate checks against.
- Prefer **specifics** (numbers, technologies, scope) over adjectives.
- **Not plain text?** Convert first — PDFs/DOCX/emails → `.txt`/`.md` (ask the
  agent to do it). GraphRAG reads text, and the staging step below only picks up
  `.txt` and `.md`.

Then stage them for indexing:

```bash
mkdir -p kb/graphrag/input
cp kb/sources/*.txt kb/sources/*.md kb/graphrag/input/ 2>/dev/null || true
```

## 2. Configure models

Copy and edit:

```bash
cp kb/graphrag/settings.example.yaml kb/graphrag/settings.yaml
cp kb/graphrag/.env.example          kb/graphrag/.env
```

- **Completion model** — any OpenAI-compatible endpoint
  (`GRAPHRAG_API_BASE`, `GRAPHRAG_API_KEY`, `GRAPHRAG_LLM_MODEL`).
- **Embeddings** — any OpenAI-compatible embeddings endpoint
  (`GRAPHRAG_EMBED_BASE`, `GRAPHRAG_EMBED_MODEL`, `GRAPHRAG_EMBED_KEY`).

### Local embeddings (default)

`tools/embeddings_vulkan.sh` starts a local `llama.cpp` server running
`nomic-embed-text` behind an OpenAI-compatible `/v1/embeddings` on
`127.0.0.1:11435`. Adjust `LLAMA_SERVER`, `EMBED_MODEL`, `EMBED_PORT` via env.
Any other OpenAI-compatible embeddings server works too — just point
`GRAPHRAG_EMBED_BASE` at it.

> **Small-context embeddings:** if your embedding model has a small context (e.g.
> 2048 tokens), keep `community_reports.max_length` modest (the template uses
> 1000) so every community report fits and embeds without error.

## 3. Build the index

```bash
bash tools/embeddings_vulkan.sh                    # ensure the backend is up
pip install graphrag                               # or use .venv-graphrag
python3 -m graphrag index --root kb/graphrag       # one-off; can take many minutes
python3 tools/kb_graphrag.py --check               # index + backend + CLI
```

Indexing calls the LLM to extract entities/relationships and summarise
communities; it costs tokens and time. It caches completed steps, so a re-run
after a failure resumes rather than restarting.

## 4. Use it

```bash
python3 tools/kb_graphrag.py --jd state/job-descriptions/<key>.md \
    --out state/kb-context/<key>.md
python3 tools/kb_graphrag.py --method drift --jd ...   # deeper pass (slower)
```

The runner does this automatically (step "grounding") for each queued role.

## 5. Maintain it

- When you add or change a source, copy it into `kb/graphrag/input/` and
  **re-index** (`graphrag index --root kb/graphrag`). Stale indexes surface stale
  claims.
- **Accuracy first:** if a source once contained an overstatement, fixing the
  source and re-indexing is what stops it reappearing in generated documents.
- Keep secrets out: `kb/graphrag/.env` and `settings.yaml` are git-ignored.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `embeddings backend DOWN` | `bash tools/embeddings_vulkan.sh`; check `EMBED_PORT`. |
| `input (...) is larger than the max context size` | Lower `community_reports.max_length`; re-index. |
| GraphRAG CLI missing | `pip install graphrag` (or set `GRAPHRAG_BIN`). |
| Every run re-computes | Ensure `cache.type: json` persists between runs. |
