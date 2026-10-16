#!/usr/bin/env python3
"""Live, SCROLLABLE dashboard for the job-application queue.

Rich full-screen dashboard that follows the queue/done paths tools/run_queue.sh
publishes to state/active_queue and state/active_done, so it never dumps
historical/applied jobs.

Scrolling + filtering (interactive):
    ↑/↓ or k/j      scroll one row          PgUp/PgDn or b/f/space  scroll a page
    g / Home        jump to top             G / End                jump to bottom
    a               show ALL                r  only RUNNING
    w               only WAITING            d  only DONE
    /               filter by text (type, Enter to apply, Esc to clear)
    q / Esc         quit

Usage:
    bash tools/watch_queue.sh                 # interactive, scrollable
    python3 tools/watch_queue.py --once       # print EVERY row once (pipe to less)
    python3 tools/watch_queue.py --mode run --once
"""
import argparse
import glob
import os
import re
import select
import subprocess
import sys
import termios
import time
import tty

from rich import box
from rich.console import Console, Group
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

ROOT = os.environ.get("ROOT") or os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
STATE = os.path.join(ROOT, "state")
LOGS = os.path.join(STATE, "logs")
CONSOLE = Console()

# lines used by everything except the task rows: header, progress, register line,
# a scroll/keys footer, the panel borders and the table header.
CHROME = 9


def read_pointer(name, default):
    try:
        v = open(os.path.join(STATE, name)).read().strip()
        if v:
            return v
    except OSError:
        pass
    return default


def active_paths(queue_arg):
    active = read_pointer("active_queue", "")
    q = queue_arg or active or os.path.join(STATE, "queue.tsv")
    if queue_arg and active and os.path.basename(queue_arg) != os.path.basename(active):
        d = queue_arg[:-4] + ".done" if queue_arg.endswith(".tsv") else os.path.join(STATE, "queue.done")
    else:
        d = read_pointer("active_done", os.path.join(STATE, "queue.done"))
    return q, d


def load_tasks(qpath):
    tasks = []
    try:
        with open(qpath) as f:
            for line in f:
                line = line.rstrip("\n")
                if not line or line.lstrip().startswith("#"):
                    continue
                p = (line.split("\t") + [""] * 6)[:6]
                tasks.append(dict(company=p[0], role=p[1], url=p[2], cv=p[3], ats=p[4], key=p[5]))
    except OSError:
        pass
    return tasks


def done_set(dpath):
    s = set()
    try:
        with open(dpath) as f:
            for line in f:
                line = line.strip()
                if line:
                    s.add(line)
    except OSError:
        pass
    return s


def log_path(company, role):
    name = f"{company}-{role}".translate(str.maketrans(" /|", "___")) + ".log"
    return os.path.join(LOGS, name)


ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")


def clean(s):
    return ANSI.sub("", s).strip()


def last_status(path):
    try:
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(max(0, size - 8000))
            data = f.read().decode("utf-8", "ignore")
    except OSError:
        return ""
    data = ANSI.sub("", data)
    status, last = "", ""
    for ln in data.splitlines():
        ln = ln.strip()
        if not ln:
            continue
        last = ln
        if ln.startswith("STATUS"):
            status = ln
    return status or last


def detail(path):
    raw = last_status(path)
    if not raw:
        return ""
    if raw.startswith("STATUS"):
        parts = [p.strip() for p in raw.split("|")]
        if len(parts) >= 4:
            return f"{parts[2]}: {parts[3]}"
        if len(parts) == 3:
            return parts[2]
    return raw


def outcome(path):
    """Recorded STATUS outcome for a task, or '' if it never reported one.

    DONE/WAIT rows use this so stale logs (model errors, kills) render as a
    clean placeholder instead of leaking raw fragments like '}'.
    """
    if last_status(path).startswith("STATUS"):
        return detail(path)
    return ""


