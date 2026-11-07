# Using it: typical prompts and monitoring

<div align="center"><sub><a href="../README.md">Jobsquirrel</a> · <a href="README.md">Docs</a></sub></div>


You drive the whole thing by **talking to your agent in plain English**.
`AGENTS.md` teaches it the procedures; you set direction with short goals. You
never run the tools by hand, but you can watch everything it does.

## The rhythm

```
discover → (optionally review) → apply → monitor → reconcile → repeat
```

A normal session: find roles, queue them, run the pipeline, keep an eye on
progress, then reconcile replies and clear anything that needs a human.

## Typical prompts

You don't need special syntax, just say what you want. Examples that map to the
built-in procedures:

| You say | What the agent does |
| --- | --- |
| *"Set this up"* / *"Bootstrap it"* | runs `BOOTSTRAP.md`: interview → `config/` → archetypes → knowledge base → accounts |
| *"Find new senior roles and queue them"* | `discover.py` (+ web search) → `state/queue.tsv`, prioritised most-senior-first |
| *"What's in the queue?"* | shows pending rows and the order they'll run |
| *"Prepare documents for the top 5, don't send"* | `REVIEW=1 … run_queue.sh`: builds + gates, records `PREPARED` |
| *"Show me only contract roles"* | the toolbar's **any type** filter (full-time / part-time / contract / consultant / freelance / internship / temporary / unknown); set a row's type in its drawer |
| *"Submit the prepared ones"* | *Submit* (grid) or *Submit this application* (drawer) reuses the already-gated CV/letter and applies, with a two-step confirmation (`APPROVE_RUN_QUEUE`) |
| *"Run the pipeline"* / *"Apply to the queue"* | `PARALLEL=3 bash tools/run_queue.sh`, most senior first |
| *"Use one fixed CV for these"* | `LIGHT=1 FIXED_CV=<path> … run_queue.sh` |
| *"Apply to just this one: <url>"* | the per-role manual procedure (`AGENTS.md` §4) |
| *"Show me the CV/letter you'd send for <Company> <Role>"* | builds it and shows the text, does **not** submit |
| *"How's it going?"* / *"Status?"* | run/queue/register status (below) |
| *"Reconcile with my email"* | `gmail_reconcile.py --apply` → sets INTERVIEW/REJECTED/SUBMITTED, surfaces verification links |
| *"What needs me?"* | lists `BLOCKED`/`MANUAL`, pending CAPTCHA/2FA, emails to approve, verification links, interviews |
| *"Summarise the last run"* | reads `state/logs/run_queue.out` + the register |

**Habits that work**

- **One goal per message**, and say the mode if it matters ("review" vs "apply").
- **State constraints up front**: *"senior+ only"*, *"remote-EU"*, *"max 10 today"*.
- **Ask for a one-screen summary** when a batch finishes.
- **Fix the source, not the symptom.** If a claim is wrong, correct the document
  in `kb/sources/` (or your `config/`) and re-index, the fix then applies
  everywhere. Never let it "just tweak the letter".
- **You stay in the loop** for approvals and walls; don't ask it to bypass them.

## Monitoring

Everything is observable. Useful things to ask for, or run yourself:

- **Live run**: `bash tools/watch_queue.sh`, a dashboard (TUI) of the *current*
  run's tasks only (keys: `q` quit, `r` refresh).
- **Raw log**: `state/logs/run_queue.out`, `STATUS …` / `DONE` / `ABORT` lines
  and any model budget/rate-limit stop.
- **Structured run log**: `state/logs/runs.jsonl`, one JSON line per task
  (`company`, `role`, `outcome`, `rc`, `reason`): the machine-readable
  counterpart to `run_queue.out` for scripts and dashboards.
- **Health**: `python3 tools/doctor.py` (`--json` for scripts) checks config, the
  knowledge base, the browser, the register and git before you start a run.
