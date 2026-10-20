# Bootstrap it with your AI agent: and what it costs

This project has no installer wizard and no GUI. You hand the repository to an
AI coding agent, and **the agent sets the whole thing up with you**: it reads you
the introduction, interviews you, writes your `config/`, builds your CV
archetypes, builds your knowledge base, and sets up your accounts, explaining
each step in plain language.

You do **not** need to read the other docs to get started. The agent reads them
for you. This page just tells you how to launch an agent against the repo, how to
keep the running cost low, and how the cost works.

---

## 0. Read this first: it is not push-button autonomy

Be realistic about what this is:

- **It relies on instructions.** The behaviour lives in `AGENTS.md` and
  `BOOTSTRAP.md`. The agent is only as good as (a) the model driving it and (b)
  how accurately you filled in `config/`. A weak model or a sloppy config gives
  weak results.
- **It is not fully autonomous.** The agent does the mechanical work, find,
  tailor, gate, submit, record, reconcile, but **you** make the judgement calls
  and handle the human-only moments: your eligibility/accuracy rules, approving
  any email before it is sent, and solving CAPTCHA/2FA when an employer demands
  it. Some employers genuinely require a person.
- **You supervise the first run.** Treat the first role or two as a supervised
  trial: review the generated CV and letter, and confirm the gates behaved.
- **You are responsible for what it sends.** It is built never to fabricate and
  never to send a document that fails the gate, but you own your applications.

If you want a one-click, unattended "AI applies to 500 jobs" bot: this is not
that, and you should be wary of anything that claims to be.

---

## 1. Run it with opencode (recommended, and the cheapest to run)

