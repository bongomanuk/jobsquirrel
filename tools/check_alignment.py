#!/usr/bin/env python3
"""Role/CV alignment gate.

Keyword coverage alone is not enough: a CV can hit 60% of an ad's terms while being
the WRONG KIND of CV (e.g. an AI-Architect CV sent to a backend/systems req). This
classifies the role's family from the job description and checks that the chosen CV
archetype actually foregrounds that family's must-have stack.

Usage:
  python3 tools/check_alignment.py --cv documents/archetypes/X.docx \
      --jd state/job-descriptions/y.md
  python3 tools/check_alignment.py --cv X.docx --keywords "Rust,gRPC,distributed,Kafka,Linux"

Exit codes: 0 aligned, 1 misaligned.
"""
import argparse
import json
import os
import re
import sys

from docx import Document

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Keywords per family (lowercase, substring-matched on the JD text).
FAMILIES = {
    "systems_backend": ["rust", "c++", "golang", " go ", "go,", "java", "grpc", "protobuf",
                        "arrow", "distributed", "embedded", "robotics", "firmware",
                        "networking", "routing", "linux", "kafka", "streaming", "rest",
                        "graphql", "low-latency", "low latency", "real-time", "real time",
                        "backend", "scylla", "cassandra", "postgres", "database", "protocol"],
    "ai_ml": ["llm", "rag", "agentic", "agent", "mcp", "embedding", "vector", "fine-tun",
              "pytorch", "tensorflow", "nlp", "prompt", "guardrail", "generative",
              "machine learning", "ml engineer", "evals", "evaluation"],
    "data_science": ["data scien", "forecast", "statistic", "optimis", "optimiz", "monte carlo",
                     "experiment", "a/b", "pandas", "numpy", "scikit", "time series"],
    "platform_devops": ["kubernetes", "terraform", " docker", "ci/cd", "observability",
                        "prometheus", "grafana", "sre", "aws", "gcp", "azure", "cloud",
                        "platform engineer", "infrastructure"],
    "security": ["security engineer", "iam", "zero trust", "incident response", "soc",
                 "penetration", "threat", "vulnerability", "saml", "oauth", "secops"],
    "leadership": ["engineering manager", "head of engineering", "director of engineering",
                   "vp of engineering", "people management", "line manager", "manage a team",
                   "lead a team", "managing engineers", "head of data"],
    "consulting": ["consultant", "consulting", "konsult", "management consultant",
                   "it consultant", "technology consultant", "advisory"],
}

# Must-have tokens the CV has to contain for a given role family.
MUST = {
    "systems_backend": {
        "languages(≥2)": ("rust", "c++", "golang", " go,", "java", "c#"),
        "systems": ("linux", "networking", "distributed", "kafka", "docker", "kubernetes",
                    "database", "postgres", "scylla", "cassandra", "rest", "grpc"),
    },
    "ai_ml": {
        "ai-core(≥2)": ("llm", "rag", "agent", "machine learning", "pytorch", "tensorflow", "nlp"),
    },
    "data_science": {
        "ds-core(≥2)": ("data scien", "machine learning", "forecast", "pytorch", "tensorflow",
                        "scikit", "statistic", "python"),
    },
    "platform_devops": {
        "platform(≥2)": ("kubernetes", "docker", "terraform", "cloud", "aws", "gcp", "azure",
                         "ci/cd", "observability", "prometheus"),
    },
    "security": {
        "security(≥2)": ("security", "iam", "zero trust", "incident", "soc", "threat",
                         "vulnerability", "saml", "oauth"),
    },
    "leadership": {
        "leadership(≥1)": ("engineering manager", "head of", "director", "vp ", "led teams",
                           "managed managers", "people management", "lead a team", "mentor"),
    },
    "consulting": {},
}


# Families that a given role family may legitimately be served by (archetype must be in the set).
ACCEPT = {
    "systems_backend": {"systems_backend"},
    "ai_ml": {"ai_ml", "platform_devops"},
    "platform_devops": {"platform_devops", "systems_backend"},
    "data_science": {"data_science"},
    "security": {"security"},
    "leadership": {"leadership", "ai_ml"},
    "consulting": {"consulting", "leadership", "ai_ml", "platform_devops", "security",
                   "systems_backend", "data_science"},
}

