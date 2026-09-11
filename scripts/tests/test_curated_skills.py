#!/usr/bin/env python3
"""harness_lib.curated_skills のテスト。"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from harness_lib import curated_skills  # noqa: E402


class ListCuratedSkillsTestCase(unittest.TestCase):
    def test_returns_empty_when_lockfile_is_absent(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(curated_skills.list_curated_skills(Path(tmp)), set())

    def test_returns_declared_skill_names(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / curated_skills.LOCKFILE_NAME).write_text(
                json.dumps({"sources": {"upstream": {"skills": {"demo-skill": {}}}}}),
                encoding="utf-8",
            )
            self.assertEqual(curated_skills.list_curated_skills(root), {"demo-skill"})

    def test_raises_when_lockfile_is_corrupt(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / curated_skills.LOCKFILE_NAME).write_text(
                "{not valid json", encoding="utf-8"
            )
            with self.assertRaises(json.JSONDecodeError):
                curated_skills.list_curated_skills(root)


class InvalidSkillNamesTestCase(unittest.TestCase):
    """rm -rf の対象になる skill 名の安全性検証（RVW-002）。"""

    def test_normal_names_are_all_valid(self):
        names = {"tdd", "figma-implement", "opencli_usage", "a.b-c"}
        self.assertEqual(curated_skills.invalid_skill_names(names), [])

    def test_dot_dot_traversal_is_invalid(self):
        self.assertEqual(curated_skills.invalid_skill_names({"..", "tdd"}), [".."])

    def test_dot_is_invalid(self):
        self.assertEqual(curated_skills.invalid_skill_names({"."}), ["."])

    def test_path_with_traversal_segment_is_invalid(self):
        self.assertEqual(
            curated_skills.invalid_skill_names({"../evil", "tdd"}), ["../evil"]
        )

    def test_name_with_slash_is_invalid(self):
        self.assertEqual(
            curated_skills.invalid_skill_names({"nested/skill"}), ["nested/skill"]
        )

    def test_absolute_path_is_invalid(self):
        self.assertEqual(
            curated_skills.invalid_skill_names({"/etc/passwd"}), ["/etc/passwd"]
        )

    def test_leading_dot_hidden_name_is_invalid(self):
        self.assertEqual(curated_skills.invalid_skill_names({".hidden"}), [".hidden"])


if __name__ == "__main__":
    unittest.main()
