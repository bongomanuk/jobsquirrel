"""Backup, restore and clear: the zip is the thing you fall back on, so every
test asserts the round trip and the guardrails (no traversal, no symlinks,
config and sources survive a clear, a safety backup is always taken)."""
import gzip
import io
import json
import os
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))

import backup  # noqa: E402


def _write(path, text="x"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _root(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    (root / "config").mkdir(parents=True)
    (root / "answers").mkdir()
    (root / "state" / "logs").mkdir(parents=True)
    (root / "state" / "job-descriptions").mkdir(parents=True)
    (root / "documents" / "applications").mkdir(parents=True)
    (root / "kb" / "sources").mkdir(parents=True)
    _write(root / "VERSION", "9.9.9\n")
    _write(root / "config" / "profile.md", "name: Test")
    _write(root / "config" / "cv.json", '{"name": "Test"}')
    _write(root / "answers" / "personal-details.md", "details")
    _write(root / "state" / "applications.csv", "date,company\n")
    _write(root / "state" / "job-descriptions" / "acme.md", "the ad")
    _write(root / "state" / "logs" / "acme.log", "noise")
    _write(root / "state" / "gmail_cache.json", "{}")
    _write(root / "documents" / "applications" / "cv.docx", "docx bytes")
    _write(root / "kb" / "sources" / "master.md", "career facts")
    monkeypatch.setattr(backup, "ROOT", str(root))
    monkeypatch.setattr(backup, "BACKUP_DIR", str(root / "backups"))
    return root


def test_backup_contains_the_state_but_not_logs_or_cache(tmp_path, monkeypatch):
    root = _root(tmp_path, monkeypatch)
    path = backup.create(quiet=True)

    with zipfile.ZipFile(path) as zf:
        names = set(zf.namelist())
        meta = json.loads(zf.read("BACKUP.json"))

    assert "config/profile.md" in names
    assert "answers/personal-details.md" in names
    assert "state/applications.csv" in names
    assert "state/job-descriptions/acme.md" in names
    assert "kb/sources/master.md" in names
    assert "documents/applications/cv.docx" in names
    assert "state/logs/acme.log" not in names, "transcripts stay out of a backup"
    assert "state/gmail_cache.json" not in names, "the mail cache is derived data"
    assert meta["kind"] == "jobsquirrel-backup" and meta["version"] == "9.9.9"
    assert meta["files"] == len(names) - 1


def test_no_documents_keeps_the_zip_small(tmp_path, monkeypatch):
    _root(tmp_path, monkeypatch)
    path = backup.create(quiet=True, include_documents=False)
    with zipfile.ZipFile(path) as zf:
        assert not any(n.startswith("documents/") for n in zf.namelist())
        assert "state/applications.csv" in zf.namelist()


def test_inspect_rejects_a_random_zip(tmp_path, monkeypatch):
    _root(tmp_path, monkeypatch)
    other = tmp_path / "other.zip"
    with zipfile.ZipFile(other, "w") as zf:
        zf.writestr("hello.txt", "hi")
    assert "BACKUP.json" in backup.inspect(str(other))["error"]


def test_restore_brings_files_back_and_takes_a_safety_copy(tmp_path, monkeypatch):
    root = _root(tmp_path, monkeypatch)
    path = backup.create(quiet=True)

    (root / "config" / "profile.md").write_text("edited", encoding="utf-8")
    (root / "state" / "applications.csv").unlink()
    (root / "kb" / "sources" / "master.md").unlink()

    res = backup.restore(path, quiet=True)
    assert res["restored"] > 0, res
    assert (root / "config" / "profile.md").read_text() == "name: Test"
    assert (root / "state" / "applications.csv").exists()
    assert (root / "kb" / "sources" / "master.md").exists()
    assert res["safety"] and os.path.isfile(res["safety"]), "a pre-restore copy is mandatory"


def test_restore_replaces_a_packed_twin(tmp_path, monkeypatch):
    """Restoring the plain file must not leave a stale .gz beside it."""
    root = _root(tmp_path, monkeypatch)
    path = backup.create(quiet=True)
    ad = root / "state" / "job-descriptions" / "acme.md"
    with gzip.open(str(ad) + ".gz", "wb") as fh:
        fh.write(b"stale")
    ad.unlink()

    backup.restore(path, quiet=True)
    assert ad.read_text() == "the ad"
    assert not os.path.exists(str(ad) + ".gz")


def test_restore_ignores_traversal_and_foreign_paths(tmp_path, monkeypatch):
    root = _root(tmp_path, monkeypatch)
    evil = tmp_path / "evil.zip"
    with zipfile.ZipFile(evil, "w") as zf:
        zf.writestr("BACKUP.json", json.dumps({"kind": "jobsquirrel-backup", "format": 1}))
        zf.writestr("../escaped.txt", "nope")
        zf.writestr("/absolute.txt", "nope")
        zf.writestr("secrets/passwords.txt", "nope")
        zf.writestr("state/ok.txt", "fine")
    res = backup.restore(str(evil), safety=False, quiet=True)

    assert res["restored"] == 1
    assert not (tmp_path / "escaped.txt").exists()
    assert not os.path.exists("/absolute.txt")
    assert (root / "state" / "ok.txt").read_text() == "fine"


def test_clear_keeps_config_and_sources(tmp_path, monkeypatch):
    root = _root(tmp_path, monkeypatch)
    res = backup.clear("data", quiet=True)

    assert res["removed"] > 0
    assert (root / "config" / "profile.md").exists(), "config is never cleared"
    assert (root / "kb" / "sources" / "master.md").exists(), "the corpus is never cleared"
    assert not (root / "state" / "applications.csv").exists()
    assert not (root / "documents" / "applications" / "cv.docx").exists()
    assert (root / "state").is_dir() and (root / "documents" / "applications").is_dir()
    assert res["safety"] and os.path.isfile(res["safety"]), "clearing is always reversible"


def test_clear_full_also_drops_the_index(tmp_path, monkeypatch):
    root = _root(tmp_path, monkeypatch)
    _write(root / "kb" / "graphrag" / "output" / "entities.parquet", "idx")
    backup.clear("full", quiet=True)
    assert not (root / "kb" / "graphrag").exists()
    assert (root / "kb" / "sources" / "master.md").exists()


def test_summarise_reports_parts_and_backups(tmp_path, monkeypatch):
    _root(tmp_path, monkeypatch)
    backup.create(quiet=True)
    info = backup.summarise()
    assert info["parts"]["config"]["files"] == 2
    assert info["parts"]["state"]["files"] >= 1
    assert info["backups"] and info["backups"][0]["name"].endswith(".zip")
    assert info["has_config"] is True


def test_restore_refuses_a_broken_archive(tmp_path, monkeypatch):
    _root(tmp_path, monkeypatch)
    broken = tmp_path / "broken.zip"
    buf = io.BytesIO()
    with zipfile.ZipFile(broken, "w") as zf:
        zf.writestr("BACKUP.json", json.dumps({"kind": "jobsquirrel-backup"}))
        zf.writestr("state/x.txt", "data")
    with open(broken, "rb") as fh:
        raw = bytearray(fh.read())
    raw[-20:] = b"\x00" * 20          # corrupt the last member
    with open(broken, "wb") as fh:
        fh.write(bytes(raw))
    res = backup.restore(str(broken), safety=False, quiet=True)
    assert res.get("error"), "a corrupt archive must not half-restore silently"


def test_dashboard_needs_the_exact_confirmation_phrase(tmp_path, monkeypatch):
    """The HTTP layer refuses anything that does not type the phrase, before it
    touches a single file — the guard is not the browser dialog."""
    import dashboard

    assert dashboard.backup_clear("data", "")["error"]
    assert dashboard.backup_clear("data", "clear please")["error"]
    assert dashboard.backup_restore(str(tmp_path / "nope.zip"), "yes")["error"]


def test_dashboard_refuses_a_restore_while_a_run_is_active(tmp_path, monkeypatch):
    import dashboard

    monkeypatch.setattr(dashboard, "_runner_busy", lambda: True)
    res = dashboard.backup_restore(str(tmp_path / "x.zip"), "RESTORE")
    assert "in progress" in res["error"]
    res = dashboard.backup_clear("data", "CLEAR")
    assert "in progress" in res["error"]


def test_prune_keeps_only_the_newest_safety_copies(tmp_path, monkeypatch):
    root = _root(tmp_path, monkeypatch)
    for i in range(8):
        (root / "backups").mkdir(exist_ok=True)
        (root / "backups" / f"pre-restore-2026010{i + 1}-000000.zip").write_bytes(b"x")
    (root / "backups" / "jobsquirrel-20260101-000000.zip").write_bytes(b"x")

    assert backup.prune(keep=3) == 5
    names = sorted(os.listdir(root / "backups"))
    assert names.count("jobsquirrel-20260101-000000.zip") == 1, "your own backups are never pruned"
    assert len([n for n in names if n.startswith("pre-restore-")]) == 3
