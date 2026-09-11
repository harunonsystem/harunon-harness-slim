#!/usr/bin/env python3
"""enforce-gwm-for-worktree.sh hook のテスト。"""
import json
import os
import shutil
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent.parent
HOOK = REPO_ROOT / "packages" / "core" / "hooks" / "enforce-gwm-for-worktree.sh"


class TestEnforceGwmForWorktree(unittest.TestCase):
    def setUp(self):
        # hook は command -v gwm で存在確認するだけなので、fake gwm を PATH に用意する
        self._tmpdir = tempfile.TemporaryDirectory()
        fake_gwm = Path(self._tmpdir.name) / "gwm"
        fake_gwm.write_text("#!/bin/bash\nexit 0\n")
        fake_gwm.chmod(fake_gwm.stat().st_mode | stat.S_IEXEC)
        self._env = dict(os.environ)
        self._env["PATH"] = "{}:{}".format(self._tmpdir.name, self._env.get("PATH", ""))
        # ローカルの ~/.claude/rigor-patterns.json による profile 判定をテストから隔離する。
        self._env["RIGOR_PATTERNS_FILE"] = "/nonexistent"

    def tearDown(self):
        self._tmpdir.cleanup()

    def _run(self, command: str, tool_name: str = "Bash") -> subprocess.CompletedProcess:
        env = dict(self._env)
        env["TOOL_INPUT"] = json.dumps(
            {"tool_name": tool_name, "tool_input": {"command": command}}
        )
        return subprocess.run(
            ["bash", str(HOOK)],
            capture_output=True,
            text=True,
            timeout=10,
            cwd=str(REPO_ROOT),
            env=env,
        )

    def _run_enter_worktree(
        self, path: str = "", name: str = ""
    ) -> subprocess.CompletedProcess:
        env = dict(self._env)
        env["TOOL_INPUT"] = json.dumps(
            {"tool_name": "EnterWorktree", "tool_input": {"path": path, "name": name}}
        )
        return subprocess.run(
            ["bash", str(HOOK)],
            capture_output=True,
            text=True,
            timeout=10,
            cwd=str(REPO_ROOT),
            env=env,
        )

    def test_enter_worktree_without_path_is_allowed(self):
        result = self._run_enter_worktree(name="feature/foo")
        self.assertEqual(result.returncode, 0)

    def test_git_worktree_add_is_blocked(self):
        result = self._run("git worktree add ../wt x")
        self.assertEqual(result.returncode, 2)

    def test_git_dash_c_worktree_add_is_blocked(self):
        result = self._run("git -C /tmp/repo worktree add ../wt feature-x")
        self.assertEqual(result.returncode, 2)

    def test_git_dash_dash_git_dir_worktree_add_is_blocked(self):
        result = self._run("git --git-dir=/tmp/repo/.git worktree add ../wt feature-x")
        self.assertEqual(result.returncode, 2)

    def test_git_global_options_before_worktree_add_are_blocked(self):
        for command in (
            "git -c core.hooksPath=/tmp worktree add ../wt feature-x",
            "git --work-tree=/tmp worktree add ../wt feature-x",
        ):
            with self.subTest(command=command):
                result = self._run(command)
                self.assertEqual(result.returncode, 2)

    def test_git_commands_with_worktree_text_are_allowed(self):
        for command in (
            "git commit -m 'worktree add'",
            "git log --grep='worktree add'",
        ):
            with self.subTest(command=command):
                result = self._run(command)
                self.assertEqual(result.returncode, 0)

    def test_subshell_worktree_add_is_blocked(self):
        result = self._run("echo $(git worktree add ../wt x)")
        self.assertEqual(result.returncode, 2)

    def test_worktree_add_after_every_command_boundary_is_blocked(self):
        """改行 / & / bare subshell も起点。旧 tokenizer は改行を空白としか見なかった。"""
        for command in (
            "echo x\ngit worktree add ../wt x",
            "sleep 1 & git worktree add ../wt x",
            "(git worktree add ../wt x)",
            "true;git worktree add ../wt x",
            "true || rtk git worktree add ../wt x",
        ):
            with self.subTest(command=command):
                result = self._run(command)
                self.assertEqual(result.returncode, 2, msg=result.stderr)

    def test_claude_worktree_after_newline_is_blocked(self):
        result = self._run("echo x\nclaude worktree feature-x")
        self.assertEqual(result.returncode, 2, msg=result.stderr)

    def test_git_worktree_list_is_allowed(self):
        result = self._run("git worktree list")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), "")

    def test_non_bash_tool_is_allowed(self):
        result = self._run("git worktree add ../wt x", tool_name="SomeOtherTool")
        self.assertEqual(result.returncode, 0)


class TestFailsClosedWithoutPython3(unittest.TestCase):
    """python3 不在は deny に倒す（このフックが冒頭で宣言している fail-closed 契約）。

    worktree add の判定は python3 の tokenizer に委ねているため、python3 が無いと
    pipeline が 127 で終わり「worktree add ではない」と誤読して素通りしていた。
    無関係な Bash を巻き込まないため、worktree に言及するコマンドだけ倒す。
    """

    NEEDED = (
        "bash", "grep", "git", "jq", "readlink", "dirname",
        "cat", "shasum", "date", "sed", "env",
    )

    def _run_without_python3(self, command: str) -> subprocess.CompletedProcess:
        with tempfile.TemporaryDirectory() as binpath:
            for name in self.NEEDED:
                resolved = shutil.which(name)
                if resolved:
                    os.symlink(resolved, Path(binpath) / name)
            fake_gwm = Path(binpath) / "gwm"
            fake_gwm.write_text("#!/bin/bash\nexit 0\n")
            fake_gwm.chmod(fake_gwm.stat().st_mode | stat.S_IEXEC)
            env = {
                "PATH": binpath,
                "HOME": os.environ.get("HOME", ""),
                # ローカルの profile 判定を隔離し、全ゲート有効な rigorous に固定する
                "RIGOR_PATTERNS_FILE": "/nonexistent",
                "RIGOR_LOCAL_FILE": "/nonexistent",
                "TOOL_INPUT": json.dumps(
                    {"tool_name": "Bash", "tool_input": {"command": command}}
                ),
            }
            return subprocess.run(
                ["bash", str(HOOK)],
                capture_output=True,
                text=True,
                timeout=10,
                cwd=str(REPO_ROOT),
                env=env,
            )

    def test_worktree_add_is_denied_when_python3_is_missing(self):
        result = self._run_without_python3("git worktree add ../wt x")
        self.assertEqual(result.returncode, 2, msg=result.stderr)
        self.assertIn("python3", result.stderr)

    def test_unrelated_command_still_passes_when_python3_is_missing(self):
        # python3 不在でも worktree に無関係なコマンドは巻き込まない
        result = self._run_without_python3("ls -la")
        self.assertEqual(result.returncode, 0, msg=result.stderr)


if __name__ == "__main__":
    unittest.main()
