#!/usr/bin/env python3
"""One secure store for every secret the pipeline uses.

The store is a JSON file outside the repo (default
``~/.config/job-search/secrets.json``), mode 0600 inside a 0700 directory. It is
the source of truth for:

  agent     model/API keys and env values used by the runner
  graphrag  LLM/embeddings settings for the knowledge graph
  google    OAuth client id/secret plus the serialized credentials/token files
  accounts  per-site logins (username/password) used by the browser
  custom    anything else the operator adds from Settings -> Secrets

Files that third-party libraries insist on (``credentials.json``,
``token.json``, ``kb/graphrag/.env``) are materialized from the store with
0600 and are treated as caches. The dashboard never returns a plaintext value:
it shows a masked form and accepts a replacement.

CLI (values are read from stdin so they do not land in shell history):

  python3 tools/secrets_store.py --list
  python3 tools/secrets_store.py --check
  python3 tools/secrets_store.py --migrate
  python3 tools/secrets_store.py --set agent OPENROUTER_API_KEY   # value on stdin
  python3 tools/secrets_store.py --get agent OPENROUTER_API_KEY
  python3 tools/secrets_store.py --delete agent OPENROUTER_API_KEY
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import tempfile
import time
from pathlib import Path

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_DIR = os.path.join(os.path.expanduser("~"), ".config", "job-search")
DEFAULT_PATH = os.path.join(DEFAULT_DIR, "secrets.json")
SECTION_RE = re.compile(r"^[a-z][a-z0-9_-]{0,40}$")
NAME_RE = re.compile(r"^[A-Za-z0-9_.:@-]{1,160}$")
SECRET_RE = re.compile(r"(KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL|AUTH)", re.I)


class SecretsError(RuntimeError):
    pass


def path() -> str:
    """Where the store lives (honours JOBSQUIRREL_SECRETS)."""
    return os.path.abspath(os.path.expanduser(
        os.environ.get("JOBSQUIRREL_SECRETS") or DEFAULT_PATH))


def _empty() -> dict:
    return {"version": 1, "updated": "", "sections": {}}


def load() -> dict:
    """Read the store. A missing file is an empty store; corrupt data raises."""
    p = path()
    try:
        with open(p, encoding="utf-8") as fh:
            data = json.load(fh)
    except FileNotFoundError:
        return _empty()
    except (OSError, ValueError) as exc:
        raise SecretsError(f"cannot read {p}: {exc}") from exc
    if not isinstance(data, dict):
        raise SecretsError(f"{p} is not a JSON object")
    sections = data.get("sections")
    if not isinstance(sections, dict):
        sections = {}
    out = _empty()
    out["sections"] = {str(k): v for k, v in sections.items() if isinstance(v, dict)}
    out["updated"] = str(data.get("updated") or "")
    return out


def _fsync_dir(directory: str) -> None:
    try:
        fd = os.open(directory, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    except OSError:
        pass


def save(data: dict) -> None:
    """Atomically replace the store with 0600, in a 0700 directory."""
    p = path()
    directory = os.path.dirname(p) or "."
    os.makedirs(directory, mode=0o700, exist_ok=True)
    try:
        os.chmod(directory, 0o700)
    except OSError:
        pass
    payload = {"version": 1,
               "updated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
               "sections": data.get("sections") if isinstance(data.get("sections"), dict) else {}}
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=".secrets.", suffix=".tmp")
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2, sort_keys=False)
            fh.write("\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, p)
        os.chmod(p, 0o600)
        _fsync_dir(directory)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def _check_section(section: str) -> str:
    section = (section or "").strip()
    if not SECTION_RE.match(section):
        raise SecretsError("section must be lower-case letters, digits, _ or -")
    return section


def _check_name(name: str) -> str:
    name = (name or "").strip()
    if not NAME_RE.match(name):
        raise SecretsError("name may contain letters, digits and _ . : @ / -")
    return name


def _clean(value):
    if isinstance(value, str):
        return value[:8192]
    if isinstance(value, (dict, list)):
        # Only JSON-shaped values inside the store; cap nesting by round-trip.
        return json.loads(json.dumps(value)) if len(json.dumps(value)) < 200_000 else None
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return str(value)[:8192]


def get(section: str, name: str, default=None):
    try:
        return load()["sections"].get(section, {}).get(name, default)
    except SecretsError:
        return default


def section(name: str) -> dict:
    try:
        sec = load()["sections"].get(name, {})
        return dict(sec) if isinstance(sec, dict) else {}
    except SecretsError:
        return {}


def sections() -> dict:
    try:
        return dict(load()["sections"])
    except SecretsError:
        return {}


def put(section: str, name: str, value) -> None:
    """Set (or, with an empty string/None, delete) one entry."""
    section, name = _check_section(section), _check_name(name)
    data = load()
    sec = data["sections"].setdefault(section, {})
    if value is None or (isinstance(value, str) and value == ""):
        sec.pop(name, None)
        if not sec:
            data["sections"].pop(section, None)
    else:
        clean = _clean(value)
        if clean is None:
            raise SecretsError("value is too large")
        sec[name] = clean
    save(data)


def delete(section: str, name: str) -> bool:
    data = load()
    sec = data["sections"].get(section) or {}
    if name not in sec:
        return False
    sec.pop(name, None)
    if not sec:
        data["sections"].pop(section, None)
    save(data)
    return True


def set_section(section: str, values: dict) -> None:
    section = _check_section(section)
    data = load()
    data["sections"][section] = {_check_name(k): _clean(v) for k, v in (values or {}).items()}
    if not data["sections"][section]:
        data["sections"].pop(section, None)
    save(data)


def mask(value) -> str:
    """A display form; never the real value."""
    if value is None or value == "":
        return ""
    if isinstance(value, dict):
        return f"stored ({len(value)} field{'s' if len(value) != 1 else ''})"
    if isinstance(value, list):
        return f"stored ({len(value)} item{'s' if len(value) != 1 else ''})"
    v = str(value)
    if len(v) <= 8:
        return "••••••"
    if len(v) <= 16:
        return v[:2] + "…" + v[-2:]
    return v[:4] + "…" + v[-4:]


def check() -> dict:
    """File/permission health, without exposing values."""
    p = path()
    try:
        st = os.stat(p)
        mode = oct(st.st_mode & 0o777)
        exists = True
    except OSError:
        mode, exists = "", False
    dir_mode = ""
    try:
        dir_mode = oct(os.stat(os.path.dirname(p)).st_mode & 0o777)
    except OSError:
        pass
    problems = []
    if exists and mode not in ("0o600", "0o400"):
        problems.append(f"store mode is {mode}, expected 0600")
    if dir_mode and dir_mode not in ("0o700", "0o750", "0o750"):
        problems.append(f"store directory mode is {dir_mode}, expected 0700")
    try:
        load()
    except SecretsError as exc:
        problems.append(str(exc))
    return {"path": p, "exists": exists, "mode": mode, "dir_mode": dir_mode,
            "problems": problems, "ok": not problems}


# ------------------------------------------------------------------ migration
def _backup(path_: str, backup_dir: str) -> None:
    if not os.path.isfile(path_):
        return
    os.makedirs(backup_dir, mode=0o700, exist_ok=True)
    try:
        os.chmod(backup_dir, 0o700)
    except OSError:
        pass
    dest = os.path.join(backup_dir, os.path.basename(path_) + ".bak")
    if not os.path.exists(dest):
        try:
            shutil.copy2(path_, dest)
            os.chmod(dest, 0o600)
        except OSError:
            pass


def _read_json(path_: str) -> dict:
    try:
        with open(path_, encoding="utf-8") as fh:
            d = json.load(fh)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def google_config_path() -> str:
    return os.environ.get("JOBSQUIRREL_GOOGLE_CONFIG") or os.path.join(ROOT, "config", "google.json")


def graphrag_env_path() -> str:
    return os.environ.get("GRAPHRAG_ENV") or os.path.join(ROOT, "kb", "graphrag", ".env")


def _google_paths() -> tuple[str, str, str]:
    cfg = _read_json(google_config_path())
    config_dir = os.path.expanduser(os.environ.get("GMAIL_CONFIG_DIR")
                                    or cfg.get("config_dir") or DEFAULT_DIR)
    credentials = os.environ.get("GMAIL_CREDENTIALS") or cfg.get("credentials") or "credentials.json"
    token = os.environ.get("GMAIL_TOKEN") or cfg.get("token") or "token.json"
    if not os.path.isabs(credentials):
        credentials = os.path.join(config_dir, credentials)
    if not os.path.isabs(token):
        token = os.path.join(config_dir, token)
    return config_dir, credentials, token


def legacy_sources() -> dict:
    """What still holds a secret outside the store (paths only, no values)."""
    agent = os.path.expanduser(os.environ.get("AGENT_CFG")
                               or os.path.join(DEFAULT_DIR, "agent.json"))
    accounts = os.path.expanduser(os.environ.get("ACCOUNTS_FILE")
                                  or os.path.join(DEFAULT_DIR, "accounts.json"))
    graph = graphrag_env_path()
    config_dir, credentials, token = _google_paths()
    return {
        "agent_json": os.path.isfile(agent),
        "accounts_json": os.path.isfile(accounts),
        "graphrag_env": os.path.isfile(graph),
        "google_config": os.path.isfile(google_config_path()),
        "credentials_json": os.path.isfile(credentials),
        "token_json": os.path.isfile(token),
        "token_modify_json": os.path.isfile(os.path.join(config_dir, "token-modify.json")),
    }


def migration_status() -> dict:
    """What still looks un-imported (no values, just flags and counts)."""
    data = load()
    secs = data["sections"]
    agent = os.path.expanduser(os.environ.get("AGENT_CFG")
                               or os.path.join(DEFAULT_DIR, "agent.json"))
    accounts = os.path.expanduser(os.environ.get("ACCOUNTS_FILE")
                                  or os.path.join(DEFAULT_DIR, "accounts.json"))
    graph = graphrag_env_path()
    config_dir, credentials, token = _google_paths()
    google_cfg = _read_json(google_config_path())
    agent_env = _read_json(agent).get("env") if isinstance(_read_json(agent).get("env"), dict) else {}
    checks = {
        "agent": sum(1 for k in agent_env if k not in secs.get("agent", {})),
        "accounts": len(_read_json(accounts)) if not secs.get("accounts") else 0,
        "google_config": 1 if (not secs.get("google", {}).get("client_id")
                               and (google_cfg.get("client_id") or google_cfg.get("client_secret"))) else 0,
        "google_credentials": 1 if (not secs.get("google", {}).get("credentials")
                                    and os.path.isfile(credentials)) else 0,
        "google_token": 1 if (not secs.get("google", {}).get("token")
                              and os.path.isfile(token)) else 0,
        "google_token_modify": 1 if (not secs.get("google", {}).get("token_modify")
                                     and os.path.isfile(os.path.join(config_dir, "token-modify.json"))) else 0,
        "graphrag": 1 if (not secs.get("graphrag") and os.path.isfile(graph)) else 0,
    }
    needed = [k for k, v in checks.items() if v]
    return {"needed": needed, "counts": checks,
            "total": sum(v for v in checks.values() if isinstance(v, int))}


def migrate() -> dict:
    """Import existing secrets into the store, once, without losing the originals.

    Agent API keys are removed from `agent.json` (which keeps only the non-secret
    agent/model choice), Google client ids are removed from the repo config, and
    the old per-site file is archived. Token/credentials files and the GraphRAG
    .env stay as 0600 caches because third-party code reads them directly.
    """
    data = load()
    secs = data["sections"]
    stamp = time.strftime("%Y%m%d-%H%M%S")
    backup_dir = os.path.join(os.path.dirname(path()) or ".", f"secrets-backup-{stamp}")
    imported, touched = {}, []

    agent_path = os.path.expanduser(os.environ.get("AGENT_CFG")
                                    or os.path.join(DEFAULT_DIR, "agent.json"))
    agent = _read_json(agent_path)
    env = agent.get("env") if isinstance(agent.get("env"), dict) else {}
    if env:
        _backup(agent_path, backup_dir)
        target = secs.setdefault("agent", {})
        n = 0
        for k, v in env.items():
            k = re.sub(r"[^A-Za-z0-9_]", "", str(k))[:80]
            if k and k not in target:
                target[k] = str(v)[:8192]
                n += 1
        if n:
            imported["agent"] = n
        agent.pop("env", None)
        try:
            os.makedirs(os.path.dirname(agent_path), mode=0o700, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=os.path.dirname(agent_path), prefix=".agent.", suffix=".tmp")
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(agent, fh, indent=2)
                fh.write("\n")
            os.replace(tmp, agent_path)
            os.chmod(agent_path, 0o600)
            touched.append(os.path.relpath(agent_path, os.path.expanduser("~")))
        except OSError as exc:
            print(f"warning: could not rewrite {agent_path}: {exc}", file=sys.stderr)

    accounts_path = os.path.expanduser(os.environ.get("ACCOUNTS_FILE")
                                       or os.path.join(DEFAULT_DIR, "accounts.json"))
    accounts = _read_json(accounts_path)
    if accounts:
        _backup(accounts_path, backup_dir)
        target = secs.setdefault("accounts", {})
        n = 0
        for host, entry in accounts.items():
            if isinstance(entry, dict) and host not in target:
                target[host] = entry
                n += 1
        if n:
            imported["accounts"] = n
        archive = accounts_path + ".migrated"
        try:
            os.replace(accounts_path, archive)
            os.chmod(archive, 0o600)
            touched.append(os.path.relpath(archive, os.path.expanduser("~")))
        except OSError:
            pass

    google_cfg_path = google_config_path()
    google_cfg = _read_json(google_cfg_path)
    if google_cfg.get("client_id") or google_cfg.get("client_secret"):
        _backup(google_cfg_path, backup_dir)
        target = secs.setdefault("google", {})
        for k in ("client_id", "client_secret"):
            if google_cfg.get(k) and not target.get(k):
                target[k] = str(google_cfg[k])
                imported.setdefault("google", 0)
                imported["google"] += 1
        google_cfg["client_id"] = ""
        google_cfg["client_secret"] = ""
        try:
            with open(google_cfg_path, "w", encoding="utf-8") as fh:
                json.dump(google_cfg, fh, indent=2)
                fh.write("\n")
            touched.append(os.path.relpath(google_cfg_path, ROOT))
        except OSError:
            pass

    config_dir, credentials, token = _google_paths()
    target = secs.setdefault("google", {})
    for key, file_ in (("credentials", credentials), ("token", token),
                       ("token_modify", os.path.join(config_dir, "token-modify.json"))):
        payload = _read_json(file_)
        if payload and not target.get(key):
            target[key] = payload
            imported.setdefault("google", 0)
            imported["google"] += 1
        if os.path.isfile(file_):
            try:
                os.chmod(file_, 0o600)
            except OSError:
                pass

    graph_path = graphrag_env_path()
    if os.path.isfile(graph_path):
        target = secs.setdefault("graphrag", {})
        n = 0
        try:
            for line in open(graph_path, encoding="utf-8"):
                s = line.strip()
                if not s or s.startswith("#") or "=" not in s:
                    continue
                k, v = s.split("=", 1)
                k, v = k.strip(), v.strip()
                if k and k not in target:
                    target[k] = v[:8192]
                    n += 1
        except OSError:
            pass
        if n:
            imported["graphrag"] = n
        try:
            os.chmod(graph_path, 0o600)
        except OSError:
            pass

    # Do not leave empty sections behind.
    data["sections"] = {k: v for k, v in secs.items() if v}
    save(data)
    return {"imported": imported, "touched": touched,
            "backup": backup_dir if os.path.isdir(backup_dir) else "",
            "store": path()}


# ------------------------------------------------------------------ CLI
def _cmd_list() -> int:
    data = load()
    print(f"store: {path()}")
    for section_name, values in data["sections"].items():
        print(f"\n[{section_name}]")
        for name, value in values.items():
            print(f"  {name:<32} {mask(value) or '(empty)'}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="One secure store for Jobsquirrel secrets.")
    ap.add_argument("--list", action="store_true", help="list sections and masked values")
    ap.add_argument("--check", action="store_true", help="check file permissions and syntax")
    ap.add_argument("--migrate", action="store_true", help="import existing secret files")
    ap.add_argument("--set", nargs=2, metavar=("SECTION", "NAME"),
                    help="store a value read from stdin")
    ap.add_argument("--get", nargs=2, metavar=("SECTION", "NAME"),
                    help="print one value (for scripts; beware shell history)")
    ap.add_argument("--delete", nargs=2, metavar=("SECTION", "NAME"))
    args = ap.parse_args()

    if args.check:
        st = check()
        print(f"store: {st['path']}")
        print(f"exists: {st['exists']}  mode: {st['mode'] or '—'}  dir: {st['dir_mode'] or '—'}")
        for problem in st["problems"]:
            print(f"FAIL {problem}")
        print("RESULT: PASS" if st["ok"] else "RESULT: FAIL")
        return 0 if st["ok"] else 1
    if args.migrate:
        out = migrate()
        print(json.dumps(out, indent=2))
        return 0
    if args.set:
        value = sys.stdin.read()
        value = value[:-1] if value.endswith("\n") else value
        put(args.set[0], args.set[1], value)
        print(f"stored {args.set[0]}/{args.set[1]}  ({mask(value)})")
        return 0
    if args.get:
        value = get(args.get[0], args.get[1])
        if value is None:
            print(f"no such secret: {args.get[0]}/{args.get[1]}", file=sys.stderr)
            return 1
        print(value if isinstance(value, str) else json.dumps(value))
        return 0
    if args.delete:
        ok = delete(args.delete[0], args.delete[1])
        print("deleted" if ok else "not found")
        return 0 if ok else 1
    return _cmd_list()


if __name__ == "__main__":
    sys.exit(main())
