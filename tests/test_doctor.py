"""doctor.py emits a machine-readable health report, and its exit code tracks it."""
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCTOR = os.path.join(ROOT, "tools", "doctor.py")


def test_doctor_json_shape_and_exit_code():
    r = subprocess.run([sys.executable, DOCTOR, "--json"],
                       capture_output=True, text=True, timeout=60)
    data = json.loads(r.stdout)
    assert isinstance(data.get("ok"), bool)
    assert isinstance(data.get("checks"), list) and data["checks"]
    for c in data["checks"]:
        assert {"name", "status", "detail"} <= set(c)
        assert c["status"] in ("pass", "warn", "fail")
    # exit code must agree with the reported result
    assert r.returncode == (0 if data["ok"] else 1)
