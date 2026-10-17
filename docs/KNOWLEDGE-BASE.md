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

## 1. Curate sources: the more, the better

The knowledge base is only as rich as the corpus you feed it. **Do not stop at
your CV.** Dump everything truthful and specific you have into `kb/sources/`, a
larger corpus directly produces sharper, more targeted, more honest documents,
because retrieval can find the *exact right* fact for each ad, **with a citation**.

Put your documents there, **any format** (PDF, DOCX, DOC/ODT, HTML, Markdown,
email, CSV/JSON). You can drop them into `kb/sources/` by hand, or **upload them from
the web UI** (**Settings → Knowledge base**, then *Rebuild graph*) and see exactly what
the index contains under **Settings → GraphRAG**.

- **Every version of your CV**: a master plus each old/role-specific one.
  Different versions hold different bullets; the graph merges them.
- **A "brag document"**: every project with *numbers*: scale, users, revenue,
  latency, uptime, team sizes, budgets, outcomes.
- **Project / design / architecture notes**, RFCs, postmortems, talks, blog and
  README excerpts.
- **Performance reviews / feedback**, awards, publications.
- **Your LinkedIn export** (positions, skills, recommendations, certifications).
- **Anything else truthful** that evidences what you've done.

Rules:

- Keep **every fact traceable to a real experience**: this corpus is the ground
  truth the gate checks against.
- Prefer **specifics** (numbers, technologies, scope) over adjectives.
- **Any format works.** The ingest step below converts PDF/DOCX/DOC/ODT/HTML/
  email/Markdown to text (and passes `.txt`/`.csv`/`.json` straight through), so
  there is nothing to convert by hand.

Then ingest them (any format → GraphRAG text input):

```bash
python3 tools/kb_ingest.py --sources kb/sources --out kb/graphrag/input
```

## 2. Configure models

Copy and edit:

```bash
cp kb/graphrag/settings.example.yaml kb/graphrag/settings.yaml
cp kb/graphrag/.env.example          kb/graphrag/.env
```

- **Completion model**: any OpenAI-compatible endpoint
  (`GRAPHRAG_API_BASE`, `GRAPHRAG_API_KEY`, `GRAPHRAG_LLM_MODEL`).
- **Embeddings**: any OpenAI-compatible embeddings endpoint
  (`GRAPHRAG_EMBED_BASE`, `GRAPHRAG_EMBED_MODEL`, `GRAPHRAG_EMBED_KEY`).

### Embeddings backend and acceleration

Embeddings run locally, so this is the one part worth accelerating.
`tools/embeddings.sh` starts a `llama.cpp` (`llama-server`) with the embedding
model (`nomic-embed-text` by default) behind an OpenAI-compatible
`/v1/embeddings` on `127.0.0.1:11435`, and **auto-selects the best backend**:

| Your machine | Backend (auto) | llama.cpp build to install |
| --- | --- | --- |
| Apple Silicon (macOS) | `metal` | `brew install llama.cpp` (Metal is built in) |
| NVIDIA GPU (Linux/Windows) | `cuda` | a CUDA build (`-DGGML_CUDA=ON`) or a prebuilt CUDA release |
| AMD / Intel GPU | `vulkan` | a Vulkan build (`-DGGML_VULKAN=ON`) or a prebuilt Vulkan release |
| No GPU | `cpu` | any build |

```bash
bash tools/embeddings.sh --check                 # report server, model, backend, endpoint
bash tools/embeddings.sh                          # start it (idempotent)
EMBED_BACKEND=cuda bash tools/embeddings.sh       # force a backend: metal|cuda|vulkan|cpu
```

Notes:

- `EMBED_NGL` (default `99`) is how many layers to offload to the GPU; `99` means
  all of them. `LLAMA_SERVER` is the path to `llama-server` (or the directory
  holding it), `EMBED_MODEL` the `.gguf`, `EMBED_PORT` the port.
- If your `llama-server` binary was not built with the selected backend, it will
  fall back to CPU. Check the log (`EMBED_LOG`, default `/tmp/llama-server.log`)
  for the `offloaded N/N layers to GPU` line to confirm acceleration is active.
- Any other OpenAI-compatible embeddings server works too. Point
  `GRAPHRAG_EMBED_BASE` at it and ignore `embeddings.sh`.

> **Small-context embeddings:** if your embedding model has a small context (e.g.
> 2048 tokens), keep `community_reports.max_length` modest (the template uses
> 1000) so every community report fits and embeds without error.

## 3. Build the index

```bash
bash tools/embeddings.sh                          # ensure the backend is up (auto backend)
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
| `embeddings backend DOWN` | `bash tools/embeddings.sh`; check `EMBED_PORT` and the log. |
| `input (...) is larger than the max context size` | Lower `community_reports.max_length`; re-index. |
| GraphRAG CLI missing | `pip install graphrag` (or set `GRAPHRAG_BIN`). |
| Every run re-computes | Ensure `cache.type: json` persists between runs. |
