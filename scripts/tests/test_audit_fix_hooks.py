#!/usr/bin/env python3
"""監査で確定した hook 化候補のうち、新規スタンドアロン hook のスモークテスト。

block-webfetch-github.sh / lesson-warnings.sh / prompt-pattern-reminders.sh /
session-restart-reminder.sh の主要分岐（block する/しない、additionalContext を
出す/出さない）を検証する。
"""
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent.parent
HOOKS_DIR = REPO_ROOT / "packages" / "core" / "hooks"
BLOCK_WEBFETCH_GITHUB_HOOK = HOOKS_DIR / "block-webfetch-github.sh"
LESSON_WARNINGS_HOOK = HOOKS_DIR / "lesson-warnings.sh"
PROMPT_PATTERN_REMINDERS_HOOK = HOOKS_DIR / "prompt-pattern-reminders.sh"
SESSION_RESTART_REMINDER_HOOK = HOOKS_DIR / "session-restart-reminder.sh"


def _run(hook: Path, input_text: str = "", env: dict = None) -> subprocess.CompletedProcess:
    full_env = dict(os.environ)
    if env:
        full_env.update(env)
    return subprocess.run(
        ["bash", str(hook)],
        input=input_text,
        capture_output=True,
        text=True,
        timeout=10,
        env=full_env,
    )


class TestBlockWebfetchGithub(unittest.TestCase):
    def test_issue_url_is_blocked(self):
        result = _run(BLOCK_WEBFETCH_GITHUB_HOOK, json.dumps({"url": "https://github.com/foo/bar/issues/1"}))
        self.assertEqual(result.returncode, 2)
        self.assertIn("gh issue view", result.stderr)

    def test_pull_url_is_blocked(self):
        result = _run(BLOCK_WEBFETCH_GITHUB_HOOK, json.dumps({"url": "https://github.com/foo/bar/pull/42"}))
        self.assertEqual(result.returncode, 2)

    def test_actions_url_is_blocked(self):
        result = _run(
            BLOCK_WEBFETCH_GITHUB_HOOK,
            json.dumps({"url": "https://github.com/foo/bar/actions/runs/123"}),
        )
        self.assertEqual(result.returncode, 2)

    def test_discussions_url_is_blocked(self):
        result = _run(
            BLOCK_WEBFETCH_GITHUB_HOOK,
            json.dumps({"url": "https://github.com/foo/bar/discussions/5"}),
        )
        self.assertEqual(result.returncode, 2)

    def test_repo_home_is_allowed(self):
        result = _run(BLOCK_WEBFETCH_GITHUB_HOOK, json.dumps({"url": "https://github.com/foo/bar"}))
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), "")

    def test_raw_githubusercontent_is_allowed(self):
        result = _run(
            BLOCK_WEBFETCH_GITHUB_HOOK,
            json.dumps({"url": "https://raw.githubusercontent.com/foo/bar/main/issues/README.md"}),
        )
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), "")

    def test_tool_input_nested_url_is_recognised(self):
        result = _run(
            BLOCK_WEBFETCH_GITHUB_HOOK,
            json.dumps({"tool_input": {"url": "https://github.com/foo/bar/issues/1"}}),
        )
        self.assertEqual(result.returncode, 2)

    def test_missing_url_is_noop(self):
        result = _run(BLOCK_WEBFETCH_GITHUB_HOOK, json.dumps({}))
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), "")

    def test_lookalike_domain_with_github_com_in_path_is_allowed(self):
        # ホスト位置をアンカーしていないと、パス中に "github.com" を含むだけの
        # 別ドメインを誤検知する。
        result = _run(
            BLOCK_WEBFETCH_GITHUB_HOOK,
            json.dumps({"url": "https://example.test/docs/github.com/a/b/issues/1"}),
        )
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), "")

    def test_uppercase_host_is_blocked(self):
        result = _run(
            BLOCK_WEBFETCH_GITHUB_HOOK,
            json.dumps({"url": "https://GITHUB.COM/foo/bar/issues/1"}),
        )
        self.assertEqual(result.returncode, 2)


