# Jobsquirrel: Product & Web Interface Specification

<div align="center"><sub><a href="../README.md">🐿️ Jobsquirrel</a> · <a href="README.md">📚 Docs</a></sub></div>


Status: living document · Owner: repo owner · Applies to this repository.

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

- **Candidate**: the owner. Supplies CV/rules, reviews output, approves risky actions, solves CAPTCHA/2FA.
- **Agent**: an AI coding agent that operates the repo via its CLI tools (contract: `AGENTS.md`).
- **Human-assist**: the person completing steps the automation must not (CAPTCHA, final submit in their own browser).

## 3. Architecture

```
discover  ->  queue  ->  per-role: JD + keywords + GraphRAG context
          ->  tailored CV + letter -> alignment gate + pre-submit gate
          ->  submit via browser (Camoufox) -> record (hash + snapshot)
          ->  reconcile replies (Gmail, read-only) -> outcomes + dashboard
```

Components:
- **CLI tools** (`tools/*.py`, `tools/*.sh`): one concern each; the contract for the agent.
- **Agent harness** (`tools/agent_run.sh`, `tools/run_queue.sh`): resolves the agent and runs one headless task per role.
- **Browser** (`tools/camoufox_server.py` + `camoufox_browser.py`): Camoufox browser for real ATS forms.
- **Knowledge base**: GraphRAG over `kb/sources/` (grounding for generated documents).
- **State**: plain files under `state/` (the source of truth).
- **Dashboard** (`tools/dashboard.py`): web UI (this spec, §9).

## 4. Data model (files are the API)

| Path | Contents |
|---|---|
| `state/applications.csv` | Canonical register: `date,company,role,ats,status,letter,notes,employment,action,key,apply_url`. One row per role. `key` is the role's single identity (the queue row's last column, also what `queue.done` stores); rows written before it existed fall back to `company|role`. `action` is a short **human to-do** (reply/assessment/booking) surfaced as ⚑ in the grid and filterable. A passive waiting phrase ("await a reply") is dropped: the status and sub-state already say that, and recording a sent reply clears the flag. |
| `state/submissions.csv` | Provenance ledger: paths + sha256 + snapshot dir + evidence + confidence (`verified`/`forced`/`inferred`). |
| `state/role-groups.json` | Named groups (campaigns): `{groups:{id:{name,color}},roles:{key:[id]}}`, independent of status. |
| `state/shelved.json` | Operator shelf: `{key:{at,note}}`. A view overlay only; the register status and artifacts are unchanged. |
| `config/canonical-facts.json` | Canonical fact wording: regex replacements applied at KB ingest and CV/letter render; the gate fails forbidden variants. |
| `config/email-triage.json` | Local additions for the language-agnostic email triage (extra ATS, hard/soft marketing domains). Private; the public example is `config/email-triage.example.json`. |
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
| `backups/` | Your backup zips plus the automatic `pre-restore-*` / `pre-clear-*` safety copies (newest five kept). Git-ignored: personal data. |
| `config/profile.md` | Identity, eligibility, pay, EEO, accuracy rules (key: value). |
| `config/cv.json` | Ground-truth CV (experience/projects/education/skills/sidebar). |
| `config/archetypes.json` | Role-family CV templates (one per family) + base letter. |
| `config/google.json` | Where the Google OAuth client/token live; optional client id/secret. Editable in Settings → Accounts. |
| `config/recruiter-aliases.json` | Optional sender/agency name → register company map, kept out of the code so names stay in config. |
| `config/email.json` / `config/calendar.json` | Sender signature + attachments; calendar timezone, meeting length, working hours. |
| `kb/sources/` | Private knowledge corpus (CVs, own sites, contracts…). |
| `kb/graphrag/` | Index + settings. |
| `documents/archetypes/`, `documents/applications/`, `documents/submitted/` | Reusable CVs, per-role letters, byte snapshots. |

## 5. Status model

`QUEUED | SUBMITTED | IN_PROGRESS | INTERVIEW | OFFER | REJECTED | BLOCKED | MANUAL | PREPARED | CLOSED`.

- **Follow-up flags** (`action` in the register; ⚑ in the grid, a toolbar filter, and editable
  in the row drawer). Each row also lists its **drafted replies** (write one, or ask the agent; then
  review and send with approval). Reconcile sets an action on an interview invite (`Reply to <sender>: <subject>`) and
  clears it on a rejection; anything manual (assessment, booking) can be flagged/cleared in the UI.