# Domains this profile has NO production experience in. If the ROLE TITLE names one
# of these, the role is out of profile no matter how well the keyword scores line up:
# an "Android Engineer" ad still scores as systems_backend because it mentions Java,
# REST, distributed, databases, etc., and a "Generative Audio" research ad still
# scores as ai_ml because it mentions machine learning and PyTorch.
MISFIT_TITLE = {
    "mobile (Android/iOS)": [
        r"\bandroid\b", r"\bios\b", r"\bkotlin\b", r"\bswift\b", r"\bswiftui\b",
        r"\bjetpack\b", r"\breact native\b", r"\bflutter\b",
        r"\bmobile (?:engineer|developer|app|platform)\b",
    ],
    "audio / speech ML": [
        r"\baudio\b", r"\bspeech\b", r"\bvoice\b", r"\bacoustic\b", r"\basr\b", r"\btts\b",
        r"\btext[- ]to[- ]speech\b", r"\bspeech[- ]to[- ]text\b", r"\bsignal processing\b",
    ],
    "embedded / hardware / firmware": [
        r"\bembedded\b", r"\bfirmware\b", r"\brtos\b", r"\bmicrocontroller\b", r"\bfpga\b",
        r"\bpcb\b", r"\bhardware\b", r"\brobotics\b", r"\bdriver development\b",
    ],
    "games / graphics": [
        r"\bgame (?:engine|developer|programmer|engineer)\b",
        r"\bgraphics (?:engineer|programmer)\b", r"\brendering engineer\b", r"\bshader\b",
        r"\bunity\b", r"\bunreal\b",
    ],
}

# Languages this profile does NOT use in production. A title that makes one of
# these the primary language is out of profile even if the rest of the ad reads
# like a supported family.
MISFIT_LANG_TITLE = [
    (r"c\+\+|\bcpp\b", "C++"),
    (r"\bgolang\b|\(\s*go\s*\)|\bgo\s+(?:developer|engineer|backend|programmer)\b", "Go"),
    (r"\bkotlin\b", "Kotlin"),
    (r"\bswift\b", "Swift"),
    (r"\.net\b", ".NET"),
    (r"\bscala\b", "Scala"),
    (r"\bruby\b|\brails\b", "Ruby"),
    (r"\bphp\b", "PHP"),
    (r"\belixir\b", "Elixir"),
    (r"\berlang\b", "Erlang"),
    (r"\bclojure\b", "Clojure"),
    (r"\bhaskell\b", "Haskell"),
    (r"\bobjective-c\b", "Objective-C"),
    (r"\bperl\b", "Perl"),
    (r"\bdart\b|\bflutter\b", "Dart/Flutter"),
]

# Tokens for languages/tech this profile does NOT use in production. Bare "go" is
# only treated as the language inside explicit language/stack lines (see below),
# so the English verb "go" in prose is never mistaken for Golang.
UNSUPPORTED_TOKENS = {
    "Go": ("golang", "go"),
    "C++": ("c++", "cpp"),
    ".NET": (".net",),
    "Kotlin": ("kotlin",),
    "Swift": ("swift",),
    "Scala": ("scala",),
    "Ruby": ("ruby", "ruby on rails"),
    "PHP": ("php",),
    "Elixir": ("elixir",),
    "Erlang": ("erlang",),
    "Clojure": ("clojure",),
    "Haskell": ("haskell",),
    "Objective-C": ("objective-c",),
    "Perl": ("perl",),
    "Dart/Flutter": ("dart", "flutter"),
}
# Unambiguous language tokens usable in prose requirement phrases.
UNSUPPORTED_UNAMBIG = ("golang", "c++", "cpp", ".net", "kotlin", "swift",
                       "scala", "ruby", "php", "elixir", "erlang", "clojure", "haskell",
                       "objective-c", "perl", "dart", "flutter")


def _tok_re(t):
    return re.compile(r"(?<![a-z0-9+#.])" + re.escape(t) + r"(?![a-z0-9+#])")


