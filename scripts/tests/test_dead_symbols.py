#!/usr/bin/env python3
"""dead-symbols check と、skill frontmatter の引用符なし colon 検出のテスト。"""
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = SCRIPTS_DIR.parent

if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from harness_lib.validators.dead_symbols import check_dead_symbols  # noqa: E402
from harness_lib.validators.skills import check_skill_frontmatter  # noqa: E402


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


class TestDeadSymbols(unittest.TestCase):
    def test_reports_a_function_nothing_references(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(root / "scripts" / "mod.py", "def orphaned_helper():\n    return 1\n")

            findings = check_dead_symbols(root)

            self.assertEqual(1, len(findings))
            self.assertIn("orphaned_helper", findings[0].message)
            self.assertEqual("warn", findings[0].level)

    def test_keeps_a_function_referenced_from_python(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(root / "scripts" / "mod.py", "def used_helper():\n    return 1\n")
            _write(root / "scripts" / "caller.py", "from mod import used_helper\n\nused_helper()\n")

            self.assertEqual([], check_dead_symbols(root))

    def test_keeps_a_function_referenced_only_as_a_json_string(self):
        """settings.json / registry のような文字列参照を dead と誤判定しない。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(root / "scripts" / "mod.py", "def wired_by_name():\n    return 1\n")
            _write(root / "packages" / "core" / "settings.json", '{"hook": "wired_by_name"}\n')

            self.assertEqual([], check_dead_symbols(root))

    def test_ignores_test_helpers_and_dunders(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(
                root / "scripts" / "mod.py",
                "class Thing:\n    def __repr__(self):\n        return 'x'\n\n"
                "def test_something():\n    pass\n",
            )

            # Thing 自体は未参照なので 1 件だけ出る（__repr__ と test_ は対象外）。
            messages = [f.message for f in check_dead_symbols(root)]
            self.assertEqual(1, len(messages))
            self.assertIn("Thing", messages[0])

    def test_real_repo_has_no_dead_symbols(self):
        self.assertEqual([], check_dead_symbols(REPO_ROOT))


class TestSkillFrontmatterUnquotedColon(unittest.TestCase):
    def _skill(self, root: Path, description: str) -> None:
        _write(
            root / "packages" / "core" / "skills" / "demo" / "SKILL.md",
            f"---\nname: demo\ndescription: {description}\n---\n\nbody\n",
        )

    def test_rejects_unquoted_colon_in_description(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._skill(root, "Guidance for docs: skills, AGENTS.md")

            findings = check_skill_frontmatter(root)

            self.assertEqual(1, len(findings))
            self.assertEqual("error", findings[0].level)
            self.assertIn("description", findings[0].message)

    def test_accepts_quoted_description_containing_a_colon(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._skill(root, '"Guidance for docs: skills, AGENTS.md"')

            self.assertEqual([], check_skill_frontmatter(root))

    def test_accepts_a_plain_description(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._skill(root, "Guidance for writing docs")

            self.assertEqual([], check_skill_frontmatter(root))


if __name__ == "__main__":
    unittest.main()