- **Engagement type** (`employment` in the register; shown as a per-row badge, editable in
  the drawer, filterable in the toolbar): `full-time | part-time | contract | consultant |
  freelance | internship | temporary`. Set explicitly on the row; otherwise guessed from the
  saved job ad, then the notes; `unknown` when nothing says.
- `INTERVIEW` is one stored status with three display labels, derived from the row's
  notes (the status itself never changes): **`SCHEDULED`** when the notes contain a
  future interview date, **`INVITED`** when they only show an invitation or an
  availability exchange ("invited", "book", "availability", "reschedule"), and plain
  **`INTERVIEW`** otherwise. The label is a hint, not a record: the notes and the
  mailbox are the truth, and a row can say `INVITED` long after the interview was
  held if nothing updated it. Reconcile keeps the notes current; the drawer shows them.
- **IN PROCESS** = `SUBMITTED + IN_PROGRESS + INTERVIEW + OFFER` (the live pipeline).
- `BLOCKED` = a manual step is required (CAPTCHA/login); do not auto-retry.
- `MANUAL` = the human must act (login/email); `PREPARED` = documents ready, not sent.
- `CLOSED` = do not pursue.

## 6. CLI tool catalog (selection)

| Tool | Role |
|---|---|
| `register.py` | The register: read `--stats/--list/--show`, edit `--set/--render/--delete`, integrity `--audit` (exits non-zero on duplicates, unrecorded `queue.done` rows, SUBMITTED rows without provenance, stale counts) and repair `--dedupe/--backfill/--backfill-done/--record-provenance-gaps`. |
| `record_submission.py` | Provenance: upserts register, writes `submissions.csv`, snapshots, enforces gate receipt + evidence; **idempotent**. |
| `gate_receipt.py` | Hash-stamped PASS receipts for the exact CV/letter; `record_submission.py` refuses a SUBMITTED row without one. |
| `jd_guard.py` | A role needs a saved job ad before it may enter the queue (`--require`, `--fetch`, `--queue`). |
| `storage.py` + `stateio.py` | Compress logs, mail cache and cold per-role artifacts; `stateio` makes a packed artifact read like a plain one. See `docs/STORAGE.md`. |
| `backup.py` | Back up / restore / clear the whole system as a single zip, with a safety copy before anything destructive. |
| `agent_access.py` | The permission gate for anything outside the repo: `read`/`write`/`run`, decided by the operator's policy. |
| `verify_pending.py` | Audit ATS email verifications against the register. |
| `outcomes.py` | Conversion by source and by CV (what is actually working). |
| `check_documents.py` | Pre-submit gate (identity, placeholders, salience, claims, rate, duplication, coverage); CV-only mode; `--record` writes a receipt. |
| `check_alignment.py` | Role-family vs CV-archetype alignment gate (PASS/FAIL). |
| `ats_keywords.py` | Extract keywords from a JD; score coverage. |
| `facts.py` / `identity.py` | Authoritative facts; standard form answers (JSON). |
| `cv_builder.py` / `build_archetypes.py` / `cv_target.py` / `cv_fill.py` / `make_letter.py` | Render CVs (docx+pdf) and letters from config. `cv_fill.py` measures whether the rendered pages are actually full; `check_documents.py` fails a thin CV. |
| `kb_graphrag.py` | Build the cited context pack for a role. |
| `discover.py` / `email_opportunities.py` | Find roles from LinkedIn alerts / recruiter mail. |
| `gmail_readonly.py` / `gmail_reconcile.py` | Read-only inbox sync + reconcile the register (inbound status changes; outbound Sent mail adds dated notes only). |
| `gmail_send.py` | Send a **saved draft** with attachments: requires a human dashboard receipt; no env bypass. |
| `send_receipt.py` | One-time receipts bound to a draft's SHA-256 (issued by the dashboard after approval). |
| `draft_email.py` | Draft replies tied to a role (`state/drafts/<company-role>/`); listed, edited and sent from the row drawer. |
| `google_config.py` | Resolve/write the Google OAuth client + token paths (`--status`, `--paths`, `--write-credentials`). |
| `calendar_event.py` | List/create/update events, import `.ics` invites, suggest free slots: writes **approval-gated**. |
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
   in the drawer, edits the exact email in the approval dialog if needed, and only then does `gmail_send.py`
   send that draft (one-time receipt; no env bypass).
   Mailbox deletion uses a separate `gmail.modify` token and `gmail_delete.py --authorize AUTHORIZE-DELETE`.
