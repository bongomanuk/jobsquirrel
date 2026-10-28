#!/usr/bin/env python3
"""Ask the selected agent/model for a read-only suggestion on one review item."""

import json
import os
import re
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATE = os.path.join(ROOT, "state")
CFG = os.path.join(os.path.expanduser("~"), ".config", "job-search", "agent.json")


def _cfg():
    try:
        with open(CFG, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def _plain(body):
    body = re.sub(r"(?is)<(style|script|head)\b[^>]*>.*?</\1>", " ", body or "")
    body = re.sub(r"(?is)<br\s*/?>|</p>|</li>", "\n", body)
    body = re.sub(r"<[^>]+>", " ", body)
    return re.sub(r"[ \t]+", " ", body).strip()


def _body(mid):
    try:
        with open(os.path.join(STATE, "gmail_cache.json"), encoding="utf-8") as fh:
            return ((json.load(fh).get(mid) or {}).get("body") or "")
    except (OSError, ValueError):
        return ""


def ask(item):
    mid = str(item.get("id") or "")
    cfg = _cfg()
    agent = str(cfg.get("agent") or "")
    model = str(cfg.get("model") or "")
    env = cfg.get("env") if isinstance(cfg.get("env"), dict) else {}
    if agent == "local":
        base = (env.get("LOCAL_LLM_BASE_URL") or "http://127.0.0.1:8080/v1").rstrip("/")
        url = base + "/chat/completions"
        key = env.get("LOCAL_LLM_API_KEY") or "sk-local"
        headers = {"Content-Type": "application/json", "Authorization": f"Bearer {key}"}
    elif agent == "openrouter":
        key = env.get("OPENROUTER_API_KEY") or ""
        if not key:
            return {"error": "no OPENROUTER_API_KEY set"}
        url = "https://openrouter.ai/api/v1/chat/completions"
        headers = {"Content-Type": "application/json", "Authorization": f"Bearer {key}"}
    else:
        return {"error": "select Local LLM or OpenRouter in Settings for review suggestions"}
    if not model:
        return {"error": "no model selected in Settings"}
    prompt = (
        "Classify one job-application email. Return ONLY a JSON object with keys: "
        "action (true/false), category (INTERVIEW, VERIFICATION, REJECTION, CONFIRMATION, OTHER), "
        "company, role, reason, evidence (a short exact quote). Do not invent a company or role. "
        f"\n\nSender: {item.get('sender','')}\nSubject: {item.get('subject','')}\n"
        f"Reviewer note: {item.get('reason','')}\n\nEmail:\n{_plain(_body(mid))[:7000]}"
    )
    payload = {"model": model,
               "messages": [{"role": "system", "content": "You review job-application email for a human."},
                            {"role": "user", "content": prompt}],
               "temperature": 0.1, "max_tokens": 500}
    try:
        req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=180) as r:
            out = json.load(r)
        text = ((out.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
        text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.I | re.M).strip()
        try:
            suggestion = json.loads(text)
        except ValueError:
            suggestion = {"raw": text[:2000]}
        return {"ok": "suggestion", "suggestion": suggestion, "agent": agent, "model": model}
    except Exception as e:
        return {"error": f"model review failed: {str(e)[:300]}"}
