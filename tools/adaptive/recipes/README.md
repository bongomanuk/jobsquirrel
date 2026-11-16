# Adaptive recipes

A recipe is what the adaptive harness learned about one employer's form. It is
declarative JSON, keyed by host and blocker signature, and it is replayed by the
same separate harness, never by the main runner.

Naming: `<host>-<slug>.json`, for example `jobs.example.com-multi-step-wizard.json`.

Every recipe must carry:

- `name`, `host`, `blocker`, `created`, `verified`
- `steps`: a list of `{op, ...}` objects using only the ops in
  `tools/adaptive/validate.py` (`nav`, `fill`, `type`, `select`, `check`,
  `upload`, `press`, `click`, `pick`, `eval`, `waitfor`, `waittext`, `waiturl`,
  `sleep`, `snap`, `text`).

Placeholders `{{email}}`, `{{name}}` and `{{cv}}` are filled by the caller.

Validate before saving or reusing:

```bash
python3 tools/adaptive/validate.py tools/adaptive/recipes/<name>.json
python3 tools/adaptive/validate.py --all
```

A recipe is evidence of a form pattern, not a licence to bypass a control. If
the page shows a CAPTCHA, 2FA, a rate limit, a fee or a payment step, the harness
stops and reports it; no recipe is saved for that.
