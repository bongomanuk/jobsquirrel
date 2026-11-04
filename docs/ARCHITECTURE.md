# Architecture

## Shape

A set of small, single-purpose CLI tools (Python + a few shell scripts) that share
three things: the **config** (`config/`), the **register** (`state/applications.csv`)
and the **provenance ledger** (`state/submissions.csv`). The runner
(`tools/run_queue.sh`) orchestrates them per job by spawning an AI coding agent
whose instructions are generated from the config, so all the "knowledge" lives
in config + data, not in the scripts.

```
config/profile.md ─┐
config/cv.json  ───┼─> cv_builder ─> archetypes ─> cv_target/letter ─> GATE ─> ATS (browser) ─> record
config/archetypes.json ┘                         check_alignment / check_documents        │
                                                                                          ▼
      inbox <─ gmail_readonly/gmail_reconcile ── register (applications.csv) <── submissions.csv
```

## Configuration (the only person-specific inputs)

| File | What it holds |
|---|---|
| `config/profile.md` | Identity, work authorisation, languages, availability, pay, **eligibility** and **accuracy** rules, EEO answers. Read as `- key: value`. |
| `config/cv.json` | The CV as data: `experience[]`, `projects[]`, `skills[]`, `education[]`, `certifications[]`, `languages[]`, `sidebar{}`. Ground truth for the gate. |
| `config/archetypes.json` | Role-family templates: `{key,title,headline,tagline,opening,profile,fit,skills,tags}`. |

If `config/profile.md` / `cv.json` / `archetypes.json` are absent, the tools fall
back to the matching `*.example.*` file, so the project runs out of the box with
placeholder data.

## Data model

**`state/applications.csv`**: the canonical outcome register, one row per role:
`date, company, role, ats, status, letter, notes, employment, action, key,
apply_url`. **`key`** is the role's single identity (the queue row's last column);
`queue.done` stores the same key and `apply_url` is the apply target, so a rename
or a `|` in a company name can never create a second, orphaned row. Rows written
before that column existed fall back to `company|role`.

Statuses: `QUEUED, PREPARED, IN_PROGRESS, SUBMITTED, INTERVIEW, OFFER, REJECTED,
BLOCKED, MANUAL, CLOSED` (`PREPARED` = documents built and gated, nothing sent).
Managed by `tools/register.py`: read with `--stats/--list/--show`, edit with
`--set/--render/--delete`, and **audit** with `--audit` (exits non-zero on a
duplicate row or key, a `queue.done` entry with no row, a `SUBMITTED` row with no
provenance, a stale `state/counts.md`, a PREPARED row whose application email was
actually sent with attachments, an INTERVIEW row with no invitation in its notes,
a live role with no saved job description, or a finished queue alias of a register
row). `record_submission.py` and the pre-submit gate both refuse a SUBMITTED row
without the saved advert (`--no-jd` is the explicit exception for a network
profile). `SUBMITTED` is refused without
provenance, which is written by the submission action itself (hash, snapshot,
gate receipt, then ledger + status); an application email does the same
automatically. Repair with `--dedupe`,
`--backfill`, `--backfill-done` and `--record-provenance-gaps`; `--stats`
regenerates `state/counts.md`, which is never edited by hand.

**`state/submissions.csv`**: the provenance ledger: the exact files sent per
application, with `sha256` and a snapshot directory under `documents/submitted/`.
Written by `tools/record_submission.py` (which also upserts the register).

**Queues**: `state/queue.tsv` tab-separated:
`company  role  url  cv-archetype  ats  key`. `run_queue.sh` processes rows whose
`key` is not in `state/queue.done`, **most-senior-first** by default
(`PRIORITISE=1`; set `PRIORITISE=0` for file order). `tools/prioritise_queue.py`
sorts the queue file itself by seniority.

## Tools by role

- **Build**: `cv_builder.py` (library), `build_archetypes.py`, `cv_target.py`, `cv_fill.py`,
  `make_letter.py`, `fix_letterheads.py`.
- **Gate**: `check_alignment.py` (role family ↔ CV), `check_documents.py`
  (pre-submit), `ats_keywords.py` (coverage), `facts.py` (claim/tense checks),
  `gate_receipt.py` (hash-stamped PASS receipts; `record_submission.py` refuses a
  `SUBMITTED` row without one), `jd_guard.py` (a role needs a saved job ad before
  it is queued).
- **Record**: `register.py`, `record_submission.py`, `outcomes.py`.
- **Email**: `gmail_readonly.py`, `gmail_reconcile.py`, `gmail_calendar_auth.py`,
  `gmail_send.py`, `discover.py`, `email_opportunities.py`, `email_verify.py`.
