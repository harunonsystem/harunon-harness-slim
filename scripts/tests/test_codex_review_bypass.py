#!/usr/bin/env python3
"""codex-review-bypass.sh のフィクスチャテスト。

理由付き実行で gate flag（/tmp/.codex-review-gate-<key>）が立つこと、
ログファイル（~/.claude/codex-review-bypass.log 相当）に理由が記録されること、
理由なし/repo 外実行の拒否を検証する。

KEY は git_root + branch のハッシュ（lib/review-gate.sh と同じ算出方法）。
一時 git repo のパスは実行ごとに一意なため、実マシンの /tmp フラグと衝突しない。
tearDown で確実に削除する。
"""
import hashlib
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent.parent
HOOK = REPO_ROOT / "packages" / "core" / "hooks" / "codex-review-bypass.sh"


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


class TestCodexReviewBypass(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.repo = _make_git_repo(self.root)
        self.git_root = _git_out(self.repo, "rev-parse", "--show-toplevel")
        self.branch = _git_out(self.repo, "rev-parse", "--abbrev-ref", "HEAD")
        # LOG は $HOME/.claude/codex-review-bypass.log に書かれるため HOME を隔離する。
        # スクリプトは >> でディレクトリを自動作成しないため事前に作る必要がある。
        self.fake_home = self.root / "home"
        (self.fake_home / ".claude").mkdir(parents=True)
        # フラグ名前空間を tempdir に隔離（実 /tmp を汚染せず、TMPDIR が /tmp
        # 配下でも書き込める。CODEX_REVIEW_FLAG_DIR は review-gate.sh の注入点）。
        self.flag_dir = self.root / "flags"
        self.flag_dir.mkdir(exist_ok=True)
        self._flag = self.flag_dir / f".codex-review-gate-{_review_key(self.git_root, self.branch)}"

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

    def test_reason_sets_gate_flag_with_head(self):
        result = self._run(
            ["ドキュメントのみの変更"], cwd=str(self.repo), home=str(self.fake_home)
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertTrue(self._flag.exists())
        head = _git_out(self.repo, "rev-parse", "HEAD")
        self.assertEqual(self._flag.read_text().strip(), head)

    def test_reason_is_logged(self):
        result = self._run(["緊急hotfix"], cwd=str(self.repo), home=str(self.fake_home))
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        log = self.fake_home / ".claude" / "codex-review-bypass.log"
        self.assertTrue(log.exists())
        content = log.read_text()
        self.assertIn("緊急hotfix", content)
        self.assertIn(self.git_root, content)
        self.assertIn("BYPASS", content)

    def test_outside_git_repo_is_rejected(self):
        outside = self.root / "not-a-repo"
        outside.mkdir()
        result = self._run(["理由"], cwd=str(outside), home=str(self.fake_home))
        self.assertEqual(result.returncode, 1)
        self.assertIn("gitリポジトリ内で実行してください", result.stdout + result.stderr)
        self.assertFalse(self._flag.exists())


if __name__ == "__main__":
    unittest.main()
