"""Register guards: unproven SUBMITTED, status lies the audit must catch,
and company-only notes that must not flip several roles at once."""
import csv
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))

import register as R

SUB_FIELDS = ["date", "company", "role", "ats", "apply_url", "status", "confidence",
              "cv_file", "cv_sha256", "letter_file", "letter_sha256", "evidence",
              "snapshot_dir", "recorded_at"]


@pytest.fixture()
def reg(tmp_path, monkeypatch):
    path = lambda n: str(tmp_path / n)  # noqa: E731
    monkeypatch.setattr(R, "CSV_PATH", path("apps.csv"))
    monkeypatch.setattr(R, "MD_PATH", path("register.md"))
    monkeypatch.setattr(R, "LOCK_PATH", path("apps.csv.lock"))
    monkeypatch.setattr(R, "COUNTS_PATH", path("counts.md"))
    monkeypatch.setattr(R, "QUEUE_PATH", path("queue.tsv"))
    monkeypatch.setattr(R, "DONE_PATH", path("queue.done"))
    monkeypatch.setattr(R, "SUBMISSIONS_PATH", path("subs.csv"))
    monkeypatch.setattr(R, "DRAFTS_DIR", path("drafts"))
    monkeypatch.setattr(R, "JD_DIR", path("job-descriptions"))
    os.makedirs(path("job-descriptions"), exist_ok=True)
    # a saved advert for the fixture roles that reach a live status
    for slug in ("acme-engineer", "neko-health-director-of-engineering"):
        (tmp_path / "job-descriptions" / f"{slug}.md").write_text("# Ad\n")
    open(path("apps.csv"), "w").write(",".join(R.FIELDS) + "\n")
    open(path("queue.tsv"), "w").write("")
    open(path("queue.done"), "w").write("")
    open(path("counts.md"), "w").write("total: 0\n")
    open(path("subs.csv"), "w").write(",".join(SUB_FIELDS) + "\n")
    os.makedirs(path("drafts"), exist_ok=True)
    return tmp_path


def _counts(tmp_path, n):
    (tmp_path / "counts.md").write_text(f"total: {n}\n")


def _ledger(tmp_path, company, role, status="SUBMITTED"):
    with open(tmp_path / "subs.csv", "a", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=SUB_FIELDS)
        w.writerow({"date": "2026-11-03", "company": company, "role": role,
                    "status": status, "confidence": "verified"})


def test_submitted_requires_provenance(reg):
    with pytest.raises(ValueError):
        R.upsert("Acme", "Engineer", "SUBMITTED")
    # the annotation is not a shortcut on a new claim either
    with pytest.raises(ValueError):
        R.upsert("Acme", "Engineer", "SUBMITTED", notes="provenance not recorded")
    # a real ledger row unblocks it
    R.upsert("Beta", "Architect", "PREPARED")
    _ledger(reg, "Beta", "Architect")
    R.upsert("Beta", "Architect", "SUBMITTED")


def test_existing_pre_ledger_annotation_is_accepted(reg):
    # a row written before the ledger existed, annotated by --record-provenance-gaps
    with open(reg / "apps.csv", "a", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=R.FIELDS)
        w.writerow({"date": "2026-10-01", "company": "Legacy", "role": "Engineer",
                    "status": "SUBMITTED", "notes": "provenance not recorded",
                    "key": R.make_key("Legacy", "Engineer")})
    R.set_row("Legacy", "Engineer", status="SUBMITTED", note="re-affirmed")
    assert R.find_row("Legacy", "Engineer")["status"] == "SUBMITTED"


def test_audit_flags_prepared_that_was_emailed(reg, capsys):
    R.upsert("Acme", "Engineer", "PREPARED")
    _counts(reg, 1)
    d = reg / "drafts" / "acme-engineer"
    d.mkdir()
    draft = d / "20261103-120000.txt"
    draft.write_text("To: hr@acme.test\nSubject: Application\nAttachment: Peter_Hollas_CV_Acme.docx\n"
                     "Company: Acme\nRole: Engineer\n---\nHi\n")
    (reg / "drafts" / "sent.json").write_text(json.dumps({str(draft): {"at": "2026-11-03T12:00:00"}}))
    assert R.audit() == 1
    out = capsys.readouterr().out
    assert "PREPARED but an application email with attachments was sent" in out


def test_audit_flags_interview_without_evidence(reg, capsys):
    R.upsert("Acme", "Engineer", "INTERVIEW", notes="applied and waiting")
    _counts(reg, 1)
    assert R.audit() == 1
    assert "INTERVIEW without an invitation" in capsys.readouterr().out


def test_audit_accepts_interview_with_evidence(reg, capsys):
    R.upsert("Acme", "Engineer", "INTERVIEW", notes="gmail: INTERVIEW Tue, 3 Nov 2026 (invited)")
    _counts(reg, 1)
    assert R.audit() == 0


def test_audit_flags_finished_queue_alias(reg, capsys):
    R.upsert("Neko Health", "Director of Engineering", "REJECTED")
    _counts(reg, 1)
    (reg / "queue.tsv").write_text(
        "Neko Health starting at $405K/year\tDirector of Engineering\thttps://x\t\t\talias-key\n")
    (reg / "queue.done").write_text("alias-key\n")
    assert R.audit() == 1
    assert "queue alias of a register row" in capsys.readouterr().out


def test_add_note_never_flips_several_rows(reg):
    R.upsert("Acme", "Engineer", "PREPARED")
    R.upsert("Acme", "Architect", "PREPARED")
    R.add_note("Acme", "gmail: INTERVIEW", status="INTERVIEW")
    rows = R.load()
    assert all(r["status"] != "INTERVIEW" for r in rows)
    assert all("gmail: INTERVIEW" in r["notes"] for r in rows)
    # a unique match still transitions
    R.add_note("Engineer", "gmail: INTERVIEW", status="INTERVIEW")
    assert R.find_row("Acme", "Engineer")["status"] == "INTERVIEW"
