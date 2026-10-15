#!/usr/bin/env python3
"""Gate-pass receipts — cryptographic proof that the pre-submit gates passed.

The integrity promise of this project ("never send a document that fails the
gate") should not depend on an agent *choosing* to run the gate. So the gates
write a small JSON **receipt** on PASS, keyed by the sha256 of the exact files
they validated, and `record_submission.py` refuses to record a `SUBMITTED` row
unless a matching, fresh receipt exists for the CV and letter being uploaded.

Receipts live in `state/gates/` (git-ignored).

Use as a library:
    import gate_receipt as GR
    GR.emit("documents", {"cv": cv_path, "letter": letter_path})
    ok, why = GR.find_pass({"cv": cv_path, "letter": letter_path})

Env:
    GATES_DIR          override the receipts directory
    GATE_MAX_AGE_HOURS how long a receipt stays valid (default 168 = 7 days)
"""
import hashlib
import json
import os
import time
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GATES_DIR = os.environ.get("GATES_DIR", os.path.join(ROOT, "state", "gates"))
DEFAULT_MAX_AGE_HOURS = float(os.environ.get("GATE_MAX_AGE_HOURS", "168"))


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _resolve(path):
    if not path:
        return ""
    return path if os.path.isabs(path) else os.path.join(ROOT, path)


def _hashes(files):
    """{name: sha256} for the files that exist; missing/empty entries dropped."""
    out = {}
    for name, path in (files or {}).items():
        if path and os.path.isfile(_resolve(path)):
            out[name] = _sha256(_resolve(path))
    return out


def emit(gate, files, meta=None):
    """Write a PASS receipt for `gate` covering `files` ({name: path}).

    Returns the receipt path, or None if there was nothing to hash.
    """
    hs = _hashes(files)
    if not hs:
        return None
    os.makedirs(GATES_DIR, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    key = hashlib.sha256(
        "|".join(f"{k}:{v}" for k, v in sorted(hs.items())).encode()
    ).hexdigest()[:12]
    rec = {
        "gate": gate,
        "result": "PASS",
        "at": stamp,
        "at_epoch": time.time(),
        "files": {
            k: {"path": os.path.relpath(_resolve(v), ROOT) if _resolve(v).startswith(ROOT) else _resolve(v),
                "sha256": hs[k]}
            for k, v in files.items() if k in hs
        },
        "meta": meta or {},
    }
    path = os.path.join(GATES_DIR, f"{gate}-{stamp}-{key}.json")
    with open(path, "w") as fh:
        json.dump(rec, fh, indent=2)
    return path


def find_pass(files, max_age_hours=DEFAULT_MAX_AGE_HOURS):
    """Find a fresh PASS receipt whose recorded hashes cover every given file.

    Subset semantics: a receipt for {cv, letter} satisfies a query for {cv}.
    Returns (ok: bool, detail: str).
    """
    want = _hashes(files)
    if not want:
        return False, "no gateable files supplied"
    if not os.path.isdir(GATES_DIR):
        return False, "no gate receipts exist (run the gate with --record)"
    now = time.time()
    best = None
    for name in sorted(os.listdir(GATES_DIR)):
        if not name.endswith(".json"):
            continue
        try:
            rec = json.load(open(os.path.join(GATES_DIR, name)))
        except Exception:
            continue
        if rec.get("result") != "PASS":
            continue
        age_h = (now - float(rec.get("at_epoch") or 0)) / 3600.0
        if max_age_hours and age_h > max_age_hours:
            continue
        rec_hs = {k: (v or {}).get("sha256") for k, v in (rec.get("files") or {}).items()}
        if all(rec_hs.get(k) == v for k, v in want.items()):
            if best is None or (rec.get("at_epoch") or 0) > (best.get("at_epoch") or 0):
                best = rec
    if best:
        return True, f"{best['gate']} gate PASS at {best.get('at')}"
    return False, "no fresh PASS receipt matches the files being recorded"


if __name__ == "__main__":  # tiny self-test / inspection helper
    import argparse
    ap = argparse.ArgumentParser(description="Inspect gate receipts.")
    ap.add_argument("--list", action="store_true")
    args = ap.parse_args()
    if args.list:
        if not os.path.isdir(GATES_DIR):
            print("(no receipts)")
        else:
            for n in sorted(os.listdir(GATES_DIR)):
                print(" ", n)
