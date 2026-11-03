import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import ontology as ONT


def test_example_ontology_is_valid():
    data = json.loads((ROOT / "config" / "ontology.example.json").read_text())
    assert {"classes", "relations"} <= set(data)
    assert "PERSON" in data["classes"]
    assert "TECHNOLOGY" in data["classes"]
    assert "REQUIRES" in data["relations"]
    assert "SATISFIES" in data["relations"]


def test_class_mapping_and_aliases():
    assert ONT.class_for("technology") == "TECHNOLOGY"
    assert ONT.class_for("company") == "ORGANIZATION"
    assert ONT.class_for("tool") == "TECHNOLOGY"
    assert ONT.class_for("something-unexpected") == "CONCEPT"
    meta = ONT.class_meta("technology")
    assert meta["id"] == "TECHNOLOGY"
    assert meta["label"] == "Technology"
    assert meta["color"].startswith("#")


def test_summary_without_pandas():
    class Frame:
        columns = ["type"]
        def __getitem__(self, key):
            class Col:
                def tolist(self_inner):
                    return ["TECHNOLOGY", "company", "SKILL"]
            return Col()
    out = ONT.summary(Frame())
    counts = {c["id"]: c["count"] for c in out["classes"]}
    assert counts["TECHNOLOGY"] == 1
    assert counts["ORGANIZATION"] == 1
    assert counts["SKILL"] == 1
    assert out["total"] == 3
