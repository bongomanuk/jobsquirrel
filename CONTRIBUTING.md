# Contributing to Jobsquirrel

Thanks for wanting to help. Jobsquirrel is a small, agent-first toolkit; the code is
plain Python + a little shell, with no framework. Contributions that make it
**more accurate**, **more portable** (more countries, languages, ATSes) or
**easier to run as an agent** are especially welcome.

## Ground rules

- **Never add a person-specific or country-specific default.** Everything personal
  belongs in `config/` (git-ignored). No real names, employers, cities, currencies
  or languages may be hard-coded in `tools/`.
- **Truthfulness is a feature.** Don't weaken the gates (`check_documents.py`,
  `check_alignment.py`, `facts.py`). If anything, make them catch more.
- **Keep it agent-drivable.** New behaviour should be a CLI tool + a line in
  `AGENTS.md`/`BOOTSTRAP.md`, not something a human has to click.

## Running it locally

```bash
bash tools/install.sh                 # deps + Camoufox browser + GraphRAG + LibreOffice check
cp config/profile.example.md config/profile.md   # (or let an agent bootstrap you)
cp config/cv.example.json    config/cv.json
cp config/archetypes.example.json config/archetypes.json
python3 tools/build_archetypes.py
```

Use the project venv: `.venv/bin/python tools/<tool>.py`.

## Before you open a PR

- Python: `.venv/bin/python -m py_compile tools/*.py`.
- Shell: `bash -n tools/*.sh install.sh`.
- Tests: `python3 -m pytest -q` (see `tests/`). CI runs these on every PR.
- **No personal or country-specific references** anywhere (your name, your city/
  country, or real employers/clients you used while testing). Check with your own
  terms:
  ```
  grep -rniE "<your-name>|<your-city>|<your-country>|<your-employer>" . | grep -v "\.git/"
  ```
  which must return nothing.
- Don't commit anything under `config/` (your data), `state/`, `documents/` or
  `kb/` (generated/private) — they're git-ignored on purpose.

## What's most useful

- **ATS recipes** (`docs/ATS-RECIPES.md`) for systems that don't work yet, or
  fixes for ones that changed.
- **New run modes** or guardrails, always documented in `AGENTS.md`.
- **Portability:** making the eligibility/accuracy rules handle more countries,
  languages and work-authorisation cases.
- **Tests** for the gates (they're the safety net).

## Style

- Small, single-purpose CLI tools in `tools/`; no heavyweight dependencies.
- Comments explain *why*, not *what*. No emojis in code or docs.
- Match the existing structure; prefer editing an existing tool over adding a new one.

## Reporting bugs / ideas

Open an issue with: what you ran, the exact output, and what you expected. If it's
about a specific ATS, include the (public) apply URL and what the form did.