PHASES = [
    (r"record_submission", "Recording submission"),
    (r"RESULT:\s*PASS|check_documents", "Document gate"),
    (r"email_verify|security code|verification code|complete the application", "Email verification"),
    (r"thanks page|thank-you|submitted|submit application|click.*submit|\bsubmit\b", "Submitting"),
    (r"upload", "Uploading CV + cover letter"),
    (r"render_motivation|Motivation_|cv_builder|cover letter", "Writing cover letter"),
    (r"ats_keywords|job-descriptions", "Reading job description"),
    (r"react-select|select__|combobox|fill |\.fill|select ", "Filling application form"),
    (r"greenhouse|lever\.co|ashbyhq|myworkdayjobs|workday|teamtailor|smartrecruiters|jobylon|workable|easycruit|varbi|apply", "On employer application form"),
    (r"WebSearch|web search|resolve|employer|company site|careers", "Researching employer / ATS"),
    (r"eligib|location|remote|work model|work auth", "Checking location eligibility"),
]


def _tail_lines(path, nbytes=16000):
    try:
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(max(0, size - nbytes))
            data = f.read().decode("utf-8", "ignore")
    except OSError:
        return []
    return [ln.strip() for ln in ANSI.sub("", data).splitlines() if ln.strip()]


def _is_noise(s):
    if len(s) > 150:
        return True
    if s[0] in "{<":
        return True
    if s.startswith(("$ ", "GET ", "POST ", "PUT ", "DELETE ", "timeout ", "→", ">", "e")):
        return True
    if re.match(r"^e?\d+[:.\]]", s):
        return True
    if re.match(r"^(true|false|ok|okay|null|none)$", s, re.I):
        return True
    if "://" in s and s.count(" ") == 0:
        return True
    if s.count(":") > 2 and ("{" in s or "[" in s):
        return True
    if re.search(r"[\{\}\[\]\"]", s):
        return True
    if not re.search(r"[A-Za-z]{3}\s+[A-Za-z]{3}", s):
        return True
    return False


def describe(path):
    lines = _tail_lines(path)
    phase = ""
    for ln in reversed(lines):
        for pat, label in PHASES:
            if re.search(pat, ln, re.I):
                phase = label
                break
        if phase:
            break
    snippet = ""
    for ln in reversed(lines):
        if not _is_noise(ln):
            snippet = ln
            break
    out = phase or "Working"
    if snippet and snippet.lower()[:20] not in out.lower():
        out = f"{out} — {snippet}"
    return out


HAVE_PROC = os.path.isdir("/proc")


