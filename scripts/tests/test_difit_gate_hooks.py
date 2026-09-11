#!/usr/bin/env python3
"""difit ゲート hooks のフィクスチャテスト。

対象:
- block-commit-without-difit.sh （commit 前 difit gate）
- set-difit-flag.sh             （difit 実行成功後の flag 設定）
- difit-skip.sh                 （手動スキップ）

KEY は lib/review-gate.sh の codex_review_key（repo + branch）を流用する
（test_review_gate_hooks.py と同じ算出方法・同じ隔離パターン）。
"""
import hashlib
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from typing import Optional


REPO_ROOT = Path(__file__).resolve().parent.parent.parent
HOOKS_DIR = REPO_ROOT / "packages" / "core" / "hooks"
COMMIT_GATE_HOOK = HOOKS_DIR / "block-commit-without-difit.sh"
SET_FLAG_HOOK = HOOKS_DIR / "set-difit-flag.sh"
SKIP_HOOK = HOOKS_DIR / "difit-skip.sh"


def _review_key(git_root: str, branch: str) -> str:
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
        ["git", "-C", str(repo), "config", "user.name", "Test"],
        check=True,
        capture_output=True,
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


def _write_and_stage(repo: Path, rel_path: str, content: str) -> None:
    target = repo / rel_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", rel_path], check=True, capture_output=True)


def _commit_command_input() -> str:
    return json.dumps({"tool_input": {"command": "git commit -m 'test commit'"}})


def _difit_command_input() -> str:
    return json.dumps({"tool_input": {"command": "bunx difit"}})


class DifitGateTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.repo = _make_git_repo(self.root)
        self.git_root = _git_out(self.repo, "rev-parse", "--show-toplevel")
        self.branch = _git_out(self.repo, "rev-parse", "--abbrev-ref", "HEAD")
        self.flag_dir = self.root / "flags"
        self.flag_dir.mkdir(exist_ok=True)
        self._prev_flag_dir = os.environ.get("CODEX_REVIEW_FLAG_DIR")
        os.environ["CODEX_REVIEW_FLAG_DIR"] = str(self.flag_dir)

    def tearDown(self):
        if self._prev_flag_dir is None:
            os.environ.pop("CODEX_REVIEW_FLAG_DIR", None)
        else:
            os.environ["CODEX_REVIEW_FLAG_DIR"] = self._prev_flag_dir
        self._tmp.cleanup()

    def difit_flag(self, branch: Optional[str] = None) -> Path:
        key = _review_key(self.git_root, branch or self.branch)
        return self.flag_dir / f".difit-done-{key}"

    def _run(
        self, hook: Path, json_input: str, cwd=None, args=None, home=None
    ) -> subprocess.CompletedProcess:
        env = dict(os.environ)
        if home is not None:
            env["HOME"] = home
        return subprocess.run(
            ["bash", str(hook), *(args or [])],
            input=json_input,
            capture_output=True,
            text=True,
            timeout=30,
            cwd=cwd,
            env=env,
        )


