#!/usr/bin/env python3
"""pr-desc-sync-check.sh のフィクスチャテスト。

push 成功を検出したら `gh pr view` で対象ブランチの open PR を確認し、
あれば additionalContext で乖離チェックを促す（deny はしない）。
gh は実バイナリを呼ばず、PATH 先頭に fake gh スタブを注入して隔離する。
"""
import json
import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent.parent
HOOK = REPO_ROOT / "packages" / "core" / "hooks" / "pr-desc-sync-check.sh"


def _make_git_repo(parent: Path) -> Path:
    repo = parent / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.email", "test@example.com"],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.name", "Test"], check=True, capture_output=True
    )
    subprocess.run(
        ["git", "-C", str(repo), "commit", "-q", "--allow-empty", "-m", "init"],
        check=True,
        capture_output=True,
    )
    return repo


def _write_fake_gh(bin_dir: Path, script_body: str) -> None:
    gh = bin_dir / "gh"
    gh.write_text(f"#!/bin/bash\n{script_body}\n", encoding="utf-8")
    gh.chmod(gh.stat().st_mode | stat.S_IEXEC)


def _push_command_input(stdout: str = "", stderr: str = "", exit_code=None, interrupted=False):
    tool_response = {"stdout": stdout, "stderr": stderr, "interrupted": interrupted}
    if exit_code is not None:
        tool_response["exitCode"] = exit_code
    return json.dumps(
        {"tool_input": {"command": "git push"}, "tool_response": tool_response}
    )


class PrDescSyncCheckTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.repo = _make_git_repo(self.root)
        self.bin_dir = self.root / "bin"
        self.bin_dir.mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def _run(self, json_input: str, cwd=None) -> subprocess.CompletedProcess:
        env = dict(os.environ)
        env["PATH"] = f"{self.bin_dir}:{env.get('PATH', '')}"
        return subprocess.run(
            ["bash", str(HOOK)],
            input=json_input,
            capture_output=True,
            text=True,
            timeout=30,
            cwd=cwd,
            env=env,
        )


class TestPrDescSyncCheck(PrDescSyncCheckTestCase):
    def test_non_push_command_is_noop(self):
        json_input = json.dumps({"tool_input": {"command": "git status"}})
        result = self._run(json_input, cwd=str(self.repo))
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertEqual(result.stdout.strip(), "")

    def test_interrupted_push_is_noop(self):
        result = self._run(_push_command_input(interrupted=True), cwd=str(self.repo))
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertEqual(result.stdout.strip(), "")

    def test_nonzero_exit_code_is_noop(self):
        result = self._run(_push_command_input(exit_code=1), cwd=str(self.repo))
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertEqual(result.stdout.strip(), "")

    def test_rejected_push_output_is_noop(self):
        result = self._run(
            _push_command_input(stderr="! [rejected]        main -> main (non-fast-forward)"),
            cwd=str(self.repo),
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertEqual(result.stdout.strip(), "")

    def test_successful_push_without_open_pr_is_silent(self):
        """gh が PR なしで失敗終了 → additionalContext を出さず silent に exit 0"""
        _write_fake_gh(self.bin_dir, 'echo "no pull requests found" >&2; exit 1')
        result = self._run(_push_command_input(stdout="branch -> branch"), cwd=str(self.repo))
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertEqual(result.stdout.strip(), "")

    def test_gh_not_found_is_silent(self):
        """gh コマンド自体が使えない環境でも silent に exit 0
        （PATH を bash/git/jq が揃う /usr/bin:/bin のみに絞り、gh の実体が
        置かれている /opt/homebrew/bin 等を除外する）"""
        env = dict(os.environ)
        env["PATH"] = "/usr/bin:/bin"
        result = subprocess.run(
            ["bash", str(HOOK)],
            input=_push_command_input(stdout="branch -> branch"),
            capture_output=True,
            text=True,
            timeout=30,
            cwd=str(self.repo),
            env=env,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertEqual(result.stdout.strip(), "")

    def test_successful_push_with_open_pr_emits_additional_context(self):
        """gh が PR情報を返す → additionalContext に PR 番号と乖離チェック指示を含める"""
        _write_fake_gh(
            self.bin_dir,
            'echo \'{"number":123,"body":"old description"}\'',
        )
        result = self._run(_push_command_input(stdout="branch -> branch"), cwd=str(self.repo))
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("additionalContext", result.stdout)
        self.assertIn("PR #123", result.stdout)
        self.assertIn("gh pr edit", result.stdout)

    def test_outside_git_repo_is_silent(self):
        outside = self.root / "not-a-repo"
        outside.mkdir()
        _write_fake_gh(self.bin_dir, 'echo \'{"number":123,"body":"x"}\'')
        result = self._run(_push_command_input(stdout="branch -> branch"), cwd=str(outside))
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertEqual(result.stdout.strip(), "")


if __name__ == "__main__":
    unittest.main()
