#!/usr/bin/env python3
"""One secure store for every secret the pipeline uses.

The store is an encrypted JSON file outside the repo (default
``~/.config/job-search/secrets.json``), mode 0600 inside a 0700 directory. It is
AES-256-GCM encrypted; the key lives in the OS keyring when one is available
(Linux Secret Service via ``secret-tool``, macOS Keychain, Windows Credential
Locker) and otherwise in a 0600 key file beside the store. It is the source of
truth for:

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
  python3 tools/secrets_store.py --encrypt
  python3 tools/secrets_store.py --migrate
  python3 tools/secrets_store.py --decrypt-backup FILE [--out DIR]
  python3 tools/secrets_store.py --set agent OPENROUTER_API_KEY   # value on stdin
  python3 tools/secrets_store.py --get agent OPENROUTER_API_KEY
  python3 tools/secrets_store.py --delete agent OPENROUTER_API_KEY
"""
from __future__ import annotations

import argparse
import base64
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

try:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
except ImportError:  # surfaced with a clear message when a store is used
    AESGCM = None

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_DIR = os.path.join(os.path.expanduser("~"), ".config", "job-search")
DEFAULT_PATH = os.path.join(DEFAULT_DIR, "secrets.json")
STORE_FORMAT = "jobsquirrel-secrets"
STORE_VERSION = 2
STORE_CIPHER = "AES-256-GCM"
STORE_AAD = b"jobsquirrel-store-v2"
BACKUP_AAD = b"jobsquirrel-backup-v1"
KEY_ENV = "JOBSQUIRREL_SECRETS_KEY"
NO_KEYRING = "JOBSQUIRREL_NO_KEYRING"
KEYRING_SERVICE = "jobsquirrel"
KEYRING_ACCOUNT = "secrets-key"
SECTION_RE = re.compile(r"^[a-z][a-z0-9_-]{0,40}$")
NAME_RE = re.compile(r"^[A-Za-z0-9_.:@-]{1,160}$")
SECRET_RE = re.compile(r"(KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL|AUTH)", re.I)


class SecretsError(RuntimeError):
    pass


def path() -> str:
    """Where the store lives (honours JOBSQUIRREL_SECRETS)."""
    return os.path.abspath(os.path.expanduser(
        os.environ.get("JOBSQUIRREL_SECRETS") or DEFAULT_PATH))


_KEY = None                 # key that decrypted the store in this process
_KEY_SOURCE = ""            # env | keyring | keyfile


def key_path() -> str:
    """The fallback key file beside the store."""
    p = path()
    return (os.path.splitext(p)[0] if p.endswith(".json") else p) + ".key"