class TestBlockCommitWithoutDifit(DifitGateTestCase):
    def test_non_difit_route_is_allowed_without_flag(self):
        """staged diff が review 相当（小さいコードのみ）→ flag なしでも allow"""
        _write_and_stage(self.repo, "src/foo.ts", "export const foo = 1;\n")
        result = self._run(COMMIT_GATE_HOOK, _commit_command_input(), cwd=str(self.repo))
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertEqual(result.stdout.strip(), "", msg="review route は素通しで出力なし")

    def test_difit_route_without_flag_is_denied(self):
        """staged diff が components/ 配下 → difit route → flag なしで deny"""
        _write_and_stage(
            self.repo, "src/components/Button/Button.tsx", "export const Button = () => null;\n"
        )
        result = self._run(COMMIT_GATE_HOOK, _commit_command_input(), cwd=str(self.repo))
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("permissionDecision", result.stdout)
        self.assertIn("deny", result.stdout)

    def test_commit_after_every_command_boundary_is_gated(self):
        """改行 / & / bare subshell / $( ) の直後の commit も gate に載せる（旧 regex は素通り）。"""
        _write_and_stage(
            self.repo, "src/components/Button/Button.tsx", "export const Button = () => null;\n"
        )
        for command in (
            "echo x\ngit commit -m 'x'",
            "sleep 1 & git commit -m 'x'",
            "(git commit -m 'x')",
            "echo $(git commit -m 'x')",
            "true;rtk git commit -m 'x'",
        ):
            with self.subTest(command=command):
                json_input = json.dumps({"tool_input": {"command": command}})
                result = self._run(COMMIT_GATE_HOOK, json_input, cwd=str(self.repo))
                self.assertEqual(result.returncode, 0, msg=result.stderr)
                self.assertIn("deny", result.stdout)

    def test_commit_word_inside_quotes_is_not_gated(self):
        _write_and_stage(
            self.repo, "src/components/Button/Button.tsx", "export const Button = () => null;\n"
        )
        json_input = json.dumps({"tool_input": {"command": "echo 'git commit -m x'"}})
        result = self._run(COMMIT_GATE_HOOK, json_input, cwd=str(self.repo))
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertEqual(result.stdout.strip(), "")

    def test_difit_route_with_flag_is_allowed(self):
        """difit route だが difit-done flag 済み（diff 未変更）→ allow"""
        _write_and_stage(
            self.repo, "src/components/Button/Button.tsx", "export const Button = () => null;\n"
        )
        set_flag_result = self._run(SET_FLAG_HOOK, _difit_command_input(), cwd=str(self.repo))
        self.assertEqual(set_flag_result.returncode, 0, msg=set_flag_result.stderr)

        result = self._run(COMMIT_GATE_HOOK, _commit_command_input(), cwd=str(self.repo))
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertEqual(result.stdout.strip(), "")

    def test_difit_skip_with_matching_diff_is_allowed(self):
        """difit-skip 経由でも、その後 diff が変わっていなければ allow"""
        fake_home = self.root / "home"
        (fake_home / ".claude").mkdir(parents=True)
        _write_and_stage(
            self.repo, "src/components/Button/Button.tsx", "export const Button = () => null;\n"
        )
        skip_result = self._run(
            SKIP_HOOK, "", cwd=str(self.repo), args=["目視確認済み"], home=str(fake_home)
        )
        self.assertEqual(skip_result.returncode, 0, msg=skip_result.stderr)

        result = self._run(COMMIT_GATE_HOOK, _commit_command_input(), cwd=str(self.repo))
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertEqual(result.stdout.strip(), "")

    def test_flag_becomes_stale_after_additional_staging(self):
        """difit 実行後に別ファイルを追加 stage → フィンガープリント不一致で deny"""
        _write_and_stage(
            self.repo, "src/components/Button/Button.tsx", "export const Button = () => null;\n"
        )
        set_flag_result = self._run(SET_FLAG_HOOK, _difit_command_input(), cwd=str(self.repo))
        self.assertEqual(set_flag_result.returncode, 0, msg=set_flag_result.stderr)

        # difit 実行後に別の変更を追加 stage（レビュー対象と commit 対象が乖離する）
        _write_and_stage(
            self.repo, "src/components/Other/Other.tsx", "export const Other = () => null;\n"
        )

        result = self._run(COMMIT_GATE_HOOK, _commit_command_input(), cwd=str(self.repo))
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("deny", result.stdout)
        self.assertIn("再レビュー", result.stdout, msg="diff変化後の再レビュー要求メッセージが無い")

    def test_non_commit_command_is_noop(self):
        json_input = json.dumps({"tool_input": {"command": "git status"}})
        result = self._run(COMMIT_GATE_HOOK, json_input, cwd=str(self.repo))
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertEqual(result.stdout.strip(), "")

    def test_large_file_count_diff_without_flag_is_denied(self):
        """10 ファイル以上の変更（components 配下でなくても）→ difit route → deny"""
        for i in range(10):
            _write_and_stage(self.repo, f"src/file{i}.ts", f"export const v{i} = {i};\n")

        result = self._run(COMMIT_GATE_HOOK, _commit_command_input(), cwd=str(self.repo))
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("deny", result.stdout)


