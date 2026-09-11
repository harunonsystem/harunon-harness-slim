"""Lesson ledger validator tests."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path


SCRIPTS_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = SCRIPTS_DIR.parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from harness_lib.validators.lessons import check_lessons  # noqa: E402


def _write_ledger(root: Path, lessons: list[dict]) -> None:
    path = root / "packages" / "core" / "lessons" / "lessons.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(lessons, ensure_ascii=False), encoding="utf-8")


def _lesson(*, enforced_by: str, status: str = "enforced", lesson_date: str | None = None) -> dict:
    return {
        "id": "lesson-test",
        "date": lesson_date or date.today().isoformat(),
        "summary": "テスト用 lesson",
        "source_runtime": "codex",
        "enforced_by": enforced_by,
        "status": status,
    }


class TestLessonValidator(unittest.TestCase):
    def test_validator_is_registered_in_execution_order(self):
        from harness_lib.validators import CHECKS

        self.assertIn(("lessons", check_lessons), CHECKS)

    def test_existing_rule_target_is_accepted(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rule = root / "packages" / "core" / "rules" / "policy.md"
            rule.parent.mkdir(parents=True)
            rule.write_text("## policy\n", encoding="utf-8")
            _write_ledger(root, [_lesson(enforced_by="rule:rules/policy.md#policy")])

            self.assertEqual(check_lessons(root), [])

    def test_missing_rule_target_is_an_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_ledger(root, [_lesson(enforced_by="rule:rules/missing.md#policy")])

            findings = check_lessons(root)

            self.assertEqual(len(findings), 1)
            self.assertEqual(findings[0].level, "error")
            self.assertIn("lesson-test", findings[0].message)
            self.assertIn("missing.md", findings[0].message)

    def test_test_target_must_be_collectable(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            test_file = root / "scripts" / "tests" / "test_fixture.py"
            test_file.parent.mkdir(parents=True)
            test_file.write_text(
                "import unittest\n\n"
                "class FixtureTest(unittest.TestCase):\n"
                "    def test_present(self):\n"
                "        pass\n",
                encoding="utf-8",
            )
            _write_ledger(
                root,
                [_lesson(enforced_by="test:scripts/tests/test_fixture.py::FixtureTest::test_absent")],
            )

            findings = check_lessons(root)

            self.assertEqual(len(findings), 1)
            self.assertEqual(findings[0].level, "error")
            self.assertIn("collectable", findings[0].message)

    def test_collectable_test_target_is_accepted(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            test_file = root / "scripts" / "tests" / "test_fixture.py"
            test_file.parent.mkdir(parents=True)
            test_file.write_text(
                "import unittest\n\n"
                "class FixtureTest(unittest.TestCase):\n"
                "    def test_present(self):\n"
                "        pass\n",
                encoding="utf-8",
            )
            _write_ledger(
                root,
                [_lesson(enforced_by="test:scripts/tests/test_fixture.py::FixtureTest::test_present")],
            )

            self.assertEqual(check_lessons(root), [])

    def test_old_pending_lesson_is_a_warning_with_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            old = (date.today() - timedelta(days=31)).isoformat()
            _write_ledger(root, [_lesson(enforced_by="pending", status="pending", lesson_date=old)])

            findings = check_lessons(root)

            self.assertEqual(len(findings), 1)
            self.assertEqual(findings[0].level, "warn")
            self.assertIn("lesson-test", findings[0].message)

    def test_recent_pending_lesson_has_no_warning(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_ledger(root, [_lesson(enforced_by="pending", status="pending")])

            self.assertEqual(check_lessons(root), [])

    def test_enforced_hook_target_missing_is_an_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_ledger(root, [_lesson(enforced_by="hook:hooks/missing.sh")])

            findings = check_lessons(root)

            self.assertEqual(len(findings), 1)
            self.assertEqual(findings[0].level, "error")
            self.assertIn("missing.sh", findings[0].message)

    def test_rule_target_with_matching_heading_is_accepted(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rule = root / "packages" / "core" / "rules" / "policy.md"
            rule.parent.mkdir(parents=True)
            rule.write_text("# Title\n\n## policy\nbody\n", encoding="utf-8")
            _write_ledger(root, [_lesson(enforced_by="rule:rules/policy.md#policy")])

            self.assertEqual(check_lessons(root), [])

    def test_rule_target_with_mismatched_anchor_is_an_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rule = root / "packages" / "core" / "rules" / "policy.md"
            rule.parent.mkdir(parents=True)
            rule.write_text("## other-heading\nbody\n", encoding="utf-8")
            _write_ledger(root, [_lesson(enforced_by="rule:rules/policy.md#policy")])

            findings = check_lessons(root)

            self.assertEqual(len(findings), 1)
            self.assertEqual(findings[0].level, "error")
            self.assertIn("lesson-test", findings[0].message)
            self.assertIn("anchor", findings[0].message)

    def test_malformed_json_ledger_is_a_single_error_without_traceback(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "packages" / "core" / "lessons" / "lessons.json"
            path.parent.mkdir(parents=True)
            path.write_text("{not valid json", encoding="utf-8")

            findings = check_lessons(root)

            self.assertEqual(len(findings), 1)
            self.assertEqual(findings[0].level, "error")

    def test_dict_root_is_an_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "packages" / "core" / "lessons" / "lessons.json"
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps({"id": "lesson-test"}), encoding="utf-8")

            findings = check_lessons(root)

            self.assertEqual(len(findings), 1)
            self.assertEqual(findings[0].level, "error")

    def test_unknown_enforced_by_kind_is_an_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_ledger(root, [_lesson(enforced_by="foo:bar")])

            findings = check_lessons(root)

            self.assertEqual(len(findings), 1)
            self.assertEqual(findings[0].level, "error")
            self.assertIn("lesson-test", findings[0].message)

    def test_non_importable_test_module_reports_exception_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            test_file = root / "scripts" / "tests" / "test_broken.py"
            test_file.parent.mkdir(parents=True)
            test_file.write_text("raise RuntimeError('boom')\n", encoding="utf-8")
            _write_ledger(
                root,
                [_lesson(enforced_by="test:scripts/tests/test_broken.py::Foo::test_bar")],
            )

            findings = check_lessons(root)

            self.assertEqual(len(findings), 1)
            self.assertEqual(findings[0].level, "error")
            self.assertIn("RuntimeError", findings[0].message)
            self.assertIn("boom", findings[0].message)


if __name__ == "__main__":
    unittest.main()
