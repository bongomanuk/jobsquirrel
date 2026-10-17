# 🐿️ Jobsquirrel

**An open, self-hosted job-application agent: hand it your CV and it finds, tailors, gates and applies to jobs for you.**

*A diligent squirrel for your job hunt. It gathers the roles, tailors each one,
and never stashes a nut it can't actually crack.* 🐿️

An agentic pipeline that takes **your CV** and applies to jobs for you, end to
end, in a way that is honest, targeted, and auditable. You give it your CV and a
few rules (where you can work, what you will accept, what you must never
overstate). It then discovers roles, tailors a CV and cover letter per role,
gates them for accuracy and quality, submits applications through a real browser,
reads your inbox to track replies, and keeps a single source of truth for every
application and the exact files sent.

It is **person-agnostic and country-agnostic**: nothing here is tied to a
particular person, employer, language or country. You configure everything in
`config/`.

**First run, one prompt. No cloning, no setup.** Start your agent and paste this:

```text
Clone https://github.com/bongomanuk/jobsquirrel.git into ./jobsquirrel and set it
up with me: read AGENTS.md, then read docs/INTRO.md to me and run the first-run
bootstrap in BOOTSTRAP.md.
```

That's the whole installation. The agent clones the repo, installs the
dependencies, interviews you about your identity, eligibility, languages,
availability and the claims you must never overstate, writes your config, builds
your CV archetypes and a private knowledge graph from your documents, and sets up
your accounts, explaining each step in plain language.

Already have it cloned? Just `cd jobsquirrel`, run `opencode`, and say:
*"Read AGENTS.md, introduce the project, and run the bootstrap."*

Works the same with Claude Code, Cursor or any file-and-shell agent (the contract
is [AGENTS.md](AGENTS.md)). See
**[docs/AGENT-SETUP.md](docs/AGENT-SETUP.md)** for per-agent instructions, how to
keep it cheap with opencode + DeepSeek Flash, and **what it costs to run**.

> ⚠️ **Not push-button autonomy.** The agent does the mechanical work, but it
> relies on the instructions in `AGENTS.md` and on **you** for the judgement
> calls (your rules, approving emails, solving CAPTCHA/2FA). A weak model or a
> sloppy `config/` gives weak results. Treat the first applications as a
> supervised trial.

> ⚠️ **You are responsible for what it sends.** The pipeline is built to be
> truthful and to never fabricate, but you own your applications. Review the
> gate, keep your `config/` accurate, and never send a letter that fails it.

---

## Why it exists

Applying well is repetitive but not mechanical: every role needs a CV that
mirrors the ad and a letter in your own voice, both strictly true. Doing that by
hand does not scale; doing it carelessly looks like spam and can misrepresent you.
This project automates the repetitive parts while keeping the two things that
matter, **truthfulness** and **targeting**: as hard gates.

🐿️ It gathers tirelessly, targets precisely, and never embellishes. That's the whole idea.

## Design principles

1. **Never fabricate.** Every claim must be supported by `config/cv.json` and
   `config/profile.md`. A JD keyword may only appear if your CV backs it.
2. **No AI slop.** Letters are written per role, in your voice, with no shared
   sentences and no banned phrasing. The gate blocks it.
3. **Target the role.** Name the company and role, mirror the ad's language, and
   clear an ATS-keyword threshold.
4. **Eligibility first.** Only apply to roles you can actually take, on-site in
   your city, or remote where you're allowed to work, and never to roles that
   need a language or authorisation you don't have.
5. **Gate before submit, enforced.** Nothing is uploaded until the pre-submit
   gate passes, and the tooling **refuses to record a submission without a
   hash-stamped gate receipt** for the exact files sent.
6. **Everything is recorded.** One row per (company, role); the exact bytes sent
   are snapshotted and hashed.
7. **Be a considerate client, not a sneaky one.** A real browser profile, paced
   submissions, named contacts, and a hard stop on any CAPTCHA/2FA. The goal is to
   be polite, not to evade, and to prefer the employer's own ATS over portals.

## Why Jobsquirrel? 🐿️