class TestSetDifitFlag(DifitGateTestCase):
    def test_difit_command_sets_done_flag(self):
        result = self._run(SET_FLAG_HOOK, _difit_command_input(), cwd=str(self.repo))
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertTrue(self.difit_flag().exists(), msg="difit-done flag が無い")

    def test_npx_difit_command_sets_done_flag(self):
        # difit skill は `command -v difit` 不在時に `npx difit` へフォールバックする
        json_input = json.dumps({"tool_input": {"command": "npx difit staged"}})
        result = self._run(SET_FLAG_HOOK, json_input, cwd=str(self.repo))
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertTrue(self.difit_flag().exists(), msg="npx difit で flag が立たない")

    def test_non_difit_command_is_noop(self):
        json_input = json.dumps({"tool_input": {"command": "git status"}})
        result = self._run(SET_FLAG_HOOK, json_input, cwd=str(self.repo))
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertFalse(self.difit_flag().exists())

    def test_interrupted_difit_does_not_set_flag(self):
        json_input = json.dumps(
            {
                "tool_input": {"command": "bunx difit"},
                "tool_response": {"interrupted": True},
            }
        )
        result = self._run(SET_FLAG_HOOK, json_input, cwd=str(self.repo))
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertFalse(self.difit_flag().exists())

    def test_nonzero_exit_code_does_not_set_flag(self):
        json_input = json.dumps(
            {
                "tool_input": {"command": "bunx difit"},
                "tool_response": {"exitCode": 1},
            }
        )
        result = self._run(SET_FLAG_HOOK, json_input, cwd=str(self.repo))
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertFalse(self.difit_flag().exists())


class TestDifitSkip(DifitGateTestCase):
    def test_no_reason_is_rejected(self):
        result = self._run(SKIP_HOOK, "", cwd=str(self.repo), args=[])
        self.assertEqual(result.returncode, 1)
        self.assertIn("理由を指定してください", result.stdout + result.stderr)
        self.assertFalse(self.difit_flag().exists())

    def test_reason_sets_done_flag(self):
        fake_home = self.root / "home"
        (fake_home / ".claude").mkdir(parents=True)
        result = self._run(
            SKIP_HOOK, "", cwd=str(self.repo), args=["軽微な変更"], home=str(fake_home)
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertTrue(self.difit_flag().exists())

    def test_reason_is_logged(self):
        fake_home = self.root / "home"
        (fake_home / ".claude").mkdir(parents=True)
        result = self._run(
            SKIP_HOOK, "", cwd=str(self.repo), args=["緊急対応"], home=str(fake_home)
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        log = fake_home / ".claude" / "difit-skip.log"
        self.assertTrue(log.exists())
        content = log.read_text()
        self.assertIn("緊急対応", content)
        self.assertIn("SKIP", content)

    def test_outside_git_repo_is_rejected(self):
        outside = self.root / "not-a-repo"
        outside.mkdir()
        result = self._run(SKIP_HOOK, "", cwd=str(outside), args=["理由"])
        self.assertEqual(result.returncode, 1)
        self.assertIn("gitリポジトリ内で実行してください", result.stdout + result.stderr)


class TestCommitClearsDifitFlag(DifitGateTestCase):
    """codex-review-reminder.sh は commit 成功時に difit-done flag を削除する。"""

    def test_successful_commit_removes_difit_flag(self):
        reminder_hook = HOOKS_DIR / "codex-review-reminder.sh"
        self.difit_flag().write_text("2026-01-01T00:00:00Z\n")

        json_input = json.dumps(
            {
                "tool_input": {"command": "git commit -m 'x'"},
                "tool_response": {"stdout": " 1 file changed, 2 insertions(+)"},
            }
        )
        result = self._run(reminder_hook, json_input, cwd=str(self.repo))
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertFalse(self.difit_flag().exists(), msg="commit成功後にflagが消えていない")

    def test_failed_commit_keeps_difit_flag(self):
        reminder_hook = HOOKS_DIR / "codex-review-reminder.sh"
        self.difit_flag().write_text("2026-01-01T00:00:00Z\n")

        json_input = json.dumps(
            {
                "tool_input": {"command": "git commit -m 'x'"},
                "tool_response": {"stdout": "nothing to commit"},
            }
        )
        result = self._run(reminder_hook, json_input, cwd=str(self.repo))
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertTrue(self.difit_flag().exists(), msg="commit失敗時にflagが消えてはいけない")


if __name__ == "__main__":
    unittest.main()
