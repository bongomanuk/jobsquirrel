"""The agent config carries one provider/model per role.

Main and subagent may use different providers; an empty subagent provider
inherits the main agent, and an empty model means the provider's default.
"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))

import dashboard as D


class _Store:
    """Minimal stand-in so agent_env does not touch the real secrets store."""

    KEY_ENV = "JOBSQUIRREL_KEY"

    @staticmethod
    def key_b64():
        return ""

    @staticmethod
    def get(section, name):
        return ""


@pytest.fixture()
def cfg(tmp_path, monkeypatch):
    path = tmp_path / "agent.json"
    monkeypatch.setattr(D, "AGENT_CFG_FILE", str(path))
    monkeypatch.setattr(D, "_stored_agent_env", lambda: {})
    monkeypatch.setattr(D, "CHAT_SESSION", str(tmp_path / "chat.session"))
    monkeypatch.setattr(D, "ROLE_CHAT_DIR", str(tmp_path / "role-chats"))
    monkeypatch.setattr(D, "SS", _Store)
    return path


def test_legacy_config_has_both_roles(cfg):
    cfg.write_text(json.dumps({"agent": "opencode", "model": "zen/model"}))
    got = D.load_agent_cfg()
    assert got["roles"]["main"] == {"agent": "opencode", "model": "zen/model"}
    assert got["roles"]["subagent"] == {"agent": "", "model": ""}


def test_subagent_can_use_another_provider(cfg):
    D.save_agent_cfg({"agent": "opencode", "model": "zen/model",
                      "subagent_agent": "openrouter", "subagent_model": "deepseek/deepseek-chat",
                      "parallel": 2})
    got = D.load_agent_cfg()
    assert got["roles"]["main"] == {"agent": "opencode", "model": "zen/model"}
    assert got["roles"]["subagent"] == {"agent": "openrouter",
                                        "model": "deepseek/deepseek-chat"}
    assert got["models"]["openrouter"] == "deepseek/deepseek-chat"


def test_subagent_env_uses_its_own_provider_and_model(cfg, monkeypatch):
    monkeypatch.setattr(D, "load_agent_cfg", lambda: {
        "agent": "opencode", "model": "zen/main", "models": {"openrouter": "or/sub"},
        "env": {}, "parallel": 3, "subagent_agent": "openrouter",
        "subagent_model": "or/sub",
        "roles": {"main": {"agent": "opencode", "model": "zen/main"},
                  "subagent": {"agent": "openrouter", "model": "or/sub"}}})
    sub = D.agent_env(subagent=True)
    main = D.agent_env()
    assert sub["AGENT"] == "openrouter" and sub["MODEL"] == "or/sub"
    assert main["AGENT"] == "opencode" and main["MODEL"] == "zen/main"


def test_subagent_without_a_provider_inherits_main(cfg, monkeypatch):
    monkeypatch.setattr(D, "load_agent_cfg", lambda: {
        "agent": "opencode", "model": "zen/main", "models": {},
        "env": {}, "parallel": 3, "subagent_agent": "", "subagent_model": "zen/cheap",
        "roles": {"main": {"agent": "opencode", "model": "zen/main"},
                  "subagent": {"agent": "", "model": "zen/cheap"}}})
    sub = D.agent_env(subagent=True)
    assert sub["AGENT"] == "opencode" and sub["MODEL"] == "zen/cheap"


def test_clearing_a_provider_key_removes_it(cfg, monkeypatch):
    class Recorder(_Store):
        removed = []
        stored = {}

        @classmethod
        def delete(cls, section, name):
            cls.removed.append((section, name))
            return True

        @classmethod
        def put(cls, section, name, value):
            cls.stored[(section, name)] = value

    monkeypatch.setattr(D, "SS", Recorder)
    D.save_agent_cfg({"env": {"OPENROUTER_API_KEY": ""}})
    assert ("agent", "OPENROUTER_API_KEY") in Recorder.removed