6. **Web UI.** Binds `127.0.0.1`; every write needs a per-session token (anti-CSRF); risky
   actions also gated (see §9).
7. **Recruitment-scam checks (`tools/scam_check.py`).** Every saved advert and every
   scanned message is checked for the known scam families: remote-access software
   (AnyDesk/TeamViewer/RustDesk), wallet/seed-phrase requests, pay-to-work fees,
   equipment cheques, task scams, money mules, reshipping, crypto salaries,
   labour-trafficking red flags, recovery scams, chat-only interviews, unrealistic
   pay, early ID/bank details, pressure and free-mailbox senders. A **HIGH** signal blocks `prepare_role.py`
   (exit 3; `--allow-scam` overrides after human verification), and the signal is
   stored in `state/scam/<key>.json`, shown as a ⚠ marker on the grid and a red/amber
   banner in the role drawer and the Gmail review. The hard rule: never download or
   install software for an interview, never join a chat-only interview, never share a
   wallet/seed phrase/private key, never pay a fee or move money. See `docs/SCAMS.md`.
   Mail is checked against the company's apply domain (lookalikes), free mailboxes,
   Reply-To mismatches, links (installers, IP/punycode hosts, wallet-connect, file
   hosts) and attachments (executables, archives); the worst warning per role is kept
   in `state/scam-emails.json`. Roles with a HIGH or specific MEDIUM signal are grouped
   in the **Probably scams** bucket, separate from **Needs you**.

## 8. Repository model

One repository, self-contained. Personal data (config, state, documents, the knowledge base)
stays on your machine and out of version control; the code and the documentation are generic
and person-agnostic. Everything that reaches a site goes through the same human-approval gates
and stops at any CAPTCHA/2FA rather than working around it.

## 9. Web interface specification (`tools/dashboard.py`)

### 9.1 Tech & running
- Python **stdlib only** (`http.server`, `subprocess`, `json`); single-page **vanilla JS**; no deps, no build.
- Binds **127.0.0.1** by default; `--host`, `--port` (default 8765), `--open`.
- A random **session token** is generated per launch, injected into the page, and required
  (header `X-Session`) for every write: anti-CSRF.
- Read-only until you act; the curated log view reuses `watch_queue` phase/noise knowledge.

### 9.2 Shell (single-grid IA)
The whole app is **one master data grid**: one canonical row per application, so the
same record is never duplicated across separate pages.
- **Header:** mascot 🐿️ · health pill (`/api/health`; click it to open Settings → About with
  the full check list, version and instance details) · three destinations: **📋 Applications**,
  **🕸️ Knowledge** and **⚙ Settings**. Version, build/update status, logs and the
  About/credits live in Settings. The broad Prepare / Run Submissions actions are
  not in the header; the grid card's action bar has scoped **Prepare** and **Submit**, and
  a `PREPARED` row's drawer has **Submit this application**.
- **Grid card:** the grid, its search/filter/view controls and its actions are one bordered
  card. The action bar sits directly above the table (not floating at the top of the page) with
  consistently sized buttons: **Export CSV**, **☰ Grouped**, **🏷 Groups**, **📬 Review**,
  **⚡ Prepare** (generate documents for the rows currently shown; review-only),
  **🚀 Submit** (submit the prepared rows in this view; approval-gated), **↻ Match** (recompute
  fit) and **ⓘ Legend**. Prepare, Submit, Match and Export CSV each show a plain-language
  confirmation dialog with the scope and effect before they run.
- **Application states header:** the section carries the bucket filter chips
  (**Active · Focus · Probably scams · Shelved · Needs you · Prepared · Ongoing · To apply · Done · All**)
  with live counts, plus the live-tail line (`/api/live`) and the run controls. Click a chip to filter the
  grid to that bucket; the active chip is highlighted. There is no separate metric strip, and the section
  sits directly above the grid card.
- **Process control:** while a run is active the Application states header shows **⏸ Pause** (workers
  finish the current task then wait) and **⏹ Stop** (no new tasks; terminate the in-flight action).
  Backend: `POST /api/action/pause` + `/api/action/stop` (`state/queue.pause` / `state/queue.stop`).