def body_language_misfits(low):
    """Languages the job requires that are not in this profile's stack, found in the
    JD body (not just the title): explicit language/stack lines and requirement phrases."""
    out = []
    for m in re.finditer(r"(?im)^\s*(?:languages?|tech(?:nology)?\s*stack|our\s+stack|stack)\s*[:：]\s*(.+)$", low):
        line = m.group(1)
        for lang, toks in UNSUPPORTED_TOKENS.items():
            if any(_tok_re(t).search(line) for t in toks):
                out.append(f"job's stack lists {lang}, which this profile does not use")
    for m in re.finditer(
        r"(?i)\b(?:strong|proven|expertise\s+in|experience\s+(?:with|in|of)|proficient(?:cy)?\s+in"
        r"|deep\s+(?:knowledge|understanding)\s+of|solid|skilled\s+in|advanced|extensive)\b[^.\n]{0,60}", low):
        seg = m.group(0)
        for t in UNSUPPORTED_UNAMBIG:
            if _tok_re(t).search(seg):
                out.append(f"job requires {t} experience, which is not in this profile's stack")
    seen, res = set(), []
    for r in out:
        if r not in seen:
            seen.add(r); res.append(r)
    return res


# Specific phrases that only appear when the role is genuinely in a misfit domain
# (used when the title is generic, e.g. "Backend Engineer" at an audio company).
STRONG_DOMAIN_PHRASES = {
    "mobile (Android/iOS)": [
        r"android sdk", r"jetpack compose", r"ios app", r"\bxcode\b", r"play store",
        r"app store", r"kotlin multiplatform", r"mobile app development",
    ],
    "audio / speech ML": [
        r"speech recognition", r"text[- ]to[- ]speech", r"speech[- ]to[- ]text", r"\basr\b",
        r"\btts\b", r"acoustic model", r"generative audio", r"audio ml", r"voice agent",
        r"music generation", r"speech synthesis",
    ],
}


def _all_paragraphs(doc):
    """Top-level and table-cell paragraphs (archetypes are laid out in tables)."""
    paras = list(doc.paragraphs)
    for tbl in doc.tables:
        for row in tbl.rows:
            for cell in row.cells:
                for p in cell.paragraphs:
                    paras.append(p)
                for nt in cell.tables:
                    for nrow in nt.rows:
                        for ncell in nrow.cells:
                            paras.extend(ncell.paragraphs)
    return paras


def docx_paras(path):
    d = Document(path)
    return [p.text.lower() for p in _all_paragraphs(d) if p.text.strip()]


def framing(path):
    """CV text WITHOUT the shared 'Tools & technologies' line, which every archetype
    carries and which would otherwise mask a wrong archetype."""
    paras = docx_paras(path)
    keep = [p for p in paras if "tools & technologies" not in p and "scikit-learn" not in p]
    return " ".join(keep)


def _term_count(text, term):
    """Substring count, except bare 'rest' which means the REST API style.

    Counting 'rest' as a plain substring also matched 'interest', 'interested'
    and 'restaurant', which silently inflated systems_backend scores for ads
    that contain no systems terms at all (e.g. an analytics-engineering req).
    """
    if term == "rest":
        return len(re.findall(r"(?<![a-z])rest(?:ful)?(?![a-z])", text))
    return text.count(term)


def classify(text):
    scores = {f: sum(_term_count(text, t) for t in terms) for f, terms in FAMILIES.items()}
    fam = max(scores, key=scores.get)
    return fam, scores


def load_archetypes():
    """The configured CV archetypes (config/archetypes.json, falling back to the
    example). Keys drive which CVs exist; nothing about them is hard-coded."""
    for fn in ("archetypes.json", "archetypes.example.json"):
        p = os.path.join(ROOT, "config", fn)
        if os.path.isfile(p):
            with open(p, encoding="utf-8") as fh:
                data = json.load(fh)
            return [a for a in data if isinstance(a, dict)]
    return []


ARCHETYPES = load_archetypes()


def archetype_family(entry):
    """Infer an archetype's role family from its own key/title/tagline/tags."""
    text = " ".join(str(entry.get(k, "")) for k in ("key", "title", "headline", "tagline"))
    text += " " + " ".join(str(t) for t in (entry.get("tags") or []))
    return classify(text.lower())[0]


