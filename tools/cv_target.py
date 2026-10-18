#!/usr/bin/env python3
"""Targeted CV generator.

Renders a role-specific CV from a content pack the runner produced (grounded in
the GraphRAG context), in two outputs:

  <out>/<prefix>_CV_<key>.docx   ATS-safe: single column, standard headings,
                                 no tables/text-boxes -> parses cleanly.
  <out>/<prefix>_CV_<key>.pdf    Styled two-column (human/email read).
  <prefix> is CV_PREFIX ("First_Last" from profile.md, or $CV_PREFIX).

Content pack JSON (produced by the agent from state/kb-context/<key>.md):
{
  "key": "...", "company": "...", "role": "...",
  "headline": "...", "role_line": "...", "tagline": "...",
  "profile": "role-targeted summary paragraph",
  "skills": ["Category: items", ...],
  "experience": [{"employer","dates","title","location","bullets":[...]}, ...],
  "selected_work": ["...", ...],
  "education": ["...", ...], "certifications": ["...", ...], "languages": ["...", ...]
}
Missing fields fall back to the CV-backed defaults in cv_builder.

Usage:
  python3 tools/cv_target.py --key <key> --content state/cv-content/<key>.json
  python3 tools/cv_target.py --key <key> --content <json> --out documents/applications
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import zipfile
from xml.sax.saxutils import escape as _xml_escape

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cv_builder as B  # reuse the styling primitives (no duplicated layout code)

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CORE_XML = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
    '<cp:coreProperties '
    'xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
    'xmlns:dc="http://purl.org/dc/elements/1.1/" '
    'xmlns:dcterms="http://purl.org/dc/terms/" '
    'xmlns:dcmitype="http://purl.org/dc/dcmitype/" '
    'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
    '<dc:title>{title}</dc:title>'
    '<dc:creator>{author}</dc:creator>'
    '<cp:lastModifiedBy>{author}</cp:lastModifiedBy>'
    '<cp:revision>1</cp:revision>'
    '<dcterms:created xsi:type="dcterms:W3CDTF">{when}</dcterms:created>'
    '<dcterms:modified xsi:type="dcterms:W3CDTF">{when}</dcterms:modified>'
    '</cp:coreProperties>'
)
APP_XML = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
    '<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties" '
    'xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes">'
    '<Application>Microsoft Office Word</Application><AppVersion>16.0000</AppVersion>'
    '<Company></Company></Properties>'
)


def scrub_metadata(path, author=None, title="", when="2026-09-28T09:00:00Z"):
    """Remove generation tell-tales (python-docx author/application) from the docx."""
    author = author or B.NAME
    tmp = path + ".scrub"
    with zipfile.ZipFile(path) as zin:
        items = {n: zin.read(n) for n in zin.namelist()}
    items["docProps/core.xml"] = CORE_XML.format(
        title=_xml_escape(title), author=_xml_escape(author), when=when).encode()
    items["docProps/app.xml"] = APP_XML.encode()
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zout:
        for n, data in items.items():
            zout.writestr(n, data)
    os.replace(tmp, path)


def _default_data(key):
    """Fallback content from the CV-backed defaults."""
    exp = []
    for e in B.EXPERIENCE:
        emp, _, ttl = e["org"].partition("  |  ")
        exp.append({"employer": emp.strip(), "title": ttl.strip(),
                    "dates": e["dates"].split("  |  ")[0].strip(),
                    "location": (e["dates"].split("  |  ")[1].strip() if "  |  " in e["dates"] else ""),
                    "bullets": list(e["core"])})
    return {
        "key": key, "company": "", "role": "",
        "headline": "Engineering Leader", "role_line": "ENGINEERING LEADER",
        "tagline": "Engineering leadership  ·  Platform architecture  ·  AI  ·  Security",
        "profile": "", "skills": [], "experience": exp,
        "selected_work": list(B.PROJECTS),
        "education": list(B.SIDEBAR["education"]),
        "certifications": list(B.SIDEBAR["certificates"]),
        "languages": list(B.SIDEBAR["languages"]),
    }


# ---------------- ATS-safe single column ----------------
def render_ats(data, path):
    doc = B.new_doc(font="Calibri")
    for s in doc.sections:
        s.top_margin = B.Cm(0.9); s.bottom_margin = B.Cm(0.8)
        s.left_margin = B.Cm(1.2); s.right_margin = B.Cm(1.2)

    p = doc.add_paragraph(); p.paragraph_format.space_after = B.Pt(0)
    r = p.add_run(B.CVD_NAME); r.bold = True; r.font.size = B.Pt(16); r.font.color.rgb = B.DARK
    p = doc.add_paragraph(); p.paragraph_format.space_after = B.Pt(1)
    r = p.add_run("  |  ".join(x for x in (B._EMAIL, B._PHONE, B._LOCATION, B._LINKEDIN) if x))
    r.font.size = B.Pt(9); r.font.color.rgb = B.GREY
    if data.get("role_line"):
        p = doc.add_paragraph(); p.paragraph_format.space_after = B.Pt(6)
        r = p.add_run(data["role_line"]); r.font.size = B.Pt(10); r.font.color.rgb = B.ACCENT

    def h(text):
        hp = doc.add_paragraph(); hp.paragraph_format.space_before = B.Pt(5); hp.paragraph_format.space_after = B.Pt(1.0)
        rr = hp.add_run(text.upper()); rr.bold = True; rr.font.size = B.Pt(10.5); rr.font.color.rgb = B.ACCENT

    def bullet(text):
        bp = doc.add_paragraph(); bp.paragraph_format.left_indent = B.Cm(0.5); bp.paragraph_format.first_line_indent = B.Cm(-0.35)
        bp.paragraph_format.space_after = B.Pt(0.8)
        r0 = bp.add_run("\u2022  "); r0.font.size = B.Pt(8.5)
        rr = bp.add_run(text); rr.font.size = B.Pt(8.5)

    if data.get("profile"):
        h("Professional summary")
        doc.add_paragraph(data["profile"]).runs[0].font.size = B.Pt(8.5)
    if data.get("skills"):
        h("Core skills")
        for s in data["skills"]:
            bullet(s)
    h("Experience")
    for e in data["experience"]:
        ep = doc.add_paragraph(); ep.paragraph_format.space_before = B.Pt(4); ep.paragraph_format.space_after = B.Pt(0)
        r = ep.add_run(e.get("employer", "")); r.bold = True; r.font.size = B.Pt(9.5)
        meta = "  |  ".join(x for x in (e.get("title", ""), e.get("dates", ""), e.get("location", "")) if x)
        mp = doc.add_paragraph(); mp.paragraph_format.space_after = B.Pt(2)
        rr = mp.add_run(meta); rr.italic = True; rr.font.size = B.Pt(8.0); rr.font.color.rgb = B.GREY
        for b in e.get("bullets", []):
            bullet(b)
        for g in e.get("groups", []):
            label = g.get("label", "")
            if label:
                gp = doc.add_paragraph(); gp.paragraph_format.space_before = B.Pt(2); gp.paragraph_format.space_after = B.Pt(0.5)
                gp.paragraph_format.left_indent = B.Cm(0.1)
                gr = gp.add_run(label); gr.bold = True; gr.italic = True; gr.font.size = B.Pt(8.5); gr.font.color.rgb = B.ACCENT
            for b in g.get("bullets", []):
                bullet(b)
    if data.get("selected_work"):
        h("Selected work")
        for b in data["selected_work"]:
            bullet(b)
    education = []
    for item in ((data.get("education") or [])
                 + (data.get("certifications") or B.SIDEBAR["certificates"])
                 + (data.get("languages") or B.SIDEBAR["languages"])):
        if item and item not in education:
            education.append(item)
    if education:
        h("Education and certifications")
        for b in education:
            bullet(b)
    doc.save(path)
    scrub_metadata(path, title=f"{B.CVD_NAME} — {data.get('role','CV')}")


# ---------------- styled two-column ----------------
def render_styled(data, path):
    doc = B.new_doc(font="Georgia")
    for s in doc.sections:
        s.top_margin = B.Cm(0); s.bottom_margin = B.Cm(0); s.left_margin = B.Cm(0); s.right_margin = B.Cm(0)
    if os.path.exists(os.path.join(_REPO, "documents", "assets", "sidebar_bar.png")):
        try:
            B.add_page_bar(doc, os.path.join(_REPO, "documents", "assets", "sidebar_bar.png"), 6.2, 29.7)
        except Exception:
            pass
    tbl = doc.add_table(rows=1, cols=2); tbl.autofit = False; B._no_borders(tbl)
    layout = B.OxmlElement('w:tblLayout'); layout.set(B.qn('w:type'), 'fixed'); tbl._tbl.tblPr.append(layout)
    tw = B.OxmlElement('w:tblW'); tw.set(B.qn('w:w'), str(int(21.0 * 567))); tw.set(B.qn('w:type'), 'dxa'); tbl._tbl.tblPr.append(tw)
    left, right = tbl.cell(0, 0), tbl.cell(0, 1)
    left.width = B.Cm(6.2); right.width = B.Cm(14.8)
    tbl.columns[0].width = B.Cm(6.2); tbl.columns[1].width = B.Cm(14.8)
    if B.HEADSHOT and os.path.exists(B.HEADSHOT):
        try:
            ph = left.paragraphs[0]; ph.alignment = B.WD_ALIGN_PARAGRAPH.CENTER; ph.paragraph_format.space_after = B.Pt(6)
            ph.add_run().add_picture(B.HEADSHOT, width=B.Cm(3.3))
        except Exception:
            pass
    contact = [x for x in (B._PHONE, B._EMAIL, B._LOCATION, B._WEBSITE, B._LINKEDIN, *B._OTHER_SITES) if x]
    education = data.get("education") or B.SIDEBAR["education"]
    certifications = data.get("certifications") or B.SIDEBAR["certificates"]
    languages = data.get("languages") or B.SIDEBAR["languages"]
    # Never print a heading with nothing under it, and don't repeat a line twice.
    seen = set()

    def uniq(lines):
        out = []
        for line in lines or []:
            if line and line not in seen:
                seen.add(line); out.append(line)
        return out

    if contact:
        B.s_head(left, "Contact")
        for line in contact:
            B.s_text(left, line)
    if education:
        B.s_head(left, "Education")
        for line in uniq(education):
            B.s_text(left, line)
    if certifications:
        B.s_head(left, "Certificates")
        for line in uniq(certifications):
            B.s_text(left, line)
    if B.SIDEBAR["leadership"]:
        B.s_head(left, "Leadership")
        for line in uniq(B.SIDEBAR["leadership"]):
            B.s_text(left, line, bullet=True)
    if languages:
        B.s_head(left, "Languages")
        for line in uniq(languages):
            B.s_text(left, line)
    if data.get("skills"):
        B.s_head(left, "Core skills")
        for s in data["skills"][:8]:
            B.s_text(left, s, bullet=True)
    if B.SIDEBAR["strengths"]:
        B.s_head(left, "Additional strengths")
        for line in B.SIDEBAR["strengths"]:
            B.s_text(left, line, bullet=True)

    p = right.paragraphs[0]; p.paragraph_format.space_after = B.Pt(0)
    r = p.add_run(B.CVD_NAME.upper()); r.bold = True; r.font.size = B.Pt(24); r.font.color.rgb = B.NAVY; B._tracking(r, 20)
    p = right.add_paragraph(); p.paragraph_format.space_after = B.Pt(0)
    r = p.add_run(data.get("role_line", "ENGINEERING LEADER")); r.font.size = B.Pt(11); r.font.color.rgb = B.NAVY; B._tracking(r, 40)
    p = right.add_paragraph(); p.paragraph_format.space_after = B.Pt(2)
    r = p.add_run(data.get("tagline", "")); r.italic = True; r.font.size = B.Pt(10.5); r.font.color.rgb = B.GREY
    if data.get("profile"):
        B.m_head(right, "Profile"); B.m_body(right, data["profile"], size=9.0)
    B.m_head(right, "Work experience")
    for e in data["experience"]:
        B.m_entry(right, e.get("employer", ""), e.get("dates", ""), e.get("title", ""), e.get("bullets", []), [], 13.4, groups=e.get("groups"))
    if data.get("selected_work"):
        B.m_head(right, "Selected work")
        for b in data["selected_work"]:
            B.m_bullet(right, b)
    doc.save(path)
    scrub_metadata(path, title=f"{B.CVD_NAME} — {data.get('role','CV')}")


def to_pdf(docx_path):
    out = os.path.dirname(docx_path) or "."
    subprocess.run(["soffice", "--headless", "--convert-to", "pdf", "--outdir", out, docx_path],
                   capture_output=True, text=True, timeout=180)
    return os.path.splitext(docx_path)[0] + ".pdf"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--key", required=True)
    ap.add_argument("--content", help="path to content JSON")
    ap.add_argument("--out", default=os.path.join(_REPO, "documents", "applications"))
    ap.add_argument("--no-pdf", action="store_true")
    args = ap.parse_args()

    data = json.load(open(args.content)) if args.content else _default_data(args.key)
    data.setdefault("key", args.key)
    # The profile is a high-level professional summary: flag implementation details.
    low = ["websocket", "scylladb", "talend", "apigee", "spring cloud data flow", "camel",
           "coap", "mqtt", "xmpp", "kafka", "postgres", "kubernetes", "terraform", "keycloak",
           "svelte", "prometheus", "zeromq", "0mq", "mule", "hibernate", "graphql", "sqlite",
           "monte carlo", "lp/mip", "rest api", "ci/cd", "spring boot", "mcp", "rag"]
    hits = [t for t in low if t in (data.get("profile") or "").lower()]
    if hits:
        print(f"WARN profile contains implementation detail (move to experience): {hits}")
    os.makedirs(args.out, exist_ok=True)
    ats = os.path.join(args.out, f"{B.CV_PREFIX}_CV_{args.key}.docx")
    render_ats(data, ats)
    print("wrote", ats)
    if not args.no_pdf:
        styled = os.path.join(args.out, f".styled_{args.key}.docx")
        render_styled(data, styled)
        pdf = to_pdf(styled)
        os.replace(pdf, os.path.join(args.out, f"{B.CV_PREFIX}_CV_{args.key}.pdf"))
        os.remove(styled)
        print("wrote", os.path.join(args.out, f"{B.CV_PREFIX}_CV_{args.key}.pdf"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
