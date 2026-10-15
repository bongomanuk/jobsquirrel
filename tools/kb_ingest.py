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
import os
import re
import shutil
import subprocess
import sys

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


def main():
    global _SOURCES
    ap = argparse.ArgumentParser(description="Convert kb/sources/ into GraphRAG text input.")
    ap.add_argument("--sources", default=os.path.join(ROOT, "kb", "sources"))
    ap.add_argument("--out", default=os.path.join(ROOT, "kb", "graphrag", "input"))
    args = ap.parse_args()
    _SOURCES = os.path.abspath(args.sources)
    out_dir = os.path.abspath(args.out)
    os.makedirs(out_dir, exist_ok=True)

    if not os.path.isdir(_SOURCES):
        print(f"no sources dir: {_SOURCES}")
        return 0

    ok, skipped, failed = 0, 0, 0
    for dirpath, _dirs, files in os.walk(_SOURCES):
        for fn in sorted(files):
            if fn.startswith("."):
                continue
            path = os.path.join(dirpath, fn)
            ext = os.path.splitext(fn)[1].lower()
            try:
                dest = convert(path, out_dir)
            except Exception as exc:
                print(f"  FAIL  {os.path.relpath(path, _SOURCES)}: {exc}")
                failed += 1
                continue
            if dest:
                print(f"  ok    {os.path.relpath(path, _SOURCES)} -> {os.path.relpath(dest, out_dir)}")
                ok += 1
            else:
                print(f"  skip  {os.path.relpath(path, _SOURCES)} (unsupported {ext or 'no ext'})")
                skipped += 1
    print(f"\ningested {ok} file(s) into {os.path.relpath(out_dir, ROOT)} "
          f"({skipped} skipped, {failed} failed)")
    print("next: build the index ->  python3 -m graphrag index --root kb/graphrag")
    return 0


if __name__ == "__main__":
    sys.exit(main())
