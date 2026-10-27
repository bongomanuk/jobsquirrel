#!/usr/bin/env python3
"""Fail if a git repository contains live credentials.

Scans tracked/untracked files and (by default) git history for common live-key
formats and for the exact values in the private agent/GraphRAG config. It never
prints a secret value.

Usage:
  python3 tools/secret_scan.py [--repo jobsquirrel] [--no-history]
"""

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HOME = Path.home()
PRIVATE_FILES = (
    HOME / ".config" / "job-search" / "agent.json",
    ROOT / "kb" / "graphrag" / ".env",
)
SECRET_NAME = re.compile(r"(KEY|TOKEN|SECRET|PASSWORD|PASSWD|CREDENTIAL)", re.I)
PATTERNS = (
    ("OpenRouter key", re.compile(r"sk-or-v1-[0-9a-fA-F]{32,}")),
    ("API key", re.compile(r"\bsk-[A-Za-z0-9_-]{32,}\b")),
    ("GitHub token", re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,})\b")),
    ("AWS access key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("Google API key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")),
    ("Private key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----")),
)


def _clean(value):
    value = str(value).strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        value = value[1:-1]
    return value


def _private_values():
    values = set()
    for path in PRIVATE_FILES:
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        if path.suffix == ".json":
            try:
                data = json.loads(text)
            except ValueError:
                continue
            env = data.get("env") if isinstance(data.get("env"), dict) else {}
            for name, value in env.items():
                value = _clean(value)
                if SECRET_NAME.search(str(name)) and len(value) >= 16:
                    values.add(value)
        else:
            for line in text.splitlines():
                if "=" not in line or line.lstrip().startswith("#"):
                    continue
                name, value = line.split("=", 1)
                value = _clean(value)
                if SECRET_NAME.search(name) and len(value) >= 16:
                    values.add(value)
    for name, value in os.environ.items():
        value = _clean(value)
        if SECRET_NAME.search(name) and len(value) >= 16:
            values.add(value)
    return sorted(values)


def _git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)


def _repo_files(repo):
    r = _git(repo, "ls-files", "-z", "--cached", "--others", "--exclude-standard")
    if r.returncode:
        raise SystemExit(f"not a git repository: {repo}")
    return [p for p in r.stdout.split("\0") if p]


def _scan_files(repo, known):
    findings = []
    for rel in _repo_files(repo):
        path = repo / rel
        try:
            raw = path.read_bytes()
        except OSError:
            continue
        if b"\0" in raw[:4096]:
            continue
        text = raw.decode("utf-8", "ignore")
        for lineno, line in enumerate(text.splitlines(), 1):
            for value in known:
                if value in line:
                    findings.append((f"{rel}:{lineno}", "known private credential"))
            for label, pattern in PATTERNS:
                if pattern.search(line):
                    findings.append((f"{rel}:{lineno}", label))
    return findings


def _scan_history(repo, known):
    findings = []
    if _git(repo, "rev-parse", "--verify", "HEAD").returncode:
        return findings
    for value in known:
        r = _git(repo, "log", "--all", "--format=%h %s", "-S", value, "--")
        for line in r.stdout.splitlines():
            if line.strip():
                findings.append((line.strip(), "known private credential"))
    for label, pattern in PATTERNS:
        r = _git(repo, "log", "--all", "--format=%h %s", "-G", pattern.pattern, "--")
        for line in r.stdout.splitlines():
            if line.strip():
                findings.append((line.strip(), label))
    return findings


def main():
    ap = argparse.ArgumentParser(description="Fail if a git repository contains live credentials.")
    ap.add_argument("--repo", default="jobsquirrel" if (ROOT / "jobsquirrel").is_dir() else ".",
                    help="repository to scan (default: jobsquirrel, else current directory)")
    ap.add_argument("--no-history", action="store_true", help="skip git history")
    args = ap.parse_args()
    repo = (ROOT / args.repo).resolve() if not Path(args.repo).is_absolute() else Path(args.repo)
    known = _private_values()
    findings = _scan_files(repo, known)
    if not args.no_history:
        findings.extend(_scan_history(repo, known))
    findings = sorted(set(findings), key=lambda x: (x[0], x[1]))
    if not findings:
        print(f"RESULT: PASS - no live credentials in {repo.name}")
        return 0
    print(f"RESULT: FAIL - {len(findings)} possible credential leak(s) in {repo.name}")
    for where, label in findings[:100]:
        print(f"  {where} - {label}")
    if len(findings) > 100:
        print(f"  … {len(findings) - 100} more")
    print("Do not push. Rotate any key found in history; deleting it from the tip is not enough.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
