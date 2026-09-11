#!/usr/bin/env python3
"""差分から Codex review の profile を選ぶテスト。"""

import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "packages/runtimes/codex/harunon-core/scripts"))
from review_profile import choose_profile


class TestReviewProfile(unittest.TestCase):
    def test_tiny_low_risk_change_uses_sol_medium(self):
        self.assertEqual(
            choose_profile(["M\tsrc/foo.ts"], added=2, deleted=1),
            {"model": "gpt-5.6-sol", "effort": "medium"},
        )

    def test_normal_change_uses_sol_medium(self):
        self.assertEqual(
            choose_profile(["M\tsrc/foo.ts", "M\ttest/foo.test.ts"], added=30, deleted=10),
            {"model": "gpt-5.6-sol", "effort": "medium"},
        )

    def test_sensitive_path_uses_sol_medium(self):
        self.assertEqual(
            choose_profile(["M\tsrc/auth/session.ts"], added=1, deleted=1),
            {"model": "gpt-5.6-sol", "effort": "medium"},
        )

    def test_large_change_uses_sol_medium(self):
        self.assertEqual(
            choose_profile(["M\tsrc/foo.ts"], added=250, deleted=200),
            {"model": "gpt-5.6-sol", "effort": "medium"},
        )


if __name__ == "__main__":
    unittest.main()
