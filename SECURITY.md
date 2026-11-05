# Security

Jobsquirrel runs on your machine and handles personal data (your CV, your
applications, your inbox). Please **do not open a public issue** for a
vulnerability.

## Reporting

- Use **GitHub Security Advisories** → **Report a vulnerability** on this
  repository (private, visible to the maintainers).
- Include the version (`VERSION`), your OS, the steps to reproduce and the
  impact.
- Never include your CV, `config/`, tokens, application data or a real
  recruiter's details. A minimal reproduction is enough.
- We aim to acknowledge within 7 days and to ship a fix or a mitigation as soon
  as practical.

## Scope

In scope: the pipeline tools, the dashboard, the browser automation, the
encrypted secret store, the document gates and the scam detector.

Out of scope: third-party applicant-tracking sites, Gmail/Google APIs, the model
provider, and anything that requires a compromised machine or account.

## Good practice for operators

- Keep `config/`, `state/`, `documents/` and `kb/` out of version control.
- Keep secrets in the encrypted store, never in a tracked `.env` or a prompt.
- Run the dashboard on `127.0.0.1`; it is not designed to be exposed.
- Treat a HIGH scam signal as a wall, not a suggestion. See
  [docs/SCAMS.md](docs/SCAMS.md).
