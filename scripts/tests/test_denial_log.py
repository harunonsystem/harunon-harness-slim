#!/usr/bin/env python3
"""lib/denial-log.sh の配線テスト。

block-grep-in-bash.sh / block-dangerous-in-bash.sh /
block-pr-without-codex-review.sh / block-repeated-codex-review.sh の deny 判定が
${HARNESS_DENIAL_LOG} に 1 行 JSONL として記録されることを検証する。
"""
import hashlib
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent.parent
HOOKS_DIR = REPO_ROOT / "packages" / "core" / "hooks"
DENIAL_LOG_LIB = HOOKS_DIR / "lib" / "denial-log.sh"
GREP_HOOK = HOOKS_DIR / "block-grep-in-bash.sh"
DANGEROUS_HOOK = HOOKS_DIR / "block-dangerous-in-bash.sh"
PR_GATE_HOOK = HOOKS_DIR / "block-pr-without-codex-review.sh"
REPEAT_GATE_HOOK = HOOKS_DIR / "block-repeated-codex-review.sh"


def _make_git_repo(parent: Path) -> Path:
    """空コミットを含む git リポジトリを作成して返す（test_review_gate_hooks.py と同じ形）。"""
    repo = parent / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.email", "test@example.com"],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.name", "Test"], check=True, capture_output=True
    )
    subprocess.run(
        ["git", "-C", str(repo), "commit", "--allow-empty", "-m", "init"],
        check=True,
        capture_output=True,
    )
    return repo


