# Account setup

<div align="center"><sub><a href="../README.md">Jobsquirrel</a> · <a href="README.md">Docs</a></sub></div>


The pipeline needs a few accounts and credentials. **None are required to read
this project**, everything degrades gracefully, but this is the order to set
them up so the agent can run the full loop (apply, track replies, verify email).

The software (Python deps, the Camoufox browser, GraphRAG, LibreOffice) is fetched
by `bash tools/install.sh`; this document covers the accounts and credentials
needed on top of that.

Secrets live **outside the repo**, in `~/.config/job-search/` by default (override
with `GMAIL_CONFIG_DIR` / `ACCOUNTS_FILE`). They are git-ignored.

Check the current status at any time:

```bash
bash tools/setup_accounts.sh --check
```

The same status, and the Gmail / Google Calendar authorisation flows, are available in
the web UI: **Settings → Accounts** (`python3 tools/dashboard.py --open`). The agent will
walk you through the steps below either way.

---

## 0. An LLM for the agent (required)

You need a capable coding agent and a model key to drive the pipeline (opencode,
Claude Code, Cursor, …). If you also use the knowledge base (GraphRAG), it needs
its own LLM + embeddings key, see [KNOWLEDGE-BASE.md](KNOWLEDGE-BASE.md). Keep
those keys in the central secrets store (**Settings → Secrets**); GraphRAG reads a
0600 mirror at `kb/graphrag/.env`. Never commit them.

## 1. Camoufox browser (required to apply)

The submission step drives Camoufox, a Firefox-based browser.

```bash
pip install camoufox[geoip]
python3 -m camoufox fetch
python3 tools/camoufox_server.py --port 9872 &
python3 tools/camoufox_browser.py --server http://127.0.0.1:9872 nav https://example.com
```

## 2. Gmail (recommended, reply tracking + verification)

Gmail access lets the pipeline classify confirmations/interviews/rejections,
surface **verification links/codes** for you to act on, and (opt-in) send replies
with attachments. The token requests `gmail.readonly`, `gmail.send` and
`calendar.events`; sending mail and writing to the calendar are still gated on
your explicit approval for each action, and the pipeline never deletes mail.

Everything here is done from the dashboard: **Settings → Accounts → Google**.

1. **Google Cloud project**: https://console.cloud.google.com → create a project
   (e.g. `job-pipeline`). **APIs & Services → Library → enable Gmail API** (and
   Calendar API if you want interview booking). **OAuth consent screen**:
   User type **External** → Create; app name/support email = your details;
   **Scopes** → add `gmail.readonly`, `gmail.send` and `calendar.events`;
   **Test users** → add your own email. Leave it in **Testing** (no Google
   verification needed for personal use).
2. **OAuth client**: Credentials → Create credentials → **OAuth client ID** →
   **Desktop app** → Create.
3. **Configure it, then authorise**: either:
   - paste the **Client ID** and **Client secret** into Settings → Accounts and
     press **Save Google settings**; the pipeline writes `credentials.json` for
     you; or
   - download the JSON and point **credentials** at it in the same panel; or
   - drop it at the default `~/.config/job-search/credentials.json`.
   Then press **Authorise Gmail**. A browser opens for consent (first run:
   `pip install google-auth google-auth-oauthlib google-api-python-client`).
   The token is saved next to the client (mode 0600) and it also carries the
   Calendar scope, so one consent covers Gmail **and** Calendar.
4. **Verify**: `python3 tools/gmail_readonly.py --sync` (classifies recent mail),
   or just **Re-check** in the panel.

### Where the files live (all configurable)

Defaults suit most people, but a new user (or a second account) can point the
pipeline anywhere. `config/google.json` (see `config/google.example.json`):

| key | meaning |
| --- | --- |
| `config_dir` | folder holding the client/token (default `~/.config/job-search`) |
| `credentials` | `credentials.json`, absolute or relative to `config_dir` |
| `token` | `token.json`, absolute or relative to `config_dir` |
| `client_id` / `client_secret` | paste these in Settings → Accounts; they are stored in the secrets store and `credentials.json` is written from it |

