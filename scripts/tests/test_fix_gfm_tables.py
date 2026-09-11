#!/usr/bin/env python3
"""fix_gfm_tables.py のテスト。"""
import importlib.util
import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent.parent
HOOK_PATH = REPO_ROOT / "packages" / "core" / "hooks" / "fix_gfm_tables.py"


def _load_fix_gfm_tables():
    spec = importlib.util.spec_from_file_location("fix_gfm_tables", HOOK_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules["fix_gfm_tables"] = module
    spec.loader.exec_module(module)
    return module


fg = _load_fix_gfm_tables()


class TestCodeFencePreservation(unittest.TestCase):
    def test_keeps_pipe_lines_inside_backtick_fence_unchanged(self):
        content = (
            "# Test\n"
            "\n"
            "```bash\n"
            "cat file.txt | head -5\n"
            'echo "a | b"\n'
            "```\n"
        )

        self.assertEqual(fg.fix_gfm_tables(content), content)

    def test_keeps_pipe_lines_inside_tilde_fence_unchanged(self):
        content = (
            "~~~\n"
            "ps aux | grep node\n"
            "~~~\n"
        )

        self.assertEqual(fg.fix_gfm_tables(content), content)

    def test_keeps_other_fence_marker_inside_open_fence_unchanged(self):
        content = (
            "```markdown\n"
            "~~~\n"
            "left | right\n"
            "~~~\n"
            "```\n"
        )

        self.assertEqual(fg.fix_gfm_tables(content), content)

    def test_fixes_table_after_closed_fence(self):
        content = (
            "```bash\n"
            "cat a | wc -l\n"
            "```\n"
            "\n"
            "foo | bar\n"
            "--- | ---\n"
        )
        expected = (
            "```bash\n"
            "cat a | wc -l\n"
            "```\n"
            "\n"
            "| foo | bar |\n"
            "| --- | --- |\n"
        )

        self.assertEqual(fg.fix_gfm_tables(content), expected)


class TestTableFixing(unittest.TestCase):
    def test_adds_missing_outer_pipes_to_table_rows(self):
        content = "foo | bar | baz\n--- | --- | ---\na | b | c\n"
        expected = "| foo | bar | baz |\n| --- | --- | --- |\n| a | b | c |\n"

        self.assertEqual(fg.fix_gfm_tables(content), expected)

    def test_keeps_well_formed_table_unchanged(self):
        content = "| foo | bar |\n| --- | --- |\n| a | b |\n"

        self.assertEqual(fg.fix_gfm_tables(content), content)


class TestNonTableLines(unittest.TestCase):
    """セパレータ行を伴わないパイプ入りの行を表に変形しないこと。"""

    def test_list_item_with_pipes_in_inline_code_is_untouched(self):
        # 実際に core-standards.md の箇条書きが 1 列テーブルに壊された形（2026-09-10）。
        content = "- 完了報告に検証表を付ける: ` | Check | Command | PASS / FAIL | `（該当するもの）\n"

        self.assertEqual(fg.fix_gfm_tables(content), content)

    def test_single_pipe_line_without_separator_is_untouched(self):
        content = "左 | 右\n\n次の段落\n"

        self.assertEqual(fg.fix_gfm_tables(content), content)

    def test_two_pipe_lines_without_separator_are_untouched(self):
        content = "a | b\nc | d\n"

        self.assertEqual(fg.fix_gfm_tables(content), content)

    def test_prose_mentioning_a_pipe_is_untouched(self):
        content = "`ps aux | head` の出力を読む。\n"

        self.assertEqual(fg.fix_gfm_tables(content), content)

    def test_table_after_an_untouched_pipe_line_is_still_fixed(self):
        content = "`a | b` は表ではない\n\nfoo | bar\n--- | ---\n"
        expected = "`a | b` は表ではない\n\n| foo | bar |\n| --- | --- |\n"

        self.assertEqual(fg.fix_gfm_tables(content), expected)


if __name__ == "__main__":
    unittest.main()
