#!/usr/bin/env python3
"""scripts/mise-global-check.py の CLI レベルテスト（subprocess 経由）。

実機の ~/.config/mise/config.toml には一切触れず、すべて一時ファイルを --example /
--config で明示的に指す。
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CLI = REPO_ROOT / "scripts" / "mise-global-check.py"

EXAMPLE_TOML = (
    '[tools]\npnpm = "1.0"\n\n[env]\nPI_FFF_MODE = "override"\n'
)


def run_cli(*args: str, input_text: str | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(CLI), *args],
        input=input_text,
        capture_output=True,
        text=True,
        timeout=30,
    )


class MiseGlobalCheckCliTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.example = self.root / "example.toml"
        self.example.write_text(EXAMPLE_TOML, encoding="utf-8")
        self.config = self.root / "config.toml"

    def tearDown(self):
        self._tmp.cleanup()

    def test_clean_config_exits_zero(self):
        self.config.write_text(
            '[tools]\npnpm = "1.0"\n\n[env]\nPI_FFF_MODE = "override"\n', encoding="utf-8"
        )
        result = run_cli("--example", str(self.example), "--config", str(self.config))
        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        self.assertIn("宣言どおり", result.stdout)

    def test_drift_without_apply_exits_one_and_prints_findings(self):
        self.config.write_text('[tools]\npnpm = "1.0"\n', encoding="utf-8")
        result = run_cli("--example", str(self.example), "--config", str(self.config))
        self.assertEqual(result.returncode, 1, msg=result.stdout + result.stderr)
        self.assertIn("PI_FFF_MODE", result.stdout)
        # --apply-env なしでは書き換わらない
        self.assertNotIn("[env]", self.config.read_text(encoding="utf-8"))

    def test_apply_env_yes_writes_key_and_preserves_rest(self):
        self.config.write_text(
            "# keep this comment\n[tools]\npnpm = \"1.0\"\n", encoding="utf-8"
        )
        result = run_cli(
            "--example", str(self.example), "--config", str(self.config),
            "--apply-env", "--yes",
        )
        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        text = self.config.read_text(encoding="utf-8")
        self.assertIn("# keep this comment", text)
        self.assertIn('pnpm = "1.0"', text)
        self.assertIn('PI_FFF_MODE = "override"', text)

    def test_apply_env_interactive_no_skips_and_leaves_file_unchanged(self):
        original = "[tools]\npnpm = \"1.0\"\n"
        self.config.write_text(original, encoding="utf-8")
        result = run_cli(
            "--example", str(self.example), "--config", str(self.config), "--apply-env",
            input_text="n\n",
        )
        self.assertEqual(result.returncode, 1, msg=result.stdout + result.stderr)
        self.assertIn("スキップ", result.stdout)
        self.assertEqual(self.config.read_text(encoding="utf-8"), original)

    def test_corrupt_toml_exits_two(self):
        self.config.write_text("[env\nnot valid", encoding="utf-8")
        result = run_cli("--example", str(self.example), "--config", str(self.config))
        self.assertEqual(result.returncode, 2, msg=result.stdout + result.stderr)
        self.assertIn("ERROR", result.stderr)

    def test_config_env_var_default_is_used_when_no_flag(self):
        self.config.write_text(
            '[tools]\npnpm = "1.0"\n\n[env]\nPI_FFF_MODE = "override"\n', encoding="utf-8"
        )
        import os

        env = dict(os.environ)
        env["MISE_GLOBAL_CONFIG"] = str(self.config)
        result = subprocess.run(
            [sys.executable, str(CLI), "--example", str(self.example)],
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
