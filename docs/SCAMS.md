<div align="center">

# The scam detector

**A warning system, not a verdict.**

[The hard rule](#the-hard-rule) · [Threat model](#threat-model) · [Signals](#signals) · [Email checks](#email-checks) · [Where it runs](#where-it-runs) · [The bucket](#the-probably-scams-bucket) · [Overrides](#overrides-and-clearing) · [Limits](#limits-and-false-positives) · [Extending](#extending-the-rules) · [Tests](#tests)

</div>

Job hunting attracts fraud. The patterns are not subtle once you know them, and
they all end the same way: you install something, pay something, or hand over
identity, bank or crypto credentials.

`tools/scam_check.py` is the single rule set. It runs on every saved advert and
every scanned message, and it feeds the dashboard's **Probably scams** bucket.
It never submits, never clicks and never downloads anything.

## The hard rule

> **Never download or install software, join a chat-only interview, share a
> wallet, seed phrase or private key, pay a fee, or move money during a
> recruitment process.** A real employer interviews over its own video link and
> never needs remote-access tools.

"Install AnyDesk so we can help you with the interview" is how a remote-access
session is used to drain a crypto wallet or a bank account. "Install our trading
app" and "share your seed phrase" are the same scam with a different wrapper.

## Threat model

| The scam | What the attacker wants | What it looks like |
|---|---|---|
| Remote-access interview | Control of your machine and browser session | "Install AnyDesk/TeamViewer/RustDesk before the call" |
| Crypto drain | Your wallet, seed phrase or private key | "Install Trust Wallet", "validate your wallet", "claim your signing bonus" |
| Advance fee | A payment from you | Training, certification, equipment, onboarding, visa or a background-check fee |
| Equipment cheque | Your bank account and a reversed cheque | "We'll send a cheque; buy the kit and send the balance back" |
| Money mule | Your bank account as a laundering hop | "Receive payments and forward them", "keep a commission" |
| Reshipping | Your address to receive stolen goods | "Receive packages, repackage and forward them" |
| Task scam | Your own money or crypto, "unlocked" by fake earnings | "Complete tasks", "deposit to unlock more work" |
| Crypto salary | A crypto payment rail and your wallet | "Salary paid in USDT", "deposit crypto to start" |
| Labour trafficking | Your passport and your freedom | A job abroad, travel/visa fees, "we hold your passport" |
| Recovery scam | A second fee from an earlier victim | "We can recover your lost crypto for a fee" |
| Chat-only interview | Untraceable contact | The whole process runs on Telegram/WhatsApp/Signal |
| Credential phishing | Your email or ATS login | A lookalike domain, a shortened or IP link, an unexpected login page |

## Signals

Each signal has a stable `key` (shown in the scan JSON and the dashboard), a
level, and an action. The patterns are deliberately specific: "crypto" and
"download" are ordinary words in a security or engineering advert, so they only
count in a scam context.

### HIGH: a wall

| `key` | What it catches | Do |
|---|---|---|
| `remote-access-software` | Download/install AnyDesk, TeamViewer, UltraViewer, RustDesk, Quick Assist or a remote desktop, especially "before the interview" | Never install it. Decline and report. |
| `crypto-wallet` | Seed phrase, recovery phrase, private key, MetaMask, Trust Wallet, USDT, "install our trading app" | Never share a wallet or seed phrase. |
| `pay-to-work` | A fee for training, certification, a background check, equipment, onboarding, registration, a visa or a uniform; gift cards; wire transfer | Do not pay or transfer. |
| `fake-check` | "We'll send you a cheque", "cash the cheque", "buy equipment and we reimburse you" | Never cash or forward money. |
| `chat-only-interview` | An interview or hiring process on Telegram, WhatsApp, Signal, Google Hangouts or "text only" | Ask for a video call on the company's platform. |
| `no-experience-high-pay` | "No experience needed, earn €300/day", data entry, package forwarding/reshipping | Treat it as a scam until verified. |
| `task-scam` | "Complete tasks/ratings/reviews", "deposit your own money or crypto to unlock more work" | Never deposit your own money or crypto to get paid. |
| `money-mule` | "Receive payments into your bank account and forward them", "keep a commission", laundering | Never move money through your account for an employer. |
| `reshipping` | "Receive packages at home, repackage and forward them" | Do not receive or forward parcels for an employer. |
| `crypto-salary` | "Salary paid in USDT/bitcoin", "deposit crypto to start" | Never send crypto to an employer or accept a crypto-only salary. |
| `trafficking-risk` | A job abroad with travel/visa fees up front, or "we hold your passport" | Never surrender your passport or pay travel costs up front. |
| `recovery-scam` | "We can recover your lost funds/crypto for a fee" | Do not pay a recovery agent; report to the police. |
| `software-download-link` | A link to an installer or a remote-access tool | Never download it. |
| `ip-address-link` | A raw IP host instead of a company domain | Do not open it. |
| `wallet-link` | A connect/claim/airdrop/mint link that mentions a wallet, crypto, web3 or NFT | Never connect a wallet for a job. |
| `file-host-download` | A file host (Mega, Drive, Dropbox, WeTransfer…) carrying an executable or archive | Do not download it. |
| `dangerous-attachment` | An `.exe`, `.scr`, `.msi`, `.dmg`, `.pkg`, `.bat`, `.cmd`, `.ps1`, `.vbs`, `.js`, `.hta`, `.lnk`, `.iso`, `.jar`, `.apk` or a remote-access tool | Do not open it. |

### MEDIUM: verify before you reply

| `key` | What it catches | Do |
|---|---|---|
| `lookalike-domain` | A sender domain that looks like the company's but is not (`acme-careers.com` vs `acme.com`) | Check the real domain and the recruiter on the employer's site. |
| `free-mail-sender` | A recruiter writing from Gmail/Outlook/Yahoo/Proton | Verify the person through the company. |
| `reply-to-mismatch` | Replies go to a different, unverified address than the sender | Reply only to an address you can verify. |
| `bank-or-id-early` | A request to send a bank account, IBAN, sort code, SSN/NINO, passport or licence before a signed offer | Do not send ID or bank details early. |
| `punycode-link` | A host that starts `xn--` and can imitate a real domain | Check the spelling before opening anything. |
| `archive-attachment` | A `.zip`, `.rar`, `.7z` and similar archives that can hide an installer | Do not open it unless you can verify the sender and the contents. |
| `no-interview-hire` | "Hired immediately, no interview/references required" | Ask for a real interview and a named hiring manager. |

### LOW: a note, never a gate

| `key` | What it catches |
|---|---|
| `urgency` | "Urgent", "immediate start", "reply within 24 hours", "limited positions" |
| `shortened-link` | A `bit.ly`/`tinyurl`/`t.co` link that hides its destination |
| `sender-domain-mismatch` | A completely different domain (often a legitimate agency or job board) |
| `engagement-bait` | "Reply YES/INTERESTED": an engagement hook used by fake-recruiter texts |

## Known scam families

The signals map to the families the FTC, FBI IC3, Europol and national fraud
agencies describe:

| Family | Signals |
|---|---|
| Fake check / overpayment | `fake-check`, `pay-to-work` |
| Advance fee (training, kit, certification, admin) | `pay-to-work` (starter kit, placement/finder's fee) |
| Task / "optimization" scam | `task-scam`, `crypto-salary`, `no-experience-high-pay` |
| Crypto job scam | `crypto-wallet`, `crypto-salary`, `wallet-link` |
| Money mule | `money-mule`, `reshipping`, `bank-or-id-early` |
| Reshipping | `reshipping`, `no-experience-high-pay` |
| Remote-access interview | `remote-access-software`, `software-download-link`, `dangerous-attachment` |
| Chat-only / messaging-app interview | `chat-only-interview`, `engagement-bait` |
| Fake recruiter / impersonation | `free-mail-sender`, `lookalike-domain`, `reply-to-mismatch`, `punycode-link` |
| Identity theft before interview | `bank-or-id-early` |
| Labour trafficking abroad | `trafficking-risk`, `no-experience-high-pay` |
| Recovery scam | `recovery-scam`, `pay-to-work` |
| Credential phishing | `ip-address-link`, `shortened-link`, `punycode-link`, `lookalike-domain` |

### Research and sources

- **FTC**: *Job Scams*, *That job offer text is probably a scam*, *Job
  scammers are looking to hire you*, *Can you unbox the signs of a reshipping
  scam?* (`consumer.ftc.gov`).
- **FBI IC3**: *Scammers Defraud Individuals via Work-From-Home Scams*,
  *Cryptocurrency Job Scams*, *False Job Advertisements Linked to Labor
  Trafficking at Scam Compounds*, and the 2025 IC3 report on AI/deepfake
  employment scams (`ic3.gov`, `fbi.gov`).
- **Europol**: *How to spot fake job adverts*, *Crackdown on money mule service
  providers*, and the crypto-investment-fraud guidance (`europol.europa.eu`).
- **Scamwatch (Australia)**: *Jobs and employment scams* (`scamwatch.gov.au`).
- **NAB / ANZ**: employment-scam red flags and money-mule guidance.

These sources describe the patterns; the scanner is a local heuristic layer, not
a substitute for verifying the employer. It cannot detect a deepfake interview,
a hijacked real advert, or a fake domain when there is no known company domain
to compare against: those need the human checks below.

## Email checks

The mail scan looks at more than the body:

- **From domain vs the apply domain.** A lookalike is MEDIUM; a completely
  different domain is only a LOW note because agencies and job boards write from
  their own domains. Known ATS and job-board domains are never flagged.
- **Reply-To.** A reply address that differs from the sender and is a free
  mailbox, an IP host or punycode is MEDIUM.
- **Links.** Installers, raw IP hosts, punycode hosts, wallet-connect/claim URLs
  and file hosts carrying an executable or archive.
- **Attachments.** Executables, installers, scripts and remote-access tools are
  HIGH; compressed archives are MEDIUM.
- **Body and subject.** The signals in the table above.

## Where it runs

| Step | Tool | Result |
|---|---|---|
| Job-ad ingest | `jd_guard.py`, `discover.py --fetch-jd` | `state/scam/<key>.json` |
| Document preparation | `prepare_role.py` | **Refuses a HIGH signal** (`PREP FAIL`, exit 3) |
| Mail sync | `gmail_readonly.py --sync` | Prints `SCAM <LEVEL>` per message |
| Mail reconcile | `gmail_reconcile.py` | Prints a **scam warnings** section, adds `scam` to the review item, and writes the worst warning per role to `state/scam-emails.json` |
| Dashboard | `dashboard.py`, `tools/web/app.js` | scam marker on the grid, a red/amber banner in the drawer and the Gmail review, and the **Probably scams** bucket |

The dashboard reads the advert scan and `state/scam-emails.json` and keeps the
**worst** level per role, so the grid, the drawer and the bucket agree.

## The Probably scams bucket

The bucket is deliberately conservative. A role enters it when:

- the advert or a message has a **HIGH** signal;
- or a **specific MEDIUM** signal: `lookalike-domain`, `reply-to-mismatch`,
  `punycode-link` or `archive-attachment`;
- or **two independent MEDIUM** signals.

A single free mailbox, a generic domain mismatch or an agency's own domain is
only a note, not a bucket entry. That is intentional: agencies and ATS footers
would otherwise fill the bucket and hide the real risk.

The bucket sits beside **Active / Focus / Needs you**, and the **SCAMS** node in
the Application states graph jumps straight to it.

## Overrides and clearing

- **Preparation override:** `prepare_role.py --allow-scam` continues despite a
  HIGH signal. Use it only after verifying the employer yourself; the scan file
  stays on the record.
- **Clear a warning:** the role drawer has **Clear scam warning** (with a
  confirmation). It removes the advert scan and the role's entry in
  `state/scam-emails.json`. Only use it after verifying the employer.
- **Do not delete a warning to make a role look clean.** The warning is the
  point.

## Limits and false positives

- The scanner is a **warning system, not a verdict**. A small employer can write
  from a Gmail address; a security advert can say "cryptography"; a legitimate
  ATS footer can contain a shortened link. These are notes, not gates.
- A legitimate advert's own anti-fraud notice ("scammers may ask for payment for
  equipment") is recognised and skipped.
- Email matching still decides which role a message belongs to. A marketing mail
  that matches a role can raise a warning there; verify before acting.
- A HIGH signal is a gate because the cost of being wrong is asymmetric: one
  remote-access session can empty a wallet.

## Extending the rules

Signals live in `SIGNALS` in `tools/scam_check.py`:

```python
{
    "key": "remote-access-software",
    "level": "high",
    "re": r"...",
    "why": "why this is a scam pattern",
    "advice": "what the human should do",
}
```

Add a specific regex, a level and the advice. Add a test in
`tests/test_scam_check.py` for a positive and a negative case, and keep the
patterns tight: a single ordinary word is not a signal.

## Tests

```bash
python3 tools/scam_check.py --jd state/job-descriptions/<key>.md
python3 tools/scam_check.py --text "Download AnyDesk before the interview" --json
python3 -m pytest -q tests/test_scam_check.py
```

The suite covers the high signals, the email/domain/link/attachment checks, the
lookalike and real-domain cases, and the advert's own anti-fraud notice.