### 9.3 Master grid (the one table)
Columns: **Date · Company · Role · ATS · Status · Match · Queue · Files · Job ad**
(every header/cell/chip has a hover tooltip; **ⓘ Legend** explains them all).
- Search / filter / sort: **click any column header** to sort the whole list (the grid switches to a flat
  view so the order is not hidden inside collapsed groups), click again to reverse, and **☰ Grouped** in
  the toolbar returns to the bucket sections. The active sort carries an arrow. **Export CSV**.
- **Match** = ATS-keyword coverage % of the CV (computed for every role that has a saved ad;
  shown with an `align✗` badge when the alignment gate failed).
- **Queue** = `pending | human | retry | done`; **Files** = provenance recorded (✓/-);
  **Job ad** = a saved job description exists (✓/-).
- **Live updates:** the page opens one SSE stream (`/api/events`) and receives cheap state/live
  revisions. It fetches the grid only when state changes and refreshes the live strip only when logs or
  actions change. Polling remains a fallback (10s grid, 5s live) and pauses while the tab is hidden;
  an active run keeps the 3s/2.5s cadence. Scroll, sort and filters are preserved across updates.
  and floats **in-flight** rows (🥜) and **QUEUED** rows (queued but not yet in the register) to the top.
- **Application states graph** above the grid (collapsed by default): a clickable diagram of
  QUEUED → DRAFTING → PREPARED → SUBMITTED → IN_PROGRESS → INTERVIEW → OFFER, with BLOCKED/MANUAL
  branches and REJECTED/CLOSED terminals. Each node shows its live count and a
  one-line annotation; clicking a node expands its sub-states and filters the grid to that status,
  and clicking a sub-state filters further. **SCAMS** and **SHELVED** are side nodes that filter
  their buckets. The open/closed state is remembered.
- **Columns:** right-click any column header to choose which columns are visible. The choice is
  saved per browser. Drag a divider to resize a column; double-click it to reset that column.
- **Right-click a row** for the full action menu: open details / documents / the ad / the apply page,
  discuss the role, prepare documents, submit prepared (approval-gated), recompute the match, draft a
  reply with the agent, set the status, flag or clear a follow-up, **pin to the top**, re-queue, hand to a human, unblock/remove from the queue, and copy the company, role,
  URL or key. Keyboard: arrows move, Escape closes.
- **🏷 Groups** in the toolbar opens the group manager: create a campaign, rename or delete one.
  Deleting a group removes its memberships, not the roles. Right-click a row → Groups to add or
  remove that role.
- **Shelved** is a view overlay, not a status: right-click a row → **Shelve for later** keeps its
  status, notes, documents and provenance unchanged and moves it to the **Shelved** bucket and
  the **SHELVED** node in the state graph. The node sits next to **SCAMS** but is independent of
  it. Unshelve from the same menu.
- The menu is **state-aware**: it opens with the company, role, status chip, fit, ⚑ flag and interview
  time, and only offers actions that apply (no submit unless `PREPARED`, no reply draft on a closed
  role, no queue action on a prepared one, "Reopen as" instead of "Set status" on a rejected/closed
  one). Items that cannot apply are omitted rather than greyed out.
- **Pin** sorts a role first inside its group (📌).

### 9.4 Detail drawer (right-hand)
Clicking a row opens a drawer with a single tab strip that never wraps:
- **Summary**: structured sections rather than one long column. **Next action** flags, edits or
  clears a follow-up. **Status** shows the status chip, sub-state, stage chips and a compact
  metadata grid. **Actions** has Prepare, Graph evidence, Recompute match and, when prepared,
  Submit. **Drafted replies** is a collapsible section. **Role settings** groups status, type,
  work model and pay override behind one **Save changes**. **Match** shows alignment, coverage,
  missing skills and keyword tools. **History and notes** is a collapsible section with past
  updates and the editable notes.
- **Chat**: a chat box scoped to this role. The first turn carries the row, status, ⚑ action,
  notes, the saved job ad and CV pack; each role keeps its own agent session and transcript
  (`state/logs/role-chat/<key>.log`), with Stop and Clear. Tool calls stay collapsed like the main console.
- **Files**: CV/letter paths + sha256 (click to copy), confidence, evidence, snapshot, screenshots.
- **Job ad · ATS · Evidence**: the ad text, keywords, and the GraphRAG context pack
  **plus the entities and source documents it cited** (resolved from the index).
- **Docs**: the **rendered** tailored CV (inline preview) and cover letter, with buttons to
  open either in the viewer and to open the CV PDF; the raw content pack is behind a toggle.