Environment overrides win over the file: `GMAIL_CONFIG_DIR`, `GMAIL_CREDENTIALS`,
`GMAIL_TOKEN` (and `JOBSQUIRREL_GOOGLE_CONFIG` to relocate `google.json` itself).
Check the resolved paths any time:

```bash
python3 tools/google_config.py --status     # paths, what exists, scopes, account
python3 tools/google_config.py --paths      # shell-friendly CONFIG_DIR/CREDENTIALS/TOKEN
```

> **Testing-mode tokens expire ~weekly**: re-run `--auth` when that happens. A
> Google Workspace account with an *Internal* app avoids it. Optional least-data
> tip: create a Gmail filter that labels application mail and set
> `GMAIL_QUERY=label:applications`.

### Sending mail (opt-in, attachments supported)

Email is **draft-first**. The agent saves a reply with `tools/draft_email.py`; you
review it in the role drawer and press **Send with approval**. Only then does the
dashboard opens the exact email (To/Cc/Subject/body) in an editable approval
dialog. Amend anything, then choose **Approve & send** (a one-time receipt is
issued for the edited draft) or **Save changes, don't send**. Attachments are
edited in the draft itself. A human at a terminal can still get an explicit
preview + y/N prompt. There is no environment-variable bypass: an agent setting
`APPROVE_SEND_EMAIL=1` cannot send. Every send is recorded on the role as a
dated note with the Gmail message id (use a `draft_email.py` draft or pass
`--company/--role`); `gmail_reconcile.py` also scans Sent as a backstop.
To enable it, re-authorise including `gmail.send` (the tool's `--auth` uses the
scopes in `gmail_readonly.py`).

```bash
python3 tools/gmail_send.py --to recruiter@example.com --subject "Application: X" \
    --body-file state/draft.txt --signature \
    --attach documents/applications/Your_Name_CV_x.docx \
    --attach documents/applications/Your_Name_Motivation_x.docx
```

`--attach` is repeatable; a bare filename is also looked up in the configured
`attachment_dir`. `--draft state/letters-content/<name>.txt` reads the
`To:`/`Subject:`/`Attachment:` header and body straight from a saved draft (CLI
flags still override). `--cc`/`--bcc` are supported, and `--dry-run` prints the
recipients, attachment names and body without sending. Behaviour lives in
`config/email.json` (see `config/email.example.json`):

