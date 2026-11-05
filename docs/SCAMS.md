# Recruitment scams: gates and warnings

Job hunting attracts fraud. The common patterns are not subtle once you know
them, and they all end the same way: you install something, pay something, or
hand over identity, bank or crypto credentials.

## The hard rule

> **Never download or install software, join a chat-only interview, share a
> wallet, seed phrase or private key, pay a fee, or move money during a
> recruitment process.** A real employer interviews over its own video link and
> never needs remote-access tools.

This is not caution for its own sake. "Install AnyDesk so we can help you with
the interview" is how a remote-access session is used to drain a crypto wallet
or a bank account. "Install our trading app" and "share your seed phrase" are
the same scam with a different wrapper.

## Known patterns

| Signal | What it looks like | Level |
|---|---|---|
| Remote-access software | "Download/install AnyDesk, TeamViewer, UltraViewer, RustDesk or Quick Assist before the interview" | **HIGH** |
| Crypto wallet / seed phrase | "Install Trust Wallet", "share your seed phrase / private key", "USDT", "trading app" | **HIGH** |
| Pay to work | A fee for training, certification, a background check, equipment, onboarding, a visa or a uniform | **HIGH** |
| Equipment cheque | "We'll send you a cheque to buy equipment; cash it and send the balance back" | **HIGH** |
| Chat-only interview | The whole process runs on Telegram, WhatsApp, Signal or "text only" | **HIGH** |
| Too good to be true | "No experience needed, earn €300/day", "data entry", "package forwarding/reshipping" | **HIGH** |
| ID or bank details early | Passport/ID copy, SSN/NINO, bank account, IBAN or sort code before a signed offer | MEDIUM |
| Pressure | "Urgent", "immediate start", "reply within 24 hours", "limited positions" | MEDIUM |
| Unverified employer | "Our client", "a leading company", an undisclosed employer | MEDIUM |
| Free mailbox | The recruiter writes from Gmail/Outlook/Yahoo/Proton, not the company domain | MEDIUM |

## How the pipeline checks

`tools/scam_check.py` is the single rule set. It is deliberately specific:
"crypto" and "download" are ordinary words in a security or engineering advert,
so they only count in a scam context.

- **Job-ad ingest** (`jd_guard.py` and `discover.py --fetch-jd`) scans every
  saved advert and writes `state/scam/<key>.json`.
- **Document preparation** (`prepare_role.py`) scans the advert first and
  **refuses to prepare a role that trips a HIGH signal** (`PREP FAIL`, exit 3).
  Re-run with `--allow-scam` only after you have verified the employer yourself.
- **Mail** (`gmail_readonly.py --sync`, `gmail_reconcile.py`) scans every message
  body and sender, prints a **scam warnings** section, and attaches the warning
  to the human review item.
- **Dashboard**: a ⚠ marker on the grid row, and a red/amber banner in the role
  drawer and the Gmail review with the signals, the advice and the hard rule.

The scanner is a **warning system, not a verdict**: a legitimate small employer
can write from a Gmail address, and a security advert can say "cryptography". A
HIGH signal is a gate because the cost of being wrong is asymmetric — one
remote-access session can empty a wallet.

## What the agent must do

1. Treat a HIGH signal as a wall: record the role `BLOCKED` (or `MANUAL`) with
   the signal and stop. Do not prepare documents, do not submit, do not open a
   remote session.
2. Never download or install software for an interview, never join a chat-only
   interview, never share a wallet/seed phrase/private key, never pay a fee and
   never move money.
3. Surface the warning to the human with the exact signal and the source.
4. If the human verifies the employer and wants to proceed, they can re-run
   `prepare_role.py --allow-scam`; the warning stays on the record.

## What you should do

- Verify the employer independently: the company's own domain, a named person,
  and a video call on the company's platform.
- Use a separate browser profile and never a remote-access tool.
- Never share a wallet, seed phrase, private key, bank credentials or a
  one-time code.
- Report the message to the platform and, where relevant, the national fraud
  authority.

## False positives

The scan is configurable only through its rule set. If a legitimate advert
trips a pattern, note it on the role and use `--allow-scam` for preparation; the
scan file stays so the warning is still visible. Do not delete the warning to
make a role look clean.