class TestDenialLogWiring(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.log_path = self.root / "hook-denials.jsonl"

    def tearDown(self):
        self._tmp.cleanup()

    def _read_entries(self):
        if not self.log_path.exists():
            return []
        return [
            json.loads(line)
            for line in self.log_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    # (a) 4 hook それぞれの deny が 1 行記録される -----------------------------

    def test_grep_deny_is_recorded(self):
        env = dict(os.environ)
        env.pop("HARNESS_RUNTIME", None)
        env["HARNESS_DENIAL_LOG"] = str(self.log_path)
        env["TOOL_INPUT"] = json.dumps({"command": "grep foo bar.txt"})
        result = subprocess.run(
            ["bash", str(GREP_HOOK)], capture_output=True, text=True, timeout=10, env=env
        )
        self.assertEqual(result.returncode, 2)

        entries = self._read_entries()
        self.assertEqual(len(entries), 1, msg=entries)
        entry = entries[0]
        self.assertEqual(entry["hook"], "block-grep-in-bash")
        self.assertEqual(entry["reason"], "grep-in-bash")
        self.assertEqual(entry["detail"], "grep foo bar.txt")
        self.assertRegex(entry["ts"], r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
        # HARNESS_RUNTIME はこの hook では未設定のため空文字になる
        self.assertEqual(entry["runtime"], "")

    def test_dangerous_deny_is_recorded_with_runtime(self):
        env = dict(os.environ)
        env["HARNESS_DENIAL_LOG"] = str(self.log_path)
        env["HARNESS_RUNTIME"] = "claude"
        env["TOOL_INPUT"] = json.dumps({"command": "git push origin main"})
        result = subprocess.run(
            ["bash", str(DANGEROUS_HOOK)], capture_output=True, text=True, timeout=10, env=env
        )
        self.assertEqual(result.returncode, 2)

        entries = self._read_entries()
        self.assertEqual(len(entries), 1, msg=entries)
        entry = entries[0]
        self.assertEqual(entry["hook"], "block-dangerous-in-bash")
        self.assertEqual(entry["reason"], "git-push")
        self.assertEqual(entry["runtime"], "claude")
        self.assertEqual(entry["detail"], "git push origin main")

    def test_pr_gate_deny_is_recorded(self):
        repo = _make_git_repo(self.root)
        flag_dir = self.root / "flags"
        flag_dir.mkdir()
        env = dict(os.environ)
        env["HARNESS_DENIAL_LOG"] = str(self.log_path)
        env["CODEX_REVIEW_FLAG_DIR"] = str(flag_dir)
        cmd = "gh pr create --title 'test'"
        json_input = json.dumps({"tool_input": {"command": cmd}})
        result = subprocess.run(
            ["bash", str(PR_GATE_HOOK)],
            input=json_input,
            capture_output=True,
            text=True,
            timeout=30,
            cwd=str(repo),
            env=env,
        )
        # このゲートは exit 2 ではなく permissionDecision: deny の JSON を出力して exit 0 する
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("deny", result.stdout)

        entries = self._read_entries()
        self.assertEqual(len(entries), 1, msg=entries)
        entry = entries[0]
        self.assertEqual(entry["hook"], "block-pr-without-codex-review")
        self.assertEqual(entry["reason"], "pr-without-review")
        self.assertEqual(entry["detail"], cmd)

    def test_repeated_review_deny_is_recorded(self):
        repo = _make_git_repo(self.root)
        flag_dir = self.root / "flags"
        flag_dir.mkdir()
        env = dict(os.environ)
        env["HARNESS_DENIAL_LOG"] = str(self.log_path)
        env["CODEX_REVIEW_FLAG_DIR"] = str(flag_dir)

        git_root = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "--show-toplevel"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        branch = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "--abbrev-ref", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        # lib/review-gate.sh の KEY 算出（SHA-1）を再現し、2 回目のレビューとして
        # deny させるため done flag を事前に置く（test_review_gate_hooks.py と同じ形）。
        key = hashlib.sha1(f"{git_root}\n{branch}\n".encode()).hexdigest()
        (flag_dir / f".codex-review-done-{key}").write_text("2026-01-01T00:00:00Z\n")
        # 空 diff ガードに先に捕まると reason が review-empty-target になるため、
        # レビュー対象がある状態にしてから再レビュー deny を検証する。
        (repo / "work.txt").write_text("change\n", encoding="utf-8")

        # --base を付けると explicit branch mode になり、この fixture では diff が
        # 空で review-empty-target 側の deny になる。ここで見たいのは再レビュー
        # deny なので scope 未指定 + dirty（上の work.txt）のままにする。
        cmd = "node codex-companion.mjs review"
        json_input = json.dumps({"tool_input": {"command": cmd}})
        result = subprocess.run(
            ["bash", str(REPEAT_GATE_HOOK)],
            input=json_input,
            capture_output=True,
            text=True,
            timeout=30,
            cwd=str(repo),
            env=env,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("deny", result.stdout)

        entries = self._read_entries()
        self.assertEqual(len(entries), 1, msg=entries)
        entry = entries[0]
        self.assertEqual(entry["hook"], "block-repeated-codex-review")
        self.assertEqual(entry["reason"], "repeated-review")
        self.assertEqual(entry["detail"], cmd)

    # (b) 許可されたコマンドでは追記されない ------------------------------------

    def test_allowed_command_is_not_recorded(self):
        env = dict(os.environ)
        env["HARNESS_DENIAL_LOG"] = str(self.log_path)
        env["TOOL_INPUT"] = json.dumps({"command": "git status"})
        result = subprocess.run(
            ["bash", str(GREP_HOOK)], capture_output=True, text=True, timeout=10, env=env
        )
        self.assertEqual(result.returncode, 0)
        self.assertEqual(self._read_entries(), [])

    # (c) ログ先が書き込み不能でも hook の終了コードは変わらない -------------------

    def test_write_failure_does_not_change_hook_exit_code(self):
        # chmod 0o500（自身への write 不可）にすると、hook 側の mkdir -p が失敗する。
        # tearDown の TemporaryDirectory.cleanup() は親（self.root）の write 権限で
        # readonly_dir 自体を削除できるため、ここで chmod を戻す cleanup は不要
        # （戻す cleanup を addCleanup すると tearDown 後の削除済みパスに当たり
        # FileNotFoundError になる）。
        readonly_dir = self.root / "readonly"
        readonly_dir.mkdir()
        os.chmod(readonly_dir, 0o500)
        broken_log = readonly_dir / "nested" / "hook-denials.jsonl"

        env = dict(os.environ)
        env["HARNESS_DENIAL_LOG"] = str(broken_log)
        env["TOOL_INPUT"] = json.dumps({"command": "grep foo bar.txt"})
        result = subprocess.run(
            ["bash", str(GREP_HOOK)], capture_output=True, text=True, timeout=10, env=env
        )
        self.assertEqual(result.returncode, 2, msg=result.stderr)
        self.assertFalse(broken_log.parent.exists())

    # (d) detail は先頭 500 文字に切られる --------------------------------------

    def test_detail_is_truncated_to_500_chars(self):
        long_detail = "x" * 600
        env = dict(os.environ)
        env["HARNESS_DENIAL_LOG"] = str(self.log_path)
        script = f'source "{DENIAL_LOG_LIB}"; record_denial "test-hook" "test-reason" "{long_detail}"'
        result = subprocess.run(
            ["bash", "-c", script], capture_output=True, text=True, timeout=10, env=env
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)

        entries = self._read_entries()
        self.assertEqual(len(entries), 1, msg=entries)
        self.assertEqual(len(entries[0]["detail"]), 500)
        self.assertEqual(entries[0]["detail"], long_detail[:500])


if __name__ == "__main__":
    unittest.main()
