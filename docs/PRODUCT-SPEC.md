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
- **Browser** (`tools/camoufox_server.py` + `camoufox_browser.py`) — Camoufox browser for real ATS forms.
- **Knowledge base** — GraphRAG over `kb/sources/` (grounding for generated documents).
- **State** — plain files under `state/` (the source of truth).
- **Dashboard** (`tools/dashboard.py`) — web UI (this spec, §9).

## 4. Data model (files are the API)

| Path | Contents |
|---|---|
| `state/applications.csv` | Canonical register: `date,company,role,ats,status,letter,notes,employment,action`. One row per company+role. `action` is a short follow-up flag (reply/assessment/booking) surfaced as ⚑ in the grid and filterable. |
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
| `config/google.json` | Where the Google OAuth client/token live; optional client id/secret. Editable in Settings → Accounts. |
| `config/recruiter-aliases.json` | Optional sender/agency name → register company map (kept out of the code, and out of the public mirror). |
| `config/email.json` / `config/calendar.json` | Sender signature + attachments; calendar timezone, meeting length, working hours. |
| `kb/sources/` | Private knowledge corpus (CVs, own sites, contracts…). |
| `kb/graphrag/` | Index + settings. |
| `documents/archetypes/`, `documents/applications/`, `documents/submitted/` | Reusable CVs, per-role letters, byte snapshots. |

## 5. Status model

`SUBMITTED | IN_PROGRESS | INTERVIEW | OFFER | REJECTED | BLOCKED | MANUAL | PREPARED | CLOSED`.

- **Follow-up flags** (`action` in the register; ⚑ in the grid, a toolbar filter, and editable
  in the row drawer). Each row also lists its **drafted replies** (write one, or ask the agent; then
  review and send with approval). Reconcile sets an action on an interview invite (`Reply to <sender> — <subject>`) and
  clears it on a rejection; anything manual (assessment, booking) can be flagged/cleared in the UI.
- **Engagement type** (`employment` in the register; shown as a per-row badge, editable in
  the drawer, filterable in the toolbar): `full-time | part-time | contract | consultant |
  freelance | internship | temporary`. Set explicitly on the row; otherwise guessed from the
  saved job ad, then the notes; `unknown` when nothing says.
- `INTERVIEW` splits into three display labels (the stored status stays `INTERVIEW`,
  derived from the notes): **`SCHEDULED`** (a future interview is booked), **`INVITED`**
  (being arranged, no confirmed time), and plain **`INTERVIEW`** (held — awaiting the outcome).
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
| `gmail_send.py` | Send a **saved draft** with attachments — requires a human dashboard receipt; no env bypass. |
| `send_receipt.py` | One-time receipts bound to a draft's SHA-256 (issued by the dashboard after approval). |
| `draft_email.py` | Draft replies tied to a role (`state/drafts/<company-role>/`); listed, edited and sent from the row drawer. |
| `google_config.py` | Resolve/write the Google OAuth client + token paths (`--status`, `--paths`, `--write-credentials`). |
| `calendar_event.py` | List/create/update events, import `.ics` invites, suggest free slots — writes **approval-gated**. |
| `approval.py` | Reusable human-approval gate (interactive y/N or `APPROVE_<TOKEN>=1`). |
| `camoufox_server.py` / `camoufox_browser.py` | Camoufox browser API + CLI. |
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
5. **Email.** Draft-first: the agent saves a reply (`draft_email.py`), the human presses **Send with approval**
   in the drawer, and only then does `gmail_send.py` send that exact draft (one-time receipt; no env bypass).
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
- **Toolbar:** search (company/role/ATS), status filter, queue filter, **Export CSV**, row count,
  **⚡ Prepare shown** (generate documents, review-only) and **↻ Match** (recompute) for the rows shown.
- **Metric pills are filters:** click *in process / interviews / blocked / human / offers / total /
  submissions* to filter the grid to that set (click again or *total* to clear); the active pill is highlighted.
- **Process control:** while a run is active the strip shows **⏸ Pause** (workers finish the current task
  then wait) and **⏹ Stop** (no new tasks; terminate the in-flight action). Backend: `POST /api/action/pause`
  + `/api/action/stop` (`state/queue.pause` / `state/queue.stop`).

