#!/usr/bin/env python3
"""One plain-English style rule, shared by every tool that writes text.

The pipeline writes CVs, letters, emails, register notes and briefs. All of it
must read like a person wrote it: no em dashes, no AI-slop vocabulary, no
stock phrases. This module is the single definition of "slop" so the gate, the
draft saver and the CLI cannot drift apart.

Checked (hard errors):
  * em dash (U+2014) anywhere, and " -- " used as a dash
  * banned slop vocabulary ("leverage", "delve", "robust", ...)
  * empty phrases ("it's worth noting", "when it comes to", ...)
  * binary contrasts ("not just X but Y", "isn't X, it's Y")
  * throat-clearing openers ("here's the thing", "let me be clear", ...)
  * faux-insight setups ("what most people miss", ...)
  * importance puffery ("a testament to", "pivotal moment", ...)
  * weasel attribution ("studies show", "experts agree", ...)
  * trailing -ing commentary (", highlighting the team's ...")

Usage:
  python3 tools/writing_style.py --check FILE [FILE ...]
  printf 'text' | python3 tools/writing_style.py --stdin
  python3 tools/writing_style.py --check --dir state/drafts
"""
from __future__ import annotations

import argparse
import os
import re
import sys

# (regex, human label). Word boundaries are explicit so stems catch inflections
# without matching inside other words (e.g. "realm" not "realms of" is covered,
# but "realtor" is not).
BANNED = [
    (r"\bdelv(?:e|es|ed|ing)\b", "delve"),
    (r"\bfoster(?:s|ed|ing)?\b", "foster"),
    (r"\bleverag(?:e|es|ed|ing)\b", "leverage"),
    (r"\butili[sz](?:e|es|ed|ing)\b", "utilize/utilise"),
    (r"\bfacilitat(?:e|es|ed|ing)\b", "facilitate"),
    (r"\bempower(?:s|ed|ing|ment)?\b", "empower"),
    (r"\bstreamlin(?:e|es|ed|ing)\b", "streamline"),
    (r"\brobust(?:ly|ness)?\b", "robust"),
    (r"\bcutting[- ]edge\b", "cutting-edge"),
    (r"\bparadigm shift\b", "paradigm shift"),
    (r"\bgame[- ]chang(?:er|ers|ing)\b", "game changer"),
    (r"\bthis is huge\b", "this is huge"),
    (r"\bthis changes everything\b", "this changes everything"),
    (r"\btapestry\b", "tapestry"),
    (r"\brealm\b", "realm"),
    (r"\bbeacon\b", "beacon"),
    (r"\bmulti-?faceted\b", "multifaceted"),
    (r"\bmeticulous(?:ly)?\b", "meticulous"),
    (r"\bintricate\b", "intricate"),
    (r"\bparamount\b", "paramount"),
    (r"\btransformative\b", "transformative"),
    (r"\belevat(?:e|es|ed|ing)\b", "elevate"),
    (r"\bembark(?:s|ed|ing)?\b", "embark"),
    (r"\bsupercharg(?:e|es|ed|ing)\b", "supercharge"),
    (r"\bever[- ]evolving\b", "ever-evolving"),
    (r"\bseamless(?:ly)?\b", "seamless"),
    (r"\bunlock(?:s|ed|ing)?\b", "unlock"),
    (r"\bgame plan\b", "game plan"),
    (r"\bholistic(?:ally)?\b", "holistic"),
    (r"\bsynerg(?:y|ies|istic)\b", "synergy"),
    (r"\bbest[- ]in[- ]class\b", "best-in-class"),
    (r"\bworld[- ]class\b", "world-class"),
    (r"\bstate[- ]of[- ]the[- ]art\b", "state-of-the-art"),
    (r"\bnext[- ]generation\b", "next-generation"),
    (r"\bmission[- ]critical\b", "mission-critical"),
    (r"\bpassionate about\b", "passionate about"),
    (r"\bdeep dive\b", "deep dive"),
    (r"\bdive into\b", "dive into"),
    (r"\bjourney\b", "journey"),
    (r"\blandscape\b", "landscape"),
    (r"\bdynamic(?:ally)?\b", "dynamic"),
    (r"\binnovat(?:e|es|ed|ing|ive)\b", "innovative"),
    (r"\brevolutioni[sz](?:e|es|ed|ing)\b", "revolutionize"),
]