There are plenty of "auto-apply" projects. Most optimise for **volume**: scrape
a board, blast one CV everywhere, evade the CAPTCHA, repeat. That gets accounts
banned, reads as spam to recruiters, and can quietly misrepresent you. Jobsquirrel
optimises for **getting the job**: and makes truthfulness and targeting *enforced
gates* rather than good intentions.

| | Typical auto-apply bot | **Jobsquirrel** |
| --- | --- | --- |
| **Documents** | One CV for all, or a blind LLM rewrite | Per-role CV + letter, **grounded in a private knowledge graph with citations** |
| **Truthfulness** | Claims "never fabricates" (unchecked) | **Enforced**: no claim without a source; unsupported lines are blocked |
| **Quality gate** | none | **Pre-submit gate**: real identity, no placeholders, no AI-slop, ATS coverage, correct engagement |
| **Targeting** | keyword match | **Alignment gate** maps the role family to the right CV archetype; a mismatched CV cannot be submitted |
| **CAPTCHA / anti-bot** | solved / bypassed (stealth hacks) | **stops and hands to you**: no evasion, so no tool-driven ToS or ban risk |
| **Who runs it** | locked to one vendor or cloud | **any agent** (opencode, Claude Code, Cursor, …) via `AGENTS.md` |
| **Cost** | metered API per run | runs on cheap **DeepSeek Flash** (~cents/application); everything else is local |
| **Record** | a log line, if any | **audit trail**: one row per company+role, exact files hashed & snapshotted, inbox reconciled |
| **Setup** | hard-coded personal defaults | **person- and country-agnostic**: everything lives in `config/` |
| **Licence** | MIT / AGPL / non-commercial | **Apache-2.0**: permissive, open-core friendly |

