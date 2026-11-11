# Application states and transitions

This is the state model the dashboard, the queue runner and the reconciliation
tools share. The register (`state/applications.csv`) is the only record of an
application. The queue is work to do; a finished queue row is not a state.

## The states

| State | Meaning | Who sets it |
| --- | --- | --- |
| `QUEUED` | In the apply queue. Nothing has been prepared or sent. | discovery, the dashboard, a retry |
| `DRAFTING` | The advert is saved and preparation has started, but there are no gated documents yet. Shown for a queue row that has an ad, keywords or grounding. | preparation |
| `PREPARED` | The CV (and a letter only when required) is generated, measured and gate-PASS. Ready to submit. | a review/prepare run |
| `SUBMITTED` | The application was sent and confirmed, with a matching provenance row. An ATS status such as Under Consideration stays here: it is still waiting, not a new stage. | `record_submission.py`, or an approved email with the documents |
| `IN_PROGRESS` | An active process step is underway: an assessment, background checks, or a live recruiter conversation. Mere employer review stays `SUBMITTED`. | reconciliation, a manual update |
| `INTERVIEW` | An interview is invited, scheduled or held. Its sub-state says which. | reconciliation, a manual update |

| `OFFER` | An offer was received. | a manual update |
| `REJECTED` | The employer declined. | reconciliation, a manual update |
| `BLOCKED` | A wall stopped the run: a CAPTCHA or login, a gate failure, a missing advert, an email-only ATS, or an unclear eligibility rule. It is work for you, not a rejection. | the runner or the agent, with the exact reason |
| `MANUAL` | A human-owned lead or step: an intro meeting, a network row, a recruiter email with no advert. | `email_opportunities.py`, a manual update |
| `CLOSED` | The role is not applicable: not eligible, expired, withdrawn or a duplicate. The sub-state says which. | the runner, `prepare_role.py`, a manual update |

There is no `NO RESULT` application state. A run that cannot produce an
application records `BLOCKED` or `CLOSED` with the exact reason. A finished
queue row that never became a register row is a **queue leftover**, not an
application; see below.

`INTERVIEW` rows also carry **`interview_stage`** in the register: `screen`,
`hiring-manager`, `technical`, `panel`, `final` or `offer` (empty when not
recorded). The sub-state says *what is happening* (invited, scheduled, today,
held); the stage says *which round* it is. The drawer records it without
changing the status, and the grid shows it as a small chip.

## The normal path

```
QUEUED -> DRAFTING -> PREPARED -> SUBMITTED -> IN_PROGRESS -> INTERVIEW -> OFFER
                                      |                            |
                                      +-> BLOCKED / CLOSED          +-> REJECTED
```

`SUBMITTED` is the handoff from the candidate to the employer. `IN_PROGRESS` is
not set by a successful submit; it means an active step has started: an
assessment, background checks, or a live conversation. A silent employer, or an
ATS label such as Under Consideration, keeps the row at `SUBMITTED` and its
sub-state (`awaiting`, `acknowledged`, `stale`, `assessment`).

## Branch rules

- **QUEUED or DRAFTING -> BLOCKED** when the run hits a wall before it can
  prepare a usable application: a missing or dead advert, an unclear location or
  work model, a failed alignment/fill/pre-submit gate, a login/CAPTCHA, or an
  email-only application that the browser cannot send.
- **PREPARED -> SUBMITTED** only after a real confirmation and a provenance row.
  A submit click alone is not enough.
- **PREPARED -> BLOCKED or CLOSED** when the submission cannot happen: a wall,
  or a posting that expired or was filled.
- **Any active state -> CLOSED** when the role is withdrawn, expired, not
  eligible, or a duplicate.
- **BLOCKED -> QUEUED** when you retry or re-queue it. That is the only way back
  into the apply path.
- **MANUAL -> QUEUED, PREPARED or CLOSED** when the human decides what the lead
  is worth. `MANUAL` is never a silent waiting state.
- A network or email-only row has no apply URL. It can be prepared or have a
  draft email, but it is not submitted through a browser. **Prepare and submit**
  is offered only when the row has a real URL; otherwise use **Prepare
  documents** and the email route.

## Reposts and second attempts

One row is kept per company and role. A repost reuses that row:

- Preparation for the new attempt records `PREPARED`, even when the earlier
  attempt is `IN_PROGRESS` or `SUBMITTED`. The register refuses a live-to-
  `PREPARED` write unless the review is an explicit repost (`--repost`); a plain
  document refresh leaves the live status alone and notes the new files.
- The note keeps the earlier status and date, for example
  `repost: earlier application still IN_PROGRESS since 2026-10-08; new documents
  prepared, not submitted`. The live recruiter thread is not lost.
- A submission run does **not** reset `PREPARED` to `QUEUED`. The grid shows a
  spinner while the run is live, and the outcome sets `SUBMITTED`, `BLOCKED` or
  `CLOSED` directly. A crash leaves the row at `PREPARED`, which is the truth.

## Queue leftovers

`state/queue.done` records that a queue row finished. If no register row was
created, the row is a leftover: work was attempted, but there is no application
to track. It is not an application state and must not appear in the state map.

```bash
python3 tools/queue_leftovers.py --write        # list them in state/queue-leftovers.md
python3 tools/queue_leftovers.py --drop         # remove them from the active queue
```

The active queue should contain only work to do. A row that is already in
`queue.done`, or whose register row is `SUBMITTED`, `IN_PROGRESS`, `INTERVIEW`,
`OFFER`, `REJECTED`, `CLOSED`, `BLOCKED` or `MANUAL`, is not pending. Clean it
with:

```bash
python3 tools/queue_clean.py --apply
```

`--drop` also moves their `queue.done` entries to `state/queue-leftovers.done`,
so the register audit stays honest. The full queue rows are kept in
`state/queue-leftovers.tsv` and every artifact stays on disk. Append a row from
that file to `state/queue.tsv` to re-queue it, or leave it closed.

## The state map

The **Application states** panel draws this model: the normal path, the
BLOCKED/MANUAL branches, SCAMS and SHELVED side nodes, and the REJECTED/CLOSED
terminals. The bucket chips are views of the same rows, not extra states.
`SCAMS` and `SHELVED` are overlays: they never replace the register status.