### 9.5 Settings panel (⚙ Settings)
- Sections: **Accounts** (status + Gmail/Calendar authorisation), **Secrets** (the encrypted
  store: agent keys, GraphRAG, Google OAuth, per-site logins and custom entries, masked),
  **AI & agent** (which agent CLI + model picker + API-token env, and the GraphRAG LLM settings),
  **Knowledge base** (list / upload / delete sources, rebuild the index), **GraphRAG** (a status card
  and launcher for the full-page Knowledge workspace), **Agent permissions**
  (per-category allow/ask/deny), **CAPTCHA** (private build: provider, model, timeout, key),
  **Profile & CV** (edit files, regenerate), **Logs** (browse and tail task logs, or open the
  standalone page), **Backup & data**, and **About** (full health checks from `doctor.py`, the
  register audit, version, build/update status, the running instance's Python/platform/uptime/
  PID/data paths/register/queue/graph counts, release notes, documentation/GitHub links and the
  credit). Clicking the header health pill opens About and scrolls to the checks.
- Every field saves on change; Settings has no save buttons. The CAPTCHA pane, the AI/agent
  pane and the secrets Replace field all write immediately and report the result in a toast.

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
  an Activity pane toggles open/closed). Drives whatever `tools/agent_run.sh --which` resolves -
  `opencode`, `claude`, or any `AGENT=` CLI.
- `POST /api/chat` + `GET /api/chat/stream` return **typed segments** (user / tool / text / status);
  the conversation persists across messages (session pinned; `＋ New` resets), tool runs collapse,
  and a spinner shows while working. A message sent while the agent is busy is **queued** (never
  rejected) and runs in order; the UI keeps polling while messages wait.
- **Prompt history:** press **↑** in the chat input for a popup of your previous prompts (newest
  selected at the bottom; ↑ walks back in time, ↓ forward, Enter fills the input, Esc closes). Typing
  filters the list, and clicking an entry selects it. The last 100 prompts persist in the browser.
- The embedded agent is granted **scoped read access** to the operator's project folders
  (`~/vscode`, `~/Documents`, `~/projects`, `~/src`) and may spawn subagents, so "look at my
  projects" requests don't silently stall on `external_directory` denials; secrets
  (`~/.ssh`, `~/.gnupg`, `~/.config`, keyrings) stay denied.

### 9.8 HTTP API