def _encode_key(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def _decode_key(text: str):
    text = (text or "").strip()
    if not text:
        return None
    for decoder in (base64.b64decode, base64.urlsafe_b64decode):
        try:
            raw = decoder(text, validate=True)
        except Exception:
            continue
        if len(raw) == 32:
            return raw
    return None


def _secret_tool(args, stdin: str = ""):
    """Talk to the Secret Service via secret-tool, or return None."""
    if shutil.which("secret-tool") is None:
        return None
    try:
        r = subprocess.run(["secret-tool", *args], input=stdin, capture_output=True,
                           text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout.strip() if r.returncode == 0 else None


def _keyring_get():
    out = _secret_tool(["lookup", "service", KEYRING_SERVICE,
                        "account", KEYRING_ACCOUNT])
    return _decode_key(out) if out else None


def _keyring_put(key: bytes) -> bool:
    if os.environ.get(NO_KEYRING):
        return False
    return _secret_tool(["store", "--label=Jobsquirrel secrets key",
                         "service", KEYRING_SERVICE, "account", KEYRING_ACCOUNT],
                        _encode_key(key)) is not None


def _keyfile_read():
    try:
        with open(key_path(), encoding="utf-8") as fh:
            return _decode_key(fh.read())
    except OSError:
        return None


def _keyfile_write(key: bytes) -> None:
    p = key_path()
    directory = os.path.dirname(p) or "."
    os.makedirs(directory, mode=0o700, exist_ok=True)
    try:
        os.chmod(directory, 0o700)
    except OSError:
        pass
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=".secrets-key.", suffix=".tmp")
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(_encode_key(key) + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, p)
        os.chmod(p, 0o600)
        _fsync_dir(directory)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def key_candidates():
    """Every key we can try, in preference order (env, keyring, keyfile)."""
    seen = set()
    env = _decode_key(os.environ.get(KEY_ENV, ""))
    if env:
        seen.add(env)
        yield env, "env"
    if not os.environ.get(NO_KEYRING):
        k = _keyring_get()
        if k and k not in seen:
            seen.add(k)
            yield k, "keyring"
    k = _keyfile_read()
    if k and k not in seen:
        seen.add(k)
        yield k, "keyfile"


def get_key(create: bool = False):
    """Return (32-byte key, source). With create, make one if none exists."""
    for key, source in key_candidates():
        return key, source
    if not create:
        raise SecretsError("no decryption key found (OS keyring, key file or "
                           f"{KEY_ENV})")
    if AESGCM is None:
        raise SecretsError("cryptography is not installed; run pip install cryptography")
    key = os.urandom(32)
    if _keyring_put(key):
        return key, "keyring"
    _keyfile_write(key)
    return key, "keyfile"


def key_b64() -> str:
    """The current key, base64, for passing to a trusted child process."""
    if _KEY:
        return _encode_key(_KEY)
    for key, _source in key_candidates():
        return _encode_key(key)
    return ""


def _is_encrypted(data: dict) -> bool:
    return data.get("format") == STORE_FORMAT and bool(data.get("payload"))


def _decrypt_store(data: dict, p: str):
    if AESGCM is None:
        raise SecretsError("cryptography is not installed; run pip install cryptography")
    try:
        nonce = base64.b64decode(data["nonce"])
        payload = base64.b64decode(data["payload"])
    except (KeyError, ValueError, TypeError) as exc:
        raise SecretsError(f"{p} is not a valid encrypted store") from exc
    tried = 0
    for key, source in key_candidates():
        tried += 1
        try:
            plain = AESGCM(key).decrypt(nonce, payload, STORE_AAD)
        except Exception:
            continue
        try:
            inner = json.loads(plain.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            continue
        if isinstance(inner, dict):
            return inner, key, source
    why = "no key available" if not tried else "no available key could decrypt it"
    raise SecretsError(f"cannot decrypt {p}: {why}")


def _read_raw() -> dict | None:
    p = path()
    try:
        with open(p, encoding="utf-8") as fh:
            data = json.load(fh)
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as exc:
        raise SecretsError(f"cannot read {p}: {exc}") from exc
    if not isinstance(data, dict):
        raise SecretsError(f"{p} is not a JSON object")
    return data


def _encrypt_payload(payload: dict, key: bytes, aad: bytes) -> dict:
    nonce = os.urandom(12)
    blob = AESGCM(key).encrypt(nonce, json.dumps(payload).encode("utf-8"), aad)
    return {"format": STORE_FORMAT, "version": STORE_VERSION, "cipher": STORE_CIPHER,
            "nonce": base64.b64encode(nonce).decode("ascii"),
            "payload": base64.b64encode(blob).decode("ascii")}


def _empty() -> dict:
    return {"version": 1, "updated": "", "sections": {}}


def load() -> dict:
    """Read and decrypt the store. Missing is empty; corrupt data raises."""
    global _KEY, _KEY_SOURCE
    data = _read_raw()
    if data is None:
        _KEY, _KEY_SOURCE = None, ""
        return _empty()
    if _is_encrypted(data):
        inner, key, source = _decrypt_store(data, path())
        _KEY, _KEY_SOURCE = key, source
    else:
        inner = data          # legacy plaintext; migrate/encrypt on next save
        _KEY, _KEY_SOURCE = None, ""
    sections = inner.get("sections")
    if not isinstance(sections, dict):
        sections = {}
    out = _empty()
    out["sections"] = {str(k): v for k, v in sections.items() if isinstance(v, dict)}
    out["updated"] = str(inner.get("updated") or "")
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


def _write_secure(p: str, data: dict) -> None:
    directory = os.path.dirname(p) or "."
    os.makedirs(directory, mode=0o700, exist_ok=True)
    try:
        os.chmod(directory, 0o700)
    except OSError:
        pass
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=".secrets.", suffix=".tmp")
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, sort_keys=False)
            fh.write("\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, p)
        os.chmod(p, 0o600)
        _fsync_dir(directory)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def _write_raw(data: dict) -> None:
    _write_secure(path(), data)


def save(data: dict) -> None:
    """Encrypt and atomically replace the store (0600 in a 0700 directory)."""
    global _KEY, _KEY_SOURCE
    payload = {"version": 1,
               "updated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
               "sections": data.get("sections") if isinstance(data.get("sections"), dict) else {}}
    key, source = (_KEY, _KEY_SOURCE) if _KEY else (None, "")
    if key is None:
        key, source = get_key(create=True)
    if AESGCM is None:
        raise SecretsError("cryptography is not installed; run pip install cryptography")
    _write_raw(_encrypt_payload(payload, key, STORE_AAD))
    _KEY, _KEY_SOURCE = key, source


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
    """File/permission/encryption health, without exposing values."""
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
    encrypted = False
    if exists:
        try:
            encrypted = _is_encrypted(_read_raw() or {})
        except SecretsError:
            pass
    problems = []
    if exists and mode not in ("0o600", "0o400"):
        problems.append(f"store mode is {mode}, expected 0600")
    if dir_mode and dir_mode not in ("0o700", "0o750"):
        problems.append(f"store directory mode is {dir_mode}, expected 0700")
    if exists and not encrypted:
        problems.append("store is plaintext; run --encrypt (the dashboard does this on start)")
    try:
        load()
    except SecretsError as exc:
        problems.append(str(exc))
    return {"path": p, "exists": exists, "mode": mode, "dir_mode": dir_mode,
            "encrypted": encrypted,
            "encryption": STORE_CIPHER if encrypted else ("plaintext" if exists else ""),
            "key_source": _KEY_SOURCE,
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


def encrypt_store() -> dict:
    """Encrypt a legacy plaintext store (idempotent)."""
    raw = _read_raw()
    if raw is None:
        return check()
    data = load()
    if not _is_encrypted(raw):
        save(data)
    return check()


def _legacy_plaintext_files() -> list[str]:
    bases = {os.path.dirname(path()) or ".", DEFAULT_DIR,
             os.path.dirname(os.path.expanduser(os.environ.get("ACCOUNTS_FILE")
                                                or os.path.join(DEFAULT_DIR, "accounts.json"))),
             os.path.dirname(os.path.expanduser(os.environ.get("AGENT_CFG")
                                                or os.path.join(DEFAULT_DIR, "agent.json"))),
             os.path.dirname(google_config_path())}
    config_dir, _credentials, _token = _google_paths()
    bases.add(config_dir)
    files = set()
    for base in bases:
        for d in glob.glob(os.path.join(base, "secrets-backup-*")):
            if os.path.isdir(d):
                for root, _dirs, names in os.walk(d):
                    files.update(os.path.join(root, n) for n in names)
        for name in ("accounts.json.migrated", "agent.json.bak", "google.json.bak"):
            f = os.path.join(base, name)
            if os.path.isfile(f):
                files.add(f)
        files.update(f for f in glob.glob(os.path.join(base, "token.json.*"))
                     if os.path.isfile(f) and os.path.basename(f) != "token.json")
    return sorted(files)


def encrypt_legacy_backups() -> dict:
    """Fold plaintext backups/archives into one encrypted archive and remove them."""
    files = _legacy_plaintext_files()
    if not files:
        return {}
    key, _source = get_key(create=True)
    if AESGCM is None:
        raise SecretsError("cryptography is not installed; run pip install cryptography")
    blob = {}
    for f in files:
        try:
            raw = open(f, "rb").read()
        except OSError:
            continue
        if len(raw) > 2_000_000:
            continue
        blob[f] = base64.b64encode(raw).decode("ascii")
    if not blob:
        return {}
    stamp = time.strftime("%Y%m%d-%H%M%S")
    out = os.path.join(os.path.dirname(path()) or ".",
                       f"secrets-backup-{stamp}.json.enc")
    wrapper = _encrypt_payload({"created": stamp, "files": blob}, key, BACKUP_AAD)
    _write_secure(out, wrapper)
    # Verify before deleting anything.
    check = _read_json(out)
    plain = AESGCM(key).decrypt(base64.b64decode(check["nonce"]),
                                base64.b64decode(check["payload"]), BACKUP_AAD)
    restored = json.loads(plain.decode("utf-8")).get("files") or {}
    if restored != blob:
        raise SecretsError("encrypted backup verification failed; originals kept")
    removed = 0
    for f in blob:
        try:
            os.remove(f)
            removed += 1
        except OSError:
            pass
    for base in {os.path.dirname(path()) or ".", DEFAULT_DIR}:
        for d in glob.glob(os.path.join(base, "secrets-backup-*")):
            if os.path.isdir(d):
                for root, _dirs, _names in os.walk(d, topdown=False):
                    try:
                        os.rmdir(root)
                    except OSError:
                        pass
    return {"archive": out, "files": len(blob), "removed": removed}


def decrypt_backup(file_: str, out: str = "") -> dict:
    """Restore an encrypted backup archive into a directory (0600 files)."""
    data = _read_json(file_)
    if not _is_encrypted(data):
        raise SecretsError("not an encrypted backup archive")
    if AESGCM is None:
        raise SecretsError("cryptography is not installed")
    for key, _source in key_candidates():
        try:
            plain = AESGCM(key).decrypt(base64.b64decode(data["nonce"]),
                                        base64.b64decode(data["payload"]), BACKUP_AAD)
            obj = json.loads(plain.decode("utf-8"))
        except Exception:
            continue
        files = obj.get("files") if isinstance(obj.get("files"), dict) else {}
        outdir = out or os.path.join(os.path.dirname(path()) or ".",
                                    "secrets-restored-" + time.strftime("%Y%m%d-%H%M%S"))
        os.makedirs(outdir, mode=0o700, exist_ok=True)
        try:
            os.chmod(outdir, 0o700)
        except OSError:
            pass
        written = []
        for i, (orig, b64) in enumerate(files.items()):
            name = os.path.basename(orig) or f"file{i}"
            dest = os.path.join(outdir, name)
            if os.path.exists(dest):
                dest = f"{dest}.{i}"
            with open(dest, "wb") as fh:
                fh.write(base64.b64decode(b64))
            os.chmod(dest, 0o600)
            written.append(dest)
        return {"out": outdir, "files": len(written)}
    raise SecretsError("cannot decrypt backup with any available key")


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
    enc = encrypt_legacy_backups()
    return {"imported": imported, "touched": touched,
            "backup": enc.get("archive") or (backup_dir if os.path.isdir(backup_dir) else ""),
            "encrypted_backup": enc,
            "store": path()}


# ------------------------------------------------------------------ CLI
def _cmd_list() -> int:
    data = load()
    st = check()
    print(f"store: {path()}  ({st['encryption'] or 'empty'}, key: {st['key_source'] or '—'})")
    for section_name, values in data["sections"].items():
        print(f"\n[{section_name}]")
        for name, value in values.items():
            print(f"  {name:<32} {mask(value) or '(empty)'}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="One secure store for Jobsquirrel secrets.")
    ap.add_argument("--list", action="store_true", help="list sections and masked values")
    ap.add_argument("--check", action="store_true", help="check encryption, permissions and syntax")
    ap.add_argument("--encrypt", action="store_true", help="encrypt a legacy plaintext store in place")
    ap.add_argument("--migrate", action="store_true", help="import legacy files and encrypt")
    ap.add_argument("--decrypt-backup", metavar="FILE", help="restore an encrypted backup archive")
    ap.add_argument("--out", default="", help="directory for --decrypt-backup")
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
        print(f"encryption: {st['encryption'] or '—'}  key: {st['key_source'] or '—'}")
        for problem in st["problems"]:
            print(f"FAIL {problem}")
        print("RESULT: PASS" if st["ok"] else "RESULT: FAIL")
        return 0 if st["ok"] else 1
    if args.encrypt:
        st = encrypt_store()
        print(f"encrypted: {st['encryption'] or '—'}  key: {st['key_source'] or '—'}")
        for problem in st["problems"]:
            print(f"FAIL {problem}")
        return 0 if st["ok"] else 1
    if args.migrate:
        out = migrate()
        print(json.dumps(out, indent=2))
        return 0
    if args.decrypt_backup:
        try:
            out = decrypt_backup(args.decrypt_backup, args.out)
        except SecretsError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1
        print(f"restored {out['files']} file(s) to {out['out']}")
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