Same idea as [ApplyPilot](https://github.com/pickle-pixel/applypilot),
[JobPilot](https://github.com/suxrobGM/jobpilot), the [AIHawk](https://github.com/feder-cr/Auto_Jobs_Applier_AI_Agent)
lineage and others, but where they race to apply to the most jobs, this one tries
to **waste the fewest**: yours and the recruiter's. Fewer, better, honest
applications you can stand behind, and a system that won't do something you'd
regret.

## The knowledge graph: feed it everything you've got 🥜

The single most powerful thing you can do is give the pipeline **a lot** about
yourself. Drop your master CV, **every** old and role-specific CV, a "brag
document", project and design notes, talks, performance-reviews, a LinkedIn
export, README excerpts, as many documents as you have, into `kb/sources/`.
**GraphRAG** turns that corpus into a private graph of your people, projects,
skills, metrics and certifications, and for each role it retrieves the most
relevant, **cited** facts.

That is not a footnote, it is the engine of the whole thing:

- **Specificity.** A thin CV yields generic bullets. A rich corpus lets each
  application surface the *exact* achievement, metric and technology a given ad
  asks for, the ones you'd never recall at 11pm, from a project you'd forgotten.
- **Truthfulness by construction.** Every generated line is traceable to a source
  in your corpus. **No source evidence, no claim.** This is what makes "never
  fabricate" real instead of aspirational.
- **It compounds.** The more you add, the better *every* application gets, and
  fixing or removing one overstatement in a source fixes it *everywhere* on
  re-index.
- **Private and local.** The index is built on your machine. Nothing is uploaded.

So: gather far more than "just a CV". The more truthful, specific material you
feed it, the sharper and more honest every application becomes.

```bash
# put .txt / .md documents in kb/sources/ (the agent can convert PDFs/DOCX to text)
bash tools/setup_kb.sh            # configure, stage sources, start embeddings, index
python3 tools/kb_graphrag.py --check
```

Add sources any time and re-index (`python3 -m graphrag index --root kb/graphrag`).
See [docs/KNOWLEDGE-BASE.md](docs/KNOWLEDGE-BASE.md).

---

## Quick start

**Easiest: let an agent do it** (see the one-prompt bootstrap at the top). The
manual steps below are what the agent runs for you, handy for reference or if
you'd rather drive it yourself.

```bash
# 1. Install everything (Python deps + Camoufox browser + GraphRAG + LibreOffice check)
bash tools/install.sh

# 2. Configure (copy the templates and edit them)
cp config/profile.example.md   config/profile.md
cp config/cv.example.json      config/cv.json
cp config/archetypes.example.json config/archetypes.json

# 3. Build your reusable archetype CVs + letters
python3 tools/build_archetypes.py     # -> documents/archetypes/

# 4. Put roles in the queue (one per line, tab-separated):
#    company  role  url  cv-archetype  ats  key
#    then run the pipeline (it tailors + gates + applies per role; most senior first):
python3 tools/run_queue.sh            # or:  PARALLEL=3 bash tools/run_queue.sh
```

See **[docs/SETUP.md](docs/SETUP.md)** for the full setup, and
**[docs/WORKFLOW.md](docs/WORKFLOW.md)** for the per-role procedure.

**Platforms and agents.** The tools run on **Linux and macOS** — macOS ships
without GNU `flock`/`setsid`/`timeout`, so the portable stand-ins in
`tools/compat/` are used automatically. The queue runners drive whichever coding
agent you have: **opencode** by default, **Claude Code** with `AGENT=claude`, or
any CLI that takes the prompt as its last argument (`AGENT="mycli run"`). See
[docs/AGENT-SETUP.md](docs/AGENT-SETUP.md#running-the-queue-with-claude-code).

---

## Driving it with an AI agent

This project is meant to be **run by an AI coding agent**, not clicked through by
hand. Fill in `config/`, then point an agent (opencode, Claude Code, Cursor, …) at
the repository and tell it what to do, discover roles, run the queue, reconcile
email, and so on.

- **[AGENTS.md](AGENTS.md)**: the agent's operating manual (auto-loaded by
  opencode and similar tools): the golden rules, the per-role commands, the gates,
  and what the agent must escalate to you.
- **[docs/AGENT-SETUP.md](docs/AGENT-SETUP.md)**: bootstrap it with opencode,
  Claude Code or any agent; keep it cheap with opencode + DeepSeek Flash; and what
  it typically costs to run.
- **[docs/USING-IT.md](docs/USING-IT.md)**: how you actually use it day to day:
  **typical prompts** and how to **monitor** a run.
- **[docs/AGENT-GUIDE.md](docs/AGENT-GUIDE.md)**: the human's guide to handing
  the project over, with an example brief and a worked exchange.
- **[docs/INTRO.md](docs/INTRO.md)**: the plain-language introduction the agent
  reads to you on first run (what it is, how it works, the modes, and your privacy).

You steer it with plain English. Typical prompts:

```text
"Find new senior roles and queue them."
"Prepare documents for the top 5, don't send yet."      # REVIEW: build + gate only
"Run the pipeline."                                       # apply, most senior first
"How's it going? What's running, done, and what needs me?"
"Reconcile with my email and tell me what needs me."
```

Watch a run live with `bash tools/watch_queue.sh`; ask for *"status + what it's
cost so far"* any time. Full prompt/monitoring guide: [docs/USING-IT.md](docs/USING-IT.md).

## Layout

```
config/                     # YOUR configuration (git-ignored once filled in)
  profile.example.md        #   identity, eligibility, availability, accuracy rules
  cv.example.json           #   your CV as structured data
  archetypes.example.json   #   role-family CV templates
tools/                      # the pipeline (language/library-free CLI tools)
  cv_builder.py             #   renders CVs + letters from config (library, not run directly)
  build_archetypes.py       #   builds one 2-page CV + base letter per archetype
  cv_target.py              #   renders a role-targeted CV (.docx ATS-safe + .pdf styled)
  make_letter.py            #   renders one cover-letter .docx
  check_documents.py        #   PRE-SUBMIT GATE (truthfulness, slop, ATS coverage, contract rate)
  check_alignment.py        #   role-family <-> CV-archetype alignment gate
  ats_keywords.py           #   extract ATS keywords from an ad; score a CV/letter
  facts.py                  #   authoritative facts from cv.json; tense/scope checks
  register.py               #   canonical outcome register (state/applications.csv)
  record_submission.py      #   provenance ledger (state/submissions.csv) + snapshots
  gate_receipt.py           #   hash-stamped gate receipts; enforces the pre-submit gate
  outcomes.py               #   conversion by source/CV, what's actually working
  gmail_readonly.py         #   read-only inbox sync + classification
  gmail_reconcile.py        #   reconcile the register with your inbox
  gmail_calendar_auth.py    #   (optional) Google Calendar read/write for interviews
  gmail_send.py             #   send email via Gmail (requires your explicit approval)
  discover.py               #   discover roles from LinkedIn Job Alert emails
  email_opportunities.py    #   surface recruiter/contract leads from your inbox
  email_verify.py           #   read the newest verification email for a site
  accounts.py               #   per-site credentials (stored outside the repo)
  identity.py               #   print your standard form answers (JSON)
  camoufox_server.py        #   one stealth browser behind a small HTTP API
  camoufox_browser.py       #   the agent-facing browser CLI (nav/snap/click/fill/...)
  run_queue.sh              #   the queue runner: applies to each queued role end-to-end
  agent_run.sh              #   runs one headless task with opencode, Claude Code or any CLI agent
  compat/                   #   portable flock/setsid/timeout for macOS
  run_linkedin.sh           #   serialized, paced LinkedIn Easy Apply (opt-in; see ToS note)
  build_human_queue.py      #   route CAPTCHA/2FA-blocked roles to a human queue
  reconcile_loop.sh         #   periodically reconcile + refresh counts
  watch_queue.sh            #   live queue progress
  prioritise_queue.py       #   sort the queue most-senior-first
  init_config.py            #   scaffold/validate config/ (used by the bootstrap)
  setup_kb.sh               #   explain + build the GraphRAG knowledge base
  kb_graphrag.py            #   build the cited grounding pack per role (required)
  kb_ingest.py              #   ingest kb/sources/ any-format -> GraphRAG text input
  embeddings.sh             #   local embeddings backend (auto CUDA/Metal/Vulkan/CPU)
state/                      # generated: register, queues, logs, saved ads, keyword files
documents/                  # generated: archetype CVs, per-role letters, submitted snapshots
kb/                         # your knowledge base (GraphRAG grounding; required for targeted docs)
docs/                       # documentation (this folder)
```

---

## How it works (one role, end to end)

1. **Discover**: `discover.py` reads LinkedIn Job Alert emails and drops anything
   already recorded, giving you new roles to queue.
2. **Eligibility gate**: the runner checks the location/work model and language
   against your `config/profile.md` rules. Ineligible roles are recorded CLOSED,
   not applied to.
3. **Alignment gate**: `check_alignment.py` confirms the role family matches the
   CV archetype you chose (so an AI-CV never goes to a backend req).
4. **Grounding**: facts come from the knowledge base (GraphRAG, `kb/`) plus `config/cv.json`. No claim outside those sources.
5. **Tailor**: a targeted CV (`cv_target.py`) and a per-role letter are produced.
6. **Pre-submit gate**: `check_documents.py` must print `RESULT: PASS`: real
   identity, no placeholders, no AI-slop, supported claims, correct engagement
   (a contract rate only in contract applications), ATS coverage. It writes a
   **hash-stamped gate receipt**, and `record_submission.py` won't record a
   submission without it, so the gate can't be skipped.
7. **Apply**: a `/config/profile.md`-aware agent drives Camoufox through the
   employer's own ATS (recipes for Teamtailor, Greenhouse, Lever, Ashby, Workday,
   Jobylon and more in [docs/ATS-RECIPES.md](docs/ATS-RECIPES.md)).
8. **Record**: `record_submission.py` snapshots the exact files and upserts the
   register.
9. **Reconcile**: `gmail_reconcile.py` matches replies to rows and sets
   INTERVIEW / REJECTED / SUBMITTED, surfacing verification links for you to act on.

## Statuses

`PREPARED, IN_PROGRESS, SUBMITTED, INTERVIEW, OFFER, REJECTED, BLOCKED, MANUAL,
CLOSED`.

## Documentation

- [docs/SETUP.md](docs/SETUP.md), install, dependencies, configuration, Gmail.
- [docs/WORKFLOW.md](docs/WORKFLOW.md), the per-role procedure in detail.
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md), components, data model, files.
- [docs/ATS-RECIPES.md](docs/ATS-RECIPES.md), how each ATS is driven.
- [docs/ELIGIBILITY.md](docs/ELIGIBILITY.md), writing your eligibility + accuracy rules.
- [docs/AGENT-SETUP.md](docs/AGENT-SETUP.md), bootstrap with opencode / Claude Code / any agent, plus cost and cheap-model tips.
- [docs/AGENT-GUIDE.md](docs/AGENT-GUIDE.md), how to hand it to and drive it with an AI agent.
- [docs/USING-IT.md](docs/USING-IT.md), typical prompts and how to monitor a run.
- [docs/INTRO.md](docs/INTRO.md), the startup introduction the agent delivers to you.
- [BOOTSTRAP.md](BOOTSTRAP.md), the first-run interview the agent runs to set everything up.
- [docs/ACCOUNT-SETUP.md](docs/ACCOUNT-SETUP.md), Gmail, Calendar, LinkedIn, browser and credentials.
- [docs/KNOWLEDGE-BASE.md](docs/KNOWLEDGE-BASE.md), set up the GraphRAG knowledge base (required for targeted documents).
- [docs/RUN-MODES.md](docs/RUN-MODES.md), discover / review / apply / fixed-CV run modes.
- [DISCLAIMER.md](DISCLAIMER.md), acceptable use, no-warranty and liability statement.

