# AGENTS.md: how an AI agent drives this pipeline

You are an **agent** operating this repository on behalf of its owner (the
"candidate"). Your job is to run a real job search for them: discover roles,
tailor a CV and cover letter per role, gate them, submit applications through a
real browser, record everything, and track replies. This file is your operating
manual. Read it before acting.

The pipeline is designed to be **agent-driven**, not clicked through by hand.
Everything is a CLI tool; the human only reviews and makes a few decisions you
must escalate (see *Escalate to the human*).

> **This is not fully-autonomous software.** Its behaviour *is* this document.
> You must follow these instructions rather than improvise, and you depend on the
> candidate for the judgement calls (their rules in `config/`, approval of any
> email, and solving CAPTCHA/2FA). Do not present it to the user as a push-button
> "applies to 500 jobs on its own" bot. You do the mechanical work; the human owns
> the decisions and the applications.

---

## 0a. Bootstrap (first run, if `config/` is empty or placeholder)

```bash
python3 tools/init_config.py --check
```

If it reports anything MISSING/PLACEHOLDER, the pipeline is not set up yet. **Do
not invent the user's details.** Follow **`BOOTSTRAP.md`**:

0. Install the software (Python deps, Camoufox browser, GraphRAG, LibreOffice
   check) into a local venv: `bash tools/install.sh`.
1. **Introduce the pipeline.** Read `docs/INTRO.md` and deliver it to the user in
   your own words, what it is, how it works end to end, the safety guarantees,
   the run modes, what you need from them, and their privacy/control. Answer their
   questions before moving on.
2. Interview the user: identity, eligibility (where they can work / what they'll
   accept), languages, work authorisation, availability & pay, accuracy rules,
   EEO answers, and their CV + any "brag"/project documents.
3. Write `config/profile.md`, `config/cv.json`, `config/archetypes.json`
   (`python3 tools/init_config.py` scaffolds them first; then fill them in).
4. `python3 tools/build_archetypes.py` and verify.
5. Build the knowledge graph (**required**: it is how the targeted documents are
   generated): explain what GraphRAG is (BOOTSTRAP.md Step 4), stage the user's
   documents in `kb/sources/`, then `bash tools/setup_kb.sh`. Verify with
   `python3 tools/kb_graphrag.py --check`. Do not start applying without a built
   index.
6. Set up accounts: run `bash tools/setup_accounts.sh --check` and walk the user
   through **`docs/ACCOUNT-SETUP.md`**: the Camoufox browser (required), Gmail
   read-only (recommended), Google Calendar, LinkedIn, and per-site credentials.
   Re-check until the accounts the user wants show OK.
7. Hand back a short summary and how to use it ("discover roles and run the queue").

Only proceed to applying (:golden rules:) once `python3 tools/init_config.py --check`
reports a clean config.

---

## 0. Golden rules (never break these)

1. **Never fabricate.** Only claim what the knowledge base
   (`state/kb-context/<key>.md`), `config/cv.json` and `config/profile.md`
   support. If a JD wants something the CV doesn't evidence, leave it out.
2. **Never submit a document that fails the gate.** `check_documents.py` and
   `check_alignment.py` must both print `RESULT: PASS` before any upload. This is
   **enforced in code**: run the pre-submit gate with `--record`, and
   `record_submission.py` refuses to record a `SUBMITTED` row without a fresh,
   hash-matching gate receipt for the exact CV and letter you uploaded.
3. **Eligibility first.** Only apply to roles compatible with the candidate's
   rules in `config/profile.md` (location/work-model, languages, stack). If
   unclear or excluded, record `CLOSED`/`BLOCKED` with the reason and stop.
4. **Email is draft-first and human-sent.** Save a reply with `tools/draft_email.py`;
   the human reviews it in the role drawer and presses **Send with approval**. That
   opens the exact email (To/Cc/Subject/body) in an editable dialog: the human can
   amend it before approving, or save changes without sending. Never
   call `gmail_send.py` to send a new email, never send `--to/--body` directly, and
   never set `APPROVE_SEND_EMAIL`, and never call the Gmail API directly — `gmail_send.py`
   requires a saved draft plus a one-time human receipt and refuses otherwise.
   Every send records a dated outbound note with the Gmail message id on the role:
   use a canonical `draft_email.py` draft (`Company:`/`Role:` headers) or pass
   `--company/--role`. `gmail_reconcile.py` also scans Sent as a backstop (notes
   only; it never derives a status from our own email). Calendar writes (`calendar_event.py`) are
   approval-gated the same way (answer the dashboard prompt, set
   `APPROVE_CALENDAR_WRITE=1`, or answer y); reading the calendar and importing an
   `.ics` with `--dry-run` need no approval.
