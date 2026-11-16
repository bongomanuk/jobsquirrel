# Adaptive harness

The main harness is deliberately conservative: one agent, one prompt, one
browser, a fixed set of tools. When it meets a form it does not understand, it
records `BLOCKED` and stops. That is the right default, but it leaves good roles
unsubmitted for a mechanical reason: an unusual widget, an iframe, a wizard, a
file chooser.

The adaptive harness is a **separate** component that takes that one page and
tries to finish it. It does not modify the main harness, and the main harness
does not import it. It is invoked as a black box and returns a JSON result.

```
tools/adaptive/
  AGENT.md          the adaptive agent's manual and hard boundary
  run.sh            launcher: dedicated port/profile, prompt, JSON result
  validate.py       recipe validator (declarative steps only)
  recipes/          verified, reusable form recipes
```

## Separation

| | Main harness | Adaptive harness |
|---|---|---|
| Code | `tools/run_queue.sh`, `tools/agent_run.sh`, prompts | `tools/adaptive/` only |
| Browser | the run's worker port | its own port (`ADAPTIVE_PORT`, default 9899) and profile |
| Writes | register, queue, documents, state | recipes, adapters, `state/logs/adaptive-*` |
| On a wall | records `BLOCKED` and stops | stops and reports the exact wall |
| On success | records the submission | returns the confirmation; the caller records |

The dedicated profile matters: a stuck page in the main worker cannot poison the
adaptive attempt, and a sign-in done in one profile is not silently reused by
the other.

## The boundary

The adaptive harness solves **forms**, not security controls. It must stop and
report, never work around:

- CAPTCHA, hCaptcha, reCAPTCHA, Turnstile, slider or rotate challenges
- 2FA, SMS/authenticator codes, device approvals, login checkpoints
- employer rate limits and application caps
- paywalls, fees, wallets, payment or ID uploads
- site terms that forbid automation

This is the same golden rule as the main harness. A harness that evades those
gets the candidate's accounts banned, and it is not a form problem.

## Running it

```bash
ADAPTIVE=1 PARALLEL=1 bash tools/run_queue.sh
```

With `ADAPTIVE=1`, a task that comes back `BLOCKED` is handed to the adaptive
harness on its own browser. If the harness returns a verified confirmation, the
caller records `SUBMITTED` with that text as evidence. If it returns a wall, the
row stays `BLOCKED` with the exact reason.

Run it directly for one role:

```bash
bash tools/adaptive/run.sh \
  --company "Acme" --role "Staff Engineer" \
  --url "https://jobs.example.com/apply" \
  --cv documents/applications/Acme_CV_staff.docx \
  --key acme-staff \
  --blocker "unknown multi-step wizard"
```

It prints one JSON line:

```json
{"ok":true,"confirmation":"Thank you for applying","recipe":"tools/adaptive/recipes/...","notes":"..."}
```

or

```json
{"ok":false,"blocker":"exact wall text","url":"...","notes":"..."}
```

## Recipes

When the harness solves a form, it writes a recipe under
`tools/adaptive/recipes/`. A recipe is a declarative list of browser steps
(`nav`, `fill`, `upload`, `click`, `waittext`, ...) with `{{email}}`, `{{name}}`
and `{{cv}}` placeholders. It is validated by `tools/adaptive/validate.py` and
replayed by the adaptive harness on the same host. It is never imported by the
main harness and it cannot contain shell or filesystem code.

A recipe is only saved after it has been tested on the page. A failed attempt
leaves no recipe behind.
