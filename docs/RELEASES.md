# Releases

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
# 1. bump the version
printf 'X.Y.Z\n' > VERSION && cp VERSION jobsquirrel/VERSION
# 2. commit + push both repos, then tag (annotated) and push the tag
git tag -a vX.Y.Z -m 'vX.Y.Z "Funny Title"' && git push origin vX.Y.Z
# 3. create the GitHub Release with the same name and notes (via the API; gh isn't required)
```
The release notes follow the house voice: a one-line gag, a theme sentence, then
**The nuts we added** (bullets) and, when relevant, a *Cracked shells* section for
behaviour that changed.