### 9.3 Master grid (the one table)
Columns: **Date · Company · Role · ATS · Status · Match · Queue · Files · Job ad**
(every header/cell/chip has a hover tooltip; **ⓘ Legend** explains them all).
- Search / filter / sort (click a header); **Export CSV**.
- **Match** = ATS-keyword coverage % of the CV (computed for every role that has a saved ad;
  shown with an `align✗` badge when the alignment gate failed).
- **Queue** = `pending | human | retry | done`; **Files** = provenance recorded (✓/—);
  **Job ad** = a saved job description exists (✓/—).
- The grid **auto-refreshes** (every ~8s, ~3s while a run is active) without losing scroll/sort/filter,
  and floats **in-flight** rows (🥜) and **QUEUED** rows (queued but not yet in the register) to the top.

### 9.4 Detail drawer (right-hand)
Clicking a row opens a drawer with tabs:
- **Summary** — a **Why / history** block first (the register's reason/notes, status, last-updated),
  then status (editable, writes back), ATS, queue, key, match, notes, and actions (Prepare).
- **Discuss** — a chat box scoped to this role. The first turn carries the row, status, ⚑ action,
  notes, the saved job ad and CV pack; each role keeps its own agent session and transcript
  (`state/logs/role-chat/<key>.log`), with Stop and Clear. Tool calls stay collapsed like the main console.
- **Provenance** — CV/letter paths + sha256 (click to copy), confidence, evidence, snapshot, screenshots.
- **Job spec · ATS · Grounding** — the ad text, keywords, and the GraphRAG context pack
  **plus the entities and source documents it cited** (resolved from the index).
- **Documents** — the **rendered** tailored CV (inline preview) and cover letter, with buttons to
  open either in the viewer and to open the CV PDF; the raw content pack is behind a toggle.

### 9.5 Settings panel (⚙ Config)
- Sections: **Accounts** (status + Gmail/Calendar authorisation), **AI & agent** (which agent CLI +
  model picker + API-token env, and the GraphRAG LLM `.env`), **Knowledge base** (list / upload /
  delete sources, rebuild the index), **GraphRAG** (browse entities / relationships / communities /
  documents), **Agent permissions** (per-category allow/ask/deny), **Profile & CV** (edit files, regenerate).

### 9.5b Agent permission gate (agent-agnostic)
- Policy in `config/agent-permissions.json`: `read_repo`/`write_repo` (default **allow**),
  `read_external`/`write_external`/`bash`/`task` (default **ask**), `web` (allow).
- Any agent reaches outside the repo via `tools/agent_access.py read|write|run …`, which
  **asks the operator** (unless the category is allow/deny) and blocks until they answer.
- The dashboard shows a **permission prompt** (Allow once / Always allow / Deny) and the policy is
  editable under **Settings → Agent permissions**. Native external access is denied so the gate can't
  be bypassed; it works for opencode, Claude Code and any `AGENT=` command.

### 9.6 Agent console (dockable)
- Dockable pullout (left by default; drag its header to any edge; splitters resize it and its panes;
  an Activity pane toggles open/closed). Drives whatever `tools/agent_run.sh --which` resolves —
  `opencode`, `claude`, or any `AGENT=` CLI.
- `POST /api/chat` + `GET /api/chat/stream` return **typed segments** (user / tool / text / status);
  the conversation persists across messages (session pinned; `＋ New` resets), tool runs collapse,
  and a spinner shows while working. A message sent while the agent is busy is **queued** (never
  rejected) and runs in order; the UI keeps polling while messages wait.
- The embedded agent is granted **scoped read access** to the operator's project folders
  (`~/vscode`, `~/Documents`, `~/projects`, `~/src`) and may spawn subagents, so "look at my
  projects" requests don't silently stall on `external_directory` denials; secrets
  (`~/.ssh`, `~/.gnupg`, `~/.config`, keyrings) stay denied.

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
| GET | `/api/accounts` | — | credential status (runs `setup_accounts.sh --check`) |
| GET | `/api/kb` | — | {sources, stats, check} |
| GET | `/api/graph` | `kind,q,limit` | graph rows from the index (entities/relationships/communities/documents) |
| GET | `/api/grounding` | `key` | a role's context pack + the entities/sources it cited, resolved |
| GET | `/api/runs` · `/api/log` · `/api/live` · `/api/tasks` · `/api/logs/tail` · `/api/agent` · `/api/chat/stream` | — | as named |
| POST | `/api/register/row` | `{company,role,status,notes}` | update a register row |
| POST | `/api/queue/action` | `{action,company,role}` | `delete` / `retry` / `unblock` |
| GET | `/api/drafts?company=&role=` | — | drafts for a role |
| GET | `/api/draft?path=` | — | one draft (headers + body) |
| POST | `/api/draft/save` | `{path?,company,role,to,cc,subject,attachments,body}` | save/update a draft |
| POST | `/api/draft/delete` | `{path}` | delete a draft |
| POST | `/api/draft/send` | `{path,clear_action?}` | send it (asks you to approve first) |
| GET | `/api/role-chat?key=` | — | that role's transcript segments + running state |
| POST | `/api/role-chat` | `{key,company,role,message}` | start/queue a role-scoped agent turn |
| POST | `/api/role-chat/stop` | `{key}` | stop that role's turn |
| POST | `/api/role-chat/new` | `{key}` | clear that role's transcript/session |
| GET | `/api/agent/models?agent=` | — | models the chosen CLI can run (opencode/Claude) for the picker |
| POST | `/api/roles/discover` | `{url}` | save a job spec from a URL |
| POST | `/api/config` | `{target,content}` | save config (JSON validated, `.bak`) |
| POST | `/api/action/run` | `{command, approval_token}` | `prepare` / `submit_queue` / `reconcile` / `build_archetypes` |
| POST | `/api/kb/upload` | multipart (`group`, `files`) | save documents into `kb/sources/<group>/` |
| POST | `/api/kb/delete` | `{path}` | remove a source document |
| POST | `/api/kb/rebuild` | — | rebuild the GraphRAG index (detached) |
| POST | `/api/accounts/auth` | `{kind}` | start Gmail/Calendar authorisation (detached) |
| POST | `/api/chat` · `/api/chat/new` | `{message}` · — | start a chat turn · reset the conversation |

All POSTs require header `X-Session: <token>` (else 403); the token is injected into the page.

### 9.9 Actions & gating
- **Prepare:** `REVIEW=1 run_queue.sh` — builds docs + gates, records PREPARED; never submits/emails. Safe.
- **Run Submissions:** `run_queue.sh` — **submits**. Requires the `APPROVE_RUN_QUEUE` approval token
  (the two-step modal: acknowledge + Confirm); refused otherwise. Every decision is logged to `state/approvals.log`.
- **Reconcile:** `gmail_reconcile.py` (read-only).
- **Regenerate archetype CVs:** `build_archetypes.py`. Safe.
- Runs are detached and logged to `state/logs/dashboard-action.log`.

### 9.9b Settings panel & knowledge graph
- **Settings** (⚙ Config) has sections: **Accounts** (credential status + Gmail/Calendar
  authorisation), **Knowledge base** (list/upload/delete source documents, rebuild the index),
  **GraphRAG** (browse entities / relationships / communities / documents from the index), and
  **Profile & CV** (edit `profile.md` / `cv.json` / `archetypes.json`, regenerate archetypes).
- Each role's detail drawer has a **Grounding** tab: the GraphRAG context pack plus the
  entities and source documents it cited, resolved from the index.

### 9.10 Theming & UX
- Dark, high-contrast; amber accent; colour-coded status chips; squirrel mascot animates; empty-state-safe.
- **Software update:** the header shows the running **version**; when `/api/update`
  (GitHub `releases/latest` vs the `VERSION` file, cached 1h) reports a newer
  release, an **⬆ update** pill appears. Clicking it shows the release notes with
  **Update now** (`git pull --ff-only`, approval-gated) — restart to apply.
- Degrades to empty state with no local data (safe on the public base).
- **One notification surface:** toasts replace in place (never stack), and the
  Prepare / Run Submissions / Reconcile buttons are disabled while a run is active.
- **Agent console:** a dockable pullout — **left by default**, or top / bottom / right. **Drag the
  console's header** to an edge (highlighted drop zones) to dock it; a small tab pulls it out when
  collapsed. The console and its Chat / Activity panes are **resizable with drag splitters** (sizes
  + dock position persist in `localStorage`), and the Activity pane is a **collapsible toggle**
  (headline summary shown in its header). Chat replies render as Markdown with runs of tool calls
  grouped into a single collapsed step block (and multi-line code fences collapsed), so only the
  assistant's prose stays in the body; a token/cost footer closes the turn. Driven by the agent's
  structured event stream — opencode `--format json`, Claude Code `stream-json` — with a
  plain-transcript fallback for any other `AGENT=` command. Action output is compressed to a
  headline + only the notable lines, with the full log behind a toggle.

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
