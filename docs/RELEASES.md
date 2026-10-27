# Releases

## Privacy (the public repo is public)
Release titles, notes, tags, commit messages and the code are all public. **Never**
put the candidate's personal data or live pipeline state in them. In particular,
never write:
- the candidate's name, email, phone, LinkedIn/website, city/country or pay target;
- a specific country, city, currency code or market name;
- employers, recruiters, job titles or companies from the live register;
- real counts from the register ("22 need you", "441 ongoing"), interview dates or
  mailbox/application statistics.

Describe features generically: "a role", "the candidate", "a configurable pay floor",
"a company name mentioned in passing". Use synthetic examples (`Acme`, `ExampleCorp`).
Screenshots, logs and examples must be redacted or synthetic. If in doubt, leave it out.

## Versioning
- `vMAJOR.MINOR.PATCH`. During active development, cut a **patch** release per batch of
  changes (`v0.5.9`, `v0.5.10`, …) rather than rewriting an existing tag.
- Bump the `VERSION` file to match; the in-app **update check** compares it to the latest
  GitHub release.

## Naming
- **Release titles must be funny AND nut/squirrel themed** — a pun or gag that nods to
  nuts, acorns, squirrels or caching. Examples: *"Deez Nuts"*, *"Dem Nuts"*, *"Acorny Joke"*,
  *"Hazel Nutt"*, *"Nuts to You"*, *"Go Nuts"*, *"Squirrelled Away"*, *"Bussin' Nuts"*.
  A funny name with no nut/squirrel angle (Rizz, Skibidi, Ohio…) does **not** qualify —
  rename it.
- Title format: `vX.Y.Z "Funny Nut Title"` (one emoji is fine).

## Cutting one
```bash
# 0. write the notes to /tmp/notes.md, then lint them (must print RESULT: PASS)
python3 tools/release_lint.py --text-file /tmp/notes.md
# 0b. scan the public clone for live credentials (must print RESULT: PASS)
python3 tools/secret_scan.py --repo jobsquirrel
# 1. bump the version
printf 'X.Y.Z\n' > VERSION && cp VERSION jobsquirrel/VERSION
# 2. commit + push both repos, then tag (annotated) and push the tag
git tag -a vX.Y.Z -m 'vX.Y.Z "Funny Title"' && git push origin vX.Y.Z
# 3. create the GitHub Release with the same name and notes (via the API; gh isn't required)
```
Never publish notes that fail `release_lint.py`. The release notes follow the house
voice: a one-line gag, a theme sentence, then **The nuts we added** (bullets) and,
when relevant, a *Cracked shells* section for behaviour that changed.

`secret_scan.py` checks tracked/untracked files and git history for live key
formats and for the exact values in the private agent/GraphRAG config. It never
prints a secret. A hit in history is still a leak: rotate the key and purge the
history; deleting it from the tip is not enough.