- **Web UI**: `python3 tools/dashboard.py --open` (binds `127.0.0.1:8765`; `--port` to change).
  A dependency-free dashboard over the register, queue, specs and provenance:
  - **One master grid** (no tabs): a row per application with Date · Company · Role · ATS ·
    Status · **Match** (ATS-keyword coverage; `align✗` = the alignment gate failed) · Queue ·
    Files · Job ad, plus search / status / queue / group filters, sortable columns, CSV export
    and an **ⓘ Legend**. Right-click a row to add it to a named **group** (a campaign), or create
    one; the **Groups** toolbar button opens the group manager to create, rename or delete
    groups. Groups are independent of status and survive renames and queue runs. Hover anything for
    what it means; click a row for the detail drawer
    (Summary · Chat · Files · Job ad · ATS · **Evidence** · Docs). The page uses one live event
    stream: the grid only rebuilds when state changes, the live strip updates when logs or actions
    change, and polling pauses while the tab is hidden.
  - **Groups / campaigns.** A group is a named campaign that crosses status. Create one with the
    **Groups** toolbar button (or right-click a row → Groups → New group…). Add or remove a role
    from right-click → Groups; a tick marks membership. Filter with the **any group** dropdown; a
    group view shows every member regardless of status, but still applies the ordinary
    search/status/queue filters. Group tags appear under the role title, and clicking one filters
    to that group. **Groups** also renames and deletes groups: deleting removes memberships, not
    roles. Groups live in `state/role-groups.json`, independent of the register, so status changes,
    renames and queue runs do not disturb them; CSV export includes a `groups` column.
  - **Evidence** shows how your knowledge graph was used for that role: the cited context pack
    plus the entities and source documents it referenced, resolved from the index.
  - **Agent console** (dockable: **left by default**; drag its header to any edge, or the pullout
    tab when collapsed; panes resize with the splitters). Chat drives whichever agent
    `tools/agent_run.sh` resolves (opencode, Claude Code, or any `AGENT=` CLI) and remembers the
    conversation across messages (＋ New to reset). Tool runs are grouped into plain-language
    sections ("Checked the application register", "Read files", "Ran tests"), with the exact
    commands and output under **Technical details**; opening or closing a section survives the
    live refresh. Work requests are handed to **background subagents** and reported in the
    **Activity** pane, so the chat stays responsive. Activity leads with a short human summary;
    the raw commands and logs stay under a collapsed **Technical details** section, both in the
    pane and in the per-task log. The chat answers questions and quick checks directly and shows
    a spinner only while it is doing that.
  - **Settings**: **Accounts** (credential status + Gmail/Calendar authorisation),
    **Secrets** (the encrypted store, with Replace saving on blur), **AI & agent**, **Knowledge base**
    (list / upload / delete source documents, rebuild the index), **GraphRAG** (browse entities,
    relationships, communities and documents), **Agent permissions**, **CAPTCHA**, **Profile & CV**
    (edit `profile.md` / `cv.json` / `archetypes.json`, regenerate the archetype CVs), **Logs**
    (browse and tail task logs, or open the standalone page) and **About** (full health checks,
    version, build/update status, this instance's runtime/data paths/counts, release notes and
    credits). Clicking the **health** pill in the header opens About and scrolls to the checks.
    Every field saves on change; there are no save buttons.
  - The header has three destinations: **Applications**, **Knowledge** and **Settings**. The
    page-level actions live in the grid card's action bar: **Prepare** (REVIEW=1, no submits),
    **Submit** and **Review**. Prepare, Submit, Match and Export CSV each show a confirmation
    dialog with the scope and effect before they run. A `PREPARED` row's drawer has **Submit this application**.
    Submitting uses the documents already generated, with no re-generation, and needs a two-step
    confirmation (`APPROVE_RUN_QUEUE`). Every action needs the per-session token (anti-CSRF) and
    the UI binds to `127.0.0.1` only; the chat agent inherits the same approval gates: it cannot
    send or delete mail without them. Prepare, submit and knowledge-base actions run detached in
    the background: the console stays usable and progress is reported in **Activity**; only the
    explicit submit approval is a blocking dialog.
- **Register**: `python3 tools/register.py --stats`;
  `python3 tools/register.py --list --status INTERVIEW`;
  `python3 tools/register.py --show "<Company>"`.
- **Conversion**: `python3 tools/outcomes.py`, response rate by source (ATS/site)
  and by CV, so you invest where it actually converts.
