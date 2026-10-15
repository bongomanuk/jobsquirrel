import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_ingest_converts_formats(tmp_path):
    src = tmp_path / "sources"
    src.mkdir()
    (src / "cv.txt").write_text("my master cv")
    (src / "brag.md").write_text("# brag\n- shipped X")
    (src / "talk.html").write_text("<html><body><h1>T</h1><p>Hi</p>"
                                   "<script>bad()</script></body></html>")
    (src / "skills.csv").write_text("skill,level\nPython,expert\n")
    out = tmp_path / "input"

    r = subprocess.run([sys.executable, "tools/kb_ingest.py",
                        "--sources", str(src), "--out", str(out)],
                       cwd=ROOT, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    files = set(os.listdir(out))
    assert {"cv.txt", "brag.md", "talk.txt", "skills.csv"} <= files
    # html tags/scripts stripped
    assert "<script" not in (out / "talk.txt").read_text()
    assert "Hi" in (out / "talk.txt").read_text()