EMPTY_PHRASES = [
    "it's worth noting", "it is worth noting", "it's important to note",
    "it is important to note", "at the end of the day", "when it comes to",
    "at its core", "in today's world", "in today's fast-paced",
    "in the age of", "in the world of", "the reality is", "the truth is",
    "with regard to", "going forward", "in conclusion", "let's dive in",
    "here's the thing", "here's what i mean", "let me be clear", "i'll be honest",
    "underneath sits", "underneath lies", "beneath the surface", "at its foundation",
    "underpinned by", "a long engineering base", "sits a long", "testament to",
    "it goes without saying", "needless to say", "at the same time as saying",
    "this is the part most people", "the part most people miss",
    "what most people get wrong", "what nobody tells you", "here's what nobody",
    "the part everyone skips", "the uncomfortable truth is",
    "experts agree", "studies show", "research shows", "many argue",
    "widely regarded as", "industry reports suggest", "it is widely",
    "plays a vital role", "plays a pivotal role", "pivotal moment",
    "solidifies its position", "underscores the importance",
    "serves as a testament", "stands as a testament", "in summary",
    "when all is said and done", "the bottom line is",
]

BINARY_CONTRAST = [
    r"\bnot just\b[^.!?]{0,90}\bbut\b",
    r"\bnot only\b[^.!?]{0,90}\bbut\b",
    r"\bisn'?t just\b",
    r"\bit'?s not\b[^.!?]{0,70}[.,;]\s*it'?s\b",
    r"\bthe question isn'?t\b",
    r"\bthis isn'?t about\b",
    r"\bmore than just\b",
]

# ", highlighting ..." and friends: a trailing clause that pretends to explain.
TRAILING_ING = [
    r",\s+(?:highlighting|underscoring|showcasing|reflecting|demonstrating|"
    r"emphasizing|emphasising|illustrating|signalling|signaling|solidifying)\b",
]

# "harness" is a fine noun (an agent harness). Only the slop verb is banned:
# "harness the power of ...", "harness X to drive Y".
HARNESS_VERB = [
    r"\bharness(?:es|ed|ing)?\s+(?:the\s+)?(?:power|potential|benefit|value|"
    r"opportunit\w*|synerg\w*|strength\w*|advantage\w*)",
    r"\bharness(?:ing)?\s+\w+\s+to\s+(?:do|achieve|deliver|drive|build|create|make|"
    r"accelerate|improve|reduce|cut|speed|scale)\b",
]

EMOJI = re.compile("[\U0001F300-\U0001FAFF\u2600-\u27BF]")


def findings(text: str) -> list[dict]:
    """Every style problem in `text`, in reading order."""
    low = (text or "").lower()
    out: list[dict] = []

    def add(kind, match, advice, pos):
        out.append({"kind": kind, "match": match, "advice": advice, "pos": pos})

    for m in re.finditer("\u2014", text):
        add("em dash", "\u2014", "use a comma, colon, full stop or brackets", m.start())
    for m in re.finditer(r"\s--\s|\s---\s", text):
        add("em dash", m.group(0).strip(), "use a comma, colon, full stop or brackets",
            m.start())

    for pattern, label in BANNED:
        for m in re.finditer(pattern, text, re.IGNORECASE):
            add("slop word", m.group(0), f"cut '{label}' and say the plain thing", m.start())
    for pattern in HARNESS_VERB:
        for m in re.finditer(pattern, low):
            add("slop word", m.group(0), "use 'harness' only as a noun (agent harness)",
                m.start())

    for phrase in EMPTY_PHRASES:
        i = low.find(phrase)
        while i != -1:
            add("empty phrase", text[i:i + len(phrase)], "cut the phrase and state the point", i)
            i = low.find(phrase, i + len(phrase))

    for pattern in BINARY_CONTRAST:
        for m in re.finditer(pattern, text, re.IGNORECASE):
            add("binary contrast", m.group(0), "state the real claim directly", m.start())
    for pattern in TRAILING_ING:
        for m in re.finditer(pattern, text, re.IGNORECASE):
            add("trailing -ing clause", m.group(0), "say what it actually did", m.start())

    for m in EMOJI.finditer(text):
        add("emoji", m.group(0), "keep prose text plain", m.start())
    out.sort(key=lambda f: f["pos"])
    return out


