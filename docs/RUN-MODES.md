# Run modes

The pipeline can be run several ways. **The agent should explain these to the
user and let them choose**, the user should never have to read this file.

## 1. Discover (find roles, no applications)

Find new roles and feed the queue; generate nothing.

```bash
python3 tools/discover.py                 # from LinkedIn Job Alert emails (dry run)
python3 tools/discover.py --queue         # add new matches to state/queue.tsv
python3 tools/email_opportunities.py --apply   # recruiter/contract leads -> register
python3 tools/prioritise_queue.py         # order the queue most-senior-first
```

## 2. Review / Prepare (generate documents, do NOT send)

For every queued role: build the **grounded, targeted CV and cover letter**,
run the alignment and pre-submit gates, save the files, and record the row as
`PREPARED`. **Nothing is submitted.** Use this to review documents before sending.

```bash
REVIEW=1 PARALLEL=3 bash tools/run_queue.sh
```

Outputs per role: `state/kb-context/<key>.md`, `state/cv-content/<key>.json`,
`documents/applications/<Prefix>_CV_<key>.docx` (+ `.pdf`) and
`documents/applications/<Prefix>_Motivation_<key>.docx`. Review them, then move the
roles you're happy with to an apply run (or send them yourself).

## 3. Apply (generated, role-targeted CVs), the default

Full end-to-end: build the targeted documents, gate them, submit through the
employer's ATS, and record provenance.

```bash
PARALLEL=3 bash tools/run_queue.sh
```

Each queued role's CV is **generated for that role** (aligned to its family and
grounded in the knowledge base). This is the highest-quality mode.

## 4. Apply with a fixed CV (no per-role generation)

Use **one** CV for every role in the run, no grounding, no per-role CV/letter.
Fast and cheap (e.g. a "general" CV), lower targeting.

```bash
LIGHT=1 FIXED_CV=documents/archetypes/<Prefix>_CV_<Archetype>.docx \
  PARALLEL=3 bash tools/run_queue.sh
```

The runner still does the eligibility/duplicate gates and records the outcome.

## 5. One role at a time (manual, for control or a retry)

Drive the per-role steps directly (see `AGENTS.md` §4): save the ad, extract ATS
keywords, ground with GraphRAG, pick the aligned archetype, build the targeted CV
+ letter, gate, apply, record. Ideal for a single URL or a re-run.

## Choosing the CV per role

- The queue's 4th column is the **starting archetype** (e.g. leadership vs
  AI-platform vs security); the runner verifies alignment and switches if needed.
- **Generated** CVs (modes 2–3) are tailored per role and grounded in the KB.
- **Fixed** (mode 4) uses your chosen archetype as-is.

## 6. Reconcile (track replies)

```bash
python3 tools/gmail_reconcile.py --apply   # set INTERVIEW / REJECTED / SUBMITTED
bash tools/reconcile_loop.sh               # continuous, refreshes counts
```

## Environment switches (summary)

| Env | Effect |
|---|---|
| `PARALLEL=n` | number of concurrent applications |
| `REVIEW=1` | generate + gate + record `PREPARED`, do **not** submit |
| `LIGHT=1 FIXED_CV=<path>` | one fixed CV for all roles, no per-role generation |
| `PRIORITISE=0` | keep file order instead of most-senior-first |
| `ELIGIBILITY_OVERRIDE=...` | one-run override of the eligibility rules |
| `ENGAGEMENT=contract` | use contract/consulting CV+letter rules (rate allowed) |
| `MODEL=...` | the agent model the runner launches |
| `CAMOUFOX_SERVER=...` | target a specific browser instance/ports |
