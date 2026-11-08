import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))

import dashboard as D


def test_a_passed_gate_does_not_hide_the_actual_blocker():
    cases = [
        ("captcha: Cloudflare challenge; CV gated PASS", "captcha"),
        ("gate PASS; app.alignerr.com is SSO-only; 2FA needed", "login"),
        ("pre-submit gate FAILED on prepared CV: name mismatch", "gate"),
        ("no ATS and no apply URL; the advert says Maila ansökan; gate PASS", "email"),
        ("no job advert exists (intro meeting / network row)", "lead"),
        ("SMS/phone-call PIN and ID verification; 2FA is a human step; gate PASS", "login"),
    ]
    for notes, want in cases:
        assert D._substate("BLOCKED", notes)[0] == want, notes
