# Eligibility and accuracy rules

The pipeline refuses to apply to roles that don't match your rules — that is a
feature, not a limitation. You define the rules in the **Eligibility** and
**Accuracy** sections of `config/profile.md`. The runner reads them at the start
of every application and records ineligible roles as `CLOSED`/`BLOCKED` with a
reason instead of applying.

## 1. Location and work model

Say where you are and what you will accept. Example:

```
## Eligibility
- based in: Berlin, Germany
- accept: on-site/hybrid in Berlin; fully remote open to Germany and the EU;
  relocation-supported roles in Switzerland
- exclude: on-site roles in other countries; roles requiring fluent <languages
  you don't speak>; roles needing local work authorisation you lack
- if the location or work model is unclear: do not apply (record BLOCKED)
```

The runner will: apply only if the role fits the `accept` list; record `CLOSED`
(no letter, no application) for `exclude` matches; and record `BLOCKED
"location unclear"` when it can't tell. Never guess a location to make a role fit.

## 2. Languages

List the languages you speak, with honest levels, and the ones you don't:

```
- languages (and honest level): English - native; German - B1
- languages you do NOT speak (never apply to roles that require these): French, Dutch
```

If a role's ad *requires* fluent proficiency in a language you don't speak, the
gate closes it. If the location is otherwise fine but the language is merely
preferred, the role may still qualify — the runner weighs the wording.

## 3. Stack / technology ("things I don't know")

The pipeline will not apply to a role whose primary language/stack you don't use.
Put the honest list in `config/profile.md` and keep `config/cv.json`'s languages
accurate:

```
## Accuracy rules (never overstate)
- Languages/tech I do NOT use (never apply to a role whose primary stack needs
  one): Go, C, C++, C#/.NET, Kotlin, Swift, Scala, Ruby, PHP, Elixir, ...
- Certifications: list "X (year)" on the certifications list only; never say I
  "hold" or am "certified in" it; keep it out of the summary.
- Management: line management of engineers only (never claim managing managers).
- Never claim experience I do not have.
```

`check_alignment.py` enforces this from the **title and the JD body** (so a
"Golang" in the tech-stack line or "strong Go experience" in the body is caught
even when the title looks generic). Roles that fail are recorded `CLOSED` and
skipped — the pipeline must never send you to an interview for something you
can't do.

## 4. Accuracy rules (never overstate)

These are the claims that must stay true in every generated document:

- **Certifications** — list them on the certifications list; do not assert you
  hold them if you don't, and never say "lapsed".
- **Management scope** — say exactly what you managed (e.g. line management of
  engineers) and nothing more.
- **Facts** — every employer, domain, technology and number must already be in
  `config/cv.json`. `facts.py` fails present-tense claims about past work and
  flags phrases not supported by the CV; `check_documents.py` blocks unsupported
  first-person claims.

Anything you add here is enforced at generation time (via the runner prompt) and
at the pre-submit gate (via `check_documents.py` / `facts.py`).

## 5. Designing your accuracy rules

Keep them short, specific and mechanical so they can be enforced:

- *Do* name the exact false claims to avoid and the correct alternative.
- *Do* state which things go on a list only (certs) vs in prose.
- *Don't* encode things the gate can't check (it can't know a metric is right —
  only whether it's in `cv.json`).

When in doubt, leave the claim out and accept lower ATS coverage; a truthful,
slightly-less-optimised application beats a fabricated one every time.
