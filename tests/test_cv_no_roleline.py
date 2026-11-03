"""The generated CV must not print the target role at the top."""
import json
import os
import subprocess
import sys

from docx import Document

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_role_line_is_not_rendered(tmp_path):
    pack = {
        "key": "demo-role",
        "company": "Acme",
        "role": "Widget Engineer",
        "role_line": "WIDGET ENGINEER",
        "tagline": "Platform engineering · delivery",
        "profile": "A profile paragraph.",
        "skills": ["Engineering: Python"],
        "experience": [{"employer": "Acme", "dates": "2020 - 2024", "title": "Engineer",
                        "location": "Stockholm", "bullets": ["Shipped a thing."]}],
        "selected_work": ["A project"],
    }
    src = tmp_path / "pack.json"
    src.write_text(json.dumps(pack))
    out = tmp_path / "out"
    out.mkdir()
    subprocess.run([sys.executable, os.path.join(ROOT, "tools", "cv_target.py"),
                    "--key", "demo-role", "--content", str(src), "--out", str(out), "--no-pdf"],
                   check=True, capture_output=True)
    doc = Document(str(out / "Peter_Hollas_CV_demo-role.docx"))
    text = "\n".join(p.text for p in doc.paragraphs)
    assert "WIDGET ENGINEER" not in text
    assert "A profile paragraph." in text
