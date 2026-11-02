#!/usr/bin/env python3
"""Back up and restore the pipeline's state as a single zip.

The backup is the thing you want before moving machines, reinstalling, or
clearing the system: everything the pipeline cannot regenerate.

    python3 tools/backup.py create                  # -> backups/jobsquirrel-<date>.zip
    python3 tools/backup.py create --no-documents   # smaller: no rendered CVs/letters
    python3 tools/backup.py inspect <zip>           # what is inside, is it valid
    python3 tools/backup.py restore <zip> --yes     # restore over the current state
    python3 tools/backup.py clear --scope data --yes
    python3 tools/backup.py list

What goes in:
    config/         your profile, CV, archetypes, mail/calendar and Google settings
    answers/        the standard form answers the prompts refer to
    kb/sources/     the documents the knowledge graph is built from
    state/          register, queues, provenance, drafts, saved ads, keyword
                    files, grounding packs, content packs, gate receipts
    documents/      rendered archetypes, per-role CVs/letters, sent snapshots
                    (only with --documents, which is the default)

What never goes in: `.git`, the virtualenvs, the public clone (`jobsquirrel/`),
`state/logs/` (agent transcripts), the derived mail cache, the GraphRAG index
(rebuildable), and the Google OAuth token (it lives outside the repo).

The zip **does** contain personal data — your CV, your applications, and any
Google client secret stored in `config/google.json`. Treat it like a passport
scan: keep it somewhere private, and do not commit it.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
import time
import zipfile
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKUP_DIR = os.environ.get("JOBSQUIRREL_BACKUPS", os.path.join(ROOT, "backups"))
MANIFEST = "BACKUP.json"
FORMAT = 1
KIND = "jobsquirrel-backup"

# Directories that make up a backup, and the prefixes a restore may write to.
CONFIG_DIRS = ("config", "answers")
STATE_DIR = "state"
SOURCES_DIR = os.path.join("kb", "sources")
DOCUMENTS_DIR = "documents"
RESTORE_PREFIXES = ("config/", "answers/", "state/", "documents/", "kb/sources/")

# Never in the zip: transcripts, derived caches, locks, running state.
STATE_SKIP_DIRS = {"logs", "__pycache__"}
STATE_SKIP_FILES = {"gmail_cache.json", "gmail_cache.json.gz", "applications.csv.lock"}
STATE_SKIP_SUFFIXES = (".lock", ".pid", ".tmp")
SAFETY_KEEP = 5          # automatic pre-restore/pre-clear copies kept on disk
SAFETY_PREFIXES = ("pre-restore-", "pre-clear-")


def _version() -> str:
    try:
        with open(os.path.join(ROOT, "VERSION"), encoding="utf-8") as fh:
            return fh.read().strip()
    except OSError:
        return ""


def _walk(top: str):
    """Files under `top`, honouring the state exclusions (and skipping symlinks)."""
    for base, dirs, files in os.walk(top):
        relbase = os.path.relpath(base, ROOT)
        parts = relbase.split(os.sep)
        if parts and parts[0] == STATE_DIR:
            dirs[:] = [d for d in dirs if d not in STATE_SKIP_DIRS]
        dirs[:] = sorted(d for d in dirs if d != "__pycache__")
        for name in sorted(files):
            if parts and parts[0] == STATE_DIR:
                if name in STATE_SKIP_FILES or name.endswith(STATE_SKIP_SUFFIXES):
                    continue
            path = os.path.join(base, name)
            if os.path.islink(path):
                continue
            yield path


def entries(include_documents: bool = True) -> list[tuple[str, str]]:
    """(absolute path, archive name) for everything that belongs in a backup."""
    out: list[tuple[str, str]] = []
    tops = [os.path.join(ROOT, d) for d in CONFIG_DIRS]
    tops.append(os.path.join(ROOT, STATE_DIR))
    tops.append(os.path.join(ROOT, SOURCES_DIR))
    if include_documents:
        tops.append(os.path.join(ROOT, DOCUMENTS_DIR))
    for top in tops:
        if not os.path.isdir(top):
            continue
        for path in _walk(top):
            out.append((path, os.path.relpath(path, ROOT)))
    return out


def _dir_size(path: str) -> tuple[int, int]:
    total = count = 0
    if not os.path.isdir(path):
        return 0, 0
    for p in _walk(path):
        try:
            total += os.path.getsize(p)
            count += 1
        except OSError:
            pass
    return total, count


def summarise() -> dict:
    """What a backup would contain right now (for the dashboard)."""
    parts = {}
    for name, rel in (("config", "config"), ("answers", "answers"),
                      ("state", "state"), ("sources", os.path.join("kb", "sources")),
                      ("documents", "documents")):
        size, count = _dir_size(os.path.join(ROOT, rel))
        parts[name] = {"bytes": size, "files": count}
    backups = list_backups()
    return {"parts": parts, "backups": backups,
            "backup_dir": os.path.relpath(BACKUP_DIR, ROOT) if BACKUP_DIR.startswith(ROOT) else BACKUP_DIR,
            "has_config": os.path.isfile(os.path.join(ROOT, "config", "profile.md")),
            "has_index": os.path.isdir(os.path.join(ROOT, "kb", "graphrag", "output")),
            "version": _version()}


def _manifest(files: list[tuple[str, str]], include_documents: bool) -> dict:
    total = 0
    for path, _ in files:
        try:
            total += os.path.getsize(path)
        except OSError:
            pass
    return {
        "kind": KIND,
        "format": FORMAT,
        "version": _version(),
        "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "host": os.uname().nodename if hasattr(os, "uname") else "",
        "includes": {"documents": bool(include_documents)},
        "files": len(files),
        "bytes": total,
    }


def create(out: str = "", include_documents: bool = True, quiet: bool = False) -> str:
    """Write a backup zip and return its path. Never overwrites an existing file."""
    os.makedirs(BACKUP_DIR, exist_ok=True)
    if not out:
        stamp = time.strftime("%Y%m%d-%H%M%S")
        out = os.path.join(BACKUP_DIR, f"jobsquirrel-{stamp}.zip")
    if os.path.exists(out):
        raise FileExistsError(out)

    files = entries(include_documents)
    meta = _manifest(files, include_documents)
    tmp = out + ".part"
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        zf.writestr(MANIFEST, json.dumps(meta, indent=2) + "\n")
        for path, arc in files:
            try:
                zf.write(path, arc)
            except OSError as exc:          # a file can vanish mid-walk
                print(f"skipped {arc}: {exc}", file=sys.stderr)
    os.replace(tmp, out)
    if os.path.basename(out).startswith(SAFETY_PREFIXES):
        prune()
    if not quiet:
        size = os.path.getsize(out)
        print(f"wrote {os.path.relpath(out, ROOT)} ({len(files)} files, "
              f"{size / 1048576:.1f} MB)")
    return out


def prune(keep: int = SAFETY_KEEP) -> int:
    """Delete old automatic safety copies (never your own backups)."""
    if not os.path.isdir(BACKUP_DIR):
        return 0
    auto = sorted((n for n in os.listdir(BACKUP_DIR)
                   if n.endswith(".zip") and n.startswith(SAFETY_PREFIXES)), reverse=True)
    removed = 0
    for name in auto[keep:]:
        try:
            os.unlink(os.path.join(BACKUP_DIR, name))
            removed += 1
        except OSError:
            pass
    return removed


def list_backups() -> list[dict]:
    if not os.path.isdir(BACKUP_DIR):
        return []
    out = []
    for name in sorted(os.listdir(BACKUP_DIR), reverse=True):
        if not name.endswith(".zip"):
            continue
        path = os.path.join(BACKUP_DIR, name)
        try:
            st = os.stat(path)
        except OSError:
            continue
        out.append({"name": name, "bytes": st.st_size,
                    "at": datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M")})
    return out[:20]


def _safe_members(zf: zipfile.ZipFile) -> list[zipfile.ZipInfo]:
    """Archive members that may be restored: no traversal, no devices, no binaries."""
    out = []
    for info in zf.infolist():
        name = info.filename.replace("\\", "/")
        if name == MANIFEST or name.endswith("/"):
            continue
        if name.startswith("/") or ".." in name.split("/"):
            continue
        mode = (info.external_attr >> 16) & 0o170000
        if mode and mode not in (0o100000, 0o040000):     # regular file / dir only
            continue
        if not name.startswith(RESTORE_PREFIXES):
            continue
        out.append(info)
    return out


def inspect(path: str) -> dict:
    """Validate a backup zip and report what it holds."""
    if not os.path.isfile(path):
        return {"error": f"not found: {path}"}
    try:
        with zipfile.ZipFile(path) as zf:
            bad = zf.testzip()
            if bad:
                return {"error": f"corrupt entry in the archive: {bad}"}
            try:
                meta = json.loads(zf.read(MANIFEST).decode("utf-8"))
            except KeyError:
                return {"error": "not a jobsquirrel backup (no BACKUP.json)"}
            except ValueError:
                return {"error": "BACKUP.json is not valid JSON"}
            if meta.get("kind") != KIND:
                return {"error": "not a jobsquirrel backup (wrong kind)"}
            members = _safe_members(zf)
            counts: dict[str, int] = {}
            for info in members:
                top = info.filename.split("/")[0]
                counts[top] = counts.get(top, 0) + 1
            meta.update({"path": path, "bytes": os.path.getsize(path),
                         "restorable_files": len(members), "by_top": counts})
            skipped = len(zf.infolist()) - len(members) - 1
            if skipped > 0:
                meta["skipped_entries"] = skipped
            return meta
    except zipfile.BadZipFile:
        return {"error": "not a zip file"}
    except OSError as exc:
        return {"error": str(exc)}


def _write_member(zf: zipfile.ZipFile, info: zipfile.ZipInfo) -> str:
    """Extract one member atomically, keeping the plain/.gz pair consistent."""
    rel = info.filename.replace("\\", "/")
    dest = os.path.join(ROOT, *rel.split("/"))
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(dest), prefix=".restore-")
    try:
        with os.fdopen(fd, "wb") as fh, zf.open(info) as src:
            shutil.copyfileobj(src, fh, 1024 * 1024)
        os.replace(tmp, dest)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    # state artifacts exist as x or x.gz, never both
    twin = dest[:-3] if dest.endswith(".gz") else dest + ".gz"
    if os.path.exists(twin):
        try:
            os.unlink(twin)
        except OSError:
            pass
    return rel


def restore(path: str, safety: bool = True, quiet: bool = False) -> dict:
    """Restore a backup over the current state, after taking a safety backup."""
    meta = inspect(path)
    if meta.get("error"):
        return meta
    safety_path = ""
    if safety:
        try:
            safety_path = create(os.path.join(BACKUP_DIR,
                                              f"pre-restore-{time.strftime('%Y%m%d-%H%M%S')}.zip"),
                                 include_documents=True, quiet=True)
        except OSError as exc:
            return {"error": f"could not write a safety backup: {exc}"}
    restored = 0
    with zipfile.ZipFile(path) as zf:
        for info in _safe_members(zf):
            try:
                _write_member(zf, info)
                restored += 1
            except OSError as exc:
                return {"error": f"failed on {info.filename}: {exc}",
                        "restored": restored, "safety": safety_path}
    if not quiet:
        print(f"restored {restored} file(s) from {os.path.basename(path)}")
        if safety_path:
            print(f"safety backup: {os.path.relpath(safety_path, ROOT)}")
    return {"ok": f"restored {restored} file(s)", "restored": restored,
            "safety": safety_path, "version": meta.get("version", ""),
            "created": meta.get("created", "")}


def _remove(path: str) -> tuple[int, int]:
    """Delete a file or directory tree; returns (files, bytes) removed."""
    files = size = 0
    if not os.path.exists(path):
        return 0, 0
    if os.path.isfile(path):
        try:
            size = os.path.getsize(path)
            os.unlink(path)
            return 1, size
        except OSError:
            return 0, 0
    for base, dirs, names in os.walk(path, topdown=False):
        for name in names:
            p = os.path.join(base, name)
            try:
                size += os.path.getsize(p)
                os.unlink(p)
                files += 1
            except OSError:
                pass
        for name in dirs:
            try:
                os.rmdir(os.path.join(base, name))
            except OSError:
                pass
    try:
        os.rmdir(path)
    except OSError:
        pass
    return files, size


def clear(scope: str = "data", safety: bool = True, quiet: bool = False) -> dict:
    """Delete generated data. `config/` and `kb/sources/` are never touched.

    scope "data": register, queues, drafts, per-role artifacts, documents and
                  sent snapshots (documents/archetypes regenerate from config)
    scope "full": the above plus the GraphRAG index (rebuild takes ~20-30 min)
    """
    if scope not in ("data", "full"):
        return {"error": "scope must be 'data' or 'full'"}
    safety_path = ""
    if safety:
        try:
            safety_path = create(os.path.join(BACKUP_DIR,
                                              f"pre-clear-{time.strftime('%Y%m%d-%H%M%S')}.zip"),
                                 include_documents=True, quiet=True)
        except OSError as exc:
            return {"error": f"could not write a safety backup: {exc}"}

    targets = [os.path.join(ROOT, STATE_DIR), os.path.join(ROOT, DOCUMENTS_DIR)]
    if scope == "full":
        targets.append(os.path.join(ROOT, "kb", "graphrag"))
    files = size = 0
    kept_state = os.path.join(ROOT, STATE_DIR, "README.md")
    for target in targets:
        if target == os.path.join(ROOT, STATE_DIR):
            # keep the directory itself, empty its contents
            for name in os.listdir(target):
                path = os.path.join(target, name)
                if path == kept_state:
                    continue
                f, b = _remove(path)
                files += f
                size += b
            continue
        f, b = _remove(target)
        files += f
        size += b
    # make the empty working directories again so the next run just works
    for name in (STATE_DIR, DOCUMENTS_DIR, os.path.join(DOCUMENTS_DIR, "archetypes"),
                 os.path.join(DOCUMENTS_DIR, "applications"),
                 os.path.join(DOCUMENTS_DIR, "submitted")):
        try:
            os.makedirs(os.path.join(ROOT, name), exist_ok=True)
        except OSError:
            pass
    if not quiet:
        print(f"cleared {files} file(s), {size / 1048576:.1f} MB")
        if safety_path:
            print(f"safety backup: {os.path.relpath(safety_path, ROOT)}")
    return {"ok": f"cleared {files} file(s)", "removed": files,
            "bytes": size, "scope": scope, "safety": safety_path}


def main() -> int:
    ap = argparse.ArgumentParser(description="Back up, restore or clear the pipeline's state.")
    sub = ap.add_subparsers(dest="cmd")

    c = sub.add_parser("create", help="write a backup zip")
    c.add_argument("--out", default="", help="path for the zip (default backups/jobsquirrel-<date>.zip)")
    c.add_argument("--no-documents", action="store_true", help="leave documents/ out (smaller)")
    c.add_argument("--quiet", action="store_true")

    l = sub.add_parser("list", help="list backups in backups/")

    i = sub.add_parser("inspect", help="validate a backup and show its contents")
    i.add_argument("zip")

    r = sub.add_parser("restore", help="restore a backup over the current state")
    r.add_argument("zip")
    r.add_argument("--yes", action="store_true", help="do it (a safety backup is taken first)")
    r.add_argument("--no-safety", action="store_true", help="skip the pre-restore backup")

    x = sub.add_parser("clear", help="delete generated data (keeps config/ and kb/sources/)")
    x.add_argument("--scope", choices=["data", "full"], default="data")
    x.add_argument("--yes", action="store_true", help="do it (a safety backup is taken first)")

    args = ap.parse_args()

    if args.cmd == "create":
        path = create(args.out, include_documents=not args.no_documents, quiet=args.quiet)
        return 0 if path else 1
    if args.cmd == "list":
        rows = list_backups()
        if not rows:
            print("no backups yet")
        for r in rows:
            print(f"  {r['at']}  {r['bytes'] / 1048576:8.1f} MB  {r['name']}")
        return 0
    if args.cmd == "inspect":
        meta = inspect(args.zip)
        if meta.get("error"):
            print(meta["error"], file=sys.stderr)
            return 2
        print(json.dumps(meta, indent=2))
        return 0
    if args.cmd == "restore":
        if not args.yes:
            print("refusing without --yes (this overwrites the current state)", file=sys.stderr)
            return 2
        res = restore(args.zip, safety=not args.no_safety)
        if res.get("error"):
            print(res["error"], file=sys.stderr)
            return 1
        return 0
    if args.cmd == "clear":
        if not args.yes:
            print("refusing without --yes (this deletes the register and documents)", file=sys.stderr)
            return 2
        res = clear(args.scope)
        if res.get("error"):
            print(res["error"], file=sys.stderr)
            return 1
        return 0
    ap.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
