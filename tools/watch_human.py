#!/usr/bin/env python3
"""FOCUSED viewer: only the HUMAN challenges.

Shows the current human step prominently (so you look here, not at the browser),
plus the queue of upcoming human challenges and their status.

Usage: bash tools/watch_human.sh     (or: python3 tools/watch_human.py)
"""
import json
import os
import sys
import time

from rich import box
from rich.console import Console, Group
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

ROOT = os.environ.get("ROOT") or os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
STATE = os.path.join(ROOT, "state")
CONSOLE = Console()


def load():
    q = os.path.join(STATE, "queue-human.tsv")
    d = os.path.join(STATE, "queue-human.done")
    cur = os.path.join(STATE, "human", "current.json")
    done = {l.strip() for l in open(d) if l.strip()} if os.path.exists(d) else set()
    rows = []
    if os.path.exists(q):
        for line in open(q):
            if not line.strip() or line.startswith("#"):
                continue
            f = (line.rstrip("\n").split("\t") + [""] * 6)[:6]
            if f[0]:
                rows.append(dict(company=f[0], role=f[1], url=f[2], reason=f[5]))
    st = {}
    if os.path.exists(cur):
        try:
            st = json.load(open(cur))
        except Exception:
            st = {}
    return rows, done, st


def build():
    rows, done, st = load()
    state = st.get("state", "")
    ndone = sum(1 for r in rows if f"{r['company']}|{r['role']}" in done)
    head = Text.assemble(("HUMAN CHALLENGES  ", "bold cyan"),
                         (time.strftime("%H:%M:%S"), "white"),
                         (f"   {ndone}/{len(rows)} done", "dim"))
    if state == "awaiting":
        banner = Text.assemble(("▶ SOLVE NOW   ", "bold white on red"),
                               (f" {st.get('company','')} — {st.get('role','')}", "bold"),
                               ("\n   ", ""), (st.get("note", ""), "yellow"))
    elif state == "filling":
        banner = Text.assemble(("⋯ preparing   ", "bold black on yellow"),
                               (f" {st.get('company','')} — {st.get('role','')}", "dim"),
                               ("   (browser busy — you can ignore it)", "dim"))
    elif state == "done":
        banner = Text.assemble(("✓ last done   ", "bold black on green"),
                               (f" {st.get('company','')} — {st.get('role','')}", "dim"),
                               ("\n   ", ""), (st.get("note", ""), "dim"))
    else:
        banner = Text("idle — start with:  bash tools/human_assist.sh", style="dim")
    groups = [head, Panel(banner, border_style="red" if state == "awaiting" else "yellow")]

    by = {}
    for r in rows:
        by.setdefault(r["reason"], []).append(r)
    for reason in sorted(by):
        t = Table(box=box.SIMPLE, expand=True, show_edge=False, pad_edge=False, header_style="bold")
        t.add_column("", width=6, no_wrap=True)
        t.add_column("Role", ratio=3, no_wrap=True)
        t.add_column("Company", ratio=1, no_wrap=True)
        for r in by[reason]:
            k = f"{r['company']}|{r['role']}"
            is_cur = k == f"{st.get('company','')}|{st.get('role','')}"
            stt = "DONE" if k in done else ("HERE" if is_cur and state == "awaiting" else "TODO")
            style = "green" if stt == "DONE" else ("bold white on red" if stt == "HERE" else "yellow")
            t.add_row(Text(stt, style=style), Text(r["role"]), Text(r["company"], style="cyan"))
        groups.append(Text(reason, style="bold"))
        groups.append(t)
    return Panel(Group(*groups), border_style="cyan", title="human-assist",
                 subtitle="Ctrl-C to quit" if sys.stdout.isatty() else None)


def main():
    if not sys.stdout.isatty():
        CONSOLE.print(build())
        return
    try:
        with Live(build(), console=CONSOLE, screen=True, refresh_per_second=4) as live:
            while True:
                time.sleep(1.5)
                live.update(build())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
