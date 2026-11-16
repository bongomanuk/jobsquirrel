"""The incremental knowledge-graph update must actually run the update pipeline."""
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_update_uses_the_base_method():
    with open(os.path.join(ROOT, "tools", "kb_update.sh"), encoding="utf-8") as fh:
        sh = fh.read()
    # graphrag appends "-update" to the method, so passing "standard-update"
    # would ask for the unregistered "standard-update-update" and run nothing.
    assert "--method standard-update" not in sh
    assert "--method standard" in sh


def test_update_loads_the_graphrag_key_from_the_store():
    with open(os.path.join(ROOT, "tools", "kb_update.sh"), encoding="utf-8") as fh:
        sh = fh.read()
    assert 'secrets_store.py" --get graphrag OPENCODE_API_KEY' in sh
