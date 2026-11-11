#!/usr/bin/env python3
"""Turn raw missing ATS keywords into readable skills, using the advert context.

The ATS extractor occasionally leaves a bare acronym ("LLMOps", "RLHF"), a
reference code ("UMKACN") or a word from a related-jobs sidebar ("BCG", "GOT").
This module resolves each missing term against the saved advert:

  * a parenthetical expansion in the ad ("Prior-Fitted Networks (PFNs)");
  * a small, unambiguous acronym map;
  * otherwise the configured model reads the ad and says what the term is,
    expanding it and marking non-skills as such.

Results are cached in state/skill-context.json keyed by the role and a hash of
the advert, so the drawer pays for one lookup per role, not per render.

  python3 tools/skill_context.py --key <role-key> [--ai] [--refresh]
"""
import argparse
import hashlib
import json
import os
import re
import sys
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ats_keywords  # noqa: E402
import stateio  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATE = os.path.join(ROOT, "state")
CACHE = os.path.join(STATE, "skill-context.json")
EXPLAIN_CACHE = os.path.join(STATE, "skill-explanations.json")
AGENT_CFG = os.path.join(os.path.expanduser("~"), ".config", "job-search", "agent.json")

# Kinds that are not requirements at all. The drawer hides them and coverage
# excludes them, so a 95% row cannot have an empty "missing" list full of
# currency codes or sidebar company names.
JUNK_KINDS = ("not-a-skill", "company", "currency", "code")

_MEM = None
_JD_MEM = {}

CURRENCY = {"SEK", "EUR", "USD", "GBP", "NOK", "DKK", "CHF", "CAD", "AUD"}
COMMON = {"GOT", "BACK", "SEE", "GET", "YOU", "THE", "AND", "FOR", "NEW", "ALL"}

KNOWN = {
    "LLMOps": "LLM Operations",
    "LLMops": "LLM Operations",
    "RLHF": "Reinforcement Learning from Human Feedback",
    "RLAIF": "Reinforcement Learning from AI Feedback",
    "dbt": "data build tool",
    "MCP": "Model Context Protocol",
    "RAG": "Retrieval-Augmented Generation",
    "PFN": "Prior-Fitted Network",
    "PFNs": "Prior-Fitted Networks",
    "W&B": "Weights & Biases",
    "SOC": "Security Operations Centre",
    "MDR": "Managed Detection and Response",
    "SIEM": "Security Information and Event Management",
    "IPR": "Instant Payments Regulation",
    "PSR": "Payment Services Regulation",
    "IAM": "Identity and Access Management",
    "RBAC": "Role-Based Access Control",
    "OIDC": "OpenID Connect",
    "SAML": "Security Assertion Markup Language",
    "CI/CD": "Continuous Integration / Continuous Delivery",
}


def _read(path):
    try:
        with open(path, encoding="utf-8", errors="ignore") as fh:
            return fh.read()
    except OSError:
        return ""


def _cache():
    global _MEM
    if _MEM is not None:
        return _MEM
    try:
        with open(CACHE, encoding="utf-8") as fh:
            data = json.load(fh)
        _MEM = data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        _MEM = {}
    return _MEM


def _save(data):
    global _MEM
    _MEM = data
    try:
        os.makedirs(STATE, exist_ok=True)
        tmp = CACHE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=1, ensure_ascii=False)
            fh.write("\n")
        os.replace(tmp, CACHE)
    except OSError:
        pass


def _agent_cfg():
    try:
        with open(AGENT_CFG, encoding="utf-8") as fh:
            cfg = json.load(fh)
    except (OSError, ValueError):
        cfg = {}
    try:
        import secrets_store as SS
        cfg["env"] = {**(cfg.get("env") if isinstance(cfg.get("env"), dict) else {}),
                      **{k: v for k, v in SS.section("agent").items() if isinstance(v, str)}}
    except Exception:
        cfg["env"] = cfg.get("env") if isinstance(cfg.get("env"), dict) else {}
    return cfg


