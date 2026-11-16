# ATS recipes (how the browser drives each system)

<div align="center"><sub><a href="../README.md">Jobsquirrel</a> · <a href="README.md">Docs</a></sub></div>


The browser CLI (`tools/camoufox_browser.py`) exposes: `status | nav | snap |
click | fill | type | select | pick | fillmap | flow | press | check | value |
eval | text | wait | waitfor | waittext | waiturl | upload | download | headers`.
Refs renumber after every `snap`, so prefer CSS selectors with
`fill '<sel>' '<text>'`. Custom widgets that render options in a listbox
(Workday, Greenhouse react-select, Ashby) are **not** clickable via dispatched
events, use `pick '<option text>' ['<opener selector>']` (it scrolls virtualised
lists and clicks with real input).

## One call per page: `flow`

Every separate browser command is a separate agent turn, and the agent re-reads
the whole transcript on each one: a 20-control form used to cost 20 turns and a
growing context, which is why a submit took five to ten minutes. `flow` runs the
whole page inside the browser server:

```bash
python3 tools/camoufox_browser.py --server $S flow '{"steps":[
  {"op":"nav","url":"https://example.test/apply"},
  {"op":"waitfor","selector":"#email"},
  {"op":"fill","selector":"#email","value":"me@example.test"},
  {"op":"pick","text":"Sweden","open":"#country"},
  {"op":"upload","selector":"input[type=file]","path":"documents/applications/CV.docx"},
  {"op":"click","target":"button[type=submit]"},
  {"op":"waittext","text":"thank you|application received","regex":true,"timeout":30000},
  {"op":"snap","match":"next|continue"}
]}'     # or: flow @steps.json
```

Steps: `nav{url}`, `fill{selector,value}`, `type`, `select{selector,value}`,
`check`, `upload{selector,path}`, `press{key,selector}`, `click{target}`,
`pick{text,open}`, `eval{js}`, `waitfor{selector,timeout,state}`,
`waittext{text,timeout,regex}`, `waiturl{url,timeout}`, `text{max}`,
`snap{match}`, `sleep{ms}`. Add `"optional": true` to a step that may legitimately
fail. The flow stops at the first failing step and returns `failed_at` and the
error, so one call covers fill → upload → submit → confirmation.

Use `waitfor` / `waittext` / `waiturl` instead of `wait` or `sleep`: they return
the moment the condition holds. `snap --match '<regex>'` narrows the ref list
without renumbering it, and `text [chars]` returns trimmed page text for reading
a confirmation.

## 2FA / sign-in checkpoints

A code or an app approval is the one thing the pipeline must not solve. When a
sign-in is stopped by one, ask the human and wait:

```bash
python3 tools/ask_human.py --reason "LinkedIn sign-in: code needed" \
  --detail "Acme / Engineer" --timeout 600
```

It pings the desktop and shows a single dialog in the dashboard; when the human
types the code it prints `{"ok":true,"answer":"482913"}`, and the agent types
that into the page and carries on. Exit code 2 / `"ok":false` means nobody
answered (or it was cancelled): record `BLOCKED` with the page left open.
Email-delivered codes do not need a human; read them with `tools/email_verify.py`.

> These recipes are starting points. Employers change their forms; when a step
> fails, `snap` the page, adjust the selector, and prefer the employer's own ATS
> over a job-board Easy Apply wherever one exists.

## Teamtailor (reliable)
Open `<job-url>/applications/new`.
- `#candidate_first_name`, `#candidate_last_name`, `#candidate_email`, `#candidate_phone`
- Cover letter: `#candidate_job_applications_attributes_0_cover_letter`
- Upload CV: `#candidate_resume_remote_url`; motivation: `#candidate_file_remote_url`
- Custom questions: `[name="candidate[answers_attributes][N][text]"]` (textarea),
  or `[range]` / `[choice]` radios
- Consent `#candidate_consent_given`, then submit. Email verification is often
  required (read the newest verify email, open the link).

## Greenhouse
- `#first_name`, `#last_name`, `#preferred_name` (if present), `#email`, `#phone`
- Upload `#resume`, `#cover_letter`
- **react-select custom questions** do not commit via `select`: focus the
  combobox input, type to filter, then really click `.select__menu .select__option`
  and verify the label renders.
- If the careers host blocks the embed, apply via `job-boards.greenhouse.io/<co>/jobs/<id>`
  (or `.../job_app?for=<co>&token=<gh_jid>`).
- **Email security-code gate**: on submit Greenhouse emails an 8-char code, read
  it (`tools/email_verify.py --query 'from:us.greenhouse-mail.io OR from:greenhouse.io newer_than:1d'`)
  and enter it into the code inputs, then resubmit.

## Lever
- `name`, `email`, `phone`; resume upload; sometimes custom questions; submit.
- May present an **hCaptcha** (human step if so).

## Ashby
- Fills and submits fine **if** custom yes/no buttons are set explicitly: click
  `button[data-option="no"]` (or `yes`), otherwise "Missing entry for required
  field".
- **Location autocomplete** (e.g. "current location"): type the city, wait for the
  dropdown, then pick the suggestion (the country entry if the city won't commit).
- **Application limits**: some companies cap applications per N days ("we can see
  you've applied to another role within the last 30 days"). This is server-side;
  it cannot be circumvented, record `CLOSED` with the reason.

## Workday (common at large enterprises)
- **Multiselect "How did you hear about us?"** is a virtualised list that renders
  collapsed: click to expand, type-to-filter + Enter, or drill in and real-click
  the leaf. Verify the chip renders, then Save & Continue.
- **Sign-in issues**: prefer the anonymous path, on the job page choose **"Apply
  Manually"** (not "Autofill with resume"). If only an account works, create one
  (`tools/accounts.py --for <url>`) or trigger password reset and read the code
  from the inbox. Repeat sub-steps ("Save and Continue") can silently no-op,
  re-snap and re-click until the section saves.

## Jobylon / Novare Executive Search
- Submits a POST to `.../wp-admin/admin-ajax.php` behind an nginx rate limit;
  hammering returns **HTTP 429**. Submit once, then back off (minutes). If it
  stays 429, record `BLOCKED`.

## Account-based platforms (Workday, SuccessFactors, own sites, agencies)
1. Get credentials: `python3 tools/accounts.py --for <url>`.
2. Pull standard answers: `python3 tools/identity.py --json`.
3. Sign up / log in; finish any email verification
   (`tools/email_verify.py --domain <host> [--open]`).
4. Apply, run the pre-submit gate, then `record_submission.py`.
5. On any CAPTCHA / 2FA / "suspicious activity": stop and set `MANUAL`.

## Video / scheduling tools
Interview invites often use Google Calendar / Teams / Zoom / Ashby scheduling.
`tools/gmail_calendar_auth.py --check` lists calendar events (with the
`calendar.events` scope it can also add interview events); self-schedule links
(e.g. Ashby `you.ashbyhq.com/meeting/<id>`) are driven the same way as an ATS form.

## Rules of thumb
- Prefer the employer ATS over LinkedIn Easy Apply (automating LinkedIn may
  breach its User Agreement, see [DISCLAIMER.md](https://github.com/bongomanuk/jobsquirrel/blob/main/DISCLAIMER.md)).
- One submission, then back off, never hammer a rate-limited endpoint.
- On any CAPTCHA/2FA/checkpoint, stop; do not evade; record `BLOCKED`/`MANUAL`.
- Record only with real evidence (the exact thank-you text or confirmation email).
