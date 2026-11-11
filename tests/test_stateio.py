"""Packed per-role artifacts: packing, restoring, and every reader's behaviour.

The point of tools/stateio.py is that a packed artifact is indistinguishable from
a plain one to the rest of the pipeline, so each test asserts the packed form
exists AND that the normal reader still sees the content.
"""
import gzip
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))

import stateio  # noqa: E402


def _write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _age(path, days):
    old = time.time() - days * 86400
    os.utime(path, (old, old))


def test_pack_then_read_without_restoring(tmp_path):
    p = _write(tmp_path / "jd" / "acme.md", "# Acme\nStaff engineer ")
    assert stateio.write(str(p), b"packed body", packed=True).endswith(".gz")
    assert not p.exists()                    # only the packed form remains
    assert stateio.read_text(str(p)) == "packed body"
    assert stateio.exists(str(p))


def test_ensure_restores_in_place(tmp_path):
    p = _write(tmp_path / "acme.md", "body")
    with gzip.open(str(p) + ".gz", "wt", encoding="utf-8") as fh:
        fh.write("body")
    p.unlink()

    assert stateio.ensure(str(p)) == str(p)
    assert p.read_text() == "body"
    assert not os.path.exists(str(p) + ".gz"), "the packed twin must be removed"


def test_write_plain_removes_a_stale_packed_twin(tmp_path):
    p = tmp_path / "acme.md"
    with gzip.open(str(p) + ".gz", "wt", encoding="utf-8") as fh:
        fh.write("old")
    stateio.write(str(p), b"new")
    assert p.read_text() == "new"
    assert not os.path.exists(str(p) + ".gz")


def test_listdir_and_stems_ignore_the_suffix(tmp_path):
    _write(tmp_path / "job-descriptions" / "a.md", "x")
    with gzip.open(tmp_path / "job-descriptions" / "b.md.gz", "wt", encoding="utf-8") as fh:
        fh.write("y")
    assert stateio.stems(str(tmp_path / "job-descriptions"), ".md") == ["a", "b"]


def test_storage_packs_cold_artifacts_only(tmp_path, monkeypatch):
    import storage

    state = tmp_path / "state"
    cold = _write(state / "job-descriptions" / "old.md", "old ad " * 400)
    hot = _write(state / "job-descriptions" / "new.md", "fresh ad " * 400)
    _age(cold, 30)

    monkeypatch.setattr(storage, "ROOT", str(tmp_path))
    assert storage.compress_state(days=7, apply=True, quiet=True) > 0
    assert cold.with_suffix(".md.gz").exists() and not cold.exists()
    assert hot.exists(), "a recently written artifact stays plain"


def test_git_tracked_artifacts_are_left_plain(tmp_path, monkeypatch):
    import storage

    state = tmp_path / "state"
    tracked = _write(state / "job-descriptions" / "tracked.md", "ad " * 400)
    loose = _write(state / "job-descriptions" / "loose.md", "ad " * 400)
    for f in (tracked, loose):
        _age(f, 30)

    monkeypatch.setattr(storage, "ROOT", str(tmp_path))
    monkeypatch.setattr(storage, "_tracked_paths", lambda: {str(tracked)})
    storage.compress_state(days=7, apply=True, quiet=True)

    assert tracked.exists(), "a version-controlled artifact stays plain"
    assert (state / "job-descriptions" / "loose.md.gz").exists()


def test_hydrate_all_restores_everything(tmp_path, monkeypatch):
    import storage

    state = tmp_path / "state"
    for name in ("job-descriptions", "ats", "gates"):
        (state / name).mkdir(parents=True)
        with gzip.open(str(state / name / "k.md.gz"), "wt", encoding="utf-8") as fh:
            fh.write("body")
    monkeypatch.setattr(storage, "ROOT", str(tmp_path))

    assert storage.hydrate_all(quiet=True) == 3
    assert (state / "job-descriptions" / "k.md").read_text() == "body"


