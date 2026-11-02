#!/usr/bin/env python3
"""Reclaim disk space from the pipeline's machine-local data, without losing it.

Almost everything this pipeline keeps is either text (logs, JSON caches) or a
regenerable index cache, and both compress hard: logs ~5x, the Gmail body cache
~9x, the GraphRAG indexing cache ~5x. The three actions below are deliberately
separate, because they differ in how safe they are to run unattended.

    python3 tools/storage.py                      # report only (default)
    python3 tools/storage.py --logs               # gzip logs older than 7 days
    python3 tools/storage.py --logs --days 1      # ... older than 1 day
    python3 tools/storage.py --gmail-cache        # gzip state/gmail_cache.json
    python3 tools/storage.py --graphrag-cache     # dry run: what archiving would save
    python3 tools/storage.py --graphrag-cache --apply
    python3 tools/storage.py --all --apply        # everything, including the archive

`--logs` only touches files whose mtime is older than the window, so a log that
is being written right now is never moved. It runs automatically at the start of
every queue run, which is what keeps state/logs/ from growing without bound.

Readers handle both forms: the dashboard lists `foo.log.gz` as task `foo`, and
gmail_reconcile/gmail_review_model read `gmail_cache.json.gz` when the plain file
is gone. Compression never deletes the only copy of anything except the GraphRAG
indexing cache, and that one is written as a restorable tar archive first.
"""
from __future__ import annotations

import argparse
import gzip
import os
import shutil
import subprocess
import sys
import tarfile
import time
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOGS = os.path.join(ROOT, "state", "logs")
GRAPHRAG_LOGS = os.path.join(ROOT, "kb", "graphrag", "logs")
GRAPHRAG_CACHE = os.path.join(ROOT, "kb", "graphrag", "cache")
ARCHIVES = os.path.join(ROOT, "kb", "archives")
GMAIL_CACHE = os.path.join(ROOT, "state", "gmail_cache.json")
DEFAULT_DAYS = 7
GRAPHRAG_LOG_DAYS = 2    # indexing runs finish in hours; a 2-day-old index log is idle
MIN_BYTES = 1024          # below this, gzip's header costs more than it saves