def cv_family(path):
    """Map a CV filename fragment to a role family via the configured archetypes."""
    b = os.path.basename(path).lower()
    for entry in ARCHETYPES:
        key = str(entry.get("key", "")).lower()
        if key and key in b:
            return archetype_family(entry)
    return None


def meets(cv, groups):
    details, ok = [], True
    for label, opts in groups.items():
        # "≥2" style: need at least 2 distinct present, else 1
        want = 2 if "≥2" in label else 1
        present = [o.strip() for o in opts if _term_count(cv, o.strip())]
        if len(present) < want:
            ok = False
        details.append(f"{label}: {len(present)}/{want} {present}")
    return ok, details


# Leadership-titled roles may legitimately take the leadership CV regardless of family.
LEAD_TITLE = re.compile(
    r"\b(cto|cio|ciso|chief|head of|director|vp|vice president|engineering manager|"
    r"manager|team lead|tech lead|technical lead|co-founder|founder|leader|lead)\b",
    re.I)


def main():
    ap = argparse.ArgumentParser(description="Role/CV alignment gate.")
    ap.add_argument("--cv", required=True)
    ap.add_argument("--jd", default="")
    ap.add_argument("--title", default="")
    ap.add_argument("--keywords", default="")
    args = ap.parse_args()

    jd = ""
    if args.jd and os.path.isfile(args.jd):
        jd = open(args.jd).read()
    if args.keywords:
        jd += " " + args.keywords.replace(",", " ")
    if not os.path.isfile(args.cv):
        print(f"RESULT: FAIL - CV not found: {args.cv}")
        return 1

    low = jd.lower()

    # --- Domain / language misfit gate (title-driven) -------------------------
    # The profile has NO mobile, audio/speech-ML, embedded/hardware or
    # games/graphics experience; titles in those domains are out of profile.
    title = (args.title or "").strip().lower()
    if not title:
        for line in jd.splitlines():
            if line.strip():
                title = line.strip().lower()
                break
    misfits = []
    for domain, pats in MISFIT_TITLE.items():
        if any(re.search(p, title) for p in pats):
            misfits.append(f"role title names {domain} - outside this profile's experience")
    for pat, lang in MISFIT_LANG_TITLE:
        if re.search(pat, title):
            misfits.append(f"role title requires {lang}, which this profile does not use in production")
    for domain, pats in STRONG_DOMAIN_PHRASES.items():
        if any(re.search(p, low) for p in pats):
            misfits.append(f"job description is for {domain} - outside this profile's experience")
    for reason in body_language_misfits(low):
        misfits.append(reason)
    if misfits:
        print(f"  role title  : {title or '(unknown)'}")
        print("RESULT: FAIL - alignment")
        for m in misfits:
            print("  -", m)
        return 1

    if not jd.strip():
        print("  no JD/keywords supplied - alignment not checked")
        return 0

    role_fam, scores = classify(low)
    cv = framing(args.cv)
    cv_fam = cv_family(args.cv)

    print(f"  role family : {role_fam}  (scores: {', '.join(f'{k}={v}' for k,v in sorted(scores.items(), key=lambda x:-x[1])[:3])})")
    print(f"  CV archetype: {cv_fam}  ({os.path.basename(args.cv)})")

    ok, details = meets(cv, MUST[role_fam])
    for d in details:
        print(f"    {d}")

    errors = []
    if not ok:
        errors.append(f"CV does not foreground the {role_fam} must-haves the role needs (profile/skills)")
    allowed = set(ACCEPT[role_fam])
    if LEAD_TITLE.search(low):
        allowed.add("leadership")
    if cv_fam and cv_fam not in allowed:
        errors.append(f"CV archetype '{cv_fam}' is not valid for a '{role_fam}' role - "
                      f"use one of the configured {sorted(allowed)} archetypes")

    if errors:
        print("RESULT: FAIL - alignment")
        for e in errors:
            print("  -", e)
        return 1
    print("RESULT: PASS - alignment")
    return 0


if __name__ == "__main__":
    sys.exit(main())
