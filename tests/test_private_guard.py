"""The public clone must refuse private material before it is committed."""
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _run(repo, terms, *args):
    env = {**os.environ, "PRIVATE_TERMS_FILE": str(terms)}
    return subprocess.run([sys.executable, "tools/private_guard.py", *args],
                          cwd=repo, env=env, capture_output=True, text=True)


def _repo(tmp_path, content):
    repo = tmp_path / "repo"
    (repo / "tools").mkdir(parents=True)
    shutil.copy(ROOT / "tools" / "private_guard.py", repo / "tools")
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    (repo / "note.txt").write_text(content, encoding="utf-8")
    subprocess.run(["git", "add", "note.txt"], cwd=repo, check=True)
    terms = tmp_path / "terms.txt"
    terms.write_text("Example Person\n", encoding="utf-8")
    return repo, terms


def test_blocks_a_name_from_the_private_terms(tmp_path):
    repo, terms = _repo(tmp_path, "Please contact Example Person about it.\n")
    r = _run(repo, terms, "--staged")
    assert r.returncode == 1
    assert "private term" in r.stderr
    assert "Example Person" not in r.stderr  # the value stays masked


def test_blocks_a_private_only_path(tmp_path):
    repo, terms = _repo(tmp_path, "harmless\n")
    (repo / "local").mkdir()
    (repo / "local" / "MANIFEST.txt").write_text("private\n", encoding="utf-8")
    subprocess.run(["git", "add", "-f", "local/MANIFEST.txt"], cwd=repo, check=True)
    r = _run(repo, terms, "--staged")
    assert r.returncode == 1
    assert "private clone" in r.stderr


def test_passes_clean_content(tmp_path):
    repo, terms = _repo(tmp_path, "A generic sentence about a role.\n")
    r = _run(repo, terms, "--staged")
    assert r.returncode == 0, r.stderr
