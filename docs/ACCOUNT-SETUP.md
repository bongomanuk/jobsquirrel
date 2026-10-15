# Account setup

The pipeline needs a few accounts and credentials. **None are required to read
this project** — everything degrades gracefully — but this is the order to set
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

---

## 0. An LLM for the agent (required)

You need a capable coding agent and a model key to drive the pipeline (opencode,
Claude Code, Cursor, …). If you also use the knowledge base (GraphRAG), it needs
its own LLM + embeddings key — see [KNOWLEDGE-BASE.md](KNOWLEDGE-BASE.md). Keep
those keys in the agent's environment and in `kb/graphrag/.env`; never commit them.

## 1. Camoufox browser (required to apply)

The submission step drives a stealth browser (patched Firefox).

```bash
pip install camoufox[geoip]
python3 -m camoufox fetch
python3 tools/camoufox_server.py --port 9872 &
python3 tools/camoufox_browser.py --server http://127.0.0.1:9872 nav https://example.com
```

## 2. Gmail (recommended — reply tracking + verification)

Read-only access lets the pipeline classify confirmations/interviews/rejections
and surface **verification links/codes** for you to act on. It uses the single
`gmail.readonly` scope and can never send, modify or delete mail by itself.

1. **Google Cloud project** — https://console.cloud.google.com → create a project
   (e.g. `job-pipeline`). **APIs & Services → Library → enable Gmail API.**
2. **OAuth consent screen** — User type **External** → Create. App name/support
   email = your details. **Scopes** → add `https://www.googleapis.com/auth/gmail.readonly`.
   **Test users** → add your own email. Leave it in **Testing** (no Google
   verification needed for personal use).
3. **OAuth client** — Credentials → Create credentials → **OAuth client ID** →
   **Desktop app** → Create → **Download JSON** → save as
   `~/.config/job-search/credentials.json`.
4. **Authorise once**:
   ```bash
   pip install google-auth google-auth-oauthlib google-api-python-client
   python3 tools/gmail_readonly.py --auth        # a browser opens; consent to the scope
   ```
   A `token.json` is written next to `credentials.json` (mode 0600).
5. **Verify**: `python3 tools/gmail_readonly.py --sync` (classifies recent mail).

> **Testing-mode tokens expire ~weekly** — re-run `--auth` when that happens. A
> Google Workspace account with an *Internal* app avoids it. Optional least-data
> tip: create a Gmail filter that labels application mail and set
> `GMAIL_QUERY=label:applications`.

### Sending mail (opt-in)

`tools/gmail_send.py` can send replies, but only with your **explicit approval**
of recipient, subject and content each time. To enable it, re-authorise including
`gmail.send` (the tool's `--auth` uses the scopes in `gmail_readonly.py`).

## 3. Google Calendar (optional — interview tracking)

To have the agent list (and add) interview events, re-authorise with
`calendar.events` (read+write):

```bash
python3 tools/gmail_calendar_auth.py            # requests gmail.readonly + gmail.send + calendar.events
python3 tools/gmail_calendar_auth.py --check --days 14
```

## 4. LinkedIn (optional — Easy Apply only)

> ⚠️ **Terms-of-service risk.** LinkedIn's User Agreement prohibits automated
> access and activity. Driving Easy Apply with a browser bot — however human-paced
> — **may breach those terms and can get your account restricted or banned.**
> This is **opt-in** and does nothing unless you set it up; if you use it, you
> accept that risk. Prefer the employer's own ATS wherever one exists. (Not legal
> advice.)

Many roles are best applied via the employer's own ATS. LinkedIn Easy Apply is
supported but deliberately **serialised and paced** (one at a time, human-like
delays, a daily cap) via `tools/run_linkedin.sh`, using a **dedicated persistent
browser profile** so you stay logged in and a device/2FA prompt isn't re-triggered.

1. Start the browser with that profile, headful, and log in once:
   ```bash
   # the runner uses its own profile dir under ~/.config/job-search/linkedin-profile
   python3 tools/camoufox_server.py --port 9869 --headful
   python3 tools/camoufox_browser.py --server http://127.0.0.1:9869 nav https://www.linkedin.com/login
   # log in in the window; complete any 2FA
   ```
2. Prefer the employer's own ATS where one exists; put LinkedIn-only roles in
   `state/queue-linkedin.tsv` and run `bash tools/run_linkedin.sh`.
3. **Never mass-apply, and stop on any CAPTCHA/checkpoint** — do not evade. If a
   checkpoint appears (or you're unsure whether it's allowed), stop and don't use
   this mode.

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

- Everything sensitive lives in `~/.config/job-search/` (`credentials.json`,
  `token.json`, `accounts.json`, `*-profile/`) — **outside** the repo.
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
