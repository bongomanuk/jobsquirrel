import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cv_builder as B
B.OUT = os.environ.get("CV_OUT", os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "documents", "archetypes"))
os.makedirs(B.OUT, exist_ok=True)

ROLES = B.load_archetypes()

def main():
    import sys
    if "-h" in sys.argv or "--help" in sys.argv:
        print("usage: build_archetypes.py\n"
              "Builds the archetype CVs and motivation letters into documents/archetypes/\n"
              "(override with CV_OUT). Identity and archetypes come from config/.")
        return
    for r in ROLES:
        r["skills"].append(("Tools & technologies",
            "Python, TypeScript, JavaScript, SQL, Java, Rust, C#, Bash; PyTorch, TensorFlow, scikit-learn, pandas, NumPy; "
            "LLM, Generative AI, RAG, embeddings, vector databases, prompt engineering, evaluation, guardrails, AI agents, MCP; "
            "Kubernetes, Docker, Terraform, CI/CD, Git, GitHub Actions, Azure DevOps; AWS, Azure, GCP; "
            "PostgreSQL, ScyllaDB, MongoDB, Cassandra, Kafka, Redis; REST APIs, GraphQL, microservices, event-driven architecture, "
            "observability, Prometheus, Grafana, SRE; ISO 27001, IAM, Okta, Keycloak, SSO/SAML, RBAC/ABAC, Zero Trust, GRC; "
            "Claude Code, GitHub Copilot."))
        B.render_cv(r)
        B.render_motivation(r)
        try:
            import cv_target
            cv_target.to_pdf(os.path.join(B.OUT, f"{B.CV_PREFIX}_CV_{r['key']}.docx"))
        except Exception as exc:
            print(f"WARN: PDF not generated for {r['key']}: {exc}")
        else:
            print(f"wrote {os.path.join(B.OUT, B.CV_PREFIX + '_CV_' + r['key'] + '.pdf')}")
    print("done")


if __name__ == "__main__":
    main()
