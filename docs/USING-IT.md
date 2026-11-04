# Using it: typical prompts and monitoring

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
| *"Submit the prepared ones"* | *🚀 Submit prepared* (grid) or *Submit this application* (drawer): reuses the already-gated CV/letter and applies — two-step confirmation (`APPROVE_RUN_QUEUE`) |
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
  (`company`, `role`, `outcome`, `rc`, `reason`) — the machine-readable
  counterpart to `run_queue.out` for scripts and dashboards.
- **Health**: `python3 tools/doctor.py` (`--json` for scripts) checks config, the
  knowledge base, the browser, the register and git before you start a run.
- **Web UI**: `python3 tools/dashboard.py --open` (binds `127.0.0.1:8765`; `--port` to change).
  A dependency-free dashboard over the register, queue, specs and provenance:
  - **One master grid** (no tabs): a row per application with Date · Company · Role · ATS ·
    Status · **Match** (ATS-keyword coverage; `align✗` = the alignment gate failed) · Queue ·
    Files · Job ad, plus search / status / queue filters, sortable columns, CSV export and an
    **ⓘ Legend**. Hover anything for what it means; click a row for the detail drawer
    (Summary · Provenance · Job spec · ATS · **Grounding** · Tailored).
  - **Grounding** shows how your knowledge graph was used for that role: the cited context pack
    plus the entities and source documents it referenced, resolved from the index.
  - **Agent console** (dockable — **left by default**; drag its header to any edge, or the pullout
    tab when collapsed; panes resize with the splitters). Chat drives whichever agent
    `tools/agent_run.sh` resolves — opencode, Claude Code, or any `AGENT=` CLI — remembers the
    conversation across messages (＋ New to reset), collapses tool runs, and shows a 🥜 spinner
    while it works. An **Activity** pane shows action output, compressed to the lines that matter.
  - **Settings** (⚙ Config): **Accounts** (credential status + Gmail/Calendar authorisation),
    **Knowledge base** (list / upload / delete source documents, rebuild the index), **GraphRAG**
    (browse entities, relationships, communities and documents), and **Profile & CV** (edit
    `profile.md` / `cv.json` / `archetypes.json`, regenerate the archetype CVs).
  - It can **start runs** from buttons: *Prepare (review)* is safe (REVIEW=1, no submits); *Submit
    prepared* (grid toolbar) and *Submit this application* (a `PREPARED` row's drawer) apply with
    the documents already generated — no re-generation — and *Apply
    queue* submits, so both need a two-step confirmation (`APPROVE_RUN_QUEUE`). Every action needs
    the per-session token (anti-CSRF) and the UI binds to `127.0.0.1` only; the chat agent inherits
    the same approval gates — it cannot send or delete mail without them.
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

## The Knowledge workspace

The top-bar **Knowledge** page is the full-page view of your knowledge base.
**Universe** shows the whole graph as theme islands; **Map** drills through
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
the graph view through a live skill overlay, so no rebuild is needed —
re-prepare the role to fold it into the CV. Rebuild only when you
change a document under Sources. A role you open under **Roles** uses the same
grounding and gates as a queue run.

## Backup, restore and start over

Settings → **Backup & data** covers the three things you do around the edges of
a job search: take a copy, put a copy back, or clear the system and start again.

**Backup** writes one `.zip` with everything the pipeline cannot regenerate:
`config/` (profile, CV, archetypes, mail/calendar and Google settings),
`answers/`, `kb/sources/` (your corpus), `state/` (register, queues, provenance,
drafts, saved ads, keyword files, grounding and content packs, gate receipts) and
— unless you untick it — `documents/` (rendered CVs, letters, and the exact files
you sent). Transcripts, the mail cache and the GraphRAG index are left out: they
are noise or rebuildable.

    python3 tools/backup.py create                 # -> backups/jobsquirrel-<date>.zip
    python3 tools/backup.py create --no-documents  # ~5 MB instead of ~150 MB
    python3 tools/backup.py list
    python3 tools/backup.py inspect backups/<file>.zip

> ⚠️ The zip holds **your personal data** — CV, applications, and any Google
> client secret in `config/google.json`. Keep it private; `backups/` is
> git-ignored for that reason.

**Restore** replaces `config/`, `state/`, `documents/` and `kb/sources/` with the
zip's contents. It asks you to type `RESTORE`, refuses while a queue run is in
progress, and **writes a safety backup first**, so a wrong choice is recoverable:

    python3 tools/backup.py restore backups/<file>.zip --yes

**Clear** deletes the pipeline's data and keeps your identity: the register,
queues, drafts, saved ads, keyword files, grounding packs and every generated
document go; `config/` and `kb/sources/` stay. *Full reset* additionally drops the
GraphRAG index (a rebuild takes 20–30 minutes). It asks you to type `CLEAR` and
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
- See [AGENT-SETUP.md](AGENT-SETUP.md) §3–4 for the model choice and cost figures.
