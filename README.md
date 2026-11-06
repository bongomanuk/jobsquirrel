<div align="center">

<img src="docs/assets/animals/rowan-red-squirrel.jpg" alt="Rowan Ash, a red squirrel in a tweed waistcoat" width="150">

# Jobsquirrel

**An open, self-hosted job-application agent. Give it your CV. It finds roles, tailors each application, gates every claim, applies through the employer's own site, and tracks the replies.**

[![version](https://img.shields.io/github/v/release/bongomanuk/jobsquirrel?style=flat-square&label=version)](https://github.com/bongomanuk/jobsquirrel/releases)
[![license](https://img.shields.io/badge/license-Apache--2.0-blue?style=flat-square)](LICENSE)
[![CI](https://github.com/bongomanuk/jobsquirrel/actions/workflows/ci.yml/badge.svg)](https://github.com/bongomanuk/jobsquirrel/actions/workflows/ci.yml)
[![python](https://img.shields.io/badge/python-3.11%2B-3776ab?style=flat-square)](docs/SETUP.md)
[![docs](https://img.shields.io/badge/docs-online-2f6f4e?style=flat-square)](https://bongomanuk.github.io/jobsquirrel/)

*Local-first. Truthful by construction. Yours to audit.*

[Quick start](#quick-start) · [Screenshots](#screenshots) · [Documentation](https://bongomanuk.github.io/jobsquirrel/) · [Scam detector](docs/SCAMS.md)

</div>

## What it does

- **Find** roles from job alerts, recruiter mail and the open web.
- **Tailor** a CV and cover letter for each role, grounded in your own evidence.
- **Gate** every document for accuracy, ATS fit and AI slop before anything is sent.
- **Apply** through the employer's own ATS with a real browser, not a form-spam script.
- **Track** replies, interviews and outcomes in one register.
- **Warn** on recruitment scams before you engage.

It runs on your machine. Your CV, your inbox and your job search stay yours. The
project says CV; if you are in the US, read it as resume.

## Screenshots

The screenshots use synthetic demo data: a sample candidate and fictional
companies.

| The grid: every role, its stage and its fit | Role detail: status, gates and next action |
|---|---|
| ![Application grid](docs/screenshots/grid.png) | ![Role detail drawer](docs/screenshots/drawer.png) |

| The knowledge universe: a central career hub and theme islands | Settings and health: version, checks and this instance |
|---|---|
| ![The knowledge universe](docs/screenshots/graph-universe.png) | ![Settings and health](docs/screenshots/settings.png) |

More views and a full walkthrough are in the
**[documentation](https://bongomanuk.github.io/jobsquirrel/)**.

## Quick start

Start your agent and paste this:

```text
Clone https://github.com/bongomanuk/jobsquirrel.git into ./jobsquirrel and set it up with me: read AGENTS.md, then read docs/INTRO.md to me and run the first-run bootstrap in BOOTSTRAP.md.
```

The agent installs the dependencies, interviews you about your identity,
eligibility and the claims you must never overstate, builds your CV archetypes
and a private knowledge graph, and sets up your accounts.

Already cloned? Run `opencode` and say:

> Read AGENTS.md, introduce the project, and run the bootstrap.

Works with opencode, Claude Code, Cursor or any file-and-shell agent. Use a
hosted model or a local one. See [Agent setup](docs/AGENT-SETUP.md).

> **Not push-button autonomy.** The agent does the mechanical work. You own the
> rules, the approvals and the judgement calls. Review the first applications.

## Built to be trusted

- **No invented claims.** Every generated line is grounded in your CV, your
  profile or the knowledge graph.
- **Hard gates.** Alignment, evidence, ATS coverage, identity and AI-slop checks
  must pass before upload.
- **Human approval.** Email and calendar writes need your explicit approval.
- **Local-first.** The dashboard, register, documents, browser and graph run on
  your machine.
- **Scam-aware.** Remote-access interviews, wallet drains, pay-to-work and
  equipment cheques are flagged before you engage.
- **Open source.** Apache 2.0. Inspect it, adapt it, run it.

You are responsible for what it sends. Keep your config accurate, review the
gates, and read [DISCLAIMER.md](DISCLAIMER.md).

## Documentation

- [Introduction](docs/INTRO.md)
- [Setup](docs/SETUP.md)
- [Agent setup](docs/AGENT-SETUP.md)
- [Using it](docs/USING-IT.md)
- [Run modes](docs/RUN-MODES.md)
- [Knowledge graph](docs/KNOWLEDGE-GRAPH.md)
- [Scam detector](docs/SCAMS.md)
- [All documentation](https://bongomanuk.github.io/jobsquirrel/)

---

<div align="center" markdown>

**If it helps, give it a star.** It helps other people find it.

Built by [Peter Hollas](https://hollas.net) · [hollas.net](https://hollas.net)

Apache License 2.0 · [LICENSE](LICENSE)

</div>
