#!/usr/bin/env python3
"""block-cd-prefix-in-bash.sh hook のテスト。

止めるのは「先頭 cd + リテラル絶対パス + 後続コマンド」だけ。command
substitution と相対パスと単独 cd は通す（skill 本文の定型を誤爆させないため）。
"""
import json
import os
import subprocess
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent.parent
HOOK = REPO_ROOT / "packages" / "core" / "hooks" / "block-cd-prefix-in-bash.sh"


def _run(command: str) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["TOOL_INPUT"] = json.dumps({"command": command})
    return subprocess.run(
        ["bash", str(HOOK)],
        capture_output=True,
        text=True,
        timeout=10,
        env=env,
    )


class TestBlockedForms(unittest.TestCase):
    def test_absolute_path_with_chain_is_blocked(self):
        result = _run("cd /Users/example/projects/app && ls")
        self.assertEqual(result.returncode, 2)

    def test_tilde_path_with_chain_is_blocked(self):
        result = _run("cd ~/projects/worktrees/app && ls")
        self.assertEqual(result.returncode, 2)

    def test_semicolon_separator_is_blocked(self):
        result = _run("cd /Users/example/app ; ls")
        self.assertEqual(result.returncode, 2)

    def test_quoted_absolute_path_is_blocked(self):
        result = _run('cd "/Users/example/my app" && ls')
        self.assertEqual(result.returncode, 2)

    def test_leading_whitespace_is_blocked(self):
        result = _run("   cd /Users/example/app && ls")
        self.assertEqual(result.returncode, 2)

    def test_message_names_the_alternatives(self):
        result = _run("cd /Users/example/app && ls")
        self.assertIn("-C", result.stderr)
        self.assertIn("subshell", result.stderr)

    def test_newline_separated_follow_up_is_blocked(self):
        # `&&` だけでなく改行区切りでも後続コマンドは走る
        result = _run("cd /Users/example/app\nls")
        self.assertEqual(result.returncode, 2)

    def test_backslash_escaped_space_in_path_is_blocked(self):
        # quote の代わりにバックスラッシュで空白を逃がす形も塞ぐ
        result = _run("cd /Users/example/My\\ App && ls")
        self.assertEqual(result.returncode, 2)

    def test_large_input_is_still_blocked(self):
        """判定を grep へのパイプで行うと SIGPIPE で素通りしていたケース。

        set -o pipefail 下では grep -q の早期終了で echo が 141 になり、
        条件式全体が偽になって allow に倒れる。
        """
        payload = "x" * 100_000
        result = _run(f"cd /Users/example/app && cat <<EOF\n{payload}\nEOF")
        self.assertEqual(result.returncode, 2)


class TestAllowedForms(unittest.TestCase):
    def test_command_substitution_is_allowed(self):
        # skill 本文で使われている定型。パスをリテラルで持たないので誤爆させない
        result = _run('cd "$(git rev-parse --show-toplevel)" && ./scripts/bootstrap.sh')
        self.assertEqual(result.returncode, 0)

    def test_relative_path_is_allowed(self):
        result = _run("cd packages/core && ls")
        self.assertEqual(result.returncode, 0)

    def test_bare_cd_is_allowed(self):
        result = _run("cd /Users/example/app")
        self.assertEqual(result.returncode, 0)

    def test_directory_flag_form_is_allowed(self):
        result = _run("git -C /Users/example/app status")
        self.assertEqual(result.returncode, 0)

    def test_subshell_form_is_allowed(self):
        result = _run("( cd /Users/example/app && ls )")
        self.assertEqual(result.returncode, 0)

    def test_cd_later_in_chain_is_allowed(self):
        result = _run("ls && cd /Users/example/app")
        self.assertEqual(result.returncode, 0)

    def test_cd_on_a_later_line_is_allowed(self):
        """行頭ではなく「入力全体の先頭」で判定する。

        grep は ^ を行頭として見るため、先頭でない cd を誤って拒否していた。
        """
        result = _run("echo prep\ncd /Users/example/app && ls")
        self.assertEqual(result.returncode, 0)

    def test_unrelated_command_is_allowed(self):
        result = _run("ls -la")
        self.assertEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()