| key | meaning |
| --- | --- |
| `from` | your address (for reference; Gmail always sends as the token's account) |
| `signature` | appended when you pass `--signature` |
| `attachment_dir` | fallback directory for relative attachment names |
| `max_attachment_mb` | refuse oversized mail before approval (Gmail's limit is 25 MB) |

## 3. Google Calendar (interview booking + tracking)

The token includes `calendar.events` (read+write), so the agent can list
upcoming interviews, **create/update events** (and invite the interviewer), and
**import an `.ics` invite straight from Gmail**:

```bash
python3 tools/gmail_calendar_auth.py            # requests gmail.readonly + gmail.send + calendar.events
python3 tools/gmail_calendar_auth.py --check --days 14
python3 tools/calendar_event.py list --days 14
python3 tools/calendar_event.py create --title "Interview: Acme" \
    --start "2026-10-22 14:00" --duration 45 --attendees recruiter@acme.com \
    --location "Teams" --description "Interview with the platform team"
python3 tools/calendar_event.py from-message <gmail-message-id>   # "Add to calendar" for you
python3 tools/calendar_event.py slots --days 5                    # free slots around your diary
```

`slots` is read-only and proposes interview times inside your working hours
without overlapping existing events: pick one, then `create` the event. The
same consent as Gmail is all it needs; timezone, default length and working
hours come from `config/calendar.json`, editable in Settings → Accounts.

Calendar writes are approval-gated: answer `y` at the prompt,
approve the dashboard prompt, or set `APPROVE_CALENDAR_WRITE=1` for that one
command. `--dry-run` shows the event
without writing. `config/calendar.json` (see `config/calendar.example.json`)
sets your timezone, default duration, calendar and working hours (the tool warns
when a slot falls outside them); `invite_attendees` controls whether attendees
also receive an invitation email.

## 4. LinkedIn (optional, manual use)

The public build reads LinkedIn job-alert email and can queue those roles, but
it does **not** automate LinkedIn Easy Apply. Use the employer's own ATS; if a
posting only offers Easy Apply, record `BLOCKED` and apply manually if you choose.

You can still log in to LinkedIn manually in the browser for research or a manual
application. Never mass-apply, and stop on any CAPTCHA/checkpoint. Automating
Easy Apply may breach LinkedIn's User Agreement and can get an account restricted;
that capability is a private add-on, not part of this build.

## 5. Per-site ATS accounts (Workday, SuccessFactors, Ashby, own sites…)

Some applications need an account. `tools/accounts.py` stores a strong password
per host (created on first use, 0600, outside the repo):

```bash
python3 tools/accounts.py --for https://company.wd3.myworkdayjobs.com/     # get or create
python3 tools/accounts.py --list
```

Email verification for these: `python3 tools/email_verify.py --domain <host> [--open]`
(reads the newest verification email; never auto-clicks unless you pass `--open`
and approve).

## 6. Secrets & privacy

- Everything sensitive lives in `~/.config/job-search/`, **outside** the repo:
  the AES-256-GCM encrypted secrets store (`secrets.json`, 0600, key in the OS
  keyring or a 0600 `secrets.key`), the `credentials.json` / `token.json`
  caches Google's libraries read, and the `*-profile/` browser profiles.
  `accounts.json` is imported into the store and its plaintext backups are
  folded into an encrypted archive.
- `.gitignore` excludes `config/*.md|json` (your data), `state/`, `documents/`
  generated content, and `kb/` sources/indices.
- Revoke access any time: https://myaccount.google.com/permissions.

## Checklist

```bash
bash tools/setup_accounts.sh --check       # status of every account above
```

| Account | Required? | Verify with |
|---|---|---|
| LLM key (agent + GraphRAG) | required | the agent runs; `kb_graphrag.py --check` |
| Camoufox browser | required to apply | `camoufox_server.py` starts |
| Gmail (read-only) | recommended | `gmail_readonly.py --sync` |
| Google Calendar | optional | `gmail_calendar_auth.py --check` |
| LinkedIn | optional | login persists in the profile |
| Per-site credentials | as needed | `accounts.py --list` |

## The secrets store

Every secret the app uses has one home: `~/.config/job-search/secrets.json`,
AES-256-GCM encrypted, mode 0600 in a 0700 directory, managed from
**Settings → Secrets** or:

```bash
python3 tools/secrets_store.py --list          # masked values only
python3 tools/secrets_store.py --check         # permissions + syntax
python3 tools/secrets_store.py --migrate       # import legacy files once
printf '%s' "$KEY" | python3 tools/secrets_store.py --set agent OPENROUTER_API_KEY
python3 tools/accounts.py --get jobs.example.com
python3 tools/accounts.py --for jobs.example.com --email you@example.com   # create + store
```

Sections are `agent` (model/API keys), `graphrag` (knowledge-graph LLM),
`google` (OAuth client id/secret plus the serialized credential/token files),
`accounts` (per-site logins) and `custom`. The dashboard only ever receives
masked values. Files that third-party code must read (`credentials.json`,
`token.json`, `kb/graphrag/.env`) are regenerated from the store with 0600;
they are caches, not the canonical copy.

The key is kept in the OS keyring when one is available (Linux Secret Service,
macOS Keychain, Windows Credential Locker), otherwise in a 0600 `secrets.key`
beside the store. `JOBSQUIRREL_SECRETS_KEY` (base64, 32 bytes) overrides both for
CI; the dashboard passes it to its agent children so a locked keyring cannot
strand a run. `tools/secrets_store.py --check` reports the encryption and key
source without printing either.

Existing installs are migrated automatically on the next dashboard start: agent
keys leave `agent.json`, the Google client id/secret leave `config/google.json`,
`accounts.json` is imported, and plaintext backups (`secrets-backup-*/`,
`accounts.json.migrated`, old token copies) are folded into one encrypted
archive. `--decrypt-backup FILE` restores such an archive into a private
directory if you ever need it.

