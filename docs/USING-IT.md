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
- **Web UI**: `python3 tools/dashboard.py` (then open http://127.0.0.1:8765, or
  `--open`). A dependency-free dashboard: counts, queue progress, a **Live** panel
  (running tasks + curated tail), recent runs, interviews, and a **curated** view of
  any task log (only the meaningful lines — gate results, commands, submissions,
  errors — never the tool spam). 🐿️ It can also **start a run** from buttons:
  *Prepare (review)* is safe (REVIEW=1, no submits); *Apply queue* submits, so it is
  refused unless you started the dashboard with `APPROVE_RUN_QUEUE=1`, and it asks to
  confirm. Actions need a per-session token (anti-CSRF) and bind to `127.0.0.1`.
  There's also a **chat panel** that drives whichever agent `tools/agent_run.sh`
  resolves — opencode, Claude Code, `hermes`, `pi`, or any CLI you point `AGENT=` at
  — streaming the reply into the page (agent-agnostic, same token gate). The chat
  agent inherits the approval gates: it cannot send email or delete mail without them.
  **Single master grid** (no tabbed pages): one row per application with columns
  Date · Company · Role · ATS · Status · **Match** (alignment + keyword coverage) · Queue ·
  Prov · Spec, plus search/status/queue filters, sort, and CSV export. Click a row to open the
  right-hand **detail drawer** (Summary · Provenance · Job spec · ATS · KB context · Tailored).
  Metrics + a live-tail line sit in the strip under the header; **Config** (edit `profile.md` /
  `cv.json` / `archetypes.json` + regenerate the CVs) is a modal; **Agent** is the bottom drawer.
- **Register**: `python3 tools/register.py --stats`;
  `python3 tools/register.py --list --status INTERVIEW`;
  `python3 tools/register.py --show "<Company>"`.
- **Conversion**: `python3 tools/outcomes.py`, response rate by source (ATS/site)
  and by CV, so you invest where it actually converts.
- **Queue state**: `state/queue.tsv` (pending), `state/queue.done` (finished,
  keyed `company|role`).
- **Replies / counts**: `bash tools/reconcile_loop.sh` keeps reconciliation and
  `state/counts.md` fresh in the background.
- **Interviews**: `python3 tools/gmail_calendar_auth.py --check --days 14`.
- **Human-only items**: `state/queue-human.tsv`, opened with
  `bash tools/human_assist.sh`.

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
