# Jobsquirrel — Product & Web Interface Specification

Status: living document · Owner: repo owner · Applies to: base (`jobsquirrel`) + the
private overlay (personal/permissive patchset).

---

## 1. Purpose

Jobsquirrel is an open, self-hosted, **agent-driven job-application pipeline**. The
human supplies a CV and a set of rules; an AI coding agent then discovers roles,
tailors a CV and cover letter per role, gates them for accuracy and quality, submits
applications through a real browser, tracks replies from the inbox, and keeps a single
source of truth for every application and the exact files sent.

**Principles (non-negotiable):**

| Principle | Meaning |
|---|---|
| Honest | Never fabricate. Claims must be backed by the knowledge base + config. |
| Gated | Nothing is submitted until the alignment + pre-submit gates PASS. |
| Auditable | Every submission records the exact bytes (hash + snapshot) and the evidence. |
| Agent-agnostic | Drives opencode, Claude Code, `hermes`, `pi`, or any CLI agent. |
| Dependency-light | CLI tools are stdlib/plain; no framework, no build step. |
| Human-in-control | Irreversible actions (send/delete email, apply) require approval. |
| Person/country-agnostic | Everything personal lives in `config/`, never in code. |

## 2. Personas & roles

- **Candidate** — the owner. Supplies CV/rules, reviews output, approves risky actions, solves CAPTCHA/2FA.
- **Agent** — an AI coding agent that operates the repo via its CLI tools (contract: `AGENTS.md`).
- **Human-assist** — the person completing steps the automation must not (CAPTCHA, final submit in their own browser).

## 3. Architecture

```
discover  ->  queue  ->  per-role: JD + keywords + GraphRAG context
          ->  tailored CV + letter -> alignment gate + pre-submit gate
          ->  submit via browser (Camoufox) -> record (hash + snapshot)
          ->  reconcile replies (Gmail, read-only) -> outcomes + dashboard
```

Components:
- **CLI tools** (`tools/*.py`, `tools/*.sh`) — one concern each; the contract for the agent.
- **Agent harness** (`tools/agent_run.sh`, `tools/run_queue.sh`) — resolves the agent and runs one headless task per role.
- **Browser** (`tools/camoufox_server.py` + `camoufox_browser.py`) — stealth browser for real ATS forms.
- **Knowledge base** — GraphRAG over `kb/sources/` (grounding for generated documents).
- **State** — plain files under `state/` (the source of truth).
- **Dashboard** (`tools/dashboard.py`) — web UI (this spec, §9).

## 4. Data model (files are the API)

| Path | Contents |
|---|---|
| `state/applications.csv` | Canonical register: `date,company,role,ats,status,letter,notes`. One row per company+role. |
| `state/submissions.csv` | Provenance ledger: paths + sha256 + snapshot dir + evidence + confidence (`verified`/`forced`/`inferred`). |
| `state/queue.tsv` | Pending roles: `company␉role␉url␉cv-archetype␉ats␉key`. |
| `state/queue.done` / `queue.retry` / `queue-human.tsv` | Completion, retry, human-assist queues. |
| `state/logs/runs.jsonl` | Structured per-task result: `{ts,company,role,outcome,rc,reason}`. |
| `state/logs/*.log` | Raw agent logs (noisy; the dashboard curates them). |
| `state/job-descriptions/<key>.md` | Saved job ad. |
| `state/ats/<key>.txt` | Extracted ATS keywords. |
| `state/kb-context/<key>.md` | Cited GraphRAG grounding pack for the role. |
| `state/cv-content/<key>.json`, `state/letters-content/<key>.json` | Generated document content packs. |
| `state/gmail_reconcile_ack.txt` | Verification links already acted on. |
| `state/approvals.log` | Every approval decision (who/what, granted or refused). |
| `state/counts.md`, `state/interviews.md`, `state/human/current.json` | Generated summaries. |
| `config/profile.md` | Identity, eligibility, pay, EEO, accuracy rules (key: value). |
| `config/cv.json` | Ground-truth CV (experience/projects/education/skills/sidebar). |
| `config/archetypes.json` | Role-family CV templates (one per family) + base letter. |
| `kb/sources/` | Private knowledge corpus (CVs, own sites, contracts…). |
| `kb/graphrag/` | Index + settings. |
| `documents/archetypes/`, `documents/applications/`, `documents/submitted/` | Reusable CVs, per-role letters, byte snapshots. |

## 5. Status model

`SUBMITTED | IN_PROGRESS | INTERVIEW | OFFER | REJECTED | BLOCKED | MANUAL | PREPARED | CLOSED`.

- **IN PROCESS** = `SUBMITTED + IN_PROGRESS + INTERVIEW + OFFER` (the live pipeline).
- `BLOCKED` = a manual step is required (CAPTCHA/login); do not auto-retry.
- `MANUAL` = the human must act (login/email); `PREPARED` = documents ready, not sent.
- `CLOSED` = do not pursue.

## 6. CLI tool catalog (selection)

