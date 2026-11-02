#!/usr/bin/env python3
"""Transparent gzip for machine-local state artifacts.

`state/` is mostly text — saved job ads, keyword files, grounding packs, content
packs, gate receipts — and it compresses 3-5x. `tools/storage.py --state` packs
the cold ones; everything that reads them goes through this module, so a packed
artifact looks exactly like a plain one.

Invariant: a path exists either plain (`x`) or packed (`x.gz`), never both. Packing
writes `x.gz` first and only then unlinks `x`; restoring writes a temp file and
`os.replace`s it over `x` before removing `x.gz`.

    import stateio
    text = stateio.read_text(path)          # reads plain or .gz, no write
    path = stateio.ensure(path)             # restores in place if packed
    for name in stateio.listdir(d):         # names without the .gz suffix
"""
from __future__ import annotations

import gzip
import os
import shutil

SUFFIX = ".gz"


def _plain(path: str) -> str:
    return path[:-len(SUFFIX)] if path.endswith(SUFFIX) else path


def variants(path: str) -> tuple[str, str]:
    plain = _plain(path)
    return plain, plain + SUFFIX


def resolve(path: str) -> str | None:
    """The file that actually exists for `path` (plain preferred), or None."""
    plain, packed = variants(path)
    if os.path.exists(plain):
        return plain
    if os.path.exists(packed):
        return packed
    return None


def exists(path: str) -> bool:
    return resolve(path) is not None


def mtime(path: str) -> int:
    found = resolve(path)
    if not found:
        return 0
    try:
        return int(os.path.getmtime(found))
    except OSError:
        return 0


def read_bytes(path: str) -> bytes | None:
    found = resolve(path)
    if not found:
        return None
    try:
        if found.endswith(SUFFIX):
            with gzip.open(found, "rb") as fh:
                return fh.read()
        with open(found, "rb") as fh:
            return fh.read()
    except (OSError, EOFError):
        return None


def read_text(path: str, encoding: str = "utf-8", errors: str = "replace") -> str:
    data = read_bytes(path)
    return "" if data is None else data.decode(encoding, errors)


def ensure(path: str) -> str | None:
    """Restore `path` in place if it is packed. Returns the plain path or None."""
    plain, packed = variants(path)
    if os.path.exists(plain):
        return plain
    if not os.path.exists(packed):
        return None
    tmp = plain + ".tmp"
    try:
        with gzip.open(packed, "rb") as src, open(tmp, "wb") as dst:
            while True:
                chunk = src.read(1024 * 1024)
                if not chunk:
                    break
                dst.write(chunk)
        os.replace(tmp, plain)
        shutil.copystat(packed, plain)   # restored file keeps the artifact's age
        os.unlink(packed)
    except (OSError, EOFError):
        try:
            os.unlink(tmp)
        except OSError:
            pass
        return plain if os.path.exists(plain) else None
    return plain


def ensure_paths(*paths: str) -> None:
    """Restore any packed path in `paths` that exists; ignore missing ones."""
    for path in paths:
        if path:
            ensure(path)


def write(path: str, data: bytes, packed: bool = False) -> str:
    """Atomically write `path` plain or packed; the other form is removed."""
    plain, gz = variants(path)
    target = gz if packed else plain
    os.makedirs(os.path.dirname(target) or ".", exist_ok=True)
    tmp = target + ".tmp"
    if packed:
        with gzip.open(tmp, "wb", compresslevel=9) as fh:
            fh.write(data)
    else:
        with open(tmp, "wb") as fh:
            fh.write(data)
    os.replace(tmp, target)
    stale = plain if packed else gz
    if os.path.exists(stale):
        try:
            os.unlink(stale)
        except OSError:
            pass
    return target


def listdir(directory: str) -> list[str]:
    """Names in `directory` with any `.gz` suffix removed, de-duplicated."""
    try:
        names = os.listdir(directory)
    except OSError:
        return []
    out = set()
    for name in names:
        if name.endswith(".tmp"):
            continue
        out.add(_plain(name) if name.endswith(SUFFIX) else name)
    return sorted(out)


def stems(directory: str, ext: str) -> list[str]:
    """File stems with `ext`, ignoring whether they are packed."""
    out = []
    for name in listdir(directory):
        if name.endswith(ext):
            out.append(name[:-len(ext)])
    return out