- **Queue state**: `state/queue.tsv` (pending), `state/queue.done` (finished,
  keyed by the row's `key`, the same identity the register uses).
- **Replies / counts**: `bash tools/reconcile_loop.sh` keeps reconciliation and
  `state/counts.md` fresh in the background.
- **Interviews**: `python3 tools/gmail_calendar_auth.py --check --days 14`.
- **Human-only items**: `state/queue-human.tsv`, opened with
  `bash tools/human_assist.sh`.

### Gmail triage

`gmail_reconcile.py` also annotates the review queue with a language-agnostic
triage hint. The regex classifier is fast but language-specific, so clearly
job-related mail can still land in OTHER. The triage layer checks ATS and
company sender domains, application/requisition ids, meeting links with dates,
LinkedIn job alerts and system senders, then marks the item as **job-related**
with a category hint.

- Open the Gmail review and choose **triage: job-related** to see only those
  messages.
- The hint is review-only: it never changes a status or sends anything.
- Personal or local domain additions go in `config/email-triage.json`; the
  public template is `config/email-triage.example.json`.

## State model: the application state machine

The application process is a **state machine**. The register keeps a small, stable set of
**statuses**: the machine stage used by the pre-submit gates, the queue and the reconciler -
and one row moves through them (`QUEUED → DRAFTING → PREPARED → SUBMITTED → IN_PROGRESS →
INTERVIEW → OFFER`, with `BLOCKED`/`MANUAL` branches and `REJECTED`/`CLOSED` terminals). The
dashboard draws that machine above the grid and every tool reads and writes the same state.

On top of each status the dashboard derives a **sub-state** from the role's notes and
follow-up flag. The sub-state is the human answer to “what is actually happening, and what
should I do next?”.

- **Knowledge graph navigation:** the arrows in the Knowledge toolbar go back and
  forward through graph views (Alt+Left / Alt+Right).
- **Columns:** right-click a column header to show or hide columns. The choice is remembered.
  Drag a divider to resize a column; double-click it to reset that column.
- The **Status** cell shows the status chip and, underneath, the sub-state when it adds detail.
- **Filters → any sub-state** narrows the grid to one sub-state; like a group, it crosses the
  bucket boundaries.
- The **top row of the grid** carries the bucket filter chips (Active, Focus, Probably scams,
  Needs you, Probably scams, Shelved, Prepared, Ongoing, To apply, Done, All) with live counts, plus the live status
  and run controls. Click a state to expand its sub-states and filter to it, then click a sub-state
  to narrow further. The small chevron at the left edge folds the state map out and back. There is no
  separate metric bar, title bar or card around the grid.
- **Level** is the seniority grade the pipeline reads from the title (Intern up to C-level). Click the **Level** header to sort by it, or pick a grade under **Filters → any level**. It works independently of the bucket chips, and the **Pay** header sorts by salary just as independently.
- **Needs you** is the first working bucket. It includes BLOCKED and NO RESULT rows (a gate refusal or an empty run is work for you), plus the sub-states that genuinely wait on you: assessments, follow-ups,
  CAPTCHA/2FA and other human walls, plus invites and offers.
- **Shelved** takes a role out of the process: it disappears from the status and
  bucket views (and the queue runner skips it) while its register status, notes,
  documents and provenance are unchanged. It stays visible under the Shelved
  bucket until you unshelve it.
- **Shelved** is a view overlay, not a status. Right-click a row → **Shelve for later**; its
  status, notes, documents and provenance stay unchanged, and it moves to the **Shelved** bucket
  at the bottom of the grid and the **SHELVED** node in the state graph. Unshelve from the same menu. The node sits next to
  SCAMS but is independent of it.

| Status | Sub-states | What it means |
|---|---|---|
| `QUEUED` | queued | In the apply queue; nothing sent yet. |
| `DRAFTING` | drafting | Ad/keywords saved; documents still being built. |
| `PREPARED` | needs review · ready to submit | Documents gated; review/send, or submit when ready. |
| `NO RESULT` | no result | A run finished without an ad, documents or a submission. |
| `SUBMITTED` | acknowledged · awaiting reply · assessment to take · assessment overdue · follow up | Sent; waiting, a test to take (or its deadline has passed), or time to chase. |
| `IN_PROGRESS` | assessment · interviewing · background check · processing | The employer is processing the application. |
| `INTERVIEW` | invited: reply · scheduled · interview today · replied: awaiting a reply · next round · final round · interviewed: awaiting outcome · interviewed: follow up | The interview stage, from arranging to awaiting the result. |
| `OFFER` | offer received · verbal offer · negotiating · accepted · declined | The offer stage. |
| `BLOCKED` | CAPTCHA · login / 2FA · email application · recruiter lead · site problem · missing information · blocked | A wall; the ones that need you appear under **Needs you**. |
| `MANUAL` | email application · recruiter lead · verification · needs you | A human step the pipeline will not take. |
| `REJECTED` | after application · after interview | Not selected; no action. |
| `CLOSED` | withdrawn · expired / gone · duplicate · not eligible · filled · closed | No further action. |

Sub-states are derived from the notes and follow-up flag the pipeline and the reconciler
already write, so they need no extra bookkeeping. Correcting a note (or setting/clearing the
follow-up flag) updates the sub-state on the next refresh. The flag is a **human to-do**
("reply to Ray", "book a time"), not a waiting state: "await a reply" is dropped, and once a
reply has been sent the row reads **replied: awaiting a reply** instead of asking you again.

## Recruitment scams

Every saved advert and every scanned message is checked for known scam signals. A
scam marker on a grid row, or a red/amber banner in the role drawer or the Gmail review,
means: **read it before you reply.**

> **Never download or install software, join a chat-only interview, share a wallet,
> seed phrase or private key, pay a fee, or move money during a recruitment process.**

The common high-risk signals are remote-access tools ("install AnyDesk before the
interview"), wallet/seed-phrase requests, pay-to-work fees, equipment cheques,
chat-only interviews on Telegram/WhatsApp, and unrealistic pay for no experience.
A HIGH signal stops document preparation; the role can still be recorded `BLOCKED`
with the reason. Mail is checked too: the sender domain against the company's
apply domain (lookalikes), free mailboxes, Reply-To mismatches, installers,
shortened/IP/punycode links, wallet-connect links and dangerous attachments.

Roles with a warning appear in the **Probably scams** bucket, separate from
**Needs you**, so a suspicious advert or message cannot hide among the ordinary
follow-ups. See **[SCAMS.md](SCAMS.md)** for the full list and what to do.

## The Knowledge workspace

The top-bar **Knowledge** page is the full-page view of your knowledge base.
It uses one toolbar for the title, the **Universe** / **Map** toggle, search,
view controls and actions. **Universe** shows the whole graph as theme islands;
**Map** drills through
**Topics** (ontology classes), **Communities** (the generated hierarchy),
**Entities** and **Ego** networks. Click an entity for its description, sources,
neighbours and strongest connections; double-click opens its ego network.
Selecting an entity lights its neighbourhood and dims the rest, then fades back
after a few seconds; clicking empty space restores the previous view. **Ask**
answers questions with citations, **Semantic** searches entities by meaning, and
**role evidence** maps a saved ad's keywords to grounded evidence and gaps.
**Sources** uploads/deletes/rebuilds documents, **Add** records a fact or skill
without a rebuild, and **Roles** opens a role in the application drawer (or
prepares a queued role). Drag to orbit, scroll to zoom, right-drag to pan.

The full guide is **[KNOWLEDGE-GRAPH.md](KNOWLEDGE-GRAPH.md)**.

The graph and the application drawer share the same evidence: a claim you add
under **Add** is appended to every GraphRAG context immediately and appears in
the graph view through a live skill overlay, so no rebuild is needed -
re-prepare the role to fold it into the CV. Rebuild only when you
change a document under Sources. A role you open under **Roles** uses the same
grounding and gates as a queue run.

## Backup, restore and start over

Settings → **Backup & data** covers the three things you do around the edges of
a job search: take a copy, put a copy back, or clear the system and start again.

**Backup** writes one `.zip` with everything the pipeline cannot regenerate:
`config/` (profile, CV, archetypes, mail/calendar and Google settings),
`answers/`, `kb/sources/` (your corpus), `state/` (register, queues, provenance,
drafts, saved ads, keyword files, grounding and content packs, gate receipts) and,
unless you untick it, `documents/` (rendered CVs, letters, and the exact files
you sent). Transcripts, the mail cache and the GraphRAG index are left out: they
are noise or rebuildable.

    python3 tools/backup.py create                 # -> backups/jobsquirrel-<date>.zip
    python3 tools/backup.py create --no-documents  # ~5 MB instead of ~150 MB
    python3 tools/backup.py list
    python3 tools/backup.py inspect backups/<file>.zip

> **Careful:** the zip holds **your personal data**: CV, applications, and any Google
> client secret in `config/google.json`. Keep it private; `backups/` is
> git-ignored for that reason.

**Restore** replaces `config/`, `state/`, `documents/` and `kb/sources/` with the
zip's contents. It asks you to type `RESTORE`, refuses while a queue run is in
progress, and **writes a safety backup first**, so a wrong choice is recoverable:

    python3 tools/backup.py restore backups/<file>.zip --yes

**Clear** deletes the pipeline's data and keeps your identity: the register,
queues, drafts, saved ads, keyword files, grounding packs and every generated
document go; `config/` and `kb/sources/` stay. *Full reset* additionally drops the
GraphRAG index (a rebuild takes 20-30 minutes). It asks you to type `CLEAR` and
takes a safety backup first:

    python3 tools/backup.py clear --scope data --yes
    python3 tools/backup.py clear --scope full --yes

Automatic pre-restore/pre-clear copies live in `backups/` and the newest five are
kept; your own backups are never pruned.

**What the agent will interrupt you for:** a CAPTCHA/2FA/bot check, an email to
approve before sending, a verification link or code, an ambiguous eligibility or
accuracy rule, or a model budget/rate-limit stop.

A handy catch-all prompt:

> *"Give me a status: what's running, what's done, what needs me, and roughly
> what it's cost so far."*

## Keeping it cheap while you use it

- Prefer **REVIEW** and **LIGHT** modes while you tune; they skip the browser and
  per-role generation.
- Keep a **single long agent session** so context stays cacheable.
- See [AGENT-SETUP.md](AGENT-SETUP.md) §3-4 for the model choice and cost figures.