def test_hydrate_matches_one_key(tmp_path, monkeypatch):
    import storage

    state = tmp_path / "state" / "job-descriptions"
    state.mkdir(parents=True)
    for key, body in (("acme-eng", "a"), ("other-eng", "b")):
        with gzip.open(str(state / f"{key}.md.gz"), "wt", encoding="utf-8") as fh:
            fh.write(body)
    monkeypatch.setattr(storage, "ROOT", str(tmp_path))

    assert storage.hydrate("acme", quiet=True) == 1
    assert (state / "acme-eng.md").exists()
    assert not (state / "other-eng.md").exists()


def test_gate_receipts_survive_being_packed(tmp_path, monkeypatch):
    """A packed receipt must still satisfy record_submission's gate check."""
    import gate_receipt as GR

    gates = tmp_path / "gates"
    monkeypatch.setattr(GR, "GATES_DIR", str(gates))
    cv = tmp_path / "cv.docx"
    cv.write_bytes(b"cv bytes")

    path = GR.emit("documents", {"cv": str(cv)})
    assert path and os.path.isfile(path)

    packed = path + ".gz"
    with open(path, "rb") as src, gzip.open(packed, "wb") as dst:
        dst.write(src.read())
    os.unlink(path)

    ok, why = GR.find_pass({"cv": str(cv)})
    assert ok, why


def test_jd_guard_finds_a_packed_ad(tmp_path, monkeypatch):
    import jd_guard

    jd = _write(tmp_path / "job-descriptions" / "acme.md", "job ad " * 80)
    with gzip.open(str(jd) + ".gz", "wt", encoding="utf-8") as fh:
        fh.write("job ad " * 80)
    jd.unlink()

    monkeypatch.setattr(jd_guard, "JD_DIR", tmp_path / "job-descriptions")
    assert jd_guard.has_jd("acme")


def test_alias_symlink_survives_its_target_being_packed(tmp_path, monkeypatch):
    """A company-role alias must resolve when storage packs the real ad.

    storage.py packs the target file and deliberately leaves the alias symlink
    alone, which used to make the alias dangle. The register audit and the
    drawer must still see the packed advert through it.
    """
    import jd_guard
    import register

    jd = _write(tmp_path / "job-descriptions" / "li_123.md", "job ad " * 80)
    with gzip.open(str(jd) + ".gz", "wt", encoding="utf-8") as fh:
        fh.write("job ad " * 80)
    jd.unlink()
    os.symlink("li_123.md", tmp_path / "job-descriptions" / "acme-role.md")

    monkeypatch.setattr(jd_guard, "JD_DIR", tmp_path / "job-descriptions")
    monkeypatch.setattr(register, "JD_DIR", str(tmp_path / "job-descriptions"))

    alias = tmp_path / "job-descriptions" / "acme-role.md"
    assert stateio.resolve(str(alias)) == str(jd) + ".gz"
    assert stateio.read_text(str(alias)) == "job ad " * 80
    assert jd_guard.has_jd("acme-role")
    assert register.jd_path("Acme", "Role", "acme-role") == str(jd) + ".gz"


def test_dashboard_lists_and_reads_packed_roles(tmp_path, monkeypatch):
    import dashboard

    state = tmp_path / "state"
    _write(state / "job-descriptions" / "plain.md", "plain ad")
    with gzip.open(state / "job-descriptions" / "packed.md.gz", "wt", encoding="utf-8") as fh:
        fh.write("packed ad")
    _write(state / "ats" / "packed.txt", "k8s\nterraform")

    monkeypatch.setattr(dashboard, "STATE", str(state))
    keys = [r["key"] for r in dashboard.roles_list()]
    assert keys == ["packed", "plain"]

    assert dashboard._read(str(state / "job-descriptions" / "packed.md")) == "packed ad"
    assert not (state / "job-descriptions" / "packed.md").exists(), \
        "browsing must not restore packed artifacts"
