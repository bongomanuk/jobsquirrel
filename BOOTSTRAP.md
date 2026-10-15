# BOOTSTRAP.md: first-run setup (the agent interviews the user)

**Agent: read this when `config/` is missing or still contains placeholders.** Your
job is to interview the user, fill in `config/`, build the CV archetypes, and set
up the knowledge graph, explaining each step in plain language. Do not invent
answers; ask.

Check first:

```bash
python3 tools/init_config.py --check
```

If anything is missing/placeholder, run the interview below, then write the files.

---

## Step 0: introduce the pipeline

**Read `docs/INTRO.md` and deliver it to the user**, in your own words and concise:
what the pipeline is, how it works end to end, the safety guarantees, the run
modes, what you'll need from them, and their privacy/control. Do not just say one
sentence, give them a real orientation so they understand what they're setting
up. Then ask whether they want to proceed.

Keep it a conversation: answer questions, and don't move on until they're happy to
continue.

## Step 0b: install the software

The repo does not bundle any software; it installs what it needs on first run:

```bash
bash tools/install.sh          # or: ./install.sh
```

This creates a local virtualenv and installs the Python dependencies, **fetches
the Camoufox stealth browser**, installs **GraphRAG** (required for document generation),
and checks for **LibreOffice** (which renders the styled PDF), telling the user
how to install it if missing. Use `bash tools/install.sh --check` any time to see
what is present. Confirm it finished before continuing.

## Step 1: interview the user

Ask these, conversationally (not all at once if the user prefers). Save answers as
you go.

**A. Identity & contact**
- Full name (as it should appear on a CV).
- Email, phone.
- City, Country (where you are based).
- LinkedIn URL; personal site/portfolio/GitHub (if any); other websites.
- Do you have a photo to include on the styled CV? (optional, `documents/assets/headshot.png`).

**B. Eligibility, where you can work**
- Which on-site/hybrid locations will you accept?
- Remote: which countries/regions must a "remote" role be open to for you to apply?
- Would you relocate? To where?
- Anything you'll definitely exclude (e.g. on-site roles abroad, contract-only, etc.)?
- If a role's location/work model is unclear, accept as "do not apply"? (recommended yes)

**C. Languages**
- Which languages do you speak, at what honest level?
- Which languages must you avoid applying to roles that *require* them fluently?
- Driving licence? (if relevant to some roles)

**D. Work authorisation**
- Right to work where you're based? Any sponsorship/visa notes?

**E. Availability & pay**
- Notice period and earliest start; any planned holidays.
- Contract rate (ex VAT), only used for contract/consulting roles (leave blank if none).
- Salary target (optional).

**F. Accuracy rules (what must never be overstated)**: get these explicitly:
- Certifications: which must be listed only (never asserted as "held")?
- Management scope: what exactly have you managed (e.g. line-managed engineers, not managers)?
- Anything else that must never be claimed?

**G. Diversity / EEO answers (optional)**: gender, age/year of birth, ethnicity,
disability, veteran status (used to fill application forms truthfully).

**H. Your CV and evidence**
- Ask the user to paste their CV, or point you at a file/folder, and (ideally) a
  "brag" document with numbers (scale, users, revenue, latency, team sizes, budget).
- Extract this into `config/cv.json` (experience with quantified bullets,
  projects, skills, education, certifications, languages, sidebar). Mark clearly
  anything uncertain and confirm with the user.
- **Then ask for everything else (this powers the knowledge graph, see Step 4).**
  Prompt them for, and collect into `kb/sources/` (as `.txt`/`.md`): **every**
  version of their CV, a brag/achievements doc, project/design notes, RFCs,
  postmortems, talks, blog/README excerpts, performance reviews, awards, and a
  LinkedIn export. The more truthful, specific material you gather, the better
  every application will be. Convert any PDFs/DOCX to text first.

**I. Target role families**
- Which role families should the CVs target (e.g. Engineering Leadership, Senior
  Software Engineer, AI/ML Engineer, Security, Data)? → fill `config/archetypes.json`
  (one entry per family, with headline/summary/skills/tags).

## Step 2: write the config

```bash
python3 tools/init_config.py                 # scaffold config/ from templates (never overwrites)
```

Then edit (you, the agent) to produce:
- `config/profile.md`, identity, eligibility, languages, availability, pay,
  accuracy rules, EEO answers (from A–G).
- `config/cv.json`, the CV as data (from H).
- `config/archetypes.json`, role families (from I).

Confirm the tricky ones (eligibility scope, accuracy rules, any ambiguous CV
bullet) with the user before moving on.

## Step 3: build the archetypes

```bash
python3 tools/build_archetypes.py
```

This writes one 2-page CV (+ styled PDF) and one base letter per archetype into
`documents/archetypes/`. Verify: `python3 tools/register.py --check`.

## Step 4: build the knowledge graph (explain + do it)

Explain to the user:

> I'm going to build a private **knowledge base** from your own documents, every
> version of your CV, project and design notes, a brag doc with numbers, talks,
> reviews, awards, a LinkedIn export, anything truthful you have. It uses GraphRAG
> to extract the people, projects, skills, metrics and certifications from them
> into a graph, then for each job it retrieves the most relevant, *cited* facts.
> The targeted CVs and letters are written only from those facts, so they stay
> accurate, this is how the system tailors a document to each role. **The more
> you feed it, the better every application gets.** It runs locally and is never
> shared.

Then:

```bash
# user drops their documents into kb/sources/ (any format) and confirms
bash tools/setup_kb.sh --check      # explain + verify prerequisites
bash tools/setup_kb.sh              # configure, ingest sources, start embeddings, index
```

`setup_kb.sh` prints what it's doing at each step. Document generation depends on
the index, so do not start applying until `python3 tools/kb_graphrag.py --check`
reports the index and embeddings backend are OK.

## Step 5: set up accounts (browser, Gmail, LinkedIn, credentials)

Explain what each account is for and let the user choose which to set up. Follow
**`docs/ACCOUNT-SETUP.md`** and re-check after each step:

```bash
bash tools/setup_accounts.sh --check
```

Guide, in order (skip any the user declines):
1. **Camoufox browser** (required to apply), install + fetch; verify it launches.
2. **Gmail, read-only** (recommended), Google Cloud project, enable the Gmail
   API, OAuth consent + Desktop client → `~/.config/job-search/credentials.json`,
   then `python3 tools/gmail_readonly.py --auth`; verify with `--sync`. Explain it
   only ever **reads** mail and surfaces verification links for them to act on.
3. **Google Calendar** (optional), `python3 tools/gmail_calendar_auth.py` so the
   agent can list/add interview events.
4. **LinkedIn** (optional; Easy Apply only), log in once in the dedicated
   persistent profile (headful). Explain the runner is serialised, paced and
   never mass-applies, and stops on any CAPTCHA/checkpoint.
5. **Per-site ATS credentials**: `tools/accounts.py` creates strong per-host
   passwords on demand; email verification via `tools/email_verify.py`.
6. **Agent + GraphRAG LLM key**: confirm the agent has a model key, and fill
   `kb/graphrag/.env` for the knowledge base.

Re-run `bash tools/setup_accounts.sh --check` until the accounts the user wants
show OK.

## Step 6: confirm and hand back

- Show a short summary: identity, eligibility, archetypes built (count), KB status.
- Tell the user how to use it: give you the queue (or ask you to discover roles),
  then "run the pipeline".
- Point them at `AGENTS.md` for how you operate, and `README.md` / `docs/` for
  reference.

When done, `python3 tools/init_config.py --check` should report a clean config.
