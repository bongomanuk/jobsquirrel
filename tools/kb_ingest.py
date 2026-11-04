#!/usr/bin/env python3
"""Ingest your personal documents into GraphRAG-ready text.

"Feed it everything" should actually work: this scans kb/sources/ and converts
whatever you have — PDF, DOCX, DOC/ODT, HTML, Markdown, email, CSV/JSON — into
plain text in the GraphRAG input folder, so you don't have to convert anything by
hand.

    python3 tools/kb_ingest.py [--sources kb/sources] [--out kb/graphrag/input]

Dependencies are optional and degrade gracefully: pdftotext/pypdf for PDF,
python-docx for DOCX, and LibreOffice (soffice) for legacy DOC/ODT. Text/Markdown
files are copied as-is; GraphRAG-native .csv/.json/.txt are handled directly.
"""
import argparse
import fnmatch
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SOURCES = ""  # set in main(); used for naming converted outputs

TEXT_EXT = {".txt", ".md", ".markdown"}
NATIVE_EXT = {".csv", ".json"}          # GraphRAG reads these directly
PDF_EXT = {".pdf"}
DOCX_EXT = {".docx"}
OFFICE_EXT = {".doc", ".odt", ".rtf", ".pptx"}
HTML_EXT = {".html", ".htm"}


def _slug(path, root):
    rel = os.path.relpath(path, root).replace(os.sep, "_")
    return re.sub(r"[^A-Za-z0-9._-]+", "_", rel)


def _write(out_dir, src, text, ext=".txt"):
    base = os.path.splitext(_slug(src, _SOURCES))[0]
    name = base + ext
    dest = os.path.join(out_dir, name)
    with open(dest, "w", encoding="utf-8", errors="ignore") as fh:
        fh.write(text)
    return dest


