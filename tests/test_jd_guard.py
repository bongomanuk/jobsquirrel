import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))

import jd_guard


SHELL = """# Acme — Engineer
LinkedIn
Home
Network
Jobs
Select language
LinkedIn Corporation © 2026
"""

REAL = """# Acme — Engineer
About the job
We are looking for an engineer to build and run the platform for customers
across the Nordics. You will own architecture, delivery and operations, work
with product and data teams, and keep the platform secure and reliable.
Responsibilities
- Build and run the platform
- Improve reliability and developer experience
Select language
LinkedIn Corporation © 2026
"""


def test_a_linkedin_shell_is_not_a_job_description(tmp_path):
    shell = tmp_path / "shell.md"
    shell.write_text(SHELL)
    assert jd_guard._looks_shell(SHELL)
    assert not jd_guard.has_spec_at(str(shell))
    real = tmp_path / "real.md"
    real.write_text(REAL)
    assert not jd_guard._looks_shell(REAL)
    assert jd_guard.has_spec_at(str(real))