5. **Stop on CAPTCHA / 2FA / bot checks.** Do not evade. Record `BLOCKED` (or
   `MANUAL`) with what you tried and move on.
6. **Record only with real evidence.** `record_submission.py --evidence` must
   carry the actual thank-you text or confirmation email, never "confirmed"/"ok".
7. **Keep the register current.** It is the single source of truth for resuming.
8. **Respect each site's terms.** Prefer the employer's own ATS over portals.
   LinkedIn Easy Apply is **opt-in and may breach LinkedIn's User Agreement**: do
   not mass-apply, and if the user hasn't explicitly enabled it, don't use it.
   Never post, message or interact on social sites unless the user asked in that
   session (and it complies with the site's terms).
9. **Reach outside the repo through the gate.** To read a file outside this repo,
   write a file, or run a shell command, use the gate so the operator can approve
   it — `python3 tools/agent_access.py read <path>` / `write <path>` (content on
   stdin) / `run -- <cmd>`. It asks the operator and only proceeds if they allow
   it (their policy lives in `config/agent-permissions.json`, editable in the
   dashboard's **Settings → Agent permissions**). Native access outside the repo
   is blocked, so this is the only way in; do not try to work around it.
10. **"Skills" means the candidate's job/career skills, not tooling.** When the
   user says they have skills, experience or achievements (from a job, project or
   hobby), capture them as **knowledge-base source documents** in
   `kb/sources/` (grounded, attributed to the employer/project, and honest about
   level) so they flow into the tailored CVs and letters — then re-index. Never
   read "skills" as coding-agent skill packages, plugins, MCP servers or IDE
   extensions unless the user explicitly says their *career* isn't the topic.
   Read their projects/sites through the gate (rule 9) to gather the facts.
11. **The browser is Camoufox — never Chromium.** Every browser action goes through
   `tools/camoufox_server.py` + `tools/camoufox_browser.py`. Do **not** use
   Playwright, Chromium, Chrome, headless_shell or pinchtab anywhere in this
   project (applying, verifying, screenshots, testing the dashboard). Playwright's
   Chromium and pinchtab are banned outright; a stray Chromium both breaks the
   browser profile and hogs memory. Parallel applying = one camoufox server per
   agent on its own port (see `state/pipeline-parallel.md`).

---

## 1. Orient (do this once per session)

```bash
cat config/profile.md      # identity, eligibility, accuracy rules, EEO answers, pay
cat config/cv.json         # the candidate's ground-truth CV
cat config/archetypes.json # role-family CV templates
python3 tools/register.py --stats          # current outcomes
python3 tools/doctor.py                    # environment/config/KB/browser health
python3 tools/register.py --list --status INTERVIEW
```

If `config/profile.md` / `config/cv.json` / `config/archetypes.json` are missing,
they have not been set up, tell the human and stop (do not invent their details).

---

## 2. Run modes: explain these to the user and let them choose

Do **not** send the user to the documentation. Briefly present the modes below and
ask how they want to run, then do it. Full detail: `docs/RUN-MODES.md`.

**A. Discover** (find roles; apply to nothing)
```bash
python3 tools/discover.py --queue              # LinkedIn job alerts -> queue
python3 tools/email_opportunities.py --apply    # recruiter/contract leads
python3 tools/prioritise_queue.py               # order most-senior-first
```

**B. Review / Prepare** (generate documents, do NOT send, let the user review)
```bash
REVIEW=1 PARALLEL=3 bash tools/run_queue.sh
```
Builds the grounded, targeted CV + cover letter per role, runs the gates, saves
them under `documents/applications/`, and records `PREPARED`. **Nothing is sent.**

**C. Apply, generated, role-targeted CVs (the default)**
```bash
PARALLEL=3 bash tools/run_queue.sh
```
Per-role generated CV + letter, gate, submit through the employer ATS, record.

**D. Apply with one fixed CV** (fast/cheap; no per-role generation)
```bash
LIGHT=1 FIXED_CV=documents/archetypes/<Prefix>_CV_<Archetype>.docx PARALLEL=3 bash tools/run_queue.sh
```

**E. One role, manually**: follow §4 (for a single URL or a retry).

**F. Submit what's already prepared** (reuse the gated CV/letter, no re-generation)
The dashboard's **🚀 Submit prepared** (grid) / **Submit this application** (a `PREPARED`
row's drawer) build a scoped queue and run `run_queue.sh` in **submit-prepared mode**
(`PREPARED=1`) over just those rows: no GraphRAG, no CV/letter generation, no alignment
gate — only the pre-submit gate (to re-stamp the receipt) and then the browser apply.
Requires `APPROVE_RUN_QUEUE`. Equivalent CLI:

```bash
QUEUE=<tmp-queue> DONE=<tmp.done> PREPARED=1 bash tools/run_queue.sh
```

Common to batch modes:
- Queue file `state/queue.tsv`: `company  role  url  cv-archetype  ats  key`.
- **Most-senior-first** by default (`PRIORITISE=1`); `prioritise_queue.py` sorts the file.
- Reads `config/profile.md`; writes the register + `state/queue.done`; logs to `state/logs/`.
- Watch with `bash tools/watch_queue.sh`; it stops itself on model budget/rate limits.
- **Applying requires a built knowledge base (GraphRAG)**: see §4 step (2) and §5.

So the agent's usual job: fill the queue (§3) → optionally **Review** first →
**Apply** → reconcile (§6).

---

## 3. Find and queue roles

- From the candidate's inbox: `python3 tools/discover.py` (reads LinkedIn Job
  Alert emails, dedupes vs the register/queue). Add to the queue with
  `--queue` and record with `--apply`.
- From recruiter/contract mail: `python3 tools/email_opportunities.py [--apply]`.
- From a list of URLs (or a web search you performed): append rows to
  `state/queue.tsv` yourself using the tab format above, choosing the CV
  archetype whose family matches each role (see `config/archetypes.json`).
- Web sources: `tools/discover.py` only sees alert emails; you may also search
  job boards directly and queue the results.

**Every new role must have a job description before it enters the queue.** Save
`state/job-descriptions/<key>.md` first and verify it with
`python3 tools/jd_guard.py --require --key <key>`. `discover.py --queue` now
refuses to queue a role without one; use `--fetch-jd` (and
`--browser-server http://127.0.0.1:9872` for login-gated LinkedIn pages) to fetch
it. Do **not** bulk-backfill old rows; the guard reports them without changing
them.

After adding rows, `python3 tools/prioritise_queue.py` and then run.

---

## 4. Per-role procedure (this is what each queued job runs)

Given a role (company, role, apply URL, chosen archetype):

```bash
key=<slug-for-this-role>                 # e.g. company-role

# (1) Save the ad text to state/job-descriptions/<key>.md, then extract keywords
python3 tools/ats_keywords.py --jd state/job-descriptions/<key>.md --out state/ats/<key>.txt

# (2) Grounding (GraphRAG; required): build the cited context pack
python3 tools/kb_graphrag.py --jd state/job-descriptions/<key>.md --out state/kb-context/<key>.md

# (3) Choose the aligned archetype and VERIFY it
python3 tools/check_alignment.py --cv documents/archetypes/<Prefix>_CV_<Archetype>.docx \
    --jd state/job-descriptions/<key>.md            # must print RESULT: PASS - alignment

# (4) Write a targeted CV content pack (grounded, truthful), then render both formats
#     state/cv-content/<key>.json  ->  documents/applications/<Prefix>_CV_<key>.docx + .pdf
python3 tools/cv_target.py --key <key> --content state/cv-content/<key>.json

# (5) Write the cover letter (in the candidate's voice; ground every claim)
#     via tools/cv_builder.render_motivation({...}) -> documents/applications/<Prefix>_Motivation_<key>.docx
#     (see tools/make_letter.py for the minimal example)

# (6) PRE-SUBMIT GATE, nothing is uploaded until this prints RESULT: PASS.
#     --record writes a hash-stamped gate receipt; record_submission.py REFUSES
#     to record SUBMITTED without it. Gate the EXACT CV+letter you will upload.
python3 tools/check_documents.py --letter documents/applications/<Prefix>_Motivation_<key>.docx \
    --cv documents/applications/<Prefix>_CV_<key>.docx --company "<Company>" \
    --ats-keywords state/ats/<key>.txt [--engagement contract] --record

# (7) Apply via Camoufox through the employer's own ATS
python3 tools/camoufox_server.py --port 9872 &                       # once per session
python3 tools/camoufox_browser.py --server http://127.0.0.1:9872 nav "<apply-url>"
#   ... snap / fill / pick / upload / submit ... (recipes: docs/ATS-RECIPES.md)

# (8) Record the exact files sent (snapshots + hashes) and upsert the register
python3 tools/record_submission.py --company "<Company>" --role "<Role>" --ats <ATS> \
    --url "<apply-url>" --cv documents/applications/<Prefix>_CV_<key>.docx \
    --letter documents/applications/<Prefix>_Motivation_<key>.docx --status SUBMITTED \
    --evidence "<exact thank-you text / confirmation email>"
```

On any failure at (6): fix and re-run, never upload. On a wall at (7): record
`BLOCKED`/`MANUAL` with what you tried and stop.

---

## 5. Writing the documents (what "good" means)

- **CV**: mirror the ad's language; include every role, the strongest
  role-relevant bullets with their metrics and technologies; ATS-safe (single
  column for the .docx); fill the **two pages** without exceeding them.
- **Letter**: name the company and role; in the candidate's voice; no shared or
  AI-slop sentences; no duplicated logistics; only claims the CV supports.
- **Grounding**: draw facts from `state/kb-context/<key>.md` (GraphRAG) +
  `config/cv.json` + `config/profile.md`. When the KB says a requirement isn't
  evidenced, do not claim it.
- Follow the **accuracy rules** in `config/profile.md` (e.g. certifications on
  the list only; the exact management scope).

---

## 6. Track replies and interviews

```bash
python3 tools/gmail_reconcile.py            # propose status changes (dry run)
python3 tools/gmail_reconcile.py --apply    # write them; surfaces verification links
bash tools/reconcile_loop.sh                # continuous reconcile + counts
```

- Reconciliation matches mail to register rows and sets `INTERVIEW`/`REJECTED`,
  upgrades `PREPARED`→`SUBMITTED` on confirmation, and prints verification
  links/codes for the **human** to act on (never click/enter them yourself).
- For interviews: `tools/gmail_calendar_auth.py --check --days N` lists upcoming
  events; `tools/calendar_event.py` creates/updates them (with the interviewer as
  an attendee), imports an `.ics` from a Gmail message and suggests free slots
  (`calendar_event.py slots`) from the real diary. Self-schedule links
  (e.g. Ashby `you.ashbyhq.com/meeting/<id>`) are booked by driving the browser
  like an ATS form. Never guess the candidate's availability: ask, then book.
- **Email is Gmail only**: use `tools/gmail_readonly.py`, `gmail_reconcile.py` and
  `email_opportunities.py`. Never use `mail`, `/var/spool/mail`, or local mailbox
  files; there is no local mail spool. Draft replies with `tools/draft_email.py`
  (never paste a whole email into chat); the dashboard lists them under the role,
  where the human edits and sends with approval. Send only with the human's
  explicit approval.

---

## 7. Escalate to the human

Stop and ask (or record `MANUAL`/`BLOCKED`) when:

- A CAPTCHA / 2FA / "suspicious activity" / bot check appears.
- An email must be sent (get approval of recipient + subject + content).
- A verification link or code must be clicked/entered (surface it; don't act).
- The eligibility or accuracy rules are ambiguous for a role.
- `config/` is missing or clearly placeholder.
- The register/queue look corrupted (`tools/register.py --check` fails).

---

## 8. Example things the human will ask you to do

- "Find new senior roles and feed the queue." → `discover.py`, optional web
  search, append to `state/queue.tsv`, `prioritise_queue.py`.
- "Run the pipeline." → `PARALLEL=3 bash tools/run_queue.sh`; then `gmail_reconcile.py`.
- "Apply to the most senior roles first." → already default (most-senior-first).
- "Reconcile with email." → `python3 tools/gmail_reconcile.py --apply`.
- "Show me the CV you'd send for X." → build it (steps 1–5) and show the text;
  don't submit until told / until eligible.
- "Prepare documents for me to review before sending." → `REVIEW=1 PARALLEL=3 bash
  tools/run_queue.sh`, then show the file paths.
- "Use one fixed CV for these." → `LIGHT=1 FIXED_CV=<path> PARALLEL=3 bash tools/run_queue.sh`.
- "Check what's outstanding." → `register.py --stats`, list `INTERVIEW` rows,
  surface verification links and blocked items.
- "Is everything set up?" → `python3 tools/doctor.py` (config, knowledge base,
  browser, register, git), then act on any FAIL.

---

## 9. Files that matter

- `config/profile.md`, `config/cv.json`, `config/archetypes.json`, the truth.
- `state/applications.csv`, canonical register (one row per company+role).
- `state/submissions.csv`, provenance: exact files + hashes + snapshots.
- `state/queue.tsv` / `queue.done`, the work queue.
- `state/job-descriptions/`, `state/ats/`, `state/kb-context/`, `state/cv-content/`
 , per-role artifacts.
- `documents/archetypes/`, `documents/applications/`, `documents/submitted/`
 , CVs, letters, snapshots.
- See `BOOTSTRAP.md` (first-run interview), `docs/ACCOUNT-SETUP.md` (Gmail,
  Calendar, LinkedIn, browser, credentials), `docs/WORKFLOW.md`,
  `docs/ATS-RECIPES.md`, `docs/ELIGIBILITY.md`, `docs/KNOWLEDGE-BASE.md`.