def human(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def _dir_size(path: str) -> tuple[int, int]:
    """(bytes, files) below path; missing path is (0, 0)."""
    total = files = 0
    for base, _dirs, names in os.walk(path):
        for name in names:
            try:
                total += os.stat(os.path.join(base, name)).st_size
                files += 1
            except OSError:
                pass
    return total, files


def _gz_to(src: str, dst: str) -> int:
    """gzip src -> dst atomically; return bytes written. Never leaves a half file."""
    tmp = dst + ".tmp"
    with open(src, "rb") as fh, open(tmp, "wb") as raw:
        with gzip.GzipFile(fileobj=raw, mode="wb", compresslevel=9) as gz:
            shutil.copyfileobj(fh, gz, 1024 * 1024)
    os.replace(tmp, dst)
    return os.path.getsize(dst)


def compress_logs(days: float = DEFAULT_DAYS, apply: bool = True, quiet: bool = False) -> int:
    """gzip *.log files older than `days` in the log directories. Returns bytes saved."""
    cutoffs = {
        LOGS: time.time() - days * 86400,
        GRAPHRAG_LOGS: time.time() - min(days, GRAPHRAG_LOG_DAYS) * 86400,
    }
    saved = done = 0
    for directory in (LOGS, GRAPHRAG_LOGS):
        cutoff = cutoffs[directory]
        try:
            names = sorted(os.listdir(directory))
        except OSError:
            continue
        for name in names:
            if not name.endswith(".log"):
                continue
            path = os.path.join(directory, name)
            try:
                st = os.stat(path)
            except OSError:
                continue
            if st.st_mtime > cutoff or st.st_size < MIN_BYTES:
                continue
            gz = path + ".gz"
            if apply:
                try:
                    written = _gz_to(path, gz)   # replace first, then drop the source
                    os.unlink(path)
                except OSError as exc:
                    print(f"FAIL {path}: {exc}", file=sys.stderr)
                    continue
                done += 1
                saved += max(0, st.st_size - written)
                if not quiet:
                    print(f"  {human(st.st_size):>9} -> {human(written):>9}  {name}.gz")
            else:
                done += 1
                saved += int(st.st_size * 0.78)   # measured ~4.5x on these logs
    verb = "compressed" if apply else "would compress"
    print(f"logs: {verb} {done} file(s), {human(saved)} {'saved' if apply else 'saved (dry run)'}")
    return saved


def compress_gmail_cache(apply: bool = True, quiet: bool = False) -> int:
    """gzip state/gmail_cache.json -> .json.gz. Derived data, safe to compress."""
    if not os.path.exists(GMAIL_CACHE):
        print("gmail cache: already compressed (or absent)")
        return 0
    size = os.path.getsize(GMAIL_CACHE)
    if size < MIN_BYTES:
        print("gmail cache: too small to bother")
        return 0
    if not apply:
        print(f"gmail cache: would compress {human(size)} (~9x smaller)")
        return int(size * 0.89)
    try:
        written = _gz_to(GMAIL_CACHE, GMAIL_CACHE + ".gz")
        os.unlink(GMAIL_CACHE)
    except OSError as exc:
        print(f"FAIL gmail cache: {exc}", file=sys.stderr)
        return 0
    saved = max(0, size - written)
    print(f"gmail cache: {human(size)} -> {human(written)}, {human(saved)} saved")
    return saved


def _zstd() -> str | None:
    return shutil.which("zstd")


def archive_graphrag_cache(apply: bool = True) -> int:
    """Tar the GraphRAG indexing cache into kb/archives and drop the loose files.

    The cache only speeds up (re)indexing; queries read kb/graphrag/output. The
    archive is restorable, so incremental indexing still has its history if the
    sources change again.
    """
    size, files = _dir_size(GRAPHRAG_CACHE)
    if not files:
        print("graphrag cache: nothing to archive")
        return 0
    stamp = datetime.now().strftime("%Y%m%d")
    if _zstd():
        name, program = f"graphrag-cache-{stamp}.tar.zst", ["zstd", "-19", "-T0", "-q"]
    else:
        name, program = f"graphrag-cache-{stamp}.tar.gz", ["gzip", "-9"]
    out = os.path.join(ARCHIVES, name)
    if not apply:
        print(f"graphrag cache: {human(size)} in {files} files")
        print(f"  would archive to kb/archives/{name} (~5x smaller, restorable)")
        return int(size * 0.8)
    os.makedirs(ARCHIVES, exist_ok=True)
    tmp = out + ".part"
    cmd = ["tar", "-C", os.path.dirname(GRAPHRAG_CACHE), "-cf", "-",
           os.path.basename(GRAPHRAG_CACHE)]
    try:
        with open(tmp, "wb") as fh:
            tar = subprocess.Popen(cmd, stdout=subprocess.PIPE)
            comp = subprocess.Popen(program, stdin=tar.stdout, stdout=fh)
            tar.stdout.close()
            comp.communicate()
            tar.wait()
        if tar.returncode or comp.returncode:
            raise OSError(f"tar/zstd failed ({tar.returncode}/{comp.returncode})")
        os.replace(tmp, out)
    except (OSError, ValueError) as exc:
        print(f"FAIL graphrag cache: {exc}", file=sys.stderr)
        try:
            os.unlink(tmp)
        except OSError:
            pass
        return 0
    written = os.path.getsize(out)
    shutil.rmtree(GRAPHRAG_CACHE, ignore_errors=True)
    saved = max(0, size - written)
    print(f"graphrag cache: {human(size)} -> {human(written)}, {human(saved)} saved")
    print(f"  archive: kb/archives/{name}")
    print(f"  restore: tar -C kb/graphrag -xf kb/archives/{name}"
          + (" --use-compress-program=unzstd" if name.endswith(".zst") else ""))
    return saved


def report() -> None:
    print("storage report (machine-local; not in git)")
    print(f"  {'area':<28}{'size':>10}{'files':>8}")
    areas = [
        ("state/logs", LOGS),
        ("kb/graphrag/logs", GRAPHRAG_LOGS),
        ("kb/graphrag/cache", GRAPHRAG_CACHE),
        ("kb/graphrag/output", os.path.join(ROOT, "kb", "graphrag", "output")),
        ("documents/submitted", os.path.join(ROOT, "documents", "submitted")),
        ("documents/applications", os.path.join(ROOT, "documents", "applications")),
    ]
    total = 0
    for label, path in areas:
        size, files = _dir_size(path)
        total += size
        print(f"  {label:<28}{human(size):>10}{files:>8}")

    cache_size = os.path.getsize(GMAIL_CACHE) if os.path.exists(GMAIL_CACHE) else 0
    gz_size = os.path.getsize(GMAIL_CACHE + ".gz") if os.path.exists(GMAIL_CACHE + ".gz") else 0
    other = cache_size + gz_size
    total += other
    print(f"  {'state/gmail_cache':<28}{human(other):>10}{'1' if other else '0':>8}")

    old_bytes = old_count = 0
    cutoff = time.time() - DEFAULT_DAYS * 86400
    for directory in (LOGS, GRAPHRAG_LOGS):
        try:
            names = os.listdir(directory)
        except OSError:
            continue
        for name in names:
            if not name.endswith(".log"):
                continue
            try:
                st = os.stat(os.path.join(directory, name))
            except OSError:
                continue
            if st.st_mtime < cutoff and st.st_size >= MIN_BYTES:
                old_count += 1
                old_bytes += st.st_size

    print(f"\n  total tracked here: {human(total)}")
    if old_count:
        print(f"  reclaimable now: {human(int(old_bytes * 0.78))} "
              f"({old_count} logs older than {DEFAULT_DAYS}d -> --logs)")
    if cache_size:
        print(f"  reclaimable now: {human(int(cache_size * 0.89))} (gmail cache -> --gmail-cache)")
    csize, cfiles = _dir_size(GRAPHRAG_CACHE)
    if cfiles:
        print(f"  reclaimable now: {human(int(csize * 0.8))} "
              f"({human(csize)} GraphRAG cache -> --graphrag-cache --apply)")
    print("\n  documents/ are .docx/.pdf: already compressed, nothing to gain.")


def main() -> int:
    ap = argparse.ArgumentParser(description="Compress the pipeline's machine-local data.")
    ap.add_argument("--logs", action="store_true", help="gzip logs older than --days")
    ap.add_argument("--days", type=float, default=DEFAULT_DAYS, help=f"log age window (default {DEFAULT_DAYS})")
    ap.add_argument("--gmail-cache", action="store_true", help="gzip state/gmail_cache.json")
    ap.add_argument("--graphrag-cache", action="store_true",
                    help="archive kb/graphrag/cache to kb/archives (dry run unless --apply)")
    ap.add_argument("--all", action="store_true", help="logs + gmail cache + graphrag archive")
    ap.add_argument("--apply", action="store_true", help="actually perform the graphrag archive")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    acts = bool(args.logs or args.gmail_cache or args.graphrag_cache or args.all)
    if not acts:
        report()
        return 0

    saved = 0
    if args.logs or args.all:
        saved += compress_logs(args.days, apply=True, quiet=args.quiet)
    if args.gmail_cache or args.all:
        saved += compress_gmail_cache(apply=True, quiet=args.quiet)
    if args.graphrag_cache or args.all:
        saved += archive_graphrag_cache(apply=args.apply)
    if saved:
        print(f"total: {human(saved)} reclaimed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
