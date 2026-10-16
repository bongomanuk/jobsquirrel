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

**`state/applications.csv`**: the canonical outcome register, one row per
`(company, role)`:
`day, company, role, ats, status, cv, letter, notes`.
Statuses: `PREPARED, IN_PROGRESS, SUBMITTED, INTERVIEW, OFFER, REJECTED, BLOCKED,
MANUAL, CLOSED`. Managed by `tools/register.py` (`--stats/--list/--show/--check/--render/--set`).

**`state/submissions.csv`**: the provenance ledger: the exact files sent per
application, with `sha256` and a snapshot directory under `documents/submitted/`.
Written by `tools/record_submission.py` (which also upserts the register).

**Queues**: `state/queue.tsv` tab-separated:
`company  role  url  cv-archetype  ats  key`. `run_queue.sh` processes rows whose
`company|role` key is not in `state/queue.done`, **most-senior-first** by default
(`PRIORITISE=1`; set `PRIORITISE=0` for file order). `tools/prioritise_queue.py`
sorts the queue file itself by seniority.

## Tools by role

- **Build**: `cv_builder.py` (library), `build_archetypes.py`, `cv_target.py`,
  `make_letter.py`, `fix_letterheads.py`.
- **Gate**: `check_alignment.py` (role family ↔ CV), `check_documents.py`
  (pre-submit), `ats_keywords.py` (coverage), `facts.py` (claim/tense checks).
- **Record**: `register.py`, `record_submission.py`.
- **Email**: `gmail_readonly.py`, `gmail_reconcile.py`, `gmail_calendar_auth.py`,
  `gmail_send.py`, `discover.py`, `email_opportunities.py`, `email_verify.py`.
- **Browser**: `camoufox_server.py`, `camoufox_browser.py`, `camoufox_test.py`.
- **Run**: `run_queue.sh` (parallel queue), `run_linkedin.sh` (serialized LinkedIn),
  `reconcile_loop.sh`, `watch_queue.sh`, `build_human_queue.py`, `human_assist.sh`.
- **Grounding (required)**: `kb_graphrag.py` (+ `kb/`), `embeddings.sh`.

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
