#!/usr/bin/env python3
"""approve-push.sh のフィクスチャテスト。

理由付き実行で push 承認フラグ（$CODEX_REVIEW_FLAG_DIR/.push-approved-<key>）が
現在の HEAD で立つこと、ログファイル（~/.claude/push-approve.log 相当）に
理由が記録されること、理由なし/repo 外実行の拒否を検証する。

KEY は git_root + branch のハッシュ（lib/review-gate.sh と同じ算出方法）。
一時 git repo のパスは実行ごとに一意なため、実マシンの /tmp フラグと衝突しない。
"""
import hashlib
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent.parent
HOOK = REPO_ROOT / "packages" / "core" / "hooks" / "approve-push.sh"


def _review_key(git_root: str, branch: str) -> str:
    """lib/review-gate.sh の KEY 算出（SHA-1 第 1 フィールド）を Python で再現する。"""
    data = f"{git_root}\n{branch}\n".encode()
    return hashlib.sha1(data).hexdigest()


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


def _git_out(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=True
    )
    return result.stdout.strip()


class TestApprovePush(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.repo = _make_git_repo(self.root)
        self.git_root = _git_out(self.repo, "rev-parse", "--show-toplevel")
        self.branch = _git_out(self.repo, "rev-parse", "--abbrev-ref", "HEAD")
        # LOG は $HOME/.claude/push-approve.log に書かれるため HOME を隔離する。
        self.fake_home = self.root / "home"
        (self.fake_home / ".claude").mkdir(parents=True)
        # フラグ名前空間を tempdir に隔離（実 /tmp を汚染しない。
        # CODEX_REVIEW_FLAG_DIR は review-gate.sh の注入点）。
        self.flag_dir = self.root / "flags"
        self.flag_dir.mkdir(exist_ok=True)
        self._flag = self.flag_dir / f".push-approved-{_review_key(self.git_root, self.branch)}"

    def tearDown(self):
        self._tmp.cleanup()

    def _run(self, args, cwd=None, home=None) -> subprocess.CompletedProcess:
        env = dict(os.environ)
        env["CODEX_REVIEW_FLAG_DIR"] = str(self.flag_dir)
        if home is not None:
            env["HOME"] = home
        return subprocess.run(
            ["bash", str(HOOK), *args],
            capture_output=True,
            text=True,
            timeout=10,
            cwd=cwd,
            env=env,
        )

    def test_no_reason_is_rejected(self):
        result = self._run([], cwd=str(self.repo), home=str(self.fake_home))
        self.assertEqual(result.returncode, 1)
        self.assertIn("理由を指定してください", result.stdout + result.stderr)
        self.assertFalse(self._flag.exists())

    def test_help_prints_usage_without_approving(self):
        # 第 1 引数は無条件に理由になるため、--help を素通しすると
        # 「理由: --help」で承認が成立していた（2026-09-10 に実際に発生）。
        for flag in ("--help", "-h"):
            with self.subTest(flag=flag):
                result = self._run([flag], cwd=str(self.repo), home=str(self.fake_home))
                self.assertEqual(result.returncode, 0, msg=result.stderr)
                self.assertIn("Usage: approve-push", result.stdout)
                self.assertFalse(self._flag.exists())

    def test_reason_sets_flag_with_head(self):
        result = self._run(["ユーザーが明示的にpushを許可"], cwd=str(self.repo), home=str(self.fake_home))
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertTrue(self._flag.exists())
        head = _git_out(self.repo, "rev-parse", "HEAD")
        self.assertEqual(self._flag.read_text().strip(), head)

    def test_reason_is_logged(self):
        result = self._run(["緊急hotfixのpush許可"], cwd=str(self.repo), home=str(self.fake_home))
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        log = self.fake_home / ".claude" / "push-approve.log"
        self.assertTrue(log.exists())
        content = log.read_text()
        self.assertIn("緊急hotfixのpush許可", content)
        self.assertIn(self.git_root, content)
        self.assertIn("APPROVE", content)

    def test_default_flag_dir_is_under_home_claude_and_created_on_demand(self):
        """CODEX_REVIEW_FLAG_DIR 未設定時は ~/.claude/review-gate に書く（/tmp は sandbox 外）。"""
        env = dict(os.environ)
        env.pop("CODEX_REVIEW_FLAG_DIR", None)
        env["HOME"] = str(self.fake_home)
        result = subprocess.run(
            ["bash", str(HOOK), "sandbox 内で承認"],
            capture_output=True, text=True, timeout=10, cwd=str(self.repo), env=env,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        flag_dir = self.fake_home / ".claude" / "review-gate"
        flag = flag_dir / f".push-approved-{_review_key(self.git_root, self.branch)}"
        self.assertTrue(flag_dir.is_dir())
        self.assertEqual(flag.read_text().strip(), _git_out(self.repo, "rev-parse", "HEAD"))
        self.assertIn("失効", result.stdout)

    def test_outside_git_repo_is_rejected(self):
        outside = self.root / "not-a-repo"
        outside.mkdir()
        result = self._run(["理由"], cwd=str(outside), home=str(self.fake_home))
        self.assertEqual(result.returncode, 1)
        self.assertIn("gitリポジトリ内で実行してください", result.stdout + result.stderr)
        self.assertFalse(self._flag.exists())


if __name__ == "__main__":
    unittest.main()
