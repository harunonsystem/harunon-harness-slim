#!/usr/bin/env python3
"""scripts/pinned-tool-version.py のテスト。"""
from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = SCRIPTS_DIR.parent


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "pinned_tool_version", SCRIPTS_DIR / "pinned-tool-version.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


pinned_tool_version = _load_module()


class PinnedVersionTestCase(unittest.TestCase):
    def test_returns_declared_version(self):
        with tempfile.TemporaryDirectory() as tmp:
            mise_toml = Path(tmp) / "mise.toml"
            mise_toml.write_text(
                '[tools]\nnode = "26"\n"npm:rulesync" = "16.14.0"\n', encoding="utf-8"
            )

            self.assertEqual(
                pinned_tool_version.pinned_version("npm:rulesync", mise_toml), "16.14.0"
            )

    def test_raises_when_tool_is_not_declared(self):
        with tempfile.TemporaryDirectory() as tmp:
            mise_toml = Path(tmp) / "mise.toml"
            mise_toml.write_text('[tools]\nnode = "26"\n', encoding="utf-8")

            with self.assertRaises(ValueError) as ctx:
                pinned_tool_version.pinned_version("npm:rulesync", mise_toml)

            self.assertIn("npm:rulesync", str(ctx.exception))

    def test_cli_reports_missing_tool_as_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            mise_toml = Path(tmp) / "mise.toml"
            mise_toml.write_text("[tools]\n", encoding="utf-8")

            rc = pinned_tool_version.main(["npm:rulesync", "--mise-toml", str(mise_toml)])

            self.assertEqual(rc, 1)


class RealRepoPinTestCase(unittest.TestCase):
    def test_rulesync_pin_is_readable_from_the_repo_mise_toml(self):
        """CI が読む経路そのもの。宣言を消したら落ちる。"""
        version = pinned_tool_version.pinned_version(
            "npm:rulesync", REPO_ROOT / "mise.toml"
        )

        self.assertRegex(version, r"^\d+\.\d+\.\d+$")


if __name__ == "__main__":
    unittest.main()
