#!/usr/bin/env python3
"""run-bang-command.sh（UserPromptSubmit）のテスト。

行頭に空白が混ざった `! <cmd>` の 1 行プロンプトだけを hook が実行し、結果を
additionalContext で返す。正しい `!` 行は Claude Code 本体が処理するので hook には
届かない前提。複数行・本文中の `!`・通常プロンプトは素通り（出力なし）。
"""
from __future__ import annotations

import json
import subprocess
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
HOOK = REPO_ROOT / "packages" / "core" / "hooks" / "run-bang-command.sh"


def run_hook(prompt: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(HOOK)], input=json.dumps({"prompt": prompt}),
        capture_output=True, text=True, timeout=30,
    )


class RunBangCommandTestCase(unittest.TestCase):
    def context(self, prompt: str) -> str:
        result = run_hook(prompt)
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertTrue(result.stdout.strip(), msg="additionalContext が返らない")
        return json.loads(result.stdout)["hookSpecificOutput"]["additionalContext"]

    def test_executes_space_prefixed_bang_line(self):
        ctx = self.context("  ! echo hook-ran-here")
        self.assertIn("hook-ran-here", ctx)
        self.assertIn("exit=0", ctx)

    def test_reports_nonzero_exit(self):
        ctx = self.context("\t! false")
        self.assertIn("exit=1", ctx)

    def test_accepts_fullwidth_space_and_trailing_newline(self):
        ctx = self.context("　! echo zenkaku\n")
        self.assertIn("zenkaku", ctx)

    def test_passthrough_without_leading_space(self):
        # 行頭の `!` は Claude Code 本体の担当。届いた場合も hook は触らない
        self.assertEqual(run_hook("! echo direct").stdout.strip(), "")

    def test_passthrough_for_multiline_and_plain_prompts(self):
        self.assertEqual(run_hook("  ! echo one\necho two").stdout.strip(), "")
        self.assertEqual(run_hook("ログ:\n  ! important").stdout.strip(), "")
        self.assertEqual(run_hook("普通の依頼です").stdout.strip(), "")
        self.assertEqual(run_hook("").stdout.strip(), "")

    def test_passthrough_on_invalid_json(self):
        result = subprocess.run(["bash", str(HOOK)], input="not json",
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), "")


if __name__ == "__main__":
    unittest.main()