| Tool | Role |
|---|---|
| `register.py` | The register: `--stats/--list/--show/--check/--render/--set/--delete`. |
| `record_submission.py` | Provenance: upserts register, writes `submissions.csv`, snapshots, enforces gate receipt + evidence; **idempotent**. |
| `check_documents.py` | Pre-submit gate (identity, placeholders, salience, claims, rate, duplication, coverage); CV-only mode; `--record` writes a receipt. |
| `check_alignment.py` | Role-family vs CV-archetype alignment gate (PASS/FAIL). |
| `ats_keywords.py` | Extract keywords from a JD; score coverage. |
| `facts.py` / `identity.py` | Authoritative facts; standard form answers (JSON). |
| `cv_builder.py` / `build_archetypes.py` / `cv_target.py` / `make_letter.py` | Render CVs (docx+pdf) and letters from config. |
| `kb_graphrag.py` | Build the cited context pack for a role. |
| `discover.py` / `email_opportunities.py` | Find roles from LinkedIn alerts / recruiter mail. |
| `gmail_readonly.py` / `gmail_reconcile.py` | Read-only inbox sync + reconcile the register. |
| `gmail_send.py` | Send email — **approval-gated**. |
| `approval.py` | Reusable human-approval gate (interactive y/N or `APPROVE_<TOKEN>=1`). |
| `camoufox_server.py` / `camoufox_browser.py` | Stealth browser API + CLI. |
| `agent_run.sh` | Resolve + run the configured agent for one task. |
| `run_queue.sh` / `run_linkedin.sh` / `human_assist.sh` | Runners (queue / LinkedIn / human). |
| `doctor.py` | Health check (config, KB, browser, register, git). |
| `dashboard.py` | Web UI (§9). |

## 7. Safety & approval model

1. **Accuracy gates.** Nothing is uploaded until `check_alignment` and `check_documents`
   both PASS; `--record` writes a **hash-stamped receipt**, and `record_submission.py`
   refuses to record `SUBMITTED` without a matching receipt for the exact files.
2. **Evidence.** A `SUBMITTED` row needs the real confirmation text/URL; placeholders are
   refused. Missing receipt/evidence ⇒ recorded as `forced` (marked `[forced]`).
3. **Approval gate (`approval.py`).** Irreversible actions require explicit approval:
   - interactive: `Approve …? [y/N]` (only on a TTY), or
   - non-interactive: `APPROVE_<TOKEN>=1` for that one command.
   Every decision (granted/refused) is appended to `state/approvals.log`. Default is
   **ask-or-refuse, never silent**.
4. **CAPTCHA/2FA.** Stop, record `BLOCKED`, never evade.
5. **Email.** All outbound mail is approval-gated (`gmail_send.py`, and follow-ups).
   Mailbox deletion uses a separate `gmail.modify` token and `gmail_delete.py --authorize AUTHORIZE-DELETE`.
6. **Web UI.** Binds `127.0.0.1`; every write needs a per-session token (anti-CSRF); risky
   actions also gated (see §9).

## 8. Repository model — base vs private overlay

- **Base (`jobsquirrel`, public):** sanitized, generic, human-approval-gated; no personal data.
- **Private overlay:** the base **plus** a reviewable patchset and personal state, kept on a
  private git server only. `tools/sync_base.sh` keeps the base identical to upstream
  (`--apply` sets base := upstream, then re-applies `patches/base.patch`); `patches/BASE_FILES.txt`
  lists the shared files.
- **Per-personal/permissive patchset** (private only): personal sender aliases, the LinkedIn
  runner, proxy/IP rotation, and the `unhinged/` scale tools. `.githooks/pre-push` **refuses any
  push to a `github.com` remote**, so state and permissive tooling cannot leak to the public base.

## 9. Web interface specification (`tools/dashboard.py`)

### 9.1 Tech & running
- Python **stdlib only** (`http.server`, `subprocess`, `json`); single-page **vanilla JS**; no deps, no build.
- Binds **127.0.0.1** by default; `--host`, `--port` (default 8765), `--open`.
- A random **session token** is generated per launch, injected into the page, and required
  (header `X-Session`) for every write — anti-CSRF.
- Read-only until you act; the curated log view reuses `watch_queue` phase/noise knowledge.

### 9.2 Shell
- **Header:** squirrel mascot 🐿️, title, live "updated" line; toolbar with **Prepare (review)**,
  **Apply queue** (risky), and a **?** Help button.
- **Tabs:** Overview · Register · Roles · CV & Config · Outcomes.
- **Tooltip/help:** every control, KPI and section header has a hover tooltip; **?** opens a
  Help overlay explaining terms, statuses, Prepare vs Apply, chat, live, logs, approvals.

### 9.3 Overview tab
- **KPI cards:** In process (hero), Interviews, Rejected, Blocked, Human queue, Total — each explained on hover.
- **Queue progress** bar (`queue.done ÷ queue.tsv`).
- **Chat** — talk to the agent (see §9.7).
- **Live** — runner state, running tasks, curated tail of the newest task log (polled).
- **Recent runs** — one row per `runs.jsonl` entry; click → curated log.
- **Interviews** — roles at INTERVIEW.
- **Task log** — curated view of a selected task.