def check(text: str, label: str = "") -> list[str]:
    """Error strings for the gate and the savers (stable wording)."""
    errors = []
    for f in findings(text):
        where = f"{label}: " if label else ""
        if f["kind"] == "em dash":
            errors.append(f"{where}em dash ({f['match']}) found: {f['advice']}")
        elif f["kind"] == "slop word":
            errors.append(f"{where}banned AI-slop word: {f['match']!r} ({f['advice']})")
        elif f["kind"] == "empty phrase":
            errors.append(f"{where}empty phrase: {f['match']!r} ({f['advice']})")
        elif f["kind"] == "binary contrast":
            errors.append(f"{where}binary contrast: {f['match']!r} ({f['advice']})")
        elif f["kind"] == "trailing -ing clause":
            errors.append(f"{where}trailing -ing commentary: {f['match']!r} ({f['advice']})")
        else:
            errors.append(f"{where}{f['kind']}: {f['match']!r} ({f['advice']})")
    return errors


def draft_body(text: str) -> str:
    """The prose part of a saved draft (drop the To/Cc/Subject header block)."""
    if "\n---\n" in text:
        head, body = text.split("\n---\n", 1)
        if re.search(r"(?m)^(?:to|subject):", head, re.IGNORECASE):
            return body
    return text


def scan_file(path: str) -> list[str]:
    with open(path, encoding="utf-8", errors="ignore") as fh:
        text = fh.read()
    body = draft_body(text)
    errors = []
    for f in findings(body):
        line = body[:f["pos"]].count("\n") + 1
        errors.append(f"{path}:{line}: {f['kind']}: {f['match']!r} - {f['advice']}")
    return errors


def scan_dir(root: str, suffix: str = ".txt") -> list[str]:
    errors = []
    for base, _dirs, files in os.walk(root):
        for name in sorted(files):
            if name.endswith(suffix):
                errors += scan_file(os.path.join(base, name))
    return errors


def main() -> int:
    ap = argparse.ArgumentParser(description="Plain-English style check (no em dashes, no AI slop).")
    ap.add_argument("files", nargs="*")
    ap.add_argument("--check", action="store_true", help="scan files (default when files are given)")
    ap.add_argument("--stdin", action="store_true", help="read text from stdin")
    ap.add_argument("--text", default="", help="check a literal string")
    ap.add_argument("--dir", default="", help="scan every .txt file under this directory")
    ap.add_argument("--quiet", action="store_true", help="print nothing; exit status only")
    args = ap.parse_args()

    errors: list[str] = []
    if args.text:
        errors += check(args.text)
    if args.stdin:
        errors += check(sys.stdin.read())
    if args.dir:
        errors += scan_dir(args.dir)
    for path in args.files:
        if os.path.isdir(path):
            errors += scan_dir(path)
        else:
            errors += scan_file(path)

    if not (args.text or args.stdin or args.dir or args.files):
        ap.print_help()
        return 2

    if errors and not args.quiet:
        for e in errors:
            print(f"FAIL  {e}")
        print(f"\nRESULT: FAIL ({len(errors)} style problem(s))")
        print("Rewrite in plain English: no em dashes, no stock phrases, no slop vocabulary.")
    elif not args.quiet:
        print("RESULT: PASS (plain English)")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
