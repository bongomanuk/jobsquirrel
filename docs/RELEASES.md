# Releases

## Privacy (release notes are public)
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
- **Release titles must be funny AND squirrel-adjacent.** The well is where a squirrel
  lives and what it lives in: dens, dreys, lodges, setts, holts, warrens and nests, or
  tree types (oak, ash, elm, beech, yew, cedar, pine, spruce, larch, willow, holm).
- Rotation: **patch releases (0.5.x) use den/nest words; minor releases (0.6+) use tree
  types.** A mixed pun is fine when it earns the laugh.
- Patch examples: *"Nest Practice"*, *"Den and Dusted"*, *"Lair Necessities"*,
  *"Warren Peace"*, *"Sett For Life"*, *"Drey Area"*, *"Holt On"*.
- Minor examples: *"Cedar Than Never"*, *"Fir Real"*, *"Spruce Springsteen"*,
  *"Elm Street"*, *"The Holm Truth"*, *"Larch-itecture"*, *"Poplar Opinion"*.
- It must actually be a joke: a plain phrase ("Room to Grow") does not qualify, and a
  funny name with no squirrel/tree angle does not either. Rename it before publishing.
- Title format: `vX.Y.Z "Funny Title"` (one emoji is fine). The GitHub release title can
  be reworded after publication without moving the tag.

## Cutting one
```bash
# 0. write the notes to /tmp/notes.md, then lint them (must print RESULT: PASS)
python3 tools/release_lint.py --text-file /tmp/notes.md
# 0b. scan the repo for live credentials (must print RESULT: PASS)
python3 tools/secret_scan.py
# 1. bump the version
printf 'X.Y.Z\n' > VERSION
# 2. commit and push, then tag (annotated) and push the tag
git tag -a vX.Y.Z -m 'vX.Y.Z "Funny Title"' && git push origin vX.Y.Z
# 3. create the GitHub Release with the same name and notes (via the API; gh isn't required)
```
Never publish notes that fail `release_lint.py`. The release notes follow the house
voice: a one-line gag, a theme sentence, then **What we dragged into the drey**
(bullets) and, when relevant, a **Loose bark** section for behaviour that changed.
(Earlier releases used "The nuts we added" / "Cracked shells"; leave them as they
are.)

`secret_scan.py` checks tracked/untracked files and git history for live key
formats and for the exact values in the private agent/GraphRAG config. It never
prints a secret. A hit in history is still a leak: rotate the key and purge the
history; deleting it from the tip is not enough.
