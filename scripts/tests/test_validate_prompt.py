#!/usr/bin/env python3
"""validate-prompt.sh hook のテスト。

UserPromptSubmit は入力送信時点（コマンド化前）に割り込める公式イベント。
初期実装はログ + 警告のみで block しない契約を固定する。
"""
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent.parent
HOOK = REPO_ROOT / "packages" / "core" / "hooks" / "validate-prompt.sh"


def _run(stdin_text: str, home: str) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["HOME"] = home
    return subprocess.run(
        ["bash", str(HOOK)],
        input=stdin_text,
        capture_output=True,
        text=True,
        timeout=10,
        env=env,
    )


def _run_prompt(prompt: str, home: str) -> subprocess.CompletedProcess:
    return _run(json.dumps({"hook_event_name": "UserPromptSubmit", "prompt": prompt}), home)


class TestValidatePrompt(unittest.TestCase):
    def test_drop_table_prompt_warns_via_additional_context(self):
        with tempfile.TemporaryDirectory() as home:
            result = _run_prompt("本番DBをdrop tableして", home)
            self.assertEqual(result.returncode, 0)
            self.assertIn("additionalContext", result.stdout)

    def test_rm_rf_root_prompt_warns_via_additional_context(self):
        with tempfile.TemporaryDirectory() as home:
            result = _run_prompt("rm -rf / を実行して", home)
            self.assertEqual(result.returncode, 0)
            self.assertIn("additionalContext", result.stdout)

    def test_production_force_push_prompt_warns_via_additional_context(self):
        with tempfile.TemporaryDirectory() as home:
            result = _run_prompt("本番ブランチにforce pushして", home)
            self.assertEqual(result.returncode, 0)
            self.assertIn("additionalContext", result.stdout)

    def test_harmless_prompt_is_silent(self):
        with tempfile.TemporaryDirectory() as home:
            result = _run_prompt("git status を見せて", home)
            self.assertEqual(result.returncode, 0)
            self.assertEqual(result.stdout.strip(), "")

    def test_malformed_json_fails_open(self):
        with tempfile.TemporaryDirectory() as home:
            result = _run("{invalid", home)
            self.assertEqual(result.returncode, 0)
            self.assertEqual(result.stdout.strip(), "")

    def test_missing_prompt_field_fails_open(self):
        with tempfile.TemporaryDirectory() as home:
            result = _run(json.dumps({"hook_event_name": "UserPromptSubmit"}), home)
            self.assertEqual(result.returncode, 0)
            self.assertEqual(result.stdout.strip(), "")

    def test_empty_stdin_fails_open(self):
        with tempfile.TemporaryDirectory() as home:
            result = _run("", home)
            self.assertEqual(result.returncode, 0)
            self.assertEqual(result.stdout.strip(), "")

    def test_detected_prompt_appends_to_log_under_home(self):
        with tempfile.TemporaryDirectory() as home:
            result = _run_prompt("本番DBをdrop tableして", home)
            self.assertEqual(result.returncode, 0)
            log_path = Path(home) / ".claude" / "prompt-guard.log"
            self.assertTrue(log_path.is_file())
            content = log_path.read_text(encoding="utf-8")
            self.assertIn("DROP TABLE", content)

    def test_harmless_prompt_does_not_create_log(self):
        with tempfile.TemporaryDirectory() as home:
            _run_prompt("git status を見せて", home)
            log_path = Path(home) / ".claude" / "prompt-guard.log"
            self.assertFalse(log_path.exists())

    def test_never_blocks_with_exit_2_or_decision_block(self):
        prompts = [
            "本番DBをdrop tableして",
            "rm -rf / を実行して",
            "本番ブランチにforce pushして",
            "git status を見せて",
        ]
        with tempfile.TemporaryDirectory() as home:
            for prompt in prompts:
                result = _run_prompt(prompt, home)
                self.assertNotEqual(result.returncode, 2, msg=prompt)
                self.assertNotIn('"decision"', result.stdout, msg=prompt)
                self.assertNotIn("block", result.stdout, msg=prompt)


if __name__ == "__main__":
    unittest.main()