def _model_conn():
    """Return (base_url, key, model) for the configured model, or None."""
    cfg = _agent_cfg()
    agent = str(cfg.get("agent") or "").strip()
    env = cfg.get("env") or {}
    model = str(cfg.get("models", {}).get(agent) or cfg.get("model") or "").strip()
    if agent == "opencode":
        try:
            import secrets_store as SS
            key = env.get("OPENCODE_API_KEY") or SS.get("graphrag", "OPENCODE_API_KEY")
        except Exception:
            key = env.get("OPENCODE_API_KEY")
        if key:
            return "https://opencode.ai/zen/go/v1", key, model.split("/")[-1] or "deepseek-v4.1-flash"
    if agent == "openrouter" and env.get("OPENROUTER_API_KEY"):
        return "https://openrouter.ai/api/v1", env["OPENROUTER_API_KEY"], model.split("/")[-1]
    if agent == "local":
        base = (env.get("LOCAL_LLM_BASE_URL") or "http://127.0.0.1:8080/v1").rstrip("/")
        return base, env.get("LOCAL_LLM_API_KEY") or "sk-local", model
    try:
        import secrets_store as SS
        key = SS.get("graphrag", "OPENCODE_API_KEY")
        if key:
            return "https://opencode.ai/zen/go/v1", key, "deepseek-v4.1-flash"
    except Exception:
        pass
    return None


def _header_company(jd_text):
    m = re.search(r"^#\s*(.+?)\s+[—-]\s+", str(jd_text or ""), re.M)
    return m.group(1).strip() if m else ""


def _deterministic(term, cleaned, original):
    """Cheap, context-grounded resolution. Returns a dict or None."""
    t = str(term or "").strip()
    if not t:
        return None
    upper = t.upper()
    if upper in CURRENCY:
        return {"term": t, "label": "", "kind": "not-a-skill", "source": "context",
                "note": "A currency code in the advert, not a skill."}
    if upper in COMMON:
        return {"term": t, "label": "", "kind": "not-a-skill", "source": "context",
                "note": "A common word from a company or page heading, not a skill."}
    company = _header_company(original)
    if company and t.lower() in [w.lower() for w in re.findall(r"\w+", company)]:
        return {"term": t, "label": "", "kind": "not-a-skill", "source": "context",
                "note": f"Part of the employer name ({company}), not a skill."}
    # The term survived cleaning only if it really appears in the advert body.
    if not re.search(r"(?<![A-Za-z0-9])" + re.escape(t) + r"(?![A-Za-z0-9])", cleaned, re.I):
        return {"term": t, "label": "", "kind": "not-a-skill", "source": "context",
                "note": "A reference code or sidebar word that is not in the advert body."}
    # "Full Name (TERM)" or "TERM (full name)".
    for pat in (rf"([A-Z][A-Za-z0-9 &/+'’.\-]{{2,70}}?)\s*\(\s*{re.escape(t)}\s*\)",
                rf"{re.escape(t)}\s*\(\s*([A-Za-z][A-Za-z0-9 &/+'’.\-]{{2,70}}?)\s*\)"):
        m = re.search(pat, cleaned, re.I)
        if m:
            full = re.sub(r"\s+", " ", m.group(1)).strip(" .,;:-")
            if full and full.lower() != t.lower() and len(full) <= 70:
                return {"term": t, "label": f"{full} ({t})", "kind": "skill",
                        "source": "advert", "note": f"The advert expands {t} as “{full}”."}
    if t in KNOWN:
        return {"term": t, "label": f"{KNOWN[t]} ({t})", "kind": "skill",
                "source": "known", "note": f"Common expansion of {t}."}
    return None


