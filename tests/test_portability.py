import os
import sys
import types

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))


def test_archetype_prefix_comes_from_the_profile_not_the_code():
    import cv_builder as B
    import prepare_role as P
    assert P.CV_PREFIX == B.CV_PREFIX
    assert P.CV_PREFIX_FILE == B.CV_PREFIX + "_CV_"


def test_default_headline_is_the_configured_archetype_not_a_house_title():
    import cv_target as T
    data = T._default_data("Senior_AI_Engineer")
    assert data["headline"] != "Engineering Leader"
    assert data["headline"] == next(
        r["headline"] for r in T.B.load_archetypes() if r.get("key") == "Senior_AI_Engineer")


def test_empty_section_is_left_empty_instead_of_refilled():
    # A deliberately empty list stays empty: the sidebar defaults must not win.
    import inspect
    import cv_target as T
    src = inspect.getsource(T.render_styled) + inspect.getsource(T.render_ats)
    assert 'data.get("education") or' not in src
    assert 'data["education"] if "education" in data' in src


def test_docx_ingest_reads_table_cells(tmp_path):
    from docx import Document
    import kb_ingest
    doc = Document()
    doc.add_paragraph("Top level paragraph")
    table = doc.add_table(rows=1, cols=2)
    table.cell(0, 0).text = "Skills in a cell"
    table.cell(0, 1).text = "More in a cell"
    path = tmp_path / "table.docx"
    doc.save(path)
    text = kb_ingest.from_docx(str(path))
    assert "Top level paragraph" in text
    assert "Skills in a cell" in text


def test_venv_bin_knows_both_layouts(tmp_path):
    import bins
    unix = tmp_path / "unix" / "bin"
    win = tmp_path / "win" / "Scripts"
    unix.mkdir(parents=True)
    win.mkdir(parents=True)
    (unix / "graphrag").write_text("#!/bin/sh\n")
    (win / "graphrag.exe").write_text("")
    assert bins.venv_bin(str(tmp_path / "unix"), "graphrag").endswith("bin/graphrag")
    assert bins.venv_bin(str(tmp_path / "win"), "graphrag").endswith("graphrag.exe")
    assert bins.venv_bin(str(tmp_path / "missing"), "graphrag") == ""


def test_letter_date_is_portable():
    import cv_builder as B
    # %-d is glibc-only and raised at import on Windows; the built string must
    # simply be a day number without a leading zero.
    day = B.LETTER_DATE.split(",")[-1].strip().split(" ")[0]
    assert day.isdigit() and not day.startswith("0")
