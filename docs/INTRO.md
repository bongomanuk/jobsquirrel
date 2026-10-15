# What this is (agent: read this to the user at the start)

*Deliver this to the user when the pipeline is first set up, in your own words —
concise, plain, no jargon. Then ask if they want to proceed with setup.*

---

**In one line:** this is an agent that runs your job search for you — it finds
roles, writes a tailored CV and cover letter for each one, makes sure every claim
is true, applies for you through the employer's own website, and tracks the
replies. You give it your CV and a few rules; it does the repetitive work.

**How it works, end to end** — for each role, in order:

1. **Find** — it watches your inbox (LinkedIn job alerts and recruiter mail) and
   can search job boards, then feeds matching roles into a work queue.
2. **Check eligibility** — it only applies where the role fits your rules (where
   you can work, work authorisation, languages, and the tech you actually use).
   Anything else is recorded as closed, not applied to.
3. **Ground every claim** — it builds a private **knowledge base** from your own
   documents (old CVs, project notes, a "brag" doc) and, for each role, pulls out
   the most relevant, *cited* facts. The documents are written only from those
   facts, so nothing is invented.
4. **Tailor** — it picks the CV family that matches the role, then writes a CV and
   a cover letter targeted at that specific job, in your voice.
5. **Gate** — before anything is sent, it checks the documents: real identity, no
   placeholders, no AI-slop, only supported claims, the right engagement (a
   contract rate only in contract applications), and good keyword coverage
   against the ad. **Nothing is submitted unless it passes.**
6. **Apply** — a stealth browser fills in and submits the employer's own
   application (Teamtailor, Greenhouse, Lever, Ashby, Workday, …), answering
   questions honestly from your rules.
7. **Record** — it stores exactly what was sent (the files, their hashes and a
   snapshot) and updates a single register: one row per company + role.
8. **Track replies** — it reads your inbox to mark interviews, rejections and
   confirmations, and surfaces any email-verification links for you to click.

**The two things it will never do wrong on purpose:** it never fabricates, and it
never sends a document that fails the gate. If a job wants something your CV
can't evidence, it leaves it out.

**Be clear about the boundaries:** this is **not** a fully-automatic bot. It
follows a written set of instructions (and works best with a capable model), and
it needs you for the calls only you can make — your rules, approving any email
before it goes, and solving a CAPTCHA/2FA when a site demands it. Think "a
tireless assistant working under your instructions", not "press go and forget it".

**Ways you can run it** (I'll explain and you choose):

- **Discover** — just find new roles and add them to the queue.
- **Review / Prepare** — build the tailored CVs and letters and let **you review
  them before anything is sent**. Nothing goes out.
- **Apply** — full auto: build the documents, gate them, and submit. (This is the
  default; it applies to the most senior roles first.)
- **Apply with a fixed CV** — use one CV for everything (fast, less tailored).
- **One role at a time** — for a single job or a retry.

**What I'll need from you:**

- Some details about you, your rules, and the claims you must never overstate
  (I'll interview you — you won't fill in forms).
- Your CV and any documents you want the knowledge base to learn from.
- Optional: access so I can track replies — read-only Gmail, and (for LinkedIn
  Easy Apply) a one-time login. I'll walk you through both.
- A few human-only moments as they come up: solving a CAPTCHA/2FA, and approving
  any email before it's sent.

**Your privacy and control:**

- Gmail is **read-only** by default (single scope); the pipeline can't send,
  change or delete your mail. Sending is a separate tool that needs your explicit
  approval of the recipient, subject and content, every time. Deleting mail is a
  gated tool that needs explicit per-use authorisation — you'll likely never use it.
- Secrets and tokens live **outside** the project folder; your CV, rules and
  applications stay git-ignored.
- Everything is recorded, so you can always see what was sent to whom, and when.

**What happens next:** I'll install what I need, interview you, write your
configuration, build your CV templates, build the knowledge base, and set up your
accounts — then show you the run modes and start finding roles.

Shall we begin?