### 9.4 Register tab
- Search box (company/role) + status filter; a scrollable list; select a row to open a detail
  panel with its fields and **editable status + notes** (writes back via `register.set_row`).

### 9.5 Roles tab
- List of saved job specs (`state/job-descriptions/*`). Selecting one shows:
  - **Match score**: alignment badge (`PASS`/`FAIL` from `check_alignment`) + **keyword coverage %**
    (ATS keywords vs the generated CV/letter content) + the **missing keywords**.
  - the **job spec** text, the **ATS keywords**, and the **GraphRAG context** pack.

### 9.6 CV & Config tab
- Select and edit `config/cv.json`, `config/archetypes.json`, `config/profile.md`.
- **Save** validates JSON and keeps a `.bak`; **Regenerate archetype CVs** runs `build_archetypes.py`.

### 9.7 Chat (agent-agnostic)
- Drives whatever `tools/agent_run.sh --which` resolves — `opencode`, `claude`, `hermes`, `pi`,
  or any CLI set via `AGENT=`.
- `POST /api/chat` starts the agent with a system preamble + your message; the reply streams into
  the panel by polling `GET /api/chat/tail?since=`. The chat agent inherits the approval gates.

### 9.8 HTTP API

| Method | Path | Params | Returns |
|---|---|---|---|
| GET | `/` | — | the single-page UI (token injected) |
| GET | `/api/state` | — | counts, in-process, queue, submissions, interviews, blocked, human |
| GET | `/api/runs` | — | recent `runs.jsonl` entries |
| GET | `/api/tasks` | — | task-log names |
| GET | `/api/log` | `task` | curated log lines for a task |
| GET | `/api/live` | — | {active, running, tail_name, tail} |
| GET | `/api/agent` | — | the resolved agent CLI |
| GET | `/api/chat/tail` | `since` | {text, offset, running} |
| GET | `/api/register` | `q,status,limit,offset` | {total, rows} |
| GET | `/api/jobs` | — | list of job-spec keys |
| GET | `/api/job` | `key` | {jd, ats, kb, content, letter, match} |
| GET | `/api/match` | `key` | {alignment, coverage, missing, archetype} |
| GET | `/api/config` | `name` | {name, content} |
| GET | `/api/outcomes` | — | {by_ats, interview_rate} |
| POST | `/api/action` | `{action}` | start a run: `review` (safe), `queue` (gated), `regen` (safe) |
| POST | `/api/chat` | `{message}` | start a chat turn |
| POST | `/api/row` | `{company,role,status,note}` | update a register row |
| POST | `/api/config` | `{name,content}` | save a config file (validated, `.bak`) |

All POSTs require header `X-Session: <token>` (else 403).

### 9.9 Actions & gating
- **Prepare (review):** `REVIEW=1 run_queue.sh` — builds docs + gates, records PREPARED; never submits/emails. Safe.
- **Apply queue:** `run_queue.sh` — submits. Refused unless the dashboard was started with
  `APPROVE_RUN_QUEUE=1`, and confirmed in a dialog.
- **Regenerate archetype CVs:** runs `build_archetypes.py`. Safe.
- Runs are detached and logged to `state/logs/dashboard-action.log`.

### 9.10 Theming & UX
- Dark, high-contrast; accent amber; status chips colour-coded; squirrel mascot animates.
- Degrades to empty state with no local data (safe on the public base).

## 10. Configuration schemas

- **`config/profile.md`** — `- key: value` lines: identity, work authorisation/languages,
  availability/pay, eligibility (based-in / accept / exclude), accuracy rules, EEO answers.
- **`config/cv.json`** — `{name, headline_default, tagline_default, profile_default, skills[],
  experience[{employer,dates,title,location,bullets[],extras{}}], projects[], education[],
  certifications[], languages[], sidebar{...}}`.
- **`config/archetypes.json`** — `[{key,title,headline,tagline,opening,profile,fit,skills[[cat,text]],tags[]}]`.

## 11. Extensibility

- **New ATS**: add a recipe to `docs/ATS-RECIPES.md`; browser CLI already generic.
- **New agent CLI**: it just needs to accept the prompt as its last argument (`AGENT=`).
- **New dashboard view**: add a `GET /api/...` endpoint + a tab (the UI is plain JS).
- **New safety gate**: implement in `tools/approval.py` and call it before the action.

## 12. Non-goals

- Not a push-button "apply to 500 jobs autonomously" bot — the human owns decisions and approvals.
- No credential storage in the repo; no CAPTCHA evasion in the base.
- No fabricated claims, credentials, or identities.

## 13. Roadmap (candidates)

Digest/notifications · offer toolkit · interview kit (grounded prep) · funnel charts ·
add-role-by-URL · per-role "generate CV+letter" button · SSE streaming for live/chat ·
approval inbox in the UI · richer archetype editor.
