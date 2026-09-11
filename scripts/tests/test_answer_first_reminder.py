#!/usr/bin/env python3
"""answer-first-reminder.sh hook のテスト。

UserPromptSubmit で疑問形のプロンプトを検出し、Response Mode: Answer-first を
思い出させる additionalContext を注入する非ブロッキング reminder の契約を固定する。
"""
import json
import subprocess
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent.parent
HOOK = REPO_ROOT / "packages" / "core" / "hooks" / "answer-first-reminder.sh"

EXPECTED_CONTEXT = (
    "疑問形の発話: ツール実行や Edit/Write より先に、この発話への回答を本文で書く"
    "（Response Mode: Answer-first。編集は明示的な変更依頼が来てから）"
)


def _run(stdin_text: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(HOOK)],
        input=stdin_text,
        capture_output=True,
        text=True,
        timeout=10,
    )


def _run_prompt(prompt: str) -> subprocess.CompletedProcess:
    return _run(json.dumps({"hook_event_name": "UserPromptSubmit", "prompt": prompt}))


class TestAnswerFirstReminder(unittest.TestCase):
    def test_half_width_question_mark_injects_context(self):
        result = _run_prompt("もう終わってる?")
        self.assertEqual(result.returncode, 0)
        self.assertIn("additionalContext", result.stdout)
        self.assertIn(EXPECTED_CONTEXT, result.stdout)

    def test_masu_ka_ending_injects_context(self):
        result = _run_prompt("テスト通ってますか")
        self.assertEqual(result.returncode, 0)
        self.assertIn("additionalContext", result.stdout)

    def test_full_width_question_mark_injects_context(self):
        result = _run_prompt("全角で終わる？")
        self.assertEqual(result.returncode, 0)
        self.assertIn("additionalContext", result.stdout)

    def test_dakke_ending_injects_context(self):
        result = _run_prompt("これって前にやっただっけ")
        self.assertEqual(result.returncode, 0)
        self.assertIn("additionalContext", result.stdout)

    def test_kana_ending_injects_context(self):
        result = _run_prompt("動くようになったかな")
        self.assertEqual(result.returncode, 0)
        self.assertIn("additionalContext", result.stdout)

    def test_trailing_whitespace_and_newlines_are_ignored(self):
        result = _run_prompt("もう終わってる?\n\n  \n")
        self.assertEqual(result.returncode, 0)
        self.assertIn("additionalContext", result.stdout)

    def test_imperative_prompt_is_silent(self):
        result = _run_prompt("これ直して")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), "")

    def test_slash_command_is_silent(self):
        result = _run_prompt("/sync-settings --check")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), "")

    def test_empty_prompt_fails_open(self):
        result = _run_prompt("")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), "")

    def test_missing_prompt_field_fails_open(self):
        result = _run(json.dumps({"hook_event_name": "UserPromptSubmit"}))
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), "")

    def test_malformed_json_fails_open(self):
        result = _run("{invalid")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), "")

    def test_empty_stdin_fails_open(self):
        result = _run("")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), "")

    def test_never_blocks_with_exit_2_or_decision_block(self):
        prompts = [
            "もう終わってる?",
            "テスト通ってますか",
            "これ直して",
            "/sync-settings --check",
        ]
        for prompt in prompts:
            result = _run_prompt(prompt)
            self.assertNotEqual(result.returncode, 2, msg=prompt)
            self.assertNotIn('"decision"', result.stdout, msg=prompt)


if __name__ == "__main__":
    unittest.main()
