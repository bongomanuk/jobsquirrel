# Writing the CV: two full pages, no padding

The generated CV has one job: give a recruiter enough true, specific material to
shortlist you in the ten seconds they spend on the first screen. A two-page CV
that stops halfway down page two reads as thin even when the facts underneath
are strong. This document is the content contract; `cv_target.py` prints the
numbers and `check_documents.py` refuses a PDF that fails them.

## The shape

| Thing | Target |
|---|---|
| Pages | exactly 2, both full |
| Last page fill | at least 70% (aim for 85-95%) |
| Experience bullets | 32-38 in total |
| Bullets per role | 6-8 for the two most recent/relevant, 4-6 for the middle, 2-3 for the earliest |
| Profile | 150-180 words |
| Selected work | 5-6 items |
| Skill lines | 7-9 categories |

`cv_target.py` prints `CONTENT` (roles, bullets, words, profile length) and
`FILL` (page count and how far down each page the text reaches). If either is
short, add evidenced detail; never pad.

## The fast, still-grounded path

`prepare_role.py` does the deterministic work once: ATS terms, GraphRAG context
(reused when the JD hash is unchanged), archetype selection + alignment, and a
seed pack copied from the closest existing grounded pack. It writes
`state/briefs/<key>.md` with the full JD, grounded context and paths.

The model then edits only the parts that should change for the role: profile,
tagline, skills, selected work and the role-specific bullet selection/order.
The static roles, dates and evidenced achievements are already in the seed, so
there is no reason to regenerate them. Write the letter prose to
`state/letters/<key>.json`, then run `finalise_docs.py`: it renders the CV with
the fill check, renders the letter, runs the pre-submit gate with `--record`
and (in REVIEW) records PREPARED only on PASS. This cuts the slow model's
output and the number of turns without skipping any grounding rule or gate.


## No targeting tells

- **No job-title line at the top.** The CV opens with the name, contact details and a short
  capability tagline. The profile does the positioning. An 11pt caps line that repeats the
  advert's title is the first thing a recruiter sees, and it reads as "this was written for
  one advert". Leave it out.
- The tagline is a capability line ("Backend engineering · real-time distributed systems"),
  never the job title and never the employer's name.
- The letter names the company and role; the CV does not need to.
- No JD phrasing copied into the profile or a heading. Mirror the language, do not echo it.

## The bullet formula

> **Action + what + how + outcome or scale** (drop the outcome when the evidence
> does not support one).

Weak (thin, no outcome):

> Worked on data pipelines and helped the team deliver projects.

Stronger (still true, more specific):

> Built a real-time, high-volume caller-fraud detection pipeline on ScyllaDB,
> Spring Cloud Data Flow and Prometheus, designed for continuous production load.

Strongest (an outcome the record supports):

> Delivered a multi-tenant AWS SaaS central hub for distributed SMS gateways at
> Google's request, on time and to specification (Keycloak, Spring, Postgres,
> React).

## Splitting compound achievements

Most thin CVs are thin because each bullet crams two or three separate facts into
one line. Split them. This adds length and makes each claim scannable, without
inventing anything:

Before:

> Owned enterprise architecture, strategy, governance and technical direction
> across the division, plus the annual budget, headcount plan and technology
> roadmap.

After (two bullets, same facts):

> Owned enterprise architecture, technology strategy, governance and technical
> direction across the division.
>
> Owned the annual budget, headcount plan and technology roadmap, and translated
> business strategy into a plan the teams delivered against.

Do this with every compound bullet before you consider adding anything new.

## Delivery and team emphasis

Hiring managers are not only buying skills; they are buying someone who gets
things into production and brings people with them. Every role should carry, where
the record supports it:

- **One delivery bullet**: what shipped, for whom, to what deadline, at what
  scale. Use plain verbs: shipped, delivered, launched, rolled out, cut over,
  handed over, ran in production.
- **One team bullet**: who you led or coached, how you set the way of working,
  how you engaged stakeholders to keep the work moving.
- **One operational bullet**, for senior roles: what you owned running, not just
  building (budget, on-call, reliability, audit).

Only write these when the evidence exists. "Delivered on time" is a claim; use it
where the record says so (for example the Google hub at HAUD), not as decoration.

## Honesty rules

- Use only facts in `config/cv.json`, `config/profile.md` and the role's
  `state/kb-context/<key>.md`.
- Never invent a metric, a team size, a deadline, a tool or an outcome.
- Keep the accuracy rules in `config/profile.md`: management scope, titles,
  certifications and employer descriptions are exact.
- If the job asks for something the record does not evidence, leave it out. A
  gap is better than a claim you have to walk back in the interview.
- Product capabilities are not personal achievements; attribute them to the
  product, and keep your own hands-on work distinct.

## Canonical facts

Some facts have one correct wording — an institution's full name, a superlative
claim, a product name. `config/canonical-facts.json` holds the exact replacements
and the forbidden variants. The knowledge-base ingest applies them before
indexing, `cv_target.py` and `render_letter.py` apply them to the content pack
before rendering, and `check_documents.py` fails a document that still contains a
forbidden variant. Add a rule when a fact must not drift; the public template is
`config/canonical-facts.example.json`.

## The loop

1. Write the pack from the KB context, splitting compound bullets and adding the
   delivery/team bullets the evidence supports.
2. Render: `python3 tools/cv_target.py --key <key> --content state/cv-content/<key>.json --require-fill`
3. If `RESULT: FILL FAIL`, go back to the evidence and add detail. Do not pad,
   do not shrink the font, do not widen the margins.
4. The pre-submit gate re-measures the PDF and fails a thin CV, so a thin CV
   cannot be uploaded by accident.

## Why 70% and not 100%

A page that ends at 95-100% looks cramped and risks spilling to a third page
after a small edit. 85-95% is the sweet spot: full, with room to breathe. Below
70%, the white space at the bottom is the first thing a reader notices.