class TestLessonWarnings(unittest.TestCase):
    def test_task_prompt_with_git_commit_warns(self):
        result = _run(
            LESSON_WARNINGS_HOOK,
            json.dumps({"tool_name": "Task", "tool_input": {"prompt": "please git commit and push"}}),
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("handoff packet", result.stdout)

    def test_agent_prompt_with_gh_pr_create_warns(self):
        result = _run(
            LESSON_WARNINGS_HOOK,
            json.dumps({"tool_name": "Agent", "tool_input": {"prompt": "then gh pr create it"}}),
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("handoff packet", result.stdout)

    def test_task_prompt_without_git_ops_is_noop(self):
        result = _run(
            LESSON_WARNINGS_HOOK,
            json.dumps({"tool_name": "Task", "tool_input": {"prompt": "implement the feature"}}),
        )
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), "")

    def test_bash_command_with_home_user_path_warns(self):
        result = _run(
            LESSON_WARNINGS_HOOK,
            json.dumps({"tool_name": "Bash", "tool_input": {"command": "cat /home/user/foo.txt"}}),
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("cloud セッション由来", result.stdout)

    def test_read_file_path_with_home_user_warns(self):
        result = _run(
            LESSON_WARNINGS_HOOK,
            json.dumps({"tool_name": "Read", "tool_input": {"file_path": "/home/user/foo.txt"}}),
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("cloud セッション由来", result.stdout)

    def test_gh_issue_create_warns(self):
        result = _run(
            LESSON_WARNINGS_HOOK,
            json.dumps({"tool_name": "Bash", "tool_input": {"command": "gh issue create --title x"}}),
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("Linear", result.stdout)

    def test_rm_codex_review_done_warns(self):
        result = _run(
            LESSON_WARNINGS_HOOK,
            json.dumps({"tool_name": "Bash", "tool_input": {"command": "rm /tmp/.codex-review-done-abc"}}),
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("review gate flag", result.stdout)

    def test_unrelated_bash_command_is_noop(self):
        result = _run(
            LESSON_WARNINGS_HOOK,
            json.dumps({"tool_name": "Bash", "tool_input": {"command": "git status"}}),
        )
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), "")

    def test_multiple_matches_are_combined_into_one_context(self):
        result = _run(
            LESSON_WARNINGS_HOOK,
            json.dumps({
                "tool_name": "Bash",
                "tool_input": {"command": "cat /home/user/x.txt && rm /tmp/.codex-review-done-abc"},
            }),
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("cloud セッション由来", result.stdout)
        self.assertIn("review gate flag", result.stdout)


class TestPromptPatternReminders(unittest.TestCase):
    def test_recurrence_phrase_triggers_diagnosing_bugs_reminder(self):
        result = _run(PROMPT_PATTERN_REMINDERS_HOOK, json.dumps({"prompt": "またこれ、同じエラーが出た"}))
        self.assertEqual(result.returncode, 0)
        self.assertIn("diagnosing-bugs", result.stdout)

    def test_verbatim_request_triggers_reminder(self):
        result = _run(PROMPT_PATTERN_REMINDERS_HOOK, json.dumps({"prompt": "ツリーをそのまま出して"}))
        self.assertEqual(result.returncode, 0)
        self.assertIn("逐語", result.stdout)

    def test_diagram_request_triggers_reminder(self):
        result = _run(PROMPT_PATTERN_REMINDERS_HOOK, json.dumps({"prompt": "シーケンス図を書いて"}))
        self.assertEqual(result.returncode, 0)
        self.assertIn("形式", result.stdout)

    def test_english_diagram_keyword_is_case_insensitive(self):
        result = _run(PROMPT_PATTERN_REMINDERS_HOOK, json.dumps({"prompt": "draw a Mermaid diagram"}))
        self.assertEqual(result.returncode, 0)
        self.assertIn("形式", result.stdout)

    def test_unrelated_prompt_is_noop(self):
        result = _run(PROMPT_PATTERN_REMINDERS_HOOK, json.dumps({"prompt": "implement the login page"}))
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), "")

    def test_missing_prompt_is_noop(self):
        result = _run(PROMPT_PATTERN_REMINDERS_HOOK, json.dumps({}))
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), "")

    def test_malformed_input_does_not_crash(self):
        result = _run(PROMPT_PATTERN_REMINDERS_HOOK, "not valid json")
        self.assertEqual(result.returncode, 0)


class TestSessionRestartReminder(unittest.TestCase):
    def _run_for_file(self, file_path: str, flag_path: Path) -> subprocess.CompletedProcess:
        return _run(
            SESSION_RESTART_REMINDER_HOOK,
            env={"FILE_PATH": file_path, "SESSION_RESTART_REMINDER_FLAG": str(flag_path)},
        )

    def test_settings_json_edit_triggers_reminder_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            flag = Path(tmp) / "flag"
            first = self._run_for_file("/repo/packages/core/settings.json", flag)
            self.assertEqual(first.returncode, 0)
            self.assertIn("セッションを切り直す", first.stdout)

            second = self._run_for_file("/repo/packages/core/settings.json", flag)
            self.assertEqual(second.returncode, 0)
            self.assertEqual(second.stdout.strip(), "")

    def test_rules_md_edit_triggers_reminder(self):
        with tempfile.TemporaryDirectory() as tmp:
            flag = Path(tmp) / "flag"
            result = self._run_for_file("/repo/packages/core/rules/core-standards.md", flag)
            self.assertEqual(result.returncode, 0)
            self.assertIn("セッションを切り直す", result.stdout)

    def test_unrelated_file_is_noop(self):
        with tempfile.TemporaryDirectory() as tmp:
            flag = Path(tmp) / "flag"
            result = self._run_for_file("/repo/src/app.py", flag)
            self.assertEqual(result.returncode, 0)
            self.assertEqual(result.stdout.strip(), "")

    def test_missing_file_path_is_noop(self):
        with tempfile.TemporaryDirectory() as tmp:
            flag = Path(tmp) / "flag"
            result = _run(
                SESSION_RESTART_REMINDER_HOOK,
                env={"FILE_PATH": "", "SESSION_RESTART_REMINDER_FLAG": str(flag)},
            )
            self.assertEqual(result.returncode, 0)
            self.assertEqual(result.stdout.strip(), "")

    def test_file_path_falls_back_to_stdin_tool_input_when_env_absent(self):
        # env で FILE_PATH を渡さない実行系（一部 runtime のブリッジ）向けに、
        # stdin の tool_input.file_path をフォールバックとして解決する。
        with tempfile.TemporaryDirectory() as tmp:
            flag = Path(tmp) / "flag"
            result = _run(
                SESSION_RESTART_REMINDER_HOOK,
                input_text=json.dumps(
                    {"tool_input": {"file_path": "/repo/packages/core/settings.json"}}
                ),
                env={"FILE_PATH": "", "SESSION_RESTART_REMINDER_FLAG": str(flag)},
            )
            self.assertEqual(result.returncode, 0)
            self.assertIn("セッションを切り直す", result.stdout)


if __name__ == "__main__":
    unittest.main()
