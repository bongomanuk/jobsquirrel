# Setup

> **You probably don't need to do this by hand.** Hand the repository to an AI
> agent: it runs the first-run interview in [BOOTSTRAP.md](../BOOTSTRAP.md),
> writes your `config/`, builds your archetypes and the knowledge base, and
> explains each step. The manual steps below are the same thing, for reference.
> For how to launch an agent (opencode, Claude Code, …) and what it costs, see
> [AGENT-SETUP.md](AGENT-SETUP.md).

## 1. Prerequisites

- **Python 3.10+**
- **LibreOffice** (`soffice`), renders the styled PDF CV/letter.
  `sudo apt-get install libreoffice` (Debian/Ubuntu) or your distro's equivalent.
- **A dedicated browser** for the submission step: Camoufox (patched Firefox).
  `pip install camoufox[geoip]` then `python3 -m camoufox fetch`.

## 2. Clone and install

The quickest way is the installer, which creates a local venv and fetches
everything (or do it by hand as shown after):

```bash
git clone <this repo> jobsquirrel && cd jobsquirrel
bash tools/install.sh          # deps + Camoufox browser + GraphRAG + LibreOffice check
bash tools/install.sh --check  # report what is present/missing
```

Manual equivalent:

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
python3 -m camoufox fetch
```

`python-docx` is required for the CV/letter builders. The Google libraries are
only needed if you use the Gmail/Calendar features. Camoufox is only needed to
actually submit.

## 3. Configure

Copy the three templates and edit them. These are the **only** files you must
fill in; everything else is tooling.

```bash
cp config/profile.example.md     config/profile.md
cp config/cv.example.json        config/cv.json
cp config/archetypes.example.json config/archetypes.json
```

- **`config/profile.md`**: your identity, work authorisation, languages,
  availability, pay, **eligibility rules** and **accuracy rules**. The parsers
  read it as `- key: value` lines. See [ELIGIBILITY.md](ELIGIBILITY.md).
- **`config/cv.json`**: your CV as structured data (experience, projects,
  skills, education, certifications, languages, sidebar). Every bullet must be
  true; this is the ground truth the gate checks against.
- **`config/archetypes.json`**: reusable role-family templates (a headline, a
  summary, skills, and tags). One 2-page CV + a base letter is generated per
  archetype, and the alignment gate maps each job to one of these families.

Everything reads `config/profile.md` / `config/cv.json` / `config/archetypes.json`
and falls back to the `.example` file if the real one is absent.

Environment overrides (all optional): `CV_NAME`, `CV_EMAIL`, `CV_PHONE`,
`CV_LOCATION`, `CV_LINKEDIN`, `CV_WEBSITE`, `CV_OTHER_SITES`, `CV_OUT`,
`CV_PREFIX`, `CV_HEADSHOT`, `CV_DATE`.

## 4. Build your archetypes

```bash
python3 tools/build_archetypes.py
# -> documents/archetypes/<Prefix>_CV_<key>.docx + .pdf and _Motivation_<key>.docx
```

`<Prefix>` is `First_Last` derived from your profile's `full name` (or `CV_PREFIX`).
These are your reusable, aligned CVs and the base for per-role CVs.

## 5. Browser (submission)

The runners start Camoufox themselves. To use it interactively:

```bash
python3 tools/camoufox_server.py --port 9872            # headless
python3 tools/camoufox_server.py --port 9871 --headful  # visible
python3 tools/camoufox_browser.py --server http://127.0.0.1:9872 nav https://example.com
```

Commands: `status | nav | snap | click | fill | type | select | pick | fillmap |
press | check | value | eval | wait | upload | download | headers`.

## 6. Gmail (read-only), optional but recommended

The pipeline can read application email with the single `gmail.readonly` scope to
classify confirmations/interviews/rejections and surface verification links. It
never sends or modifies mail.

1. Create a Google Cloud project, enable the **Gmail API**, configure an OAuth
   consent screen (External, Testing, add yourself as a test user), and create an
   **OAuth client ID → Desktop app**.
2. Save the downloaded JSON to `~/.config/job-search/credentials.json`.
3. Authorise once:
   ```bash
   pip install google-auth google-auth-oauthlib google-api-python-client
   python3 tools/gmail_readonly.py --auth
   ```
4. Use it:
   ```bash
   python3 tools/gmail_readonly.py --sync          # classify recent mail
   python3 tools/gmail_reconcile.py                # propose register changes (dry run)
   python3 tools/gmail_reconcile.py --apply        # write them
   ```

Config: `GMAIL_CONFIG_DIR` (default `~/.config/job-search`), `GMAIL_CREDENTIALS`,
`GMAIL_TOKEN`, `GMAIL_QUERY`.

> **Testing-mode tokens expire ~weekly**; re-run `--auth` when they do. A
> Workspace account with an *Internal* app avoids that.

### Calendar (optional)

`tools/gmail_calendar_auth.py` requests `calendar.events` (read+write) so the
pipeline can add interview events. `--check --days N` lists upcoming events.

## 6b. Knowledge base / GraphRAG (required for targeted documents)

To ground generated documents in **your own documents** (with citations), set up
the knowledge base, see [KNOWLEDGE-BASE.md](KNOWLEDGE-BASE.md) and `kb/README.md`:
put your docs in `kb/sources/`, configure `kb/graphrag/settings.yaml` +
`kb/graphrag/.env`, then build the index with
`python3 -m graphrag index --root kb/graphrag`. `tools/kb_graphrag.py` then builds
a cited context pack per role (`state/kb-context/<key>.md`). The targeted CVs and letters are generated from it.

## 7. Per-site credentials (optional)

`tools/accounts.py --for <url>` stores (or creates) a strong password per host,
outside the repo (default `~/.config/job-search/accounts.json`, mode 0600). Use
`--get`, `--list`, `--random`.

## 8. Verify

```bash
python3 tools/identity.py --json        # your standard answers
python3 tools/facts.py --show           # employers derived from cv.json
python3 tools/register.py --check       # register consistency (empty is fine)
```

## 9. Watch it (web UI)

```bash
python3 tools/dashboard.py --open       # single-grid dashboard over the register + queue
```

The same UI can also **configure accounts** (Settings → Accounts, with Gmail/Calendar
authorisation), **import knowledge-base documents** (Settings → Knowledge base, upload
then rebuild) and **browse the GraphRAG index** (Settings → GraphRAG). See
[USING-IT.md](USING-IT.md) for what everything means.