| Method | Path | Params | Returns |
|---|---|---|---|
| GET | `/` |: | the single-page UI (token injected) |
| GET | `/api/state` |: | {kpis, counts, queue_counts, interviews} |
| GET | `/api/health` |: | doctor.py result (cached 30s) |
| GET | `/api/events` |: | SSE stream of cheap `state` and `live` revisions; one event per change, 15s heartbeat |
| GET | `/api/revision` |: | the current `state` and `live` revision fingerprints |
| GET | `/api/grid` |: | the unified grid rows (register ⋈ queue ⋈ spec ⋈ provenance) |
| GET | `/api/health?full=1[&refresh=1]` |: | full checks + this instance's version, runtime, paths and counts for Settings → About |
| GET | `/api/grid` |: | the unified grid rows (register ⋈ queue ⋈ spec ⋈ provenance) |
| GET | `/api/backup` | `info=1`, `documents=0/1` | backup summary, or the `.zip` as a download (session token required) |
| POST | `/api/backup/restore` | multipart `file`, `confirm=RESTORE` | restores over the current state after a safety backup |
| POST | `/api/backup/clear` | `{scope: data|full, confirm=CLEAR}` | deletes generated data; `config/` and `kb/sources/` survive |
| GET | `/api/register` | `q,status,limit,offset` | {total, rows} |
| GET | `/api/provenance` | `company,role` | provenance row (sha256, evidence, snapshot) |
| GET | `/api/queue` |: | {pending, human, retry, done} |
| GET | `/api/roles` · `/api/roles/<key>` |: | spec list · {jd, ats, kb, tailored_cv, letter, match} |
| GET | `/api/config` | `target` | {target, content, format} |
| GET | `/api/outcomes` |: | {by_ats, interview_rate} |
| GET | `/api/accounts` |: | credential status (runs `setup_accounts.sh --check`) |
| GET | `/api/kb` |: | {sources, stats, check} |
| GET | `/api/graph` | `kind,q,limit` | graph rows from the index (entities/relationships/communities/documents) |
| GET | `/api/graph/ontology` |: | ontology classes, relation vocabulary and counts |
| GET | `/api/graph/types` | `limit` | canonical classes with aggregate links |
| GET | `/api/graph/type` | `type,limit` | largest connected component for one class |
| GET | `/api/graph/overview` | `parent,limit` | community hierarchy (roots or children) |
| GET | `/api/graph/community` | `id,limit` | children of a community or its leaf entities |
| GET | `/api/graph/search` | `q,limit` | matching communities and entities |
| GET | `/api/graph/ego` | `q,limit` | one entity plus its 1-hop network |
| GET | `/api/kb/find` | `name` | resolve a graph document title to a `kb/sources/` file |
| GET/POST | `/api/secrets` |: / `{section,name,value}` | masked secrets store read / write |
| POST | `/api/secrets/delete` · `/api/secrets/encrypt` · `/api/secrets/migrate` |: | remove, encrypt or import |
| GET | `/api/grounding` | `key` | a role's context pack + the entities/sources it cited, resolved |
| GET | `/api/runs` · `/api/log` · `/api/live` · `/api/tasks` · `/api/logs/tail` · `/api/agent` · `/api/chat/stream` |: | as named |
| POST | `/api/register/row` | `{company,role,status,notes}` | update a register row |
| GET | `/api/groups` |: | groups (campaigns), memberships and counts |
| POST | `/api/groups` | `{op:create\|rename\|delete\|assign,name,group,key,on}` | create, rename, delete or assign a role |
| POST | `/api/queue/action` | `{action,company,role}` | `delete` / `retry` / `unblock` |
| GET | `/api/drafts?company=&role=` |: | drafts for a role |
| GET | `/api/draft?path=` |: | one draft (headers + body) |
| POST | `/api/draft/save` | `{path?,company,role,to,cc,subject,attachments,body}` | save/update a draft |
| POST | `/api/draft/delete` | `{path}` | delete a draft |
| POST | `/api/draft/send` | `{path,clear_action?}` | send it (asks you to approve first) |
| GET | `/api/role-chat?key=` |: | that role's transcript segments + running state |
| POST | `/api/role-chat` | `{key,company,role,message}` | start/queue a role-scoped agent turn |
| POST | `/api/role-chat/stop` | `{key}` | stop that role's turn |
| POST | `/api/role-chat/new` | `{key}` | clear that role's transcript/session |
| GET | `/api/agent/models?agent=` |: | models the chosen CLI can run (opencode/Claude) for the picker |
| POST | `/api/roles/discover` | `{url}` | save a job spec from a URL |
| POST | `/api/config` | `{target,content}` | save config (JSON validated, `.bak`) |
| POST | `/api/action/run` | `{command, approval_token}` | `prepare` / `submit_queue` / `reconcile` / `build_archetypes` |
| POST | `/api/kb/upload` | multipart (`group`, `files`) | save documents into `kb/sources/<group>/` |
| POST | `/api/kb/delete` | `{path}` | remove a source document |
| POST | `/api/kb/rebuild` |: | rebuild the GraphRAG index (detached) |
| POST | `/api/accounts/auth` | `{kind}` | start Gmail/Calendar authorisation (detached) |
| POST | `/api/chat` · `/api/chat/new` | `{message}` ·: | start a chat turn · reset the conversation |

All POSTs require header `X-Session: <token>` (else 403); the token is injected into the page.

### 9.9 Actions & gating

Dashboard actions run detached: the console stays usable while they work, and progress is
reported in the **Activity** pane. Only the explicit submit approval is a blocking dialog.
The pre-submit gate also checks `config/canonical-facts.json`: a CV or letter that still
contains a non-canonical fact wording fails before it can be submitted.
- **Prepare:** `REVIEW=1 run_queue.sh`: builds docs + gates, records PREPARED; never submits/emails. Safe.
- **Run Submissions:** `run_queue.sh`: **submits**. Requires the `APPROVE_RUN_QUEUE` approval token
  (the two-step modal: acknowledge + Confirm); refused otherwise. Every decision is logged to `state/approvals.log`.
- **Reconcile:** `gmail_reconcile.py` (read-only). It also annotates the Gmail
  review queue with a language-agnostic job-related triage hint
  (`tools/email_triage.py`: ATS/company domains, application ids, meeting links,
  system senders). Review-only; it never changes a status. The review modal has a
  **triage: job-related** filter.
