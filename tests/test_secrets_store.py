import json
import os
import stat
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import secrets_store as SS


def _mode(path):
    return stat.S_IMODE(os.stat(path).st_mode)


def _setup(tmp_path, monkeypatch):
    store = tmp_path / "config" / "secrets.json"
    monkeypatch.setenv("JOBSQUIRREL_SECRETS", str(store))
    monkeypatch.setenv("AGENT_CFG", str(tmp_path / "agent.json"))
    monkeypatch.setenv("ACCOUNTS_FILE", str(tmp_path / "accounts.json"))
    monkeypatch.setenv("GRAPHRAG_ENV", str(tmp_path / "graphrag.env"))
    monkeypatch.setenv("JOBSQUIRREL_GOOGLE_CONFIG", str(tmp_path / "google.json"))
    monkeypatch.setenv("GMAIL_CONFIG_DIR", str(tmp_path / "google"))
    monkeypatch.delenv("GMAIL_CREDENTIALS", raising=False)
    monkeypatch.delenv("GMAIL_TOKEN", raising=False)
    return store


def test_set_get_mask_delete(tmp_path, monkeypatch):
    store = _setup(tmp_path, monkeypatch)
    assert SS.get("agent", "OPENROUTER_API_KEY") is None
    SS.put("agent", "OPENROUTER_API_KEY", "sk-or-v1-abcdefghijklmnop")
    assert SS.get("agent", "OPENROUTER_API_KEY") == "sk-or-v1-abcdefghijklmnop"
    assert SS.mask("sk-or-v1-abcdefghijklmnop") == "sk-o…mnop"
    assert store.exists()
    assert _mode(store) == 0o600
    assert _mode(store.parent) == 0o700
    listed = SS.load()["sections"]["agent"]
    assert "abcdefghijklmnop" not in json.dumps(SS.check())
    assert listed["OPENROUTER_API_KEY"].startswith("sk-or")
    assert SS.delete("agent", "OPENROUTER_API_KEY") is True
    assert SS.section("agent") == {}
    assert SS.delete("agent", "OPENROUTER_API_KEY") is False


def test_accounts_roundtrip(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    SS.put("accounts", "jobs.example.com",
           {"username": "me@example.com", "password": "correct horse",
            "created": "2026-01-01"})
    entry = SS.section("accounts")["jobs.example.com"]
    assert entry["username"] == "me@example.com"
    assert entry["password"] == "correct horse"


def test_migrate_legacy_sources(tmp_path, monkeypatch):
    store = _setup(tmp_path, monkeypatch)
    (tmp_path / "agent.json").write_text(json.dumps({
        "agent": "openrouter", "model": "example/model",
        "env": {"OPENROUTER_API_KEY": "sk-or-v1-abcdefghijklmnop"}}))
    (tmp_path / "accounts.json").write_text(json.dumps({
        "jobs.example.com": {"username": "me", "password": "pw", "created": "2026-01-01"}}))
    (tmp_path / "google.json").write_text(json.dumps({
        "config_dir": str(tmp_path / "google"), "credentials": "credentials.json",
        "token": "token.json", "client_id": "cid.apps.googleusercontent.com",
        "client_secret": "shh-secret"}))
    (tmp_path / "graphrag.env").write_text("GRAPHRAG_API_KEY=gr-secret\nGRAPHRAG_LLM_MODEL=x\n")
    (tmp_path / "google").mkdir(parents=True)
    (tmp_path / "google" / "credentials.json").write_text(json.dumps(
        {"installed": {"client_id": "cid", "client_secret": "shh"}}))
    (tmp_path / "google" / "token.json").write_text(json.dumps(
        {"token": "access", "refresh_token": "refresh", "client_id": "cid"}))

    out = SS.migrate()
    assert out["store"] == str(store)
    data = SS.load()["sections"]
    assert data["agent"]["OPENROUTER_API_KEY"] == "sk-or-v1-abcdefghijklmnop"
    assert data["accounts"]["jobs.example.com"]["password"] == "pw"
    assert data["google"]["client_id"] == "cid.apps.googleusercontent.com"
    assert data["google"]["credentials"]["installed"]["client_secret"] == "shh"
    assert data["google"]["token"]["refresh_token"] == "refresh"
    assert data["graphrag"]["GRAPHRAG_API_KEY"] == "gr-secret"

    agent = json.loads((tmp_path / "agent.json").read_text())
    assert "env" not in agent and agent["agent"] == "openrouter"
    assert not (tmp_path / "accounts.json").exists()
    assert (tmp_path / "accounts.json.migrated").exists()
    cfg = json.loads((tmp_path / "google.json").read_text())
    assert cfg["client_id"] == "" and cfg["client_secret"] == ""

    # Idempotent: a second pass is a no-op.
    again = SS.migrate()
    assert again["imported"] == {}


def test_migration_status_and_check(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    assert SS.migration_status()["total"] == 0
    (tmp_path / "agent.json").write_text(json.dumps({"env": {"OPENCODE_API_KEY": "x" * 20}}))
    assert "agent" in SS.migration_status()["needed"]
    st = SS.check()
    assert st["ok"]


def test_rejects_bad_names(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    for section, name in (("Agent", "X"), ("agent", "bad name"),
                          ("agent", "../x"), ("", "X")):
        try:
            SS.put(section, name, "v")
        except SS.SecretsError:
            continue
        raise AssertionError(f"accepted {section!r}/{name!r}")