- **Browser**: `camoufox_server.py`, `camoufox_browser.py`, `camoufox_test.py`.
- **Run**: `run_queue.sh` (parallel queue), `run_linkedin.sh` (serialized LinkedIn),
  `agent_run.sh` (whichever agent CLI you have), `reconcile_loop.sh`,
  `watch_queue.sh`, `build_human_queue.py`, `human_assist.sh`,
  `captcha_manual.sh`, `chain_queue.sh`, `requeue_blocked.sh`.
- **Approval and access**: `approval.py` (risky actions), `send_receipt.py`
  (one-time human receipts for a specific send), `agent_access.py` (the gate for
  anything outside the repo: read, write, run).
- **Grounding (required)**: `kb_graphrag.py` (+ `kb/`), `embeddings.sh`,
  `graph_explore.py` (read the index), `ontology.py` (+ `config/ontology.example.json`),
  `web/graph3d.js` (the Three.js Knowledge workspace).
- **Secrets**: `secrets_store.py` (encrypted 0600 store; OS keyring or key file),
  `accounts.py`, `google_config.py`, `diagnostics` via `doctor.py`.

## Knowledge workspace

The top-bar **Knowledge** page is a full-page Three.js view over the same
GraphRAG index. `graph_explore.py` exposes the Universe, ontology aggregates,
the community hierarchy, connected entity subgraphs, ego networks, semantic
search, role evidence and cited answers; `graph_importance.py` scores entities
by weighted message passing; `graph_universe.js` and `graph3d.js` are the
Universe and Map renderers, and `web/app.js` owns the node pane, focus/fade,
Ask, enrichment and edit flows. Overlays (`enrichment.json`, `edits.json`,
`orphan-links.json`) are merged at read time so they survive a rebuild.
`ontology.py` maps GraphRAG types to the classes shown in
`config/ontology.example.json`. The frontend owns the scene, orbit/zoom/pan, raycast and HTML
hotspots; `dashboard.py` owns the breadcrumbs, search, source management and
role links. Orphans are attached with evidence-backed overlay links; anything
that cannot be honestly linked is grouped in the labelled *Unlinked evidence*
island instead of floating among the themes.

The **Roles** tab in the workspace is the bridge to applications: it lists
register rows and opens one in the existing job drawer, or prepares a queued
role. The ontology's `REQUIRES` / `SATISFIES` vocabulary is the place to grow
role-to-evidence edges without changing the graph renderer.

## Machine-local state and compression

Everything the pipeline learns about a run lives in `state/` and is machine-local.
It is largely text — saved job ads, ATS keyword files, GraphRAG grounding packs,
CV content packs, letters, gate receipts, agent transcripts — so it compresses
3-7x, and `tools/storage.py` packs the cold parts:

| Area | Action | Read back by |
|---|---|---|
| logs idle for a day | `--logs`, plus `--pack-log <file>` the moment a role finishes | the dashboard reads `.gz` directly |
| per-role artifacts older than `--state-days` | `--state` | `tools/stateio.py` |
| `state/gmail_cache.json` | `--gmail-cache` | `gmail_reconcile.py` |
| `kb/graphrag/cache` | `--graphrag-cache --apply` (tar.zst archive) | re-extract if you want incremental indexing |

The invariant is that **a packed artifact is indistinguishable from a plain one**:
`stateio.resolve()` returns `x` or `x.gz`, `read_text()` reads either, and
`ensure()` restores one in place (keeping its original mtime) when a tool needs a
real file. A queue run hydrates everything at the start (`--hydrate-all`) and
packs the cold leftovers when it finishes.

Never packed: files that are appended to or written by shell redirection
(`queue*.tsv`, `*.done`, `*.csv`, `state/drafts/`, live dashboard logs), symlinks,
and — by default — anything git tracks (packing a tracked file is a deletion plus
an untracked `.gz`; `--include-tracked` overrides). `documents/` holds `.docx` and
`.pdf`, already-compressed containers; `kb/graphrag/output/` is read at query time
and stays unpacked. Details: **[STORAGE.md](STORAGE.md)**.

## Runner model

`run_queue.sh` spawns `PARALLEL` workers; each pops the next pending queue row and
runs the configured agent (`agent_run.sh`: opencode, Claude Code or any CLI) with
a generated prompt. On macOS the runner falls back to the portable `flock`,
`setsid` and `timeout` stand-ins in `tools/compat/`. The prompt (built from `config/`)
tells the agent to: read `config/profile.md`; apply the eligibility gate; choose
and verify the aligned archetype; build a targeted CV + letter; pass the
pre-submit gate; submit through the employer ATS via `camoufox_browser.py`; and
record the result. One queue slot = one application. Blocked/closed roles are
recorded with a reason; the runner never fabricates a submission.

## Knowledge base (GraphRAG)

`kb/sources/` (your CVs, notes, product docs) is indexed by Microsoft GraphRAG
into `kb/graphrag/`. `kb_graphrag.py` then builds a cited grounding pack per role
into `state/kb-context/`, which the agent uses as the single source of truth for
achievements and metrics. This is **required** for document generation: the
targeted CVs and letters are written from it.
