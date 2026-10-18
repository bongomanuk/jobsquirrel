# Releases

## Versioning
- `vMAJOR.MINOR.PATCH`. During active development, cut a **patch** release per batch of
  changes (`v0.5.9`, `v0.5.10`, …) rather than rewriting an existing tag.
- Bump the `VERSION` file to match; the in-app **update check** compares it to the latest
  GitHub release.

## Naming
- **Release titles must be funny.** A joke, a meme, a pun — never a serious codename.
  Examples: *"Deez Nuts"*, *"Dem Nuts"*, *"Bofa"*, *"Ligma"*. If it isn't a laugh, rename it.
- Title format: `vX.Y.Z "Funny Title"` (one emoji is fine).

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
