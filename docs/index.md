---
description: Jobsquirrel is an open, self-hosted job-application agent: it finds roles, tailors a CV and cover letter per role, gates them for accuracy, applies through the employer's own ATS and tracks replies. Local-first, scam-aware, Apache-2.0.
---

<div class="js-hero">
  <div>
    <h1>🐿️ Jobsquirrel</h1>
    <p><strong>An open, self-hosted job-application agent: hand it your CV (resume) and it finds, tailors, gates and applies to jobs for you.</strong></p>
    <p>Honest, targeted and auditable — with a real knowledge graph, hard gates before anything is sent, and a scam detector that knows the difference between a recruiter and a wallet drain.</p>
    <div class="js-badges">
      <img src="https://img.shields.io/github/v/release/bongomanuk/jobsquirrel?style=flat-square&label=version" alt="version">
      <img src="https://img.shields.io/badge/license-Apache--2.0-blue?style=flat-square" alt="Apache-2.0">
      <img src="https://img.shields.io/badge/python-3.11%2B-3776ab?style=flat-square" alt="Python 3.11+">
      <img src="https://img.shields.io/badge/scam--aware-yes-b91c1c?style=flat-square" alt="scam-aware">
      <img src="https://img.shields.io/github/stars/bongomanuk/jobsquirrel?style=flat-square&label=stars" alt="stars">
      <img src="https://github.com/bongomanuk/jobsquirrel/actions/workflows/ci.yml/badge.svg" alt="CI">
    </div>
    <div class="js-actions">
      <a class="primary" href="SETUP/">Quick start →</a>
      <a href="USING-IT/">How to use it</a>
      <a href="SCAMS/">The scam detector</a>
      <a href="https://github.com/bongomanuk/jobsquirrel">GitHub ↗</a>
    </div>
  </div>
  <img src="assets/animals/sir-reginald-nuttington.jpg" alt="Sir Reginald Nuttington, a red squirrel in a tweed waistcoat">
</div>

## What it does

<div class="js-cards">
  <div class="js-card"><div class="js-ico">🔎</div><h3>Discover</h3><p>Reads LinkedIn job alerts and recruiter mail, dedupes against the register, and queues the roles worth doing.</p></div>
  <div class="js-card"><div class="js-ico">🎯</div><h3>Target</h3><p>A per-role CV and letter, grounded in your private knowledge graph, mirroring the advert without inventing anything.</p></div>
  <div class="js-card"><div class="js-ico">🛡️</div><h3>Gate</h3><p>Alignment, evidence, ATS coverage, identity and no-AI-slop gates. Nothing is uploaded until they pass.</p></div>
  <div class="js-card"><div class="js-ico">🤖</div><h3>Apply</h3><p>Drives the employer's own ATS through a real Camoufox browser, then records the exact files and hashes.</p></div>
  <div class="js-card"><div class="js-ico">📬</div><h3>Track</h3><p>Reconciles Gmail, surfaces interviews and verification links, and keeps one source of truth for every role.</p></div>
  <div class="js-card"><div class="js-ico">🕵️</div><h3>Warn</h3><p>Flags recruitment scams — remote-access interviews, wallet drains, task scams, money mules, reshipping — before you engage.</p></div>
</div>

!!! tip "Everything is local"
    The dashboard, register, documents, browser and knowledge graph run on your
    machine. The only outbound calls are the ones you choose: the employer's site,
    Gmail/Calendar if enabled, and the model provider — **which can be a local
    model too**. Use opencode, Claude Code, Cursor or your own local AI agent.
    [Run it fully local →](AGENT-SETUP/#run-it-fully-local)

## A look at it

<div class="js-shots">
  <div class="js-shot"><img src="screenshots/grid.png" alt="Application grid"><span>The grid — every role, its stage and its fit.</span></div>
  <div class="js-shot"><img src="screenshots/drawer.png" alt="Role detail drawer"><span>The role drawer — stage, gates, evidence, one-click action.</span></div>
  <div class="js-shot"><img src="screenshots/graph-universe.png" alt="Knowledge universe"><span>The knowledge universe — themes as islands, weighted stars.</span></div>
  <div class="js-shot"><img src="screenshots/evidence.png" alt="Evidence overlay"><span>Evidence — every CV line scored against the ad and the graph.</span></div>
</div>

## What the forest says

*Fictional testimonials. No animal was interviewed, employed, or asked to install AnyDesk.*

<div class="js-quotes">
  <div class="js-quote">
    <img src="assets/animals/sir-reginald-nuttington.jpg" alt="Sir Reginald Nuttington">
    <blockquote>“It found me a staff role and three acorns before lunch. The CV was so well targeted I nearly forgot to bury it.”<span class="js-who">Sir Reginald Nuttington — Red Squirrel, Head of Acorn Logistics</span></blockquote>
  </div>
  <div class="js-quote">
    <img src="assets/animals/baroness-bramblewick.jpg" alt="Baroness Bramblewick">
    <blockquote>“The gate caught my CV claiming I could ‘work under pressure’. I am a hedgehog. I roll into a ball.”<span class="js-who">Baroness Bramblewick — Hedgehog, QA Lead (Spine Compliance)</span></blockquote>
  </div>
  <div class="js-quote">
    <img src="assets/animals/professor-aloysius-hoot.jpg" alt="Professor Aloysius Hoot">
    <blockquote>“It refused a role that asked me to install a screen-sharing tool. I have talons. I do not need remote access.”<span class="js-who">Professor Aloysius Hoot — Tawny Owl, Night-Shift Recruiter</span></blockquote>
  </div>
  <div class="js-quote">
    <img src="assets/animals/bartholomew-badger.jpg" alt="Bartholomew Badger">
    <blockquote>“Nine hundred applications, one real role, zero remote-access tools. Very good at tunnels.”<span class="js-who">Bartholomew Badger — Badger, Staff Engineer (Deep Digs)</span></blockquote>
  </div>
</div>

## Start here

- **[Introduction](INTRO.md)** — what it is, how it works end to end, the safety guarantees and the run modes.
- **[Setup](SETUP.md)** — install, dependencies, configuration, Gmail.
- **[Agent setup](AGENT-SETUP.md)** — opencode, Claude Code, Cursor, and **running it fully local**.
- **[Using it](USING-IT.md)** — the daily prompts, monitoring, the state model and the grid.
- **[The scam detector](SCAMS.md)** — the hard rule, every signal, the email checks and the limits.
- **[All documentation](all.md)** — the full index.

---

<div align="center" markdown>

**If it helps, give it a star** ⭐ — it helps other people find it.

[GitHub](https://github.com/bongomanuk/jobsquirrel) · [Releases](https://github.com/bongomanuk/jobsquirrel/releases) · [Report an issue](https://github.com/bongomanuk/jobsquirrel/issues)

</div>
