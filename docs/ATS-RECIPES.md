# ATS recipes (how the browser drives each system)

The browser CLI (`tools/camoufox_browser.py`) exposes: `status | nav | snap |
click | fill | type | select | pick | fillmap | press | check | value | eval |
wait | upload | download | headers`. Refs renumber after every `snap`, so prefer
CSS selectors with `fill '<sel>' '<text>'`. Custom widgets that render options in
a listbox (Workday, Greenhouse react-select, Ashby) are **not** clickable via
dispatched events — use `pick '<option text>' ['<opener selector>']` (it scrolls
virtualised lists and clicks with real input).

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
- **Email security-code gate**: on submit Greenhouse emails an 8-char code — read
  it (`tools/email_verify.py --query 'from:us.greenhouse-mail.io OR from:greenhouse.io newer_than:1d'`)
  and enter it into the code inputs, then resubmit.

## Lever
- `name`, `email`, `phone`; resume upload; sometimes custom questions; submit.
- May present an **hCaptcha** (human step if so).

## Ashby
- Fills and submits fine **if** custom yes/no buttons are set explicitly: click
  `button[data-option="no"]` (or `yes`) — otherwise "Missing entry for required
  field".
- **Location autocomplete** (e.g. "current location"): type the city, wait for the
  dropdown, then pick the suggestion (the country entry if the city won't commit).
- **Application limits**: some companies cap applications per N days ("we can see
  you've applied to another role within the last 30 days"). This is server-side;
  it cannot be circumvented — record `CLOSED` with the reason.

## Workday (common at large enterprises)
- **Multiselect "How did you hear about us?"** is a virtualised list that renders
  collapsed: click to expand, type-to-filter + Enter, or drill in and real-click
  the leaf. Verify the chip renders, then Save & Continue.
- **Sign-in issues**: prefer the anonymous path — on the job page choose **"Apply
  Manually"** (not "Autofill with resume"). If only an account works, create one
  (`tools/accounts.py --for <url>`) or trigger password reset and read the code
  from the inbox. Repeat sub-steps ("Save and Continue") can silently no-op —
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
- Prefer the employer ATS over LinkedIn Easy Apply.
- One submission, then back off — never hammer a rate-limited endpoint.
- On any CAPTCHA/2FA/checkpoint, stop; do not evade; record `BLOCKED`/`MANUAL`.
- Record only with real evidence (the exact thank-you text or confirmation email).
