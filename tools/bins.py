#!/usr/bin/env python3
"""Find external binaries on any platform.

shutil.which only searches PATH. On Windows, LibreOffice and poppler are
usually installed under Program Files and never on PATH, so a gate or a PDF
conversion silently reports "missing" on a machine that has the tool.

Every lookup also accepts an explicit override: set SOFFICE_BIN, PDFTOTEXT_BIN
or PDFINFO_BIN to the full path and it wins.
"""
from __future__ import annotations

import glob
import os
import shutil

_WINDOWS_DIRS = [
    r"C:\Program Files",
    r"C:\Program Files (x86)",
]

# Direct hits first, then globs for versioned install dirs.
_WINDOWS = {
    "soffice": [
        r"C:\Program Files\LibreOffice\program\soffice.exe",
        r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
    ],
    "libreoffice": [
        r"C:\Program Files\LibreOffice\program\soffice.exe",
        r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
    ],
    "pdftotext": [
        r"C:\Program Files\poppler\Library\bin\pdftotext.exe",
        r"C:\Program Files\poppler\bin\pdftotext.exe",
    ],
    "pdfinfo": [
        r"C:\Program Files\poppler\Library\bin\pdfinfo.exe",
        r"C:\Program Files\poppler\bin\pdfinfo.exe",
    ],
}

_WINDOWS_GLOBS = {
    "pdftotext": [
        r"poppler*\Library\bin\pdftotext.exe",
        r"poppler*\bin\pdftotext.exe",
        r"**\poppler*\Library\bin\pdftotext.exe",
    ],
    "pdfinfo": [
        r"poppler*\Library\bin\pdfinfo.exe",
        r"poppler*\bin\pdfinfo.exe",
        r"**\poppler*\Library\bin\pdfinfo.exe",
    ],
}

_POSIX = {
    "soffice": [
        "/Applications/LibreOffice.app/Contents/MacOS/soffice",  # macOS
        "/usr/lib/libreoffice/program/soffice",
        "/opt/libreoffice/program/soffice",
    ],
    "libreoffice": [
        "/Applications/LibreOffice.app/Contents/MacOS/soffice",
        "/usr/lib/libreoffice/program/soffice",
        "/opt/libreoffice/program/soffice",
    ],
}


def venv_bin(venv_dir: str, name: str) -> str:
    """A command inside a virtualenv, on either layout.

    A venv is bin/<cmd> on Unix and Scripts/<cmd>.exe on Windows. Tools that
    only looked for bin/ reported "missing" on Windows even when it was there.
    """
    if not venv_dir:
        return ""
    candidates = [os.path.join(venv_dir, "bin", name),
                  os.path.join(venv_dir, "Scripts", name + ".exe"),
                  os.path.join(venv_dir, "Scripts", name)]
    for path in candidates:
        if os.path.exists(path):
            return path
    return ""


def venv_python(venv_dir: str) -> str:
    """The interpreter inside a virtualenv, on either layout."""
    return (venv_bin(venv_dir, "python3") or venv_bin(venv_dir, "python")
            or venv_bin(venv_dir, "python3.exe"))


def find(name: str) -> str:
    """Full path to `name`, or "" when it is not installed."""
    override = os.environ.get(name.upper() + "_BIN")
    if override and os.path.exists(override):
        return override

    found = shutil.which(name)
    if found:
        return found

    for path in (_WINDOWS if os.name == "nt" else _POSIX).get(name, []):
        if os.path.exists(path):
            return path

    if os.name == "nt":
        for base in _WINDOWS_DIRS:
            for pattern in _WINDOWS_GLOBS.get(name, []):
                hits = glob.glob(os.path.join(base, pattern), recursive=True)
                if hits:
                    return sorted(hits)[0]
    return ""


def require(name: str) -> str:
    path = find(name)
    if not path:
        raise RuntimeError(f"{name} not found (install it, or set {name.upper()}_BIN)")
    return path
