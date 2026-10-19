# Workflow

There are two ways to work a role: **manually** (fine-grained control) or via the
**queue runner** (`run_queue.sh`), which does the same steps per job
automatically. Both rely on the same gates, so the automation never sends
anything a human run wouldn't.

> Day-to-day, you drive this by prompting an agent in plain English and watching
> it work, see **[USING-IT.md](USING-IT.md)** for typical prompts and how to
> monitor a run.

## Per-role procedure

```
# 1. Save the ad text
$EDITOR state/job-descriptions/<key>.md

# 2. Extract ATS keywords
python3 tools/ats_keywords.py --jd state/job-descriptions/<key>.md --out state/ats/<key>.txt

# 3. Choose the aligned CV archetype and verify
python3 tools/check_alignment.py --cv documents/archetypes/<Prefix>_CV_<Archetype>.docx \
    --jd state/job-descriptions/<key>.md      # must print RESULT: PASS - alignment

# 4. Build a targeted CV (ATS-safe .docx + styled .pdf) and a per-role letter.
#    Ground every claim in state/kb-context/<key>.md (GraphRAG) + config/cv.json.
python3 tools/cv_target.py --key <key> --content state/cv-content/<key>.json
#    ...then render the letter (see tools/make_letter.py / cv_builder.render_motivation)

# 5. PRE-SUBMIT GATE: nothing is uploaded until this prints RESULT: PASS.
#    --record writes a hash-stamped receipt; record_submission.py (step 7)
#    REFUSES to record SUBMITTED without it. Gate the files you will upload.
python3 tools/check_documents.py --letter documents/applications/<letter>.docx \
    --cv documents/applications/<cv>.docx --company "<Company>" \
    --ats-keywords state/ats/<key>.txt --record
#    (add --engagement contract only for genuine contract/consulting roles)

# 6. Apply through the employer's own ATS with the Camoufox browser
python3 tools/camoufox_server.py --port 9872 &
python3 tools/camoufox_browser.py --server http://127.0.0.1:9872 nav "<apply-url>"
#    fill, upload, answer questions honestly, submit (see docs/ATS-RECIPES.md)

# 7. Record the exact files sent (snapshots + hashes) and upsert the register
python3 tools/record_submission.py --company "<Company>" --role "<Role>" --ats <ATS> \
    --url <apply-url> --cv documents/applications/<cv>.docx \
    --letter documents/applications/<letter>.docx --status SUBMITTED \
    --evidence "<the exact thank-you text or confirmation email>"
```

## Queue runner

```bash
PARALLEL=3 bash tools/run_queue.sh            # processes state/queue.tsv
```

For each row it: checks eligibility against `config/profile.md`; picks and verifies
the aligned archetype; builds a targeted CV + letter; runs the pre-submit gate;
submits via Camoufox; and records the outcome (or the blocker). Finished rows are
appended to `state/queue.done` (keyed `company|role`). `LIGHT=1 FIXED_CV=<path>`
runs a cheaper mode with one fixed CV.

**Seniority first.** When several roles are pending, the runner applies to the
most senior first, e.g. a company's *Director of Engineering* before its
*Platform Engineer*. Rank (high→low): Chief/CTO/VP · Director/Head of ·
Principal/Staff · Lead/Manager · Senior · other. Set `PRIORITISE=0` to use file
order instead, or sort the queue file itself with
`python3 tools/prioritise_queue.py` (`--dry-run` to preview).

LinkedIn Easy Apply is handled **separately and serially** by
`tools/run_linkedin.sh` (one at a time, human-like delays, a daily cap) using a
persistent logged-in profile so you stay logged in and at a human pace.
**Note:** automating LinkedIn may breach its terms of service and can get your
account restricted, it is **opt-in**; prefer the employer's own ATS
(see [DISCLAIMER.md](../DISCLAIMER.md)).

## Tracking replies

With Gmail configured:

```bash
python3 tools/gmail_reconcile.py            # propose INTERVIEW / REJECTED / SUBMITTED
python3 tools/gmail_reconcile.py --apply    # write them + regenerate the register
bash tools/reconcile_loop.sh                # keep it running (reconcile + counts)
```

`gmail_reconcile.py` matches each message to a register row, sets the status, and
prints any **verification links/codes** for you to act on manually (it never
clicks or enters them). Ambiguous multi-role matches are reported, not guessed.

## Human steps the pipeline will not do

Some walls are for a human: CAPTCHAs / bot checks, SMS/app 2FA, "possible spam"
re-submissions, rate-limit resets. These are recorded `BLOCKED` (or `MANUAL`) with
a reason; `build_human_queue.py` routes the human-only ones to
`state/queue-human.tsv`, and `human_assist.sh` opens them in your real browser.

## Principles to keep

- Never send a letter that fails the gate.
- Never fabricate: only claim what `config/cv.json` / `config/profile.md` support.
- Only roles you can actually take (see [ELIGIBILITY.md](ELIGIBILITY.md)).
- Keep the register current, it is the source of truth for resuming.
- Pace it: a few submissions per sitting, long gaps, prefer named contacts.
