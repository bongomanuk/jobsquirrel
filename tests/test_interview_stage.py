"""Interview stage is a structured register field, separate from the status."""
import csv
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_interview_stage_roundtrip(tmp_path):
    sys.path.insert(0, os.path.join(ROOT, "tools"))
    import register as R

    app = tmp_path / "applications.csv"
    md = tmp_path / "register.md"
    with open(app, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=R.FIELDS)
        w.writeheader()
        row = {k: "" for k in R.FIELDS}
        row.update({"date": "2026-11-11", "company": "Acme", "role": "CTO",
                    "status": "INTERVIEW", "key": "acme-cto"})
        w.writerow(row)

    env = dict(os.environ, APPLICATIONS_CSV=str(app), APPLICATIONS_MD=str(md))
    code = (
        "import sys; sys.path.insert(0, r'%s'); import register as R;"
        "n = R.set_interview_stage('Acme', 'CTO', 'technical', note='stage set');"
        "r = [x for x in R.load() if x['key'] == 'acme-cto'][0];"
        "print(n, r['status'], r['interview_stage'])" % os.path.join(ROOT, "tools")
    )
    out = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "1 INTERVIEW technical"
    with open(app, newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    assert rows[0]["interview_stage"] == "technical"
    assert "stage set" in rows[0]["notes"]
