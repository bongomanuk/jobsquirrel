"""Storage compression: old logs, the Gmail body cache, and the readers that use them.

Compressing must never lose data or break the dashboard/mail tools, so each test
asserts both halves: the plain file is gone, and the content is still readable.
"""
import gzip
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))

import storage  # noqa: E402


def _write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _age(path, days):
    old = time.time() - days * 86400
    os.utime(path, (old, old))


def test_old_logs_are_gzipped_and_readable(tmp_path, monkeypatch):
    logs = tmp_path / "logs"
    old = _write(logs / "acme-eng.log", "START acme\nSTATUS SUBMITTED\n" * 200)
    _age(old, 30)
    fresh = _write(logs / "running-now.log", "still writing\n" * 200)

    monkeypatch.setattr(storage, "LOGS", str(logs))
    monkeypatch.setattr(storage, "GRAPHRAG_LOGS", str(tmp_path / "missing"))
    saved = storage.compress_logs(days=7, apply=True, quiet=True)

    assert saved > 0
    assert not old.exists() and (logs / "acme-eng.log.gz").exists()
    assert fresh.exists(), "a log being written must not be touched"
    with gzip.open(logs / "acme-eng.log.gz", "rt", encoding="utf-8") as fh:
        assert "STATUS SUBMITTED" in fh.read()


def test_dry_run_changes_nothing(tmp_path, monkeypatch):
    logs = tmp_path / "logs"
    old = _write(logs / "old.log", "x" * 5000)
    _age(old, 30)
    monkeypatch.setattr(storage, "LOGS", str(logs))
    monkeypatch.setattr(storage, "GRAPHRAG_LOGS", str(tmp_path / "missing"))

    storage.compress_logs(days=7, apply=False)
    assert old.exists()
    assert not (logs / "old.log.gz").exists()


def test_small_logs_are_left_alone(tmp_path, monkeypatch):
    logs = tmp_path / "logs"
    tiny = _write(logs / "tiny.log", "ok\n")
    _age(tiny, 30)
    monkeypatch.setattr(storage, "LOGS", str(logs))
    monkeypatch.setattr(storage, "GRAPHRAG_LOGS", str(tmp_path / "missing"))

    storage.compress_logs(days=7, apply=True, quiet=True)
    assert tiny.exists()


def _load_cache_with(cache_path):
    """gmail_reconcile.load_cache, pointed at a test cache file."""
    import gmail_reconcile

    class Path(str):
        pass

    old = gmail_reconcile.CACHE_FILE
    gmail_reconcile.CACHE_FILE = str(cache_path)
    try:
        return gmail_reconcile.load_cache(), gmail_reconcile
    finally:
        gmail_reconcile.CACHE_FILE = old


def test_gmail_cache_round_trips_through_gzip(tmp_path, monkeypatch):
    cache = tmp_path / "gmail_cache.json"
    payload = {"m1": {"subject": "Thanks for applying", "body": "we got it " * 500}}
    cache.write_text(json.dumps(payload), encoding="utf-8")

    monkeypatch.setattr(storage, "GMAIL_CACHE", str(cache))
    assert storage.compress_gmail_cache(apply=True) > 0
    assert not cache.exists()

    import gmail_reconcile

    gmail_reconcile.CACHE_FILE = str(cache)
    assert gmail_reconcile.load_cache() == payload


def test_saving_keeps_the_compressed_form(tmp_path):
    cache = tmp_path / "gmail_cache.json"
    gz = tmp_path / "gmail_cache.json.gz"
    with gzip.open(gz, "wt", encoding="utf-8") as fh:
        json.dump({"old": {"body": "x"}}, fh)

    import gmail_reconcile

    gmail_reconcile.CACHE_FILE = str(cache)
    gmail_reconcile.save_cache({"new": {"body": "y"}})

    assert not cache.exists(), "a compressed cache must not be re-inflated on write"
    with gzip.open(gz, "rt", encoding="utf-8") as fh:
        assert json.load(fh) == {"new": {"body": "y"}}


def test_dashboard_reads_compressed_task_logs(tmp_path, monkeypatch):
    import dashboard

    logs = tmp_path / "logs"
    _write(logs / "plain.log", "plain line\n")
    with gzip.open(logs / "zipped.log.gz", "wt", encoding="utf-8") as fh:
        fh.write("zipped line\n")

    monkeypatch.setattr(dashboard, "LOGS", str(logs))
    assert dashboard.task_logs() == ["plain", "zipped"]
    assert dashboard.read_task_log("zipped")["raw"] == ["zipped line"]
    assert dashboard.read_task_log("plain")["raw"] == ["plain line"]


def test_append_only_logs_are_never_packed(tmp_path, monkeypatch):
    """A log the dashboard appends to would corrupt on the next write if packed."""
    logs = tmp_path / "logs"
    live = _write(logs / "dashboard-chat.log", "chat\n" * 400)
    run = _write(logs / "run_queue.out", "queue\n" * 400)
    dead = _write(logs / "acme-eng.log", "START acme\n" * 400)
    for f in (live, run, dead):
        _age(f, 30)                     # even when it looks idle

    monkeypatch.setattr(storage, "LOGS", str(logs))
    monkeypatch.setattr(storage, "GRAPHRAG_LOGS", str(tmp_path / "missing"))
    storage.compress_logs(days=1, apply=True, quiet=True)

    assert live.exists() and run.exists(), "append-only logs stay plain"
    assert not dead.exists() and (logs / "acme-eng.log.gz").exists()


def test_pack_log_packs_one_finished_transcript(tmp_path):
    log = _write(tmp_path / "acme-eng.log", "STATUS acme | SUBMITTED\n" * 200)
    assert storage.pack_log(str(log), quiet=True) > 0

    assert not log.exists()
    with gzip.open(str(log) + ".gz", "rt", encoding="utf-8") as fh:
        assert "SUBMITTED" in fh.read()


def test_pack_log_ignores_tiny_and_missing_files(tmp_path):
    tiny = _write(tmp_path / "tiny.log", "ok\n")
    assert storage.pack_log(str(tiny), quiet=True) == 0
    assert tiny.exists()
    assert storage.pack_log(str(tmp_path / "absent.log"), quiet=True) == 0


def test_dashboard_caps_an_oversized_append_only_log(tmp_path, monkeypatch):
    import dashboard

    logs = tmp_path / "logs"
    monkeypatch.setattr(dashboard, "LOGS", str(logs))
    monkeypatch.setattr(dashboard, "LOG_CAP_BYTES", 100)
    big = _write(logs / "dashboard-action.log", "line\n" * 500)

    assert dashboard._cap_log(str(big))
    assert big.exists() and big.stat().st_size == 0, "the live log restarts empty"
    rolled = list(logs.glob("dashboard-action-*.log.gz"))
    assert rolled, "the old content is kept, gzipped"
    with gzip.open(str(rolled[0]), "rt", encoding="utf-8") as fh:
        assert "line" in fh.read()


def test_dashboard_leaves_a_small_log_alone(tmp_path, monkeypatch):
    import dashboard

    logs = tmp_path / "logs"
    monkeypatch.setattr(dashboard, "LOG_CAP_BYTES", 10_000)
    small = _write(logs / "dashboard-chat.log", "small\n")
    assert not dashboard._cap_log(str(small))
    assert small.read_text() == "small\n"
