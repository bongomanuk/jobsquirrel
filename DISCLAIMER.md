# Disclaimer, acceptable use & liability

**This is not legal advice.** If you are doing anything commercial, or you are
unsure how the law applies where you live, talk to a qualified lawyer.

Jobsquirrel is a self-hosted tool that *you* run, on *your own* accounts, for
*your own* job search. You are the operator. This page says what that means.

---

## 1. No warranty

The software is provided **"AS IS", without warranty of any kind**, express or
implied, including but not limited to the warranties of merchantability, fitness
for a particular purpose and non-infringement. See [`LICENSE`](LICENSE)
(Apache-2.0, Sections 7–8) for the full disclaimer of warranty and the
limitation of liability. In short: the authors and contributors are **not liable**
for any claim, damage or loss arising from the software or its use, and you use
it **at your own risk**.

## 2. You are responsible for what it does

The pipeline does mechanical work for you, but **you own the outcome**:

- **Your applications.** You are responsible for every CV, cover letter, form
  answer and submission made with the tool, and for the accuracy of your
  `config/` (your experience, rules and eligibility).
- **Each site's terms.** You are responsible for complying with the **terms of
  service, robots/automation policies and applicable law** of every employer,
  job board and ATS you point it at — including rules on automated access,
  scraping, rate limits and account use.
- **Your accounts and data.** You are responsible for the accounts you connect
  (e.g. email, calendar, LinkedIn) and for the personal data you process.

## 3. Acceptable use

**Intended use:** running your *own* genuine job search — discovering real roles
you can do, tailoring truthful documents, and applying where you are eligible.

**Do not use it to:**

- **Remove or bypass the human-in-the-loop safeguards** — the email-approval
  step, the document/alignment gates, or the stop-on-CAPTCHA/2FA behaviour.
  Those exist for a reason; disabling them is misuse.
- **Evade anti-bot, CAPTCHA or rate-limit protections**, or access a site in
  violation of its terms.
- **Spam or mass-apply indiscriminately**, or apply where you are not eligible
  or not authorised to work.
- **Misrepresent** your experience, identity or qualifications (the tool is
  built not to fabricate; deliberately feeding it false data is on you).
- **Process other people's personal data** without a lawful basis and their
  consent.

The authors and contributors are **not responsible for misuse** and do not
endorse uses outside the intended one.

**Some sites forbid automation outright.** LinkedIn, in particular, prohibits
automated access and activity in its User Agreement. Driving Easy Apply with a
browser bot — however paced — **may breach those terms and can get your account
restricted or banned**. That capability is **opt-in and off unless you enable
it**, and the decision and the risk are yours. Wherever an employer runs its own
ATS, apply there instead.

## 4. Third-party services

Job boards, ATS platforms, email and calendar providers, and model providers are
third parties. They can change their interfaces, **block, throttle or ban**
automation, or fail. The tool does not and cannot guarantee that any submission
will succeed, that any site will accept automated access, or that any
application will produce an interview or an offer. You assume those risks.

## 5. Privacy

By default your data stays on your machine: your CV, rules, applications, logs
and knowledge base are git-ignored and stored locally. The exception is the
**model provider** you run the agent with — the content the agent sends to it is
governed by that provider's terms. If you deploy the tool for other people, you
become the data controller for their data and take on the related obligations
(e.g. under the GDPR).

## 6. No legal advice

This page is a plain-language statement of intent and risk allocation, **not
legal advice**, and it is not a substitute for a licence, terms of service or
contract reviewed by a lawyer for your situation. The authoritative terms for the
software are in [`LICENSE`](LICENSE) (Apache License 2.0).