[opencode](https://opencode.ai) auto-loads `AGENTS.md`, so it already knows the
procedures before you say anything. **You don't even need to clone the repo**,
the agent can do that too.

```bash
opencode
```

First time only, connect a model provider:

```text
/connect     # choose the OpenCode provider (Zen/Console), paste your API key
/models      # pick a DeepSeek model (see §3)
```

Then paste this single prompt, that is the entire installation:

```text
Clone https://github.com/bongomanuk/jobsquirrel.git into ./jobsquirrel and set it
up with me: read AGENTS.md, read docs/INTRO.md to me, then run the first-run
bootstrap in BOOTSTRAP.md.
```

The agent clones the repo, installs the dependencies, walks you through the
interview, builds your config + archetypes + knowledge base, and sets up your
accounts. Only when `python3 tools/init_config.py --check` is clean does it start
applying.

If you already cloned it, just `cd jobsquirrel`, run `opencode`, and say:
*"Read AGENTS.md, introduce the project, and run the bootstrap."*

You can also pin the model in `opencode.json` (or `opencode.jsonc`) at the repo
root so the agent always starts on a cheap model:

```jsonc
{
  "$schema": "https://opencode.ai/config.json",
  "model": "opencode/deepseek-v4.1-flash"
}
```

---

## 1b. Choose the model (works for every agent)

The **Agent console header** has a model picker (the same idea as opencode's
`/model`), and **Settings → AI & agent** has the same list. The list comes from
the selected CLI (`opencode models`, or Claude Code's aliases), grouped by product
(**Free models**, **OpenCode Zen**, **OpenCode Go**, **Contributor / preview**, or
**Claude Code**); the group is the provider prefix, and free models are pulled out
so they are easy to find. Anything else can be typed in the free-text box.

Both write `~/.config/job-search/agent.json`:

```jsonc
{
  "agent": "",                    // "" = auto-detect (opencode, else claude)
  "model": "opencode/claude-haiku-4-5",
  "models": {                     // remembered choice per agent
    "opencode": "opencode/claude-haiku-4-5",
    "claude": "sonnet"
  },
  "env": { "OPENCODE_API_KEY": "..." }
}
```

- `tools/agent_run.sh` reads this file itself, so the selection applies to **chat,
  role chats, queue/apply runs and every API/CLI-invoked task** that goes through
  the runner.
- Environment overrides win for one run: `MODEL=... AGENT=... bash tools/run_queue.sh`.
- A custom agent command receives the chosen model in `$MODEL` (it decides how to
  pass it on). opencode gets `--model`, Claude Code gets `--model`.
- The **GraphRAG LLM is separate** (`kb/graphrag/.env`, same Settings page): the
  knowledge-graph builder does not use the coding-agent model.

## 2. Run it with Claude Code, Cursor, or any other agent

The contract is `AGENTS.md`. Any agent that can read files and run shell
commands can drive the pipeline.

- **Claude Code**: reads `CLAUDE.md` by convention. Either add a one-liner
  (`ln -s AGENTS.md CLAUDE.md`) or just tell it to read `AGENTS.md`:
  ```bash
  cd jobsquirrel && claude
  # "Read AGENTS.md and BOOTSTRAP.md, then bootstrap this project with me."
  ```
- **Cursor / Windsurf / Zed**: open the repo, then in chat:
  *"Read AGENTS.md, then run the first-run bootstrap in BOOTSTRAP.md."*
- **Aider / Goose / other CLI agents**: start it in the repo directory and give
  the same instruction.
- **Any other model/agent**: the same brief works. What matters is that the
  agent (1) reads `AGENTS.md`, (2) follows `BOOTSTRAP.md` on first run, and
  (3) runs the tools in `tools/` rather than improvising.

> The bootstrap is **agent-driven on purpose**: there is no separate setup
> script to keep in sync. If you read a step in this doc that the agent cannot do
> for you, that is a bug, open an issue.

### Running the queue with Claude Code

The queue runner starts one headless agent per role through
`tools/agent_run.sh`. It uses opencode if that is installed, otherwise Claude
Code; `AGENT=claude` picks Claude Code explicitly:

```bash
AGENT=claude REVIEW=1 PARALLEL=3 bash tools/run_queue.sh    # prepare only
AGENT=claude PARALLEL=3 bash tools/run_queue.sh             # apply
AGENT=claude MODEL=sonnet PARALLEL=3 bash tools/run_queue.sh
```

Sign in to the `claude` CLI first (run `claude` once in a terminal). If it is
signed out, the runner records "agent not signed in" and stops after three
failed tasks; nothing is lost and the roles stay pending.

A headless run cannot stop and ask you to approve a tool, so each task may use
only what the role needs: reading and writing files in the repo, web search and
fetch (to find the employer's own apply page), and the pipeline's Python tools.
Anything else is refused. No MCP servers are loaded, so mail and social tools
you have connected elsewhere are out of reach. This is a guardrail, not a
sandbox: `python3` can still do anything. To change it:

| Env | Effect |
|---|---|
| `CLAUDE_ALLOWED_TOOLS="..."` | replace the allowlist (space-separated rules, e.g. `Read Edit Bash(python3 *)`) |
| `CLAUDE_PERMISSION_MODE=bypassPermissions` | allow every tool (not recommended) |
| `CLAUDE_ARGS="--max-turns 80"` | extra flags for every task, e.g. `--no-session-persistence` to keep the runs out of your session history |

The same mechanism runs any other CLI agent: `AGENT="mycli run"` runs
`mycli run "<prompt>"` for each role. `AGENT` applies to `run_queue.sh`,
`run_linkedin.sh` and `human_assist.sh` alike.

### macOS

Everything runs on macOS as well as Linux. macOS ships without GNU `flock`,
`setsid` and `timeout`, so `tools/compat/` provides portable stand-ins. The
runners append that directory to `PATH` (after the system directories, so a real
command always wins where one exists) and bake the resolved `timeout` path into
each task prompt, so the agent uses the same one. The stand-ins are self-contained
Python and are covered by `tests/test_compat.py`.

---

## 3. Keeping it cheap: opencode + DeepSeek

The only thing that costs money is the **language model tokens**. Everything else
runs locally and free: the browser (Camoufox), the CV/letter rendering
(LibreOffice), and the knowledge base / GraphRAG indexing (local embeddings via
`embeddings.sh`), no API calls for those.

On [opencode](https://opencode.ai) you can run the DeepSeek "Flash" models, which
are among the cheapest capable coding models. DeepSeek **V4.1 Flash** is the
sweet spot for this pipeline; **V4 Flash** is cheaper still; use **V4 Pro** only
if you hit quality walls.

| Model (opencode id)          | Input $/1M | Output $/1M | Cache read $/1M | Typical cost per application |
| ---------------------------- | ---------: | ----------: | --------------: | ---------------------------- |
| `opencode/deepseek-v4-flash` |      $0.14 |       $0.28 |          $0.028 | ~$0.01–0.04                  |
| `opencode/deepseek-v4.1-flash` |    $0.30 |       $1.20 |          $0.006 | ~$0.03–0.10                  |
| `opencode/deepseek-v4-pro`   |      $1.74 |       $3.48 |          $0.145 | ~$0.15–0.60                  |

*(List prices are OpenCode's published rates and change over time; the provider
also offers a free `opencode/deepseek-v4.1-flash-free` variant for a limited
period. Check the console for current prices.)*

**How to keep it cheap**

- **Pick a Flash model.** `opencode/deepseek-v4.1-flash` is the default
  recommendation; drop to `deepseek-v4-flash` for lots of volume.
- **Let caching work.** Inputs are mostly repeated context (system prompt,
  `AGENTS.md`, the growing turn history); cached reads are ~50× cheaper than
  fresh input, so keep long-lived sessions in one thread instead of restarting.
- **Prefer LIGHT / REVIEW modes while tuning.** `REVIEW=1` (build + gate only, no
  submit) and `LIGHT=1 FIXED_CV=…` (one CV, no per-role generation) cost far less
  than full per-role generation.
- **Set a spend limit.** OpenCode Console (pay-as-you-go) lets you cap monthly
  usage and control auto-reload. A $20 balance goes a long way for this pipeline.
- **Don't paste the resume into a paid chat.** Use the tools; they keep context
  small and cached.
- **Batch in one session.** Discovery → queue → apply → reconcile in a single
  agent session shares the cached context.

---

## 4. How much it typically costs to run

Rough, order-of-magnitude figures, **not a quote.** Your real spend depends on
the model, how many turns the browser driving takes, and how many retries happen.

Assumptions for one full **apply** run (one role, end to end):

- ~150k–600k input tokens, **mostly cache reads** (the system prompt + history
  are re-sent each turn);
- ~10k–40k output tokens (the CV content, the letter, browser actions);
- discovery, email reconciliation, and chatting with the agent are separate and
  small.

With those assumptions:

| What                              | DeepSeek V4.1 Flash      |
| --------------------------------- | ------------------------ |
| One application (apply mode)      | ~$0.03–0.10 (≈$0.05 typ.) |
| 50 applications                   | ~$2–5                    |
| 100 applications                  | ~$3–10                   |
| A month of active use + chatting  | ~$5–15 total             |

- **DeepSeek V4 Flash** cuts those roughly in half.
- **DeepSeek V4 Pro** is ~4–6× the price of V4.1 Flash, reserve it for hard
  cases.
- **Review/Prepare mode** (no browser, no submit) is the cheapest useful run.
- If you run a lot, a flat monthly subscription (OpenCode **Go**, $10/month)
  can be cheaper than pay-as-you-go, see the OpenCode console.

The honest summary: for a normal job search this costs **single-digit dollars a
month** on a Flash model. The expensive failure modes are a bad model looping on
the browser and unbounded retries, so set a spend cap.

---

## 5. What the agent will ask you (so you're ready)

On the first run the agent interviews you. Have these to hand:

- Your CV (a file) and any "brag"/project documents you want the knowledge base
  to learn from.
- Where you can work and what you'll accept (locations, remote/hybrid/on-site,
  work authorisation, languages, contract vs permanent).
- Availability and pay expectations.
- The **accuracy rules**: claims you must never overstate (titles, scope,
  certifications, metrics).
- Optional: read-only Gmail and a one-time LinkedIn login for reply tracking and
  Easy Apply.

Then it builds everything and shows you the run modes (**Discover / Review /
Apply / fixed-CV**) so you can choose.
