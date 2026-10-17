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

### 9.2 Shell (single-grid IA)
The whole app is **one master data grid** — one canonical row per application, so the
same record is never duplicated across separate pages.
- **Header:** mascot 🐿️ · health pill (`/api/health`) · build marker · action bar
  (**⚡ Prepare**, **🚀 Run Submissions** (gated), **📥 Reconcile**, **⚙ Config**, **💬 Agent**).
- **Strip:** metric pills (in process · interviews · blocked · human · offers · total · submissions)
  and a live-tail line (`/api/live`).
- **Toolbar:** search (company/role/ATS), status filter, queue filter, **Export CSV**, row count.

### 9.3 Master grid (the one table)
Columns: **Date · Company · Role · ATS · Status · Match · Queue · Prov · Spec**.
- Search / filter / sort (click a header); **Export CSV**.
- **Match** = alignment badge (PASS/FAIL) + keyword-coverage % (computed & cached as roles are opened).
- **Queue** = `pending | human | retry | done`; **Prov** = provenance recorded; **Spec** = a saved job spec exists.

### 9.4 Detail drawer (right-hand)
Clicking a row opens a drawer with tabs:
- **Summary** — status (editable, writes back), ATS, queue, key, match, notes; actions (Prepare).
- **Provenance** — CV/letter paths + sha256 (click to copy), confidence, evidence, snapshot, screenshots.
- **Job spec · ATS · KB context · Tailored** — the ad text, keywords, GraphRAG pack, generated CV/letter.

### 9.5 Config (modal)
- Edit `config/cv.json`, `config/archetypes.json`, `config/profile.md`; JSON validated, `.bak` kept;
  **Regenerate archetype CVs** runs `build_archetypes.py`.

### 9.6 Chat (agent-agnostic, bottom drawer)
- Drives whatever `tools/agent_run.sh --which` resolves — `opencode`, `claude`, `hermes`, `pi`, or `AGENT=`.
- `POST /api/chat` + `GET /api/chat/stream?since=` stream the reply; the chat agent inherits the
  approval gates; the drawer's second pane shows the live run tail (`/api/live`).

### 9.8 HTTP API

| Method | Path | Params | Returns |
|---|---|---|---|
| GET | `/` | — | the single-page UI (token injected) |
| GET | `/api/state` | — | {kpis, counts, queue_counts, interviews} |
| GET | `/api/health` | — | doctor.py result (cached 60s) |
| GET | `/api/grid` | — | the unified grid rows (register ⋈ queue ⋈ spec ⋈ provenance) |
| GET | `/api/register` | `q,status,limit,offset` | {total, rows} |
| GET | `/api/provenance` | `company,role` | provenance row (sha256, evidence, snapshot) |
| GET | `/api/queue` | — | {pending, human, retry, done} |
| GET | `/api/roles` · `/api/roles/<key>` | — | spec list · {jd, ats, kb, tailored_cv, letter, match} |
| GET | `/api/config` | `target` | {target, content, format} |
| GET | `/api/outcomes` | — | {by_ats, interview_rate} |
| GET | `/api/runs` · `/api/log` · `/api/live` · `/api/tasks` · `/api/logs/tail` · `/api/agent` · `/api/chat/stream` | — | as named |
| POST | `/api/register/row` | `{company,role,status,notes}` | update a register row |
| POST | `/api/queue/action` | `{action,company,role}` | `delete` / `retry` / `unblock` |
| POST | `/api/roles/discover` | `{url}` | save a job spec from a URL |
| POST | `/api/config` | `{target,content}` | save config (JSON validated, `.bak`) |
| POST | `/api/action/run` | `{command, approval_token}` | `prepare` / `submit_queue` / `reconcile` / `build_archetypes` |
| POST | `/api/chat` | `{message}` | start a chat turn |

All POSTs require header `X-Session: <token>` (else 403); the token is injected into the page.

### 9.9 Actions & gating
- **Prepare:** `REVIEW=1 run_queue.sh` — builds docs + gates, records PREPARED; never submits/emails. Safe.
- **Run Submissions:** `run_queue.sh` — **submits**. Requires the `APPROVE_RUN_QUEUE` approval token
  (the two-step modal: acknowledge + Confirm); refused otherwise. Every decision is logged to `state/approvals.log`.
- **Reconcile:** `gmail_reconcile.py` (read-only).
- **Regenerate archetype CVs:** `build_archetypes.py`. Safe.
- Runs are detached and logged to `state/logs/dashboard-action.log`.

### 9.10 Theming & UX
- Dark, high-contrast; amber accent; colour-coded status chips; squirrel mascot animates; empty-state-safe.
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