def from_pdf(path):
    if shutil.which("pdftotext"):
        tmp = path + ".pdftotext"
        try:
            subprocess.run(["pdftotext", "-layout", path, tmp], check=True,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            txt = open(tmp, encoding="utf-8", errors="ignore").read()
        finally:
            if os.path.isfile(tmp):
                os.remove(tmp)
        return txt
    try:
        from pypdf import PdfReader
    except ImportError:
        try:
            from PyPDF2 import PdfReader  # type: ignore
        except ImportError:
            raise RuntimeError("no PDF extractor (install poppler-utils or pypdf)")
    return "\n".join((pg.extract_text() or "") for pg in PdfReader(path).pages)


def from_docx(path):
    try:
        from docx import Document
    except ImportError:
        raise RuntimeError("python-docx not installed (pip install python-docx)")
    doc = Document(path)
    return "\n".join(p.text for p in doc.paragraphs)


def from_office(path):
    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    if not soffice:
        raise RuntimeError("LibreOffice (soffice) not found")
    outdir = os.path.dirname(os.path.abspath(path))
    subprocess.run([soffice, "--headless", "--convert-to", "txt:Text",
                    "--outdir", outdir, path], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    produced = os.path.join(outdir, os.path.splitext(os.path.basename(path))[0] + ".txt")
    if os.path.isfile(produced):
        txt = open(produced, encoding="utf-8", errors="ignore").read()
        os.remove(produced)
        return txt
    raise RuntimeError("LibreOffice produced no text")


def from_html(path):
    from html.parser import HTMLParser

    class _Strip(HTMLParser):
        def __init__(self):
            super().__init__()
            self.parts = []
            self._skip = 0

        def handle_starttag(self, tag, attrs):
            if tag in ("script", "style"):
                self._skip += 1
            if tag in ("p", "div", "br", "li", "tr", "h1", "h2", "h3"):
                self.parts.append("\n")

        def handle_endtag(self, tag):
            if tag in ("script", "style") and self._skip:
                self._skip -= 1

        def handle_data(self, data):
            if not self._skip:
                self.parts.append(data)

    p = _Strip()
    p.feed(open(path, encoding="utf-8", errors="ignore").read())
    return re.sub(r"\n{3,}", "\n\n", "".join(p.parts))


def convert(path, out_dir):
    ext = os.path.splitext(path)[1].lower()
    if ext in TEXT_EXT or ext in NATIVE_EXT:
        dest = os.path.join(out_dir, _slug(path, _SOURCES))
        shutil.copy2(path, dest)
        return dest
    if ext in PDF_EXT:
        return _write(out_dir, path, from_pdf(path))
    if ext in DOCX_EXT:
        return _write(out_dir, path, from_docx(path))
    if ext in OFFICE_EXT:
        return _write(out_dir, path, from_office(path))
    if ext in HTML_EXT:
        return _write(out_dir, path, from_html(path))
    return None


def _norm_text(t):
    return re.sub(r"\s+", " ", str(t or "").lower()).strip()


def _sha(t):
    return hashlib.sha256(t.encode("utf-8", "ignore")).hexdigest()


def _shingles(t, n=5, cap=4000):
    w = t.split()
    return set(tuple(w[i:i + n]) for i in range(min(max(0, len(w) - n + 1), cap)))


def _jaccard(a, b):
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def main():
    global _SOURCES
    ap = argparse.ArgumentParser(description="Convert kb/sources/ into GraphRAG text input.")
    ap.add_argument("--sources", default=os.path.join(ROOT, "kb", "sources"))
    ap.add_argument("--out", default=os.path.join(ROOT, "kb", "graphrag", "input"))
    ap.add_argument("--clean", action="store_true",
                    help="clear the generated input folder before writing")
    ap.add_argument("--keep-duplicates", action="store_true",
                    help="do not collapse exact/near-duplicate documents")
    ap.add_argument("--similarity", type=float, default=0.90,
                    help="near-duplicate threshold (5-word shingle Jaccard; default 0.90)")
    args = ap.parse_args()
    _SOURCES = os.path.abspath(args.sources)
    out_dir = os.path.abspath(args.out)
    os.makedirs(out_dir, exist_ok=True)

    if not os.path.isdir(_SOURCES):
        print(f"no sources dir: {_SOURCES}")
        return 0

    ignore = []
    ignore_path = os.path.join(_SOURCES, ".ingestignore")
    if os.path.isfile(ignore_path):
        for line in open(ignore_path, encoding="utf-8", errors="ignore"):
            line = line.strip()
            if line and not line.startswith("#"):
                ignore.append(line)

    if args.clean:
        for f in os.listdir(out_dir):
            fp = os.path.join(out_dir, f)
            if os.path.isfile(fp) and not f.startswith("."):
                os.remove(fp)

    # newest first: when two CVs say the same thing, keep the current one
    cands = []
    for dirpath, _dirs, files in os.walk(_SOURCES):
        for fn in sorted(files):
            if fn.startswith("."):
                continue
            path = os.path.join(dirpath, fn)
            rel = os.path.relpath(path, _SOURCES).replace(os.sep, "/")
            if any(fnmatch.fnmatch(rel, pat) for pat in ignore):
                continue
            try:
                cands.append((os.path.getmtime(path), path))
            except OSError:
                pass
    cands.sort(key=lambda x: -x[0])

    ok, skipped, failed, exact_dups, near_dups = 0, 0, 0, 0, 0
    kept = []          # {path, dest, sha, shingles, text}
    manifest = {"kept": [], "exact_duplicates": [], "near_duplicates": []}
    tmp_root = tempfile.mkdtemp(prefix="kb-ingest-")
    try:
        for _mtime, path in cands:
            rel = os.path.relpath(path, _SOURCES)
            ext = os.path.splitext(path)[1].lower()
            tmpdir = tempfile.mkdtemp(dir=tmp_root)
            try:
                dest_tmp = convert(path, tmpdir)
            except Exception as exc:
                print(f"  FAIL  {rel}: {exc}")
                failed += 1
                shutil.rmtree(tmpdir, ignore_errors=True)
                continue
            if not dest_tmp:
                print(f"  skip  {rel} (unsupported {ext or 'no ext'})")
                skipped += 1
                shutil.rmtree(tmpdir, ignore_errors=True)
                continue
            with open(dest_tmp, encoding="utf-8", errors="ignore") as fh:
                text = fh.read()
            ntext = _norm_text(text)
            if not ntext:
                print(f"  skip  {rel} (no text)")
                skipped += 1
                shutil.rmtree(tmpdir, ignore_errors=True)
                continue
            digest = _sha(ntext)
            dup = None
            if not args.keep_duplicates:
                exact = next((k for k in kept if k["sha"] == digest), None)
                if exact:
                    dup = ("exact", exact)
                else:
                    sh = _shingles(ntext)
                    best, match = 0.0, None
                    for k in kept:
                        score = _jaccard(sh, k["shingles"])
                        if score > best:
                            best, match = score, k
                    if match and best >= args.similarity:
                        dup = ("near", match, best)
            if dup:
                kind = dup[0]
                if kind == "exact":
                    exact_dups += 1
                    manifest["exact_duplicates"].append({"skipped": rel, "kept": dup[1]["path"]})
                    print(f"  dup   {rel} == {dup[1]['path']}")
                else:
                    near_dups += 1
                    manifest["near_duplicates"].append({
                        "skipped": rel, "kept": dup[1]["path"], "similarity": round(dup[2], 3)})
                    print(f"  near  {rel} ~ {dup[1]['path']} ({dup[2]:.2f})")
                shutil.rmtree(tmpdir, ignore_errors=True)
                continue
            dest = os.path.join(out_dir, os.path.basename(dest_tmp))
            if os.path.exists(dest):
                stem, ext2 = os.path.splitext(os.path.basename(dest_tmp))
                dest = os.path.join(out_dir, f"{stem}-{digest[:8]}{ext2}")
            shutil.move(dest_tmp, dest)
            kept.append({"path": rel, "dest": os.path.basename(dest), "sha": digest,
                         "shingles": _shingles(ntext)})
            manifest["kept"].append({"source": rel, "input": os.path.basename(dest)})
            print(f"  ok    {rel} -> {os.path.basename(dest)}")
            ok += 1
            shutil.rmtree(tmpdir, ignore_errors=True)
    finally:
        shutil.rmtree(tmp_root, ignore_errors=True)

    manifest["summary"] = {"kept": ok, "exact_duplicates": exact_dups,
                           "near_duplicates": near_dups, "skipped": skipped,
                           "failed": failed, "ignored": len(ignore)}
    with open(os.path.join(out_dir, ".ingest.json"), "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2)
    print(f"\ningested {ok} file(s) into {os.path.relpath(out_dir, ROOT)} "
          f"({exact_dups} exact dup, {near_dups} near dup, {skipped} skipped, {failed} failed)")
    print("next: build the index ->  python3 -m graphrag index --root kb/graphrag")
    return 0


if __name__ == "__main__":
    sys.exit(main())
