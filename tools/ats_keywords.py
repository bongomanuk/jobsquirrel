#!/usr/bin/env python3
"""Extract ATS keywords from a job description and check coverage.

ATS scanners rank a CV/letter by how well it matches the job ad's terms. This
pulls the meaningful terms out of an ad and scores a document against them, so we
can tune the letter until the coverage is high.

Usage:
  # extract keywords from a saved ad
  python3 tools/ats_keywords.py --jd state/job-descriptions/<role>.md \
      --out state/ats/<role>.txt

  # score a letter (+ optional CV) against them
  python3 tools/ats_keywords.py --jd state/job-descriptions/<role>.md \
      --letter documents/applications/Motivation_<Company>_<Role>.docx \
      --cv documents/archetypes/YOUR_CV.docx

The keyword file is one term per line; check_documents.py reads it via
--ats-keywords.
"""
import argparse
import os
import re
import sys

from docx import Document

# Terms that matter to roles in this search. Matched case-insensitively on word
# boundaries; add to this list as new roles appear.
TECH_TERMS = [
    # languages / runtimes
    "Python", "TypeScript", "JavaScript", "Rust", "Java", "Go", "Golang", "SQL",
    "C++", "C#", "Scala", "Kotlin", "Node.js", "Svelte", "React",
    # data / AI
    "LLM", "LLMs", "RAG", "retrieval", "reranking", "reranker", "embeddings",
    "vector search", "vector database", "knowledge graph", "knowledge graphs",
    "ontology", "ontologies", "graph database", "Neo4j", "semantic search",
    "NLP", "machine learning", "ML", "MLOps", "deep learning", "fine-tuning",
    "prompt engineering", "agents", "agentic", "agent", "MCP", "tool calling",
    "function calling", "evaluation", "guardrails", "human-in-the-loop",
    "LLMOps", "LangChain", "LlamaIndex", "PyTorch", "TensorFlow", "scikit-learn",
    "Pandas", "NumPy", "Spark", "Airflow", "dbt", "Kafka", "Spark Streaming",
    "real-time", "streaming", "ETL", "ELT", "data pipelines", "data engineering",
    "data platform", "feature store", "model serving", "inference", "Vertex AI",
    "Gemini", "OpenAI", "Anthropic", "Hugging Face", "transformers", "BERT",
    # cloud / platform / infra
    "AWS", "Azure", "GCP", "Google Cloud", "Kubernetes", "Docker", "Terraform",
    "Helm", "Istio", "service mesh", "microservices", "serverless", "Lambda",
    "on-premise", "hybrid cloud", "CI/CD", "GitHub Actions", "Jenkins", "GitLab",
    "ArgoCD", "Linux", "networking", "SRE", "observability", "monitoring",
    "Prometheus", "Grafana", "OpenTelemetry", "datadog", "incident response",
    "high availability", "scalability", "distributed systems", "Postgres",
    "PostgreSQL", "MySQL", "MongoDB", "Redis", "Elasticsearch", "ScyllaDB",
    "Snowflake", "BigQuery", "databricks", "dbt",
    # security / governance / compliance
    "security", "AppSec", "application security", "cloud security", "DevSecOps",
    "threat modelling", "threat modeling", "IAM", "zero trust", "penetration testing",
    "vulnerability management", "SOC", "SIEM", "incident management", "ISO 27001",
    "ISO 42001", "SOC 2", "GDPR", "NIS2", "DORA", "EU AI Act", "NIST", "audit",
    "governance", "risk", "compliance", "encryption", "PKI", "SSO", "RBAC",
    "access control", "data sovereignty", "prompt injection",
    # ways of working / leadership
    "architecture", "enterprise architecture", "technical leadership", "team lead",
    "engineering manager", "head of engineering", "VP Engineering", "CTO",
    "mentoring", "coaching", "stakeholder management", "roadmap", "strategy",
    "agile", "Scrum", "Kanban", "product", "cross-functional", "hiring",
    "communication", "collaboration", "documentation", "testing", "TDD",
    "code review", "Claude Code", "GitHub Copilot", "AI-assisted development",
    # backend / product / domain (common in these ads)
    "backend", "API", "REST", "GraphQL", "microservices", "event-driven",
    "cloud infrastructure", "distributed systems", "data extraction",
    "structured extraction", "financial data", "fintech", "ERP", "accounting",
    "payments", "banking", "healthcare", "medtech", "public sector",
]

