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
    # The tools line belongs to the owner: config/cv.json's "tools_line". It is
    # added only when that line exists, so no one else's CV grows skills they
    # never claimed (the project's own never-fabricate rule).
    tools_line = str(B._CV.get("tools_line") or "").strip()
    for r in ROLES:
        if tools_line:
            r["skills"].append(("Tools & technologies", tools_line))
        B.render_cv(r)
        B.render_motivation(r)
        try:
            import cv_target
            pdf = cv_target.to_pdf(os.path.join(B.OUT, f"{B.CV_PREFIX}_CV_{r['key']}.docx"))
        except Exception as exc:
            print(f"WARN: PDF not generated for {r['key']}: {exc}")
        else:
            if pdf:
                print(f"wrote {pdf}")
            else:
                print(f"WARN: no PDF for {r['key']} (is LibreOffice installed?)")
    print("done")


if __name__ == "__main__":
    main()
