"""配備済み Codex plugin と SSOT の突き合わせ。

bootstrap は plugins/ を配らない（Codex のアプリ管理領域）ので、配備漏れ・未更新を
検知できるのは doctor だけ。以前は adapter 1 ファイルしか見ておらず、hook を足しても
policy を変えても「installed and current」と表示された（2026-09-06 に
block-secrets-in-commit を足して発覚）。
"""
from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

_spec = importlib.util.spec_from_file_location(
    "check_codex_plugin", REPO_ROOT / "scripts" / "check-codex-plugin.py"
)
check_codex_plugin = importlib.util.module_from_spec(_spec)
sys.modules["check_codex_plugin"] = check_codex_plugin
_spec.loader.exec_module(check_codex_plugin)


class TestInstalledPluginRoot(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.home = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_missing_plugin_returns_none(self):
        self.assertIsNone(check_codex_plugin.installed_plugin_root(self.home))

    def test_finds_installed_plugin(self):
        plugin = self.home / ".codex/plugins/cache/harunon-local/harunon-core/0.1.2"
        plugin.mkdir(parents=True)
        self.assertEqual(plugin, check_codex_plugin.installed_plugin_root(self.home))


class TestDrifts(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.ssot = self.root / "ssot"
        self.plugin = self.root / "plugin"
        self.ssot.mkdir()
        self.plugin.mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def _pair(self, rel: str, ssot_body: str, installed_body: str | None) -> dict[str, Path]:
        source = self.ssot / rel.replace("/", "_")
        source.write_text(ssot_body, encoding="utf-8")
        if installed_body is not None:
            target = self.plugin / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(installed_body, encoding="utf-8")
        return {rel: source}

    def test_identical_payload_is_clean(self):
        expected = self._pair("hooks/guard.sh", "same\n", "same\n")
        self.assertEqual([], check_codex_plugin.drifts(self.plugin, expected))

    def test_stale_file_is_reported(self):
        expected = self._pair("hooks/guard.sh", "fixed\n", "stale\n")
        found = check_codex_plugin.drifts(self.plugin, expected)
        self.assertEqual(1, len(found))
        self.assertIn("SSOT と異なります", found[0])

    def test_missing_file_is_reported(self):
        """新しい hook を足しても plugin に配備されていなければ Codex では効かない。"""
        expected = self._pair("hooks/block-secrets-in-commit.sh", "body\n", None)
        found = check_codex_plugin.drifts(self.plugin, expected)
        self.assertEqual(1, len(found))
        self.assertIn("配備されていません", found[0])

    def test_missing_ssot_source_is_reported(self):
        found = check_codex_plugin.drifts(self.plugin, {"hooks/gone.sh": self.ssot / "nope.sh"})
        self.assertEqual(1, len(found))
        self.assertIn("SSOT 側が見つかりません", found[0])


class TestExpectedFiles(unittest.TestCase):
    """比較対象は adapter + hook-pipeline が codex に配線する hook + policy。"""

    def test_covers_adapter_hooks_and_policy(self):
        expected = check_codex_plugin.expected_files(REPO_ROOT)

        self.assertIn(check_codex_plugin.ADAPTER_REL, expected)
        self.assertIn("policy/danger-rules.json", expected)
        self.assertIn("policy/hook-pipeline.json", expected)
        # hook 名は hook-pipeline.json から導出する（builder と同じ唯一の真実）
        self.assertIn("hooks/block-secrets-in-commit.sh", expected)
        self.assertIn("hooks/block-dangerous-in-bash.sh", expected)

    def test_every_expected_source_exists_in_the_repo(self):
        for rel, source in check_codex_plugin.expected_files(REPO_ROOT).items():
            self.assertTrue(source.is_file(), msg=f"{rel}: {source}")


if __name__ == "__main__":
    unittest.main()