## Safety and privacy

- The pipeline never sends, modifies or deletes mail on its own: Gmail is
  **read-only** by default, and outbound mail (`gmail_send.py`) requires your
  explicit approval of recipient, subject and content, every time.
- Credentials and tokens live **outside** the repo (default
  `~/.config/job-search/`), and `config/`, `state/`, `documents/` and `kb/`
  generated content are git-ignored.
- Do not commit `config/profile.md`, `config/cv.json` or `config/archetypes.json`
 , they contain your personal data.

## Legal and acceptable use

- Provided **"AS IS"** under Apache-2.0, **without warranty** and with liability
  limited (see [LICENSE](LICENSE), §§7–8). You run it on your own accounts and
  **you own the outcome**.
- **You are responsible for complying with each site's terms of service and
  applicable law** (automated access, anti-bot rules, data protection) and for
  the accuracy of your `config/` and applications.
- **Keep the human-in-the-loop safeguards**: the email approval, the
  document/alignment gates, and the stop-on-CAPTCHA/2FA behaviour. Don't use this
  to evade bot protections, spam, or misrepresent yourself.
- **LinkedIn is opt-in and ToS-risky.** LinkedIn's User Agreement prohibits
  automated access and activity; driving Easy Apply with a browser bot may breach
  those terms and can get your account restricted. It's off unless you set it up,
  and the risk is yours. Prefer the employer's own ATS where one exists.
- See **[DISCLAIMER.md](DISCLAIMER.md)** for the full acceptable-use and
  liability statement. It is **not legal advice**.

## License

Apache License 2.0. See [LICENSE](LICENSE). Adapt and build on it freely.

The core is deliberately permissive so anyone can use it. Commercial/enterprise
features are intended to live outside this repository (an "open core" model),
and the Apache-2.0 patent grant keeps the core safe for business use.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). In short: keep everything person- and
country-agnostic, never weaken the gates, and keep it agent-drivable.

## Publishing to GitHub

This folder is a self-contained project (nothing here depends on a parent repo):

```bash
cd jobsquirrel
git init -b main
git add .
git commit -m "Initial commit: Jobsquirrel"
git remote add origin git@github.com:<you>/jobsquirrel.git
git push -u origin main
```

`config/`, `state/`, `documents/` and `kb/` are git-ignored, so your personal data
never leaves your machine. Suggested repo description:

> An agent-driven, self-hosted job-search pipeline: give it your CV and it finds,
> tailors, gates and applies to jobs for you, truthfully, and under your rules.

Suggested topics: `job-search`, `ai-agents`, `automation`, `resume`,
`cover-letter`, `ats`, `graphrag`, `opencode`.
