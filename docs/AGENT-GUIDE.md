# Driving the pipeline with an AI agent

This project is built to be **run by an AI coding agent**, not clicked through by
hand. The intended workflow is: a human fills in `config/`, then points an agent
(opencode, Claude Code, Cursor, …) at the repository and tells it what to do. The
agent then discovers roles, tailors documents, gates them, and applies — you just
review and make the few calls only a human should.

`AGENTS.md` (repo root) is the agent's operating manual and is read automatically
by opencode and similar tools. This document is the human's guide to handing the
project over.

## 1. One-time setup (human)

```bash
pip install -r requirements.txt && python3 -m camoufox fetch
cp config/profile.example.md      config/profile.md          # your identity + rules
cp config/cv.example.json         config/cv.json             # your CV as data
cp config/archetypes.example.json config/archetypes.json     # your CV templates
python3 tools/build_archetypes.py                            # build the archetypes
# Gmail (read-only) is optional; the knowledge base (GraphRAG) is required — docs/KNOWLEDGE-BASE.md
```

That is the only manual work. Everything after this is the agent.

## 2. Hand it to the agent

Give the agent the repository path and a brief like:

> You are operating my job-search pipeline (this repo). Read `AGENTS.md` and
> `config/profile.md` first. Then:
> 1. Find new senior roles and add them to `state/queue.tsv`.
> 2. Run the pipeline (`PARALLEL=3 bash tools/run_queue.sh`).
> 3. Reconcile with my email and tell me what needs me.
> Only apply to roles that fit my eligibility and accuracy rules. Never send
> email without asking me. Stop on any CAPTCHA/2FA.

Because `AGENTS.md` is auto-loaded, most agents will already know the procedures;
the brief above just sets the goal.

On first run the agent opens by reading **`docs/INTRO.md`** to the user — a plain
language overview of what the pipeline is, how it works, the run modes, and their
privacy — before it starts the interview.

## 3. What the agent does autonomously vs escalates

**Autonomous**
- Discover roles (`discover.py`, `email_opportunities.py`, or web search) and queue them.
- Save ads, extract ATS keywords, build the grounded context pack.
- Choose and verify the aligned CV archetype; write the targeted CV + letter.
- Run the pre-submit gate; fix and re-run until it passes.
- Drive the browser (Camoufox) through the employer ATS and submit.
- Record provenance and upsert the register; reconcile email and set statuses.

**Escalate to you (it must stop and ask / record BLOCKED/MANUAL)**
- CAPTCHA / 2FA / bot checks ("suspicious activity").
- Any email to be **sent** (recipient + subject + content need your approval).
- Verification links/codes to be clicked/entered (it surfaces them only).
- Ambiguous eligibility/accuracy rules, missing `config/`, or a corrupt register.

## 4. The two ways it works

- **Batch** — fill `state/queue.tsv`, then `bash tools/run_queue.sh`. One
  sub-agent per role does the full procedure. Processes **most senior first**.
- **Per role** — the agent runs the same steps for a single job (useful for a
  retry, a specific URL, or showing you a CV before applying).

Both are described step-by-step with exact commands in `AGENTS.md` §3–§6 and
`docs/WORKFLOW.md`.

## 5. A worked exchange

```
You:  Find and queue new senior roles, then run the pipeline.
Agent: [discover.py + web search] queued 6 roles (Director, 3× EM, 2× Staff).
       [run_queue.sh] Acme Head of AI SUBMITTED · Beta CLOSED (dead
       posting) · Aon BLOCKED (hCaptcha — needs you) ... 
       Register: 120 SUBMITTED · 5 INTERVIEW · 8 REJECTED · 2 BLOCKED.
       Needs you: solve the Aon hCaptcha; approve a reply to ATG.

You:  Reconcile with email.
Agent: [gmail_reconcile.py --apply] set 1 INTERVIEW, 2 REJECTED; verification
       links surfaced for 3 applications.
```

## 6. Notes

- **Model budget:** `run_queue.sh` stops itself on model rate/budget limits and
  tells you; top up and re-run.
- **Rate limits / anti-bot:** the pipeline is deliberately polite (one submission
  at a time for LinkedIn, back-off on 429s). Do not ask the agent to hammer a site.
- **Human steps are real:** some employers genuinely require a human CAPTCHA/2FA
  pass. The system routes those to `state/queue-human.tsv` and `human_assist.sh`.
- **Accuracy is the point:** if the agent can't evidence a claim, it leaves it
  out. Lower ATS coverage is acceptable; a fabrication is not.
