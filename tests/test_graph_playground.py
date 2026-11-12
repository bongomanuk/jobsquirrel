"""The graph playground builds a FULL CV, not a sample of it.

It used to take the top three roles and three bullets from each, which looked
like "random things pulled out of the graph". Every role and every recorded
achievement must appear, with the graph supplying ranking and citations.
"""
import json
import os
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))

import graph_explore as G  # noqa: E402

SPEC = "thomson-reuters-senior-manager-product-analytics-data-engineering"


def _interpreter_with_parquet():
    """The graph needs pyarrow, which lives in the system interpreter here."""
    for py in (sys.executable, "/usr/bin/python3", "python3"):
        try:
            if subprocess.run([py, "-c", "import pyarrow"], capture_output=True).returncode == 0:
                return py
        except Exception:
            continue
    return ""


@pytest.fixture(scope="module")
def built():
    if not os.path.exists(os.path.join(G.OUT, "entities.parquet")):
        pytest.skip("no knowledge-graph index")
    if not os.path.exists(os.path.join(ROOT, "state", "job-descriptions", SPEC + ".md")):
        pytest.skip("no saved job spec for the fixture role")
    py = _interpreter_with_parquet()
    if not py:
        pytest.skip("no interpreter with parquet support")
    # Run it the way the dashboard does: the tool's own CLI, in the interpreter
    # that can read the index.
    r = subprocess.run([py, os.path.join(ROOT, "tools", "graph_explore.py"),
                        "playground", SPEC, "2", "cv"],
                       capture_output=True, text=True, timeout=180)
    data = json.loads(r.stdout or "{}")
    if data.get("error"):
        pytest.fail(data["error"])
    return data


def test_every_role_in_the_record_is_written(built):
    doc = built["doc"]
    roles = [b for b in doc["blocks"] if b.get("type") == "experience"][0]["roles"]
    cv = json.load(open(os.path.join(ROOT, "config", "cv.json")))
    assert len(roles) == len(cv.get("experience") or []), "the CV must carry the whole career"
    for role in roles:
        assert role["heading"] and role["sentences"], role


def test_no_achievement_is_dropped(built):
    doc = built["doc"]
    roles = [b for b in doc["blocks"] if b.get("type") == "experience"][0]["roles"]
    written = sum(len(r["sentences"]) for r in roles)
    cv = json.load(open(os.path.join(ROOT, "config", "cv.json")))
    expected = sum(len([b for b in (e.get("bullets") or []) if str(b).strip()])
                   for e in (cv.get("experience") or []))
    assert written == expected


def test_the_document_has_every_section(built):
    headings = [b.get("heading") for b in built["doc"]["blocks"]]
    assert headings[:4] == ["Professional summary", "Core skills", "Experience",
                            "Education & certifications"]
    edu = [b for b in built["doc"]["blocks"] if b["heading"].startswith("Education")][0]["sentences"]
    text = " ".join(s["text"] for s in edu)
    assert "Education:" in text and "Certifications:" in text
    skills = [b for b in built["doc"]["blocks"] if b["heading"] == "Core skills"][0]["sentences"]
    assert len(skills) >= 6, "skills are the record, not just the advert's matches"


def test_the_document_carries_no_build_metadata(built):
    """Counts, coverage and graph labels belong in the rail, not in the CV."""
    doc = built["doc"]
    assert doc.get("subtitle", "") == "", "no counts under the title"
    assert doc.get("meta"), "the counts still exist, in the rail field"
    text = " ".join(
        [s["text"] for b in doc["blocks"] for s in (b.get("sentences") or [])]
        + [s["text"] for b in doc["blocks"] for r in (b.get("roles") or [])
           for s in (r.get("sentences") or [])])
    for banned in ("evidence nodes", "requirements evidenced", "connections"):
        assert banned not in text, banned
    summary = [b for b in doc["blocks"] if b["heading"] == "Professional summary"][0]["sentences"]
    assert all("with evidence across" not in s["text"] for s in summary)
    assert all(s["text"].count("·") == 0 for s in summary), "no separator-joined node titles"


def test_the_build_is_animated_step_by_step(built):
    steps = built["steps"]
    writes = [s for s in steps if s["kind"] == "write"]
    assert len(writes) >= 6, "one write step per role at least"
    assert any(s["kind"] == "query" for s in steps), "the traversal is shown"
    assert steps[-1]["kind"] == "gate", "the build ends on the grounding gate"
    roles = [b for b in built["doc"]["blocks"] if b.get("type") == "experience"][0]["roles"]
    labels = [s["label"] for s in writes]
    for role in roles:
        employer = role["heading"].split(" — ")[0]
        assert any(employer in lb for lb in labels), f"no step writes {employer}"


def test_every_line_carries_its_grounding(built):
    """Provenance is measured per line, not asserted per document."""
    doc = built["doc"]
    g = doc.get("gating") or {}
    assert g.get("sentences", 0) >= 40
    assert 0 <= g.get("grounded", 0) <= g.get("sentences", 0)
    lines = [s for b in doc["blocks"] for s in (b.get("sentences") or [])]
    lines += [s for b in doc["blocks"] for r in (b.get("roles") or [])
              for s in (r.get("sentences") or [])]
    assert all("grounding" in s for s in lines), "a line without a grounding record"
    assert all(0.0 <= s["grounding"]["score"] <= 1.0 for s in lines)
    # the ones that do not clear the bar are listed, never hidden
    weak = [s for s in lines if not s["grounding"]["grounded"]]
    assert len(weak) == len(g.get("ungrounded") or [])


def test_the_graph_supplies_requirement_coverage(built):
    cov = built["doc"].get("coverage") or []
    assert cov, "no requirement-to-evidence map"
    assert all(c["keyword"] and c["nodes"] for c in cov)
    assert len(cov) <= 14


def test_each_line_marks_the_words_the_graph_produced(built):
    """The document highlights its own provenance: matched requirements and cited
    entities that actually appear in the line."""
    doc = built["doc"]
    lines = [s for b in doc["blocks"] for s in (b.get("sentences") or [])]
    lines += [s for b in doc["blocks"] for r in (b.get("roles") or [])
              for s in (r.get("sentences") or [])]
    assert all("marks" in s for s in lines), "a line without marks"
    marked = [s for s in lines if s["marks"]]
    assert len(marked) >= len(lines) // 2, "most lines should carry graph-derived words"
    for s in lines:
        low = s["text"].lower()
        for m in s["marks"]:
            assert m.lower() in low, (m, s["text"][:80])