- **Regenerate archetype CVs:** `build_archetypes.py`. Safe.
- Runs are detached and logged to `state/logs/dashboard-action.log`.

### 9.9b State model: the application state machine

The application process is a **state machine**: one register row moves through the statuses
`QUEUED → DRAFTING → PREPARED → SUBMITTED → IN_PROGRESS → INTERVIEW → OFFER`, with
`BLOCKED`/`MANUAL` branches and `REJECTED`/`CLOSED` terminals. The register `status` is that
machine stage (gates, queue, reconciliation); the dashboard draws the same machine above the
grid. On top of it the dashboard derives a human **sub-state** from the row's notes and
follow-up flag and exposes it on every grid row:

| Field | Meaning |
|---|---|
| `substate` | stable key (e.g. `assessment`, `scheduled`, `captcha`) |
| `substate_label` | short human label (e.g. "assessment to take", "scheduled") |
| `substate_hint` | what it means / what to do next |

The grid shows the sub-state under the status chip; **Filters → any sub-state** filters on
`status:substate`; the Application states panel expands each node into a clickable sub-state tree. The
`Needs you` bucket treats `assessment`, `stale`, `captcha`, `login`, `email`, `lead`, `verify`
and `info` as waiting on the candidate, alongside flagged actions, invites and offers.

| Status | Sub-states |
|---|---|
| `QUEUED` | queued |
| `DRAFTING` | drafting |
| `PREPARED` | needs review · ready to submit |
| `NO RESULT` | no result |
| `SUBMITTED` | acknowledged · awaiting reply · assessment to take · assessment overdue · follow up |
| `IN_PROGRESS` | assessment · interviewing · background check · processing |
| `INTERVIEW` | invited: reply · scheduled · interview today · replied: awaiting a reply · next round · final round · interviewed: awaiting outcome · interviewed: follow up |
| `OFFER` | offer received · verbal offer · negotiating · accepted · declined |
| `BLOCKED` | CAPTCHA · login / 2FA · email application · recruiter lead · site problem · missing information · blocked |
| `MANUAL` | email application · recruiter lead · verification · needs you |
| `REJECTED` | after application · after interview |
| `CLOSED` | withdrawn · expired / gone · duplicate · not eligible · filled · closed |

### 9.9c Knowledge workspace (top-bar **Knowledge**)

The full guide is **[KNOWLEDGE-GRAPH.md](KNOWLEDGE-GRAPH.md)**; this is the
interface contract.

- **Full-page workspace.** Universe and Map fill the area below the header; the
  job grid is out of the way. One toolbar holds the title, the **Universe** /
  **Map** toggle, the stats, the search controls and the actions. The toggle
  switches views (Universe is no longer a separate top-bar button).
- **Universe.** The whole index: level-0 communities as islands, weighted
  importance, community nebulae, zoom-tiered labels, a 1 to 3 hop focus slider and
  the same point-star renderer as the Map.
- **Map.** The same renderer drilled down through **Topics** (ontology classes),
  **Communities** (the generated hierarchy), **Entities** and **Ego** networks.
  The same toolbar has a 1 to 3 hop focus selector; breadcrumbs appear below it.
- **Focus and fade.** Selecting an entity frames it and its direct neighbours,
  lights the selected hops, dims the rest and fades back after roughly four
  seconds plus a one-second fade. The selected node keeps its marker, size and
  label. Clicking empty space clears the focus, restores the previous camera and
  re-runs the normal label set. Labels are tiered by zoom outside a focus.
- **Node pane.** Title, class, degree, mentions, community, description,
  subgraph counts/depth/layers, source documents, neighbours, strongest
  connections, **Edit details** (description/type override), **Add connection**
  (grounded overlay link), **Focus ego network** and **Open community**.
- **Ask.** Local, global, basic and drift questions answered from the graph with
  citations. Answers are redacted like context packs and never invent an
  unsupported fact.
- **Semantic search.** Entity search over the LanceDB description vectors, with
  similarity and impact shown.
- **Role evidence.** A saved ad's keywords mapped to grounded entities and an
  explicit gap list.
- **Grounded enrichment.** Reviewable proposals supported by existing text;
  approved nodes/links are gold and marked grounded. Operator edits and approved
  links live in `enrichment.json` / `edits.json` and survive a rebuild.