def _ai_resolve(terms, cleaned, timeout=60):
    conn = _model_conn()
    if not conn or not terms:
        return {}
    base, key, model = conn
    if not key or not model:
        return {}
    prompt = (
        "You are reading one job advert. For each KEYWORD, say what it actually is "
        "in this advert's context. Expand abbreviations. Classify kind as skill, tool, "
        "domain, company, currency, code or not-a-skill. Use not-a-skill ONLY for a "
        "currency, an employer/company name, a reference code, or an ordinary word from "
        "the page chrome; any capability, tool, domain, role or way of working is a "
        "skill/tool/domain even if the advert words it differently. Keep the label under "
        "70 characters and the note under 140. Never invent a skill the advert does not "
        "mention. Return ONLY a JSON array of objects with keys term, label, kind, note."
        f"\n\nKEYWORDS: {json.dumps(terms)}\n\nADVERT:\n{cleaned[:7000]}"
    )
    payload = {"model": model,
               "messages": [{"role": "system", "content": "You interpret job-advert keywords for a candidate."},
                            {"role": "user", "content": prompt}],
               "temperature": 0, "max_tokens": 900}
    out = None
    for _ in range(2):
        try:
            req = urllib.request.Request(base + "/chat/completions", data=json.dumps(payload).encode(),
                                         headers={"Content-Type": "application/json",
                                                  "Authorization": f"Bearer {key}",
                                                  "User-Agent": "Mozilla/5.0 jobsquirrel/skill-context",
                                                  "x-opencode-session": "skill-context"},
                                         method="POST")
            with urllib.request.urlopen(req, timeout=timeout) as r:
                out = json.load(r)
            break
        except Exception as e:
            if os.environ.get("SKILL_CONTEXT_DEBUG"):
                print(f"skill-context AI error: {type(e).__name__}: {e}", file=sys.stderr)
            out = None
    if out is None:
        return {}
    try:
        text = ((out.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
        text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.I | re.M).strip()
        rows = json.loads(text)
        if isinstance(rows, dict):
            rows = rows.get("terms") or rows.get("results") or []
        wanted = {t.lower() for t in terms}
        got = {}
        for row in rows if isinstance(rows, list) else []:
            term = str((row or {}).get("term") or "").strip()
            if term.lower() not in wanted:
                continue
            kind = str(row.get("kind") or "skill").strip().lower()
            label = str(row.get("label") or "").strip()[:90]
            note = str(row.get("note") or "").strip()[:180]
            # A capability named in the advert is a skill even when the model
            # would rather reject the exact wording.
            if kind == "not-a-skill" and term.upper() not in CURRENCY and term.upper() not in COMMON:
                if re.search(r"(?<![A-Za-z0-9])" + re.escape(term) + r"(?![A-Za-z0-9])",
                             cleaned, re.I):
                    kind = "skill"
                    if not label or re.search(r"\bnot mentioned\b", label, re.I):
                        label = term
            got[term.lower()] = {
                "term": term,
                "label": label,
                "kind": kind if kind in ("skill", "tool", "domain", "company",
                                         "currency", "code", "not-a-skill") else "skill",
                "note": note,
                "source": "ai",
            }
        return got
    except Exception as e:
        if os.environ.get("SKILL_CONTEXT_DEBUG"):
            print(f"skill-context parse error: {type(e).__name__}: {e}", file=sys.stderr)
        return {}


def _chat(messages, max_tokens=500, timeout=45):
    """One small chat completion, with one retry. Returns text or ''."""
    conn = _model_conn()
    if not conn:
        return ""
    base, key, model = conn
    if not key or not model:
        return ""
    payload = {"model": model, "messages": messages, "temperature": 0.2,
               "max_tokens": max_tokens}
    for _ in range(2):
        try:
            req = urllib.request.Request(
                base + "/chat/completions", data=json.dumps(payload).encode(),
                headers={"Content-Type": "application/json",
                         "Authorization": f"Bearer {key}",
                         "User-Agent": "Mozilla/5.0 jobsquirrel/skill-context",
                         "x-opencode-session": "skill-context"},
                method="POST")
            with urllib.request.urlopen(req, timeout=timeout) as r:
                out = json.load(r)
            text = ((out.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
            if text.strip():
                return text.strip()
        except Exception:
            continue
    return ""


def _explain_cache():
    try:
        with open(EXPLAIN_CACHE, encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_explain(data):
    try:
        tmp = EXPLAIN_CACHE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=1, ensure_ascii=False)
            fh.write("\n")
        os.replace(tmp, EXPLAIN_CACHE)
    except OSError:
        pass


def explain(key, term, use_ai=True, timeout=60):
    """A plain-English explanation of one missing requirement.

    Says what the term is in this advert, why the role mentions it, and what
    evidence would show it. Falls back to the short resolver note when the model
    is unavailable.
    """
    key = os.path.basename(str(key or ""))[:120]
    term = str(term or "").strip()
    if not key or not term:
        return {"term": term, "label": term, "kind": "unknown", "plain": "", "note": ""}
    original, cleaned, sha = _jd(key)
    if not original:
        return {"term": term, "label": term, "kind": "unknown",
                "plain": f"{term} is a requirement in this advert.",
                "note": "No saved advert to read."}
    detail = (resolve(key, [term]) or [{}])[0]
    cache = _explain_cache()
    entry = cache.get(key) if isinstance(cache.get(key), dict) else {}
    if entry.get("jd") != sha:
        entry = {"jd": sha, "terms": {}}
    hit = (entry.get("terms") or {}).get(term)
    if hit and hit.get("plain") and (hit.get("plain_source") or "ai") == "ai":
        return hit
    plain = ""
    if use_ai:
        # The context around the term keeps the model on the advert.
        idx = cleaned.lower().find(term.lower())
        excerpt = cleaned[max(0, idx - 1200): idx + 1800] if idx >= 0 else cleaned[:2800]
        prompt = (
            "Explain one requirement from this job advert to the candidate in plain "
            "English. Say (1) what it is, (2) why this advert mentions it, and "
            "(3) what evidence would show it. 2-3 short sentences, concrete nouns, "
            "no marketing language, no unexplained jargon. Do not invent experience "
            "the candidate has. If it is not a real skill (a currency, employer name "
            "or reference code), say that in one sentence.\n\n"
            f"TERM: {term}\nREADABLE LABEL: {detail.get('label') or term}\n"
            f"KIND: {detail.get('kind') or 'unknown'}\n"
            f"SHORT NOTE: {detail.get('note') or ''}\n\nADVERT EXCERPT:\n{excerpt}"
        )
        plain = _chat([{"role": "system", "content": "You explain job-advert requirements plainly and briefly."},
                       {"role": "user", "content": prompt}], max_tokens=1200, timeout=timeout)
    plain_source = "ai"
    if not plain:
        plain = detail.get("note") or f"{term} is named as a requirement in this advert."
        plain_source = "note"
    row = {**detail, "plain": plain.strip()[:900], "plain_source": plain_source,
           "source": detail.get("source") or "context"}
    entry["terms"] = {**(entry.get("terms") or {}), term: row}
    cache[key] = entry
    _save_explain(cache)
    return row


def _jd(key):
    """(original, cleaned, sha) for a role, memoised by file mtime."""
    path = os.path.join(STATE, "job-descriptions", key + ".md")
    try:
        mt = os.path.getmtime(path)
    except OSError:
        return "", "", ""
    hit = _JD_MEM.get(key)
    if hit and hit[0] == mt:
        return hit[1], hit[2], hit[3]
    original = _read(path)
    cleaned = ats_keywords.clean_jd(original)
    sha = hashlib.sha1(original.encode("utf-8", "ignore")).hexdigest()
    _JD_MEM[key] = (mt, original, cleaned, sha)
    return original, cleaned, sha


def resolve(key, terms, use_ai=False, refresh=False, timeout=60):
    """Resolve missing keywords for a role, in the order given."""
    key = os.path.basename(str(key or ""))[:120]
    terms = [str(t).strip() for t in (terms or []) if str(t).strip()]
    if not key or not terms:
        return []
    original, cleaned, sha = _jd(key)
    if not original:
        return [{"term": t, "label": "", "kind": "unknown", "source": "", "note": ""} for t in terms]
    store = _cache()
    entry = store.get(key) if isinstance(store.get(key), dict) else {}
    if entry.get("jd") != sha:
        entry = {"jd": sha, "terms": {}}
    out, pending = [], []
    for t in terms:
        hit = None if refresh else (entry.get("terms") or {}).get(t)
        if not hit:
            hit = _deterministic(t, cleaned, original)
        if hit is None:
            pending.append(t)
            hit = {"term": t, "label": "", "kind": "unknown", "source": "", "note": ""}
        out.append(hit)
    if use_ai and pending:
        try:
            ai = _ai_resolve(pending, cleaned, timeout=timeout)
        except Exception:
            ai = {}
        for i, row in enumerate(out):
            if row["term"].lower() in ai:
                out[i] = ai[row["term"].lower()]
        entry["terms"] = {**(entry.get("terms") or {}),
                          **{r["term"]: r for r in out if r.get("source") == "ai"}}
    entry["terms"] = {**(entry.get("terms") or {}),
                      **{r["term"]: r for r in out if r.get("source") != "unknown"}}
    store[key] = entry
    _save(store)
    deduped, seen = [], set()
    for row in out:
        k = str(row.get("term") or "").lower()
        if k and k not in seen:
            seen.add(k)
            deduped.append(row)
    return deduped


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--key", required=True)
    ap.add_argument("--term", action="append", default=[])
    ap.add_argument("--ai", action="store_true")
    ap.add_argument("--refresh", action="store_true")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    terms = args.term
    if not terms:
        ats = _read(os.path.join(STATE, "ats", args.key + ".txt"))
        terms = [ln.strip() for ln in ats.splitlines()
                 if ln.strip() and not ln.startswith("#")][:40]
    rows = resolve(args.key, terms, use_ai=args.ai, refresh=args.refresh)
    if args.json:
        print(json.dumps(rows, ensure_ascii=False, indent=1))
    else:
        for r in rows:
            print(f"{r['term']:<18} {r['kind']:<12} {r.get('label') or '-'}"
                  + (f"  — {r['note']}" if r.get("note") else ""))


if __name__ == "__main__":
    main()