STOP = set("""a an the and or for with to of in on at as by is are be we you they
their our your this that from will can have has had not but if then than so such
about into over under more most other role team teams work works working job
position candidate experience years year skills strong good great ability able
across within using use used must should would could who what when where which
while also both each all any new own you'll we're it's candidate's etc""".split())

# Generic words that survive the frequency pass but do not help ATS matching.
GENERIC = set("""cloud data science engineer engineering developer software senior
junior lead head principal staff manager director specialist business technology
technical solutions solution platform systems system IT AI ML
Google Microsoft Amazon""".split())

# Acronyms that are noise, not useful keywords.
ACRONYM_STOP = set("""AI ML IT IS US UK EU CEO CTO CFO COO VP HR PR QA KPI ROI OKR
OS ARR MRR PTO UFC NYC LATAM EMEA APAC B2B B2C YOY EOD ASAP FYI FAQ PDF URL HTTP
HTTPS API CPU GPU RAM SSD IO N/A TBD WFH I/O
YOU LL WE OUR THE AND FOR ARE NOT NEW ALL GET SEE WHY HOW WHO ITS YES NOW THIS
THAT HAVE WILL WITH YOUR FROM THEY WHAT WHEN WHERE""".split())


def docx_text(path):
    return " ".join(p.text for p in Document(path).paragraphs)


def extract(jd_text):
    low = jd_text.lower()
    found = []
    for term in TECH_TERMS:
        if re.search(r"(?<![a-z0-9])" + re.escape(term.lower()) + r"(?![a-z0-9])", low):
            found.append(term)
    # Acronyms / all-caps terms (e.g. ERP, API, CRM) that recur in the ad.
    words = re.findall(r"\b[A-Z][A-Z0-9.+#/&-]{1,5}\b", jd_text)
    freq = {}
    for w in words:
        if w.upper() in ACRONYM_STOP or w.upper() in GENERIC:
            continue
        freq[w] = freq.get(w, 0) + 1
    extras = [w for w, n in sorted(freq.items(), key=lambda x: -x[1]) if n >= 2]
    # de-dupe, keep curated order then extras
    seen = {t.lower() for t in found}
    for w in extras:
        if w.lower() not in seen:
            found.append(w)
            seen.add(w.lower())
    return found


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--jd", required=True, help="job description text file")
    ap.add_argument("--out", default="", help="write one keyword per line")
    ap.add_argument("--letter", default="")
    ap.add_argument("--cv", default="")
    ap.add_argument("--min-coverage", type=float, default=0.6)
    args = ap.parse_args()

    with open(args.jd, encoding="utf-8", errors="ignore") as fh:
        jd_text = fh.read()
    keywords = extract(jd_text)

    if args.out:
        out_dir = os.path.dirname(args.out)
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)
        with open(args.out, "w") as fh:
            fh.write("# ATS keywords extracted from " + os.path.basename(args.jd) + "\n")
            fh.write("\n".join(keywords) + "\n")
        print(f"wrote {len(keywords)} keywords to {args.out}")

    if args.letter:
        corpus = docx_text(args.letter).lower()
        if args.cv and os.path.isfile(args.cv):
            corpus += " " + docx_text(args.cv).lower()
        missing = [k for k in keywords if k.lower() not in corpus]
        cov = (len(keywords) - len(missing)) / len(keywords) if keywords else 1.0
        print(f"coverage: {len(keywords)-len(missing)}/{len(keywords)} ({cov:.0%})")
        if missing:
            print("missing:", ", ".join(missing))
        if cov < args.min_coverage:
            print("RESULT: FAIL")
            sys.exit(1)
        print("RESULT: PASS")

    if not args.out and not args.letter:
        print("\n".join(keywords))


if __name__ == "__main__":
    main()