def cmdlines():
    """Command line of every other process, arguments joined by spaces.

    Linux: /proc/<pid>/cmdline. macOS has no /proc, so there it is `ps`, which
    prints a newline inside an argument as \\012 and a tab as \\011; those are
    decoded back so a multi-line prompt reads the same as on Linux.
    """
    me = os.getpid()
    if HAVE_PROC:
        for p in glob.glob("/proc/[0-9]*/cmdline"):
            try:
                if int(p.split("/")[2]) == me:
                    continue
                yield open(p, "rb").read().replace(b"\x00", b" ").decode("utf-8", "ignore")
            except (OSError, ValueError):
                continue
        return
    try:
        out = subprocess.run(["ps", "-axww", "-o", "pid=,command="],
                             capture_output=True, timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        return
    for line in out.decode("utf-8", "ignore").splitlines():
        pid, _, c = line.strip().partition(" ")
        if not pid.isdigit() or int(pid) == me:
            continue
        yield c.replace("\\012", "\n").replace("\\011", "\t")


def runner_active():
    for c in cmdlines():
        if "run_queue.sh" in c and "watch_queue" not in c:
            return True
    return False


def live_tasks():
    """(company|role) keys with a LIVE agent worker (opencode, claude, agent_run.sh) in this repo.

    The dashboard marks RUN only for these. A mere log file is not enough:
    tasks from dead runs (model errors, kills) leave logs behind, and those
    must read WAIT, not RUN.
    """
    live = set()
    for c in cmdlines():
        if ROOT not in c or not any(a in c for a in ("opencode", "claude", "agent_run.sh")):
            continue
        # Company/Role are the first two labelled lines in every prompt. Parse
        # them independently so intervening lines (e.g. the human-assist prompt's
        # "Blocker: ...") do not break detection.
        co = re.search(r"Company(?:/tag)?:\s*([^\n]+)", c)
        ro = re.search(r"\bRole:\s*([^\n]+)", c)
        if co and ro:
            live.add(f"{co.group(1).strip()}|{ro.group(1).strip()}")
    return live


def register_counts():
    try:
        lines = open(os.path.join(STATE, "counts.md")).read().splitlines()
    except OSError:
        return ""
    parts = []
    for s in lines:
        s = s.strip()
        if not s or s.startswith(("#", "_", "```")):
            continue
        if set(s) <= {"-"}:                      # the "-----" separator row
            continue
        s = re.sub(r"\s*\([^)]*\)\s*$", "", s)   # drop "(SUBMITTED 486 + ...)" breakdown
        parts.append(re.sub(r"\s+", " ", s))     # collapse the fixed-width padding
    # surface the live-process summary right after the total so a narrow
    # terminal truncates the per-status tail, not the number that matters most
    head = [p for p in parts if p.lower().startswith("total") or "IN PROCESS" in p]
    rest = [p for p in parts if p not in head]
    return "   ".join(head + rest)


def bar(n, done, width=32):
    filled = int(width * done / max(1, n))
    return "█" * filled + "░" * (width - filled)


def _rank(t, done, live=frozenset()):
    k = f"{t['company']}|{t['role']}"
    if k in done:
        return 2
    if k in live:
        return 0
    return 1


def ordered_tasks(qpath, dpath, mode="all", text_filter="", live=frozenset()):
    tasks = load_tasks(qpath)
    done = done_set(dpath)
    tasks.sort(key=lambda t: _rank(t, done, live))
    if mode == "run":
        tasks = [t for t in tasks if _rank(t, done, live) == 0]
    elif mode == "wait":
        tasks = [t for t in tasks if _rank(t, done, live) == 1]
    elif mode == "done":
        tasks = [t for t in tasks if _rank(t, done, live) == 2]
    if text_filter:
        f = text_filter.lower()
        tasks = [t for t in tasks if f in t["company"].lower() or f in t["role"].lower()]
    return tasks, done


def term_rows():
    try:
        return os.get_terminal_size().lines
    except OSError:
        return 40


def build(queue_arg, view):
    qpath, dpath = active_paths(queue_arg)
    live = live_tasks()
    tasks, done = ordered_tasks(qpath, dpath, view.mode, view.filter, live)
    total = len(tasks)
    per_page = None if view.all_rows else max(4, term_rows() - CHROME)
    if per_page is None:
        first, last = 0, total
    else:
        max_off = max(0, total - per_page)
        view.offset = max(0, min(view.offset, max_off))
        first, last = view.offset, min(total, view.offset + per_page)
    window = tasks[first:last]

    active = runner_active()
    try:
        cap = int(read_pointer("active_parallel", "5").strip() or "5")
    except ValueError:
        cap = 5
    all_tasks = load_tasks(qpath)
    ndone = sum(1 for t in all_tasks if f"{t['company']}|{t['role']}" in done)
    nrun = sum(1 for t in all_tasks
               if f"{t['company']}|{t['role']}" in live)

    mode_label = {"all": "all", "run": "running", "wait": "waiting", "done": "done"}[view.mode]
    header = Text.assemble(
        ("Job pipeline  ", "bold cyan"),
        (time.strftime("%Y-%m-%d %H:%M:%S"), "white"),
        ("    queue: ", "dim"), (os.path.basename(qpath), "bright_cyan"),
        ("    workers: ", "dim"), (f"{nrun}/{cap}", "bold green" if active else "bold red"),
        ("    runner: ", "dim"),
        ("ACTIVE" if active else "not running", "bold green" if active else "bold red"),
    )
    header.no_wrap = True
    header.overflow = "ellipsis"
    progress = Text.assemble(
        ("  ", ""), (bar(len(all_tasks), ndone), "cyan"),
        (f"  {ndone}/{len(all_tasks)} done", "bold"), (f"   running {nrun}", "yellow"),
        ("   view: ", "dim"), (mode_label, "bold magenta"),
        (f"   showing {first + 1}-{last} of {total}" if total else "   (no matching tasks)", "dim"),
    )
    reg = Text("  " + register_counts(), style="dim", no_wrap=True, overflow="ellipsis")

    table = Table(box=box.SIMPLE, expand=True, show_edge=False, pad_edge=False, header_style="bold")
    table.add_column("", width=6, no_wrap=True)
    table.add_column("Role", ratio=3, no_wrap=True, overflow="ellipsis")
    table.add_column("Company", ratio=1, no_wrap=True, overflow="ellipsis")
    table.add_column("Latest", ratio=4, overflow="ellipsis", no_wrap=True)

    for t in window:
        k = f"{t['company']}|{t['role']}"
        lp = log_path(t["company"], t["role"])
        if k in done:
            tag, style, info = "DONE", "green", outcome(lp) or "—"
        elif k in live:
            info = describe(lp) if os.path.exists(lp) else "starting"
            tag, style = "RUN", "bold yellow"
        elif os.path.exists(lp):
            tag, style, info = "WAIT", "dim", outcome(lp) or "queued"
        else:
            tag, style, info = "WAIT", "dim", "queued"
        table.add_row(Text(tag, style=style), Text(t["role"]), Text(t["company"], style="cyan"),
                      Text(info, style="dim"))

    flt = f"  filter: '{view.filter}'" if view.filter else ""
    keys = ("↑/↓ scroll · PgUp/PgDn page · g/G top/bottom · a/r/w/d filter · / search · q quit" + flt)
    footer = Text(keys, style="dim", no_wrap=True, overflow="ellipsis")

    body = Group(header, progress, reg, table, footer)
    panel = Panel(body, border_style="blue", title="queue monitor",
                  subtitle="Ctrl-C to quit" if sys.stdout.isatty() else None)
    return panel


class View:
    def __init__(self, mode="all"):
        self.offset = 0
        self.mode = mode
        self.filter = ""
        self.all_rows = False


def read_key(timeout):
    if not select.select([sys.stdin], [], [], timeout)[0]:
        return ""
    ch = os.read(sys.stdin.fileno(), 1).decode("utf-8", "ignore")
    if ch == "\x1b":
        if select.select([sys.stdin], [], [], 0.02)[0]:
            seq = os.read(sys.stdin.fileno(), 8).decode("utf-8", "ignore")
            return "\x1b" + seq
        return "\x1b"
    return ch


def read_line(prompt):
    """One-line search prompt (leaves raw mode briefly)."""
    sys.stdout.write("\r\x1b[2K" + prompt)
    sys.stdout.flush()
    buf = ""
    while True:
        ch = read_key(60)
        if ch in ("\r", "\n", ""):
            break
        if ch == "\x1b":
            buf = ""
            break
        if ch in ("\x7f", "\x08"):
            buf = buf[:-1]
        elif ch.isprintable():
            buf += ch
        sys.stdout.write("\r\x1b[2K" + prompt + buf)
        sys.stdout.flush()
    return buf


def main():
    ap = argparse.ArgumentParser(description="Live, scrollable queue dashboard (current run only).")
    ap.add_argument("--queue", default=None, help="queue file to watch (default: the active run)")
    ap.add_argument("--interval", type=float, default=2.0)
    ap.add_argument("--once", action="store_true", help="print a single frame with EVERY row and exit")
    ap.add_argument("--mode", default="all", choices=["all", "run", "wait", "done"])
    args = ap.parse_args()

    view = View(mode=args.mode)
    if args.once or not sys.stdout.isatty():
        view.all_rows = True
        CONSOLE.print(build(args.queue, view))
        return

    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setcbreak(fd)
        with Live(build(args.queue, view), console=CONSOLE, screen=True, refresh_per_second=6) as live:
            while True:
                live.update(build(args.queue, view))
                key = read_key(args.interval)
                if key in ("q", "\x03", "\x1b"):        # q / Ctrl-C / Esc
                    if key == "\x1b":
                        break
                    break
                elif key in ("j", "\x1b[B"):
                    view.offset += 1
                elif key in ("k", "\x1b[A"):
                    view.offset = max(0, view.offset - 1)
                elif key in ("f", " ", "\x1b[6~"):
                    view.offset += max(4, term_rows() - CHROME)
                elif key in ("b", "\x1b[5~"):
                    view.offset = max(0, view.offset - max(4, term_rows() - CHROME))
                elif key in ("g", "\x1b[H"):
                    view.offset = 0
                elif key in ("G", "\x1b[F"):
                    view.offset = 10 ** 9
                elif key == "a":
                    view.mode = "all"
                elif key == "r":
                    view.mode = "run"
                elif key == "w":
                    view.mode = "wait"
                elif key == "d":
                    view.mode = "done"
                elif key == "/":
                    with CONSOLE.capture():
                        pass
                    view.filter = read_line("search: ")
                    view.offset = 0
    except KeyboardInterrupt:
        pass
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


if __name__ == "__main__":
    main()