- **Orphans.** No entity should have zero links. Curated, evidence-backed links
  live in `orphan-links.json` and are applied by `graph_attach_orphans.py`;
  unattached entities are grouped in the labelled **Unlinked evidence** island.
  `graph_quality.py --fail-orphans` enforces it.
- **Privacy.** Contract/legal material is excluded at ingest, pruned from the
  index, removed from provenance and redacted from answers; the quality gate
  fails on any sensitive or ungrounded entity.
- **Sources / Add / Roles.** Upload/delete/rebuild documents, record a fact or
  skill without a rebuild, and open or prepare a role in the application drawer.
- **Classes** lists the ontology and relation vocabulary. The ontology is
  editable in `config/ontology.json`; unknown GraphRAG types fall back to
  Concept.
- Each role's detail drawer still has a **Grounding** tab: the GraphRAG context
  pack plus the entities and source documents it cited, resolved from the index.

### 9.10 Theming & UX
- Dark, high-contrast; amber accent; colour-coded status chips; squirrel mascot animates; empty-state-safe.
- **Software update:** the header shows the running **version**; when `/api/update`
  (GitHub `releases/latest` vs the `VERSION` file, cached 1h) reports a newer
  release, an **⬆ update** pill appears. Clicking it shows the release notes with
  **Update now** (`git pull --ff-only`, approval-gated): restart to apply.
- Degrades to an empty state with no local data.
- **One notification surface:** toasts replace in place (never stack), and the
  The scoped Prepare / Submit / Reconcile actions are disabled while a run is active.
- **Agent console:** a dockable pullout: **left by default**, or top / bottom / right. **Drag the
  console's header** to an edge (highlighted drop zones) to dock it; a small tab pulls it out when
  collapsed. The console and its Chat / Activity panes are **resizable with drag splitters** (sizes
  + dock position persist in `localStorage`), and the Activity pane is a **collapsible toggle**
  (headline summary shown in its header). Chat replies render as Markdown with runs of tool calls
  grouped into a single collapsed step block (and multi-line code fences collapsed), so only the
  assistant's prose stays in the body; a token/cost footer closes the turn. Driven by the agent's
  structured event stream (opencode `--format json`, Claude Code `stream-json`) with a
  plain-transcript fallback for any other `AGENT=` command. Action output is compressed to a
  headline + only the notable lines, with the full log behind a toggle. The pane shows **current**
  activity. A finished action is a one-line "last action: <name>: finished" plus its summary, never
  its transcript, and the header reads **idle** when nothing is running (the last action's name
  survives a server restart, its log does not).
- **Background subagents.** The chat agent hands long work to `tools/delegate.py`, which posts to
  `/api/delegate`; the dashboard spawns `agent_run.sh` detached, logs it to
  `state/logs/delegated-<id>.log`, and tracks it in `state/delegated/<id>.json`. Up to four run at
  once. They appear in the Activity pane (and the console's ▶ list) with their own log, while the
  chat stays responsive; a finished one is pruned from the live list but its log remains.

## 10. Configuration schemas

- **`config/profile.md`**: `- key: value` lines for identity, work authorisation/languages,
  availability/pay, eligibility (based-in / accept / exclude), accuracy rules, EEO answers.
- **`config/cv.json`**: `{name, headline_default, tagline_default, profile_default, skills[],
  experience[{employer,dates,title,location,bullets[],extras{}}], projects[], education[],
  certifications[], languages[], sidebar{...}}`.
- **`config/archetypes.json`**: `[{key,title,headline,tagline,opening,profile,fit,skills[[cat,text]],tags[]}]`.

## 11. Extensibility

- **New ATS**: add a recipe to `docs/ATS-RECIPES.md`; browser CLI already generic.
- **New agent CLI**: it just needs to accept the prompt as its last argument (`AGENT=`).
- **New dashboard view**: add a `GET /api/...` endpoint + a tab (the UI is plain JS).
- **New safety gate**: implement in `tools/approval.py` and call it before the action.

## 12. Non-goals

- Not a push-button "apply to 500 jobs autonomously" bot: the human owns decisions and approvals.
- No credential storage in the repo; no CAPTCHA evasion.
- No fabricated claims, credentials, or identities.

## 13. Roadmap (candidates)

Digest/notifications · offer toolkit · interview kit (grounded prep) · funnel charts ·
add-role-by-URL · per-role "generate CV+letter" button · SSE streaming for live/chat ·
approval inbox in the UI · richer archetype editor.
