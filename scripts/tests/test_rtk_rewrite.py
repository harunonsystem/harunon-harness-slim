#!/usr/bin/env python3
"""rtk-rewrite.sh hook のテスト。worktree では git を書き換えないことを含む。"""
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
HOOK = REPO_ROOT / "packages" / "core" / "hooks" / "rtk-rewrite.sh"

# hook は jq で JSON を組むので実体が必要。rtk は存在確認だけなので fake で足りる
# （CI は rtk を入れないため、fake を用意しないとテスト全体が skip されて
# worktree 判定の回帰を守れなくなる）。
JQ_PRESENT = bool(shutil.which("jq"))


def _fake_rtk(bin_dir: Path) -> None:
    """`command -v rtk` を満たすだけの実行ファイルを置く。hook は rtk を実行しない。"""
    fake = bin_dir / "rtk"
    fake.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    fake.chmod(0o755)


def _init_repo(root: Path) -> None:
    def run(*args: str) -> None:
        subprocess.run(args, cwd=str(root), check=True, capture_output=True)

    run("git", "init", "--quiet", "--initial-branch", "main")
    run("git", "config", "user.email", "test@example.com")
    run("git", "config", "user.name", "Test")
    (root / "seed.txt").write_text("seed\n", encoding="utf-8")
    run("git", "add", "seed.txt")
    run("git", "commit", "--quiet", "-m", "seed")


@unittest.skipUnless(JQ_PRESENT, "jq が無いと hook が no-op になる")
class TestRtkRewrite(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.bin_dir = self.root / "bin"
        self.bin_dir.mkdir()
        _fake_rtk(self.bin_dir)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        _init_repo(self.repo)

    def tearDown(self):
        self._tmp.cleanup()

    def _worktree(self) -> Path:
        worktree = self.root / "wt"
        subprocess.run(
            ["git", "worktree", "add", "--quiet", str(worktree), "-b", "topic"],
            cwd=str(self.repo),
            check=True,
            capture_output=True,
        )
        return worktree

    def _rewritten(self, command: str, cwd: Path) -> str | None:
        """hook を通した結果の command。書き換えなし（exit 0 で無出力）なら None。"""
        env = dict(os.environ)
        env["PATH"] = f"{self.bin_dir}{os.pathsep}{env.get('PATH', '')}"
        result = subprocess.run(
            ["bash", str(HOOK)],
            input=json.dumps({"tool_input": {"command": command}}),
            capture_output=True,
            text=True,
            timeout=20,
            cwd=str(cwd),
            env=env,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        if not result.stdout.strip():
            return None
        payload = json.loads(result.stdout)
        return payload["hookSpecificOutput"]["updatedInput"]["command"]

    def test_git_is_rewritten_in_a_plain_checkout(self):
        self.assertEqual("rtk git status", self._rewritten("git status", self.repo))

    def test_git_is_not_rewritten_inside_a_worktree(self):
        # `rtk git ...` は Claude Code の worktree 隔離ガードに拒否されるため、
        # worktree では素の git を通す（2026-09-10 に実際に作業が止まった）。
        self.assertIsNone(self._rewritten("git status", self._worktree()))

    def test_non_git_commands_are_still_rewritten_inside_a_worktree(self):
        self.assertEqual("rtk ls -la", self._rewritten("ls -la", self._worktree()))

    def test_already_rtk_command_is_left_alone(self):
        self.assertIsNone(self._rewritten("rtk git status", self.repo))

    def test_unknown_command_is_left_alone(self):
        self.assertIsNone(self._rewritten("echo hello", self.repo))


if __name__ == "__main__":
    unittest.main()
