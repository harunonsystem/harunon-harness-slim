"""宣言済みツールの更新検知。

doctor の Step 0 は存在確認しかしないため、pin したまま古い版を使い続けても
気づけなかった（open-code-review が 1.1.10 のまま upstream 1.11.5 まで離れていた）。
"""
from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

_spec = importlib.util.spec_from_file_location(
    "check_tool_updates", REPO_ROOT / "scripts" / "check-tool-updates.py"
)
check_tool_updates = importlib.util.module_from_spec(_spec)
sys.modules["check_tool_updates"] = check_tool_updates
_spec.loader.exec_module(check_tool_updates)


class TestDeclaredTools(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_merges_global_example_and_project_declarations(self):
        (self.root / "mise.global.example.toml").write_text(
            '[tools]\n"npm:pi" = "1.0.0"\n', encoding="utf-8"
        )
        (self.root / "mise.toml").write_text(
            '[tools]\n"npm:rulesync" = "16.0.0"\n', encoding="utf-8"
        )
        declaration = check_tool_updates.declared_tools(self.root)
        self.assertEqual(frozenset({"npm:pi", "npm:rulesync"}), declaration.tools)

    def test_project_declaration_wins_as_the_source(self):
        """修正コマンドの出し分けに宣言元が要る。両方にあれば project 側が正。"""
        (self.root / "mise.global.example.toml").write_text(
            '[tools]\n"npm:rulesync" = "15.0.0"\n', encoding="utf-8"
        )
        (self.root / "mise.toml").write_text(
            '[tools]\n"npm:rulesync" = "16.0.0"\n', encoding="utf-8"
        )
        declaration = check_tool_updates.declared_tools(self.root)
        self.assertEqual("mise.toml", declaration.source_of["npm:rulesync"])

    def test_missing_files_are_not_an_error(self):
        self.assertEqual(frozenset(), check_tool_updates.declared_tools(self.root).tools)


def declaration(**source_of: str) -> check_tool_updates.Declaration:
    return check_tool_updates.Declaration(
        tools=frozenset(source_of), source_of=dict(source_of)
    )


class TestUpdates(unittest.TestCase):
    """宣言したものだけを見る（マシン固有ツールは harness の責務外）。"""

    def test_reports_declared_tool_with_newer_version(self):
        found = check_tool_updates.updates(
            declaration(**{"npm:rulesync": "mise.toml"}),
            {"npm:rulesync": {"current": "16.24.0", "latest": "16.24.1"}},
        )
        self.assertEqual(1, len(found))
        self.assertIn("npm:rulesync: 16.24.0 → 16.24.1", found[0])

    def test_ignores_tools_the_harness_does_not_declare(self):
        """netlify-cli 等は mise が報告しても harness は口を出さない。"""
        found = check_tool_updates.updates(
            declaration(**{"npm:rulesync": "mise.toml"}),
            {
                "npm:rulesync": {"current": "16.24.0", "latest": "16.24.0"},
                "npm:netlify-cli": {"current": "27.0.1", "latest": "27.5.0"},
            },
        )
        self.assertEqual([], found)

    def test_same_version_is_not_reported(self):
        found = check_tool_updates.updates(
            declaration(**{"npm:pi": "mise.toml"}),
            {"npm:pi": {"current": "1.0.0", "latest": "1.0.0"}},
        )
        self.assertEqual([], found)

    def test_falls_back_to_requested_and_bump_when_keys_are_missing(self):
        found = check_tool_updates.updates(
            declaration(**{"npm:pi": "mise.toml"}),
            {"npm:pi": {"requested": "1.0.0", "bump": "1.1.0"}},
        )
        self.assertIn("npm:pi: 1.0.0 → 1.1.0", found[0])


class TestUpdaterFor(unittest.TestCase):
    """宣言元と違う層を編集するコマンドを出すと、実行しても警告が消えない。"""

    def test_project_pin_points_at_the_project_file(self):
        how = check_tool_updates.updater_for("npm:rulesync", "mise.toml")
        self.assertIn("mise.toml", how)
        self.assertNotIn("--global", how)

    def test_global_example_pin_uses_mise_use_global(self):
        how = check_tool_updates.updater_for("npm:difit", "mise.global.example.toml")
        self.assertIn("mise use --global --pin", how)

    def test_agents_are_routed_through_the_agents_update_task(self):
        """pi / omp は exact pin で、mise use 直叩きは danger-rules が block する。"""
        for tool in (
            "npm:@earendil-works/pi-coding-agent",
            "npm:@oh-my-pi/pi-coding-agent",
        ):
            how = check_tool_updates.updater_for(tool, "mise.global.example.toml")
            self.assertIn("mise run agents:update", how, msg=tool)
            self.assertNotIn("mise use", how, msg=tool)


class TestUnchecked(unittest.TestCase):
    """検査できなかったものを「最新」に混ぜない。"""

    def test_declared_but_not_reported_and_not_installed_is_unchecked(self):
        found = check_tool_updates.unchecked(
            declaration(**{"npm:pi": "mise.global.example.toml"}), {}, set()
        )
        self.assertEqual(["npm:pi"], found)

    def test_installed_tool_absent_from_outdated_is_current_not_unchecked(self):
        """outdated は最新のツールを返さない。入っていれば「検査した結果 OK」。"""
        found = check_tool_updates.unchecked(
            declaration(**{"npm:pi": "mise.global.example.toml"}), {}, {"npm:pi"}
        )
        self.assertEqual([], found)


class TestShippedDeclaration(unittest.TestCase):
    OCR_TOOL = "npm:@alibaba-group/open-code-review"

    def test_ocr_cli_is_declared(self):
        """ocr-review skill が呼ぶ CLI を宣言していないと、skill だけ配っても動かない。"""
        self.assertIn(self.OCR_TOOL, check_tool_updates.declared_tools(REPO_ROOT).tools)

    def test_ocr_cli_is_installed_by_machine_setup(self):
        """宣言しただけでは新規マシンに入らない。setup-machine.sh も尋ねること。"""
        setup = (REPO_ROOT / "scripts" / "setup-machine.sh").read_text(encoding="utf-8")
        self.assertIn(self.OCR_TOOL, setup)

    def test_runtime_clis_are_declared(self):
        declared = check_tool_updates.declared_tools(REPO_ROOT).tools
        for tool in (
            "npm:@earendil-works/pi-coding-agent",
            "npm:@oh-my-pi/pi-coding-agent",
        ):
            self.assertIn(tool, declared, msg=tool)


if __name__ == "__main__":
    unittest.main()
