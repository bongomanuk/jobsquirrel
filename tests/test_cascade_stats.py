import os
import shutil
import subprocess
import json

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB = os.path.join(ROOT, "tools", "web")


def test_the_page_loads_the_stats_store_before_the_island():
    with open(os.path.join(WEB, "index.html"), encoding="utf-8") as fh:
        html = fh.read()
    assert '<script src="/grid-stats.js?v={{ASSET}}"></script>' in html
    assert html.index("/grid-stats.js") < html.index("/cascade-islands.js")
    with open(os.path.join(ROOT, "tools", "dashboard.py"), encoding="utf-8") as fh:
        server = fh.read()
    assert '"/grid-stats.js": ("grid-stats.js"' in server
    assert '"grid-stats.js", "critters.js"' in server


def test_the_island_exposes_one_stats_store():
    with open(os.path.join(WEB, "cascade-islands.js"), encoding="utf-8") as fh:
        islands = fh.read()
    assert "const gridStats = observable(" in islands
    assert "window.CascadeIslands.stats = stats;" in islands
    assert "refreshGridStats(rows, bucketOf)" in islands


def test_the_app_reads_the_snapshot_for_every_count():
    with open(os.path.join(WEB, "app.js"), encoding="utf-8") as fh:
        app = fh.read()
    assert "publishGridStats();" in app
    assert "function gridStatsSnapshot()" in app
    assert "const snap = gridStatsSnapshot();" in app
    assert "const counts = snap.status;" in app
    assert "const by = gridStatsSnapshot().substates;" in app


@pytest.mark.skipif(not shutil.which("node"), reason="node is not installed")
def test_the_derivation_keeps_shelved_roles_out_of_the_active_counts():
    script = r"""
const { derive } = require(process.argv[1]);
const rows = [
  { status: 'SUBMITTED', substate: 'acknowledged', substate_label: 'acknowledged' },
  { status: 'SUBMITTED', substate: 'assessment', focus: true },
  { status: 'CLOSED', substate: 'closed' },
  { status: 'DRAFTING', shelved: true },
  { status: 'SUBMITTED', scam: { level: 'high' } },
  { status: 'SUBMITTED', shelved: true, scam: { level: 'high' } },
];
const bucketOf = (r) => r.shelved ? 'shelved'
  : (r.scam && ['high', 'medium'].includes(r.scam.level)) ? 'scams'
  : r.status === 'CLOSED' ? 'done'
  : r.status === 'SUBMITTED' ? 'ongoing' : 'pipeline';
console.log(JSON.stringify(derive(rows, bucketOf)));
"""
    out = subprocess.run(
        ["node", "-e", script, os.path.join(WEB, "grid-stats.js")],
        capture_output=True, text=True, timeout=30,
    )
    assert out.returncode == 0, out.stderr
    snap = json.loads(out.stdout)
    assert snap["all"] == 6
    assert snap["buckets"]["shelved"] == 2
    assert snap["buckets"]["scams"] == 1
    assert snap["buckets"]["ongoing"] == 2
    assert snap["buckets"]["done"] == 1
    assert snap["active"] == 3
    assert snap["status"] == {"SUBMITTED": 3, "CLOSED": 1}
    assert snap["shelved"] == 2
    assert snap["shelvedBy"] == {"DRAFTING": 1, "SUBMITTED": 1}
    assert snap["scams"] == 1
    assert snap["focus"] == 1
    assert snap["substates"]["SUBMITTED:acknowledged"]["n"] == 1
    assert snap["substates"]["SUBMITTED:assessment"]["n"] == 1
    assert snap["substates"]["CLOSED:closed"]["n"] == 1
