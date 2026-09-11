#!/usr/bin/env python3
"""packages/core/policy/repo_target.py の resolver / CLI corpus テスト。

CMD 文字列 → 対象 repo の解決は bash(review-gate.sh) / python(kernel) / JS(bridge)
が共通で叩く唯一の実装。fail-closed 契約（解決不能は無言フォールバックせず
例外 / exit 2）を corpus で固定する。
"""
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
POLICY_DIR = REPO_ROOT / "packages" / "core" / "policy"
SCRIPT = POLICY_DIR / "repo_target.py"

sys.path.insert(0, str(POLICY_DIR))
import repo_target  # noqa: E402


class ResolveTargetTestCase(unittest.TestCase):
    """resolve_target() の corpus テスト。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp_root = Path(self._tmp.name)
        self.base = self.tmp_root / "base"
        self.base.mkdir()
        self.other = self.tmp_root / "other-repo"
        self.other.mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def test_no_indicator_returns_base(self):
        """CMD に cd/-C/--cwd が無ければ base をそのまま返す（呼び出し元 cwd 維持）。"""
        result = repo_target.resolve_target(self.base, "git push origin feature")
        self.assertEqual(result, self.base)

    def test_bare_cd_path_resolves(self):
        result = repo_target.resolve_target(self.base, f"cd {self.other} && git push")
        self.assertEqual(result, self.other.resolve())

    def test_double_quoted_cd_path_resolves(self):
        result = repo_target.resolve_target(self.base, f'cd "{self.other}" && git push')
        self.assertEqual(result, self.other.resolve())

    def test_single_quoted_cd_path_resolves(self):
        result = repo_target.resolve_target(self.base, f"cd '{self.other}' && git push")
        self.assertEqual(result, self.other.resolve())

    def test_variable_expansion_is_unresolvable(self):
        with self.assertRaises(repo_target.UnresolvableTarget):
            repo_target.resolve_target(self.base, "cd $REPO_B && git push")

    def test_command_substitution_is_unresolvable(self):
        with self.assertRaises(repo_target.UnresolvableTarget):
            repo_target.resolve_target(self.base, "cd $(get_path) && git push")

    def test_backtick_substitution_is_unresolvable(self):
        with self.assertRaises(repo_target.UnresolvableTarget):
            repo_target.resolve_target(self.base, "cd `get_path` && git push")

    def test_tilde_expands_to_home(self):
        result = repo_target.resolve_target(self.base, "cd ~ && git push")
        self.assertEqual(result, Path.home().resolve())

    def test_relative_path_resolves_against_base_not_cwd(self):
        (self.base / "sub").mkdir()
        result = repo_target.resolve_target(self.base, "cd sub && git push")
        self.assertEqual(result, (self.base / "sub").resolve())

    def test_relative_path_resolves_against_a_different_base(self):
        """同じ相対パスでも base が変われば解決先が変わる（プロセス cwd 基準ではない証明）。"""
        other_base = self.tmp_root / "other-base"
        (other_base / "sub").mkdir(parents=True)
        result = repo_target.resolve_target(other_base, "cd sub && git push")
        self.assertEqual(result, (other_base / "sub").resolve())

    def test_nonexistent_path_is_unresolvable(self):
        with self.assertRaises(repo_target.UnresolvableTarget):
            repo_target.resolve_target(self.base, "cd /nonexistent-zzz-path && git push")

    def test_multiple_cd_is_unresolvable(self):
        with self.assertRaises(repo_target.UnresolvableTarget):
            repo_target.resolve_target(
                self.base, f"cd {self.other} && cd {self.base} && git push"
            )

    def test_multiple_git_dash_c_is_unresolvable(self):
        with self.assertRaises(repo_target.UnresolvableTarget):
            repo_target.resolve_target(
                self.base, f"git -C {self.other} status && git -C {self.base} push"
            )

    def test_cwd_flag_takes_priority_over_cd(self):
        result = repo_target.resolve_target(
            self.base, f"cd {self.base} && codex-companion.mjs review --cwd {self.other}"
        )
        self.assertEqual(result, self.other.resolve())

    def test_git_dash_c_takes_priority_over_cd(self):
        result = repo_target.resolve_target(
            self.base, f"cd {self.base} && git -C {self.other} push origin feature"
        )
        self.assertEqual(result, self.other.resolve())

    def test_git_dir_equals_form_is_unresolvable(self):
        with self.assertRaises(repo_target.UnresolvableTarget):
            repo_target.resolve_target(self.base, f"git --git-dir={self.other}/.git push")

    def test_git_dir_space_form_is_unresolvable(self):
        with self.assertRaises(repo_target.UnresolvableTarget):
            repo_target.resolve_target(self.base, f"git --git-dir {self.other}/.git push")

    def test_work_tree_equals_form_is_unresolvable(self):
        with self.assertRaises(repo_target.UnresolvableTarget):
            repo_target.resolve_target(self.base, f"git --work-tree={self.other} push")

    def test_work_tree_space_form_is_unresolvable(self):
        with self.assertRaises(repo_target.UnresolvableTarget):
            repo_target.resolve_target(self.base, f"git --work-tree {self.other} push")

    def test_git_dir_env_prefix_is_unresolvable(self):
        with self.assertRaises(repo_target.UnresolvableTarget):
            repo_target.resolve_target(self.base, f"GIT_DIR={self.other}/.git git push")

    def test_git_work_tree_env_prefix_is_unresolvable(self):
        with self.assertRaises(repo_target.UnresolvableTarget):
            repo_target.resolve_target(self.base, f"GIT_WORK_TREE={self.other} git push")

    def test_cd_inside_subshell_resolves_to_that_repo(self):
        """`(cd <repo-b> && git push)` は "(cd" が 1 トークンに融合せず repo-b に解決される
        （shlex.split だけでは "(" が word 文字扱いになり抽出が効かなかった穴の再発防止）。"""
        result = repo_target.resolve_target(
            self.base, f"(cd {self.other} && git push origin feature)"
        )
        self.assertEqual(result, self.other.resolve())

    def test_subshell_cd_followed_by_outer_cd_is_unresolvable(self):
        """`(cd <repo-b> && git push) && cd <repo-c>` は 2 つの cd にまたがるため
        unresolvable（subshell 内外の両方から cd を拾えていることの確認）。"""
        third = self.tmp_root / "third-repo"
        third.mkdir()
        with self.assertRaises(repo_target.UnresolvableTarget):
            repo_target.resolve_target(
                self.base, f"(cd {self.other} && git push) && cd {third}"
            )


class GhTargetReasonTestCase(unittest.TestCase):
    """gh_target_reason() — -R/--repo/GH_REPO=/--head の corpus テスト。"""

    def test_no_override_is_resolvable(self):
        self.assertIsNone(repo_target.gh_target_reason("gh pr create --fill", "feature/x"))

    def test_dash_capital_r_owner_repo_is_unresolvable(self):
        reason = repo_target.gh_target_reason("gh pr create -R someone/other --fill", "feature/x")
        self.assertIsNotNone(reason)

    def test_repo_equals_owner_repo_is_unresolvable(self):
        reason = repo_target.gh_target_reason(
            "gh pr create --repo=someone/other --fill", "feature/x"
        )
        self.assertIsNotNone(reason)

    def test_repo_url_form_is_unresolvable(self):
        reason = repo_target.gh_target_reason(
            "gh pr create --repo https://github.com/someone/other --fill", "feature/x"
        )
        self.assertIsNotNone(reason)

    def test_gh_repo_env_prefix_is_unresolvable(self):
        reason = repo_target.gh_target_reason(
            "GH_REPO=someone/other gh pr create --fill", "feature/x"
        )
        self.assertIsNotNone(reason)

    def test_head_matching_current_branch_is_resolvable(self):
        self.assertIsNone(
            repo_target.gh_target_reason("gh pr create --head feature/x --fill", "feature/x")
        )

    def test_head_mismatched_branch_is_unresolvable(self):
        reason = repo_target.gh_target_reason(
            "gh pr create --head other-branch --fill", "feature/x"
        )
        self.assertIsNotNone(reason)

    def test_head_with_owner_prefix_is_always_unresolvable(self):
        """owner:branch 形はフォークの branch を指すため、値が一致していても常に deny。"""
        reason = repo_target.gh_target_reason(
            "gh pr create --head someone:feature/x --fill", "feature/x"
        )
        self.assertIsNotNone(reason)

    def test_body_markdown_mentioning_repo_word_is_not_a_false_positive(self):
        self.assertIsNone(
            repo_target.gh_target_reason(
                "gh pr create --fill --body 'See docs/repo-notes for details'", "feature/x"
            )
        )

    def test_quoted_body_containing_repo_flag_text_is_not_a_false_positive(self):
        """quote 内の本文は 1 トークンに畳まれるため --repo o/r の字面でも誤検知しない。"""
        self.assertIsNone(
            repo_target.gh_target_reason(
                "gh pr create --fill --body 'run with --repo someone/other later'", "feature/x"
            )
        )

    def test_gh_repo_env_after_separator_without_space_is_detected(self):
        for command in (
            "true;GH_REPO=someone/other gh pr create --fill",
            "true&&GH_REPO=someone/other gh pr create --fill",
            "true\nGH_REPO=someone/other gh pr create --fill",
            "$(GH_REPO=someone/other gh pr create --fill)",
        ):
            self.assertIsNotNone(
                repo_target.gh_target_reason(command, "feature/x"), command
            )

    def test_repo_equals_form_is_detected(self):
        self.assertIsNotNone(
            repo_target.gh_target_reason("gh pr create --repo=someone/other --fill", "feature/x")
        )


class EnvPrefixBoundaryTestCase(unittest.TestCase):
    """GIT_DIR= / GIT_WORK_TREE= の env prefix はシェル境界の直後（空白なし）でも検出する。

    旧実装の `(^|\\s)` 境界正規表現は `;GIT_DIR=/x git push` を見落とし、承認対象と
    別の repo を操作できた（2026-08-29 Codex 監査 P0）。
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.base = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_env_prefix_after_each_shell_boundary_is_unresolvable(self):
        for boundary in (";", "&&", "||", "|", "\n"):
            command = f"true{boundary}GIT_DIR=/x/.git git status"
            with self.assertRaises(repo_target.UnresolvableTarget, msg=repr(command)):
                repo_target.resolve_target(self.base, command)

    def test_env_prefix_inside_command_substitution_is_unresolvable(self):
        with self.assertRaises(repo_target.UnresolvableTarget):
            repo_target.resolve_target(self.base, "echo $(GIT_WORK_TREE=/x git status)")

    def test_env_prefix_behind_wrapper_word_is_unresolvable(self):
        for command in (
            "env GIT_DIR=/x/.git git status",
            "sudo GIT_DIR=/x/.git git status",
            "FOO=1 GIT_DIR=/x/.git git status",
        ):
            with self.assertRaises(repo_target.UnresolvableTarget, msg=command):
                repo_target.resolve_target(self.base, command)

    def test_env_assignment_text_in_argument_position_is_not_detected(self):
        """`echo "GIT_DIR=x"` は文字列引数であり環境へ効かないので解決可能。"""
        result = repo_target.resolve_target(self.base, 'echo "GIT_DIR=x" && git status')
        self.assertEqual(result, self.base)

    def test_git_dir_option_after_separator_without_space_is_unresolvable(self):
        with self.assertRaises(repo_target.UnresolvableTarget):
            repo_target.resolve_target(self.base, "true;git --work-tree=/x status")

    def test_env_prefix_behind_shell_builtins_is_unresolvable(self):
        """export/declare -x/!/then で挟んだ env 代入は実行時に環境へ漏れるため
        unresolvable にする（main の resolver では resolvable に落ちていた）。"""
        for command in (
            "export GIT_DIR=/x/.git; git push",
            "declare -x GIT_DIR=/x/.git; git push",
            "! GIT_DIR=/x/.git git push",
            "if true; then GIT_DIR=/x/.git git push; fi",
        ):
            with self.assertRaises(repo_target.UnresolvableTarget, msg=command):
                repo_target.resolve_target(self.base, command)

    def test_env_assignment_text_stays_resolvable_in_negative_cases(self):
        """env prefix と誤認しやすいが実際には環境へ効かない形は resolvable のまま。"""
        cases = (
            'echo "GIT_DIR=x" && git status',
            "git push -o GIT_DIR=1",
            "echo hi > GIT_DIR=/x",
        )
        for command in cases:
            result = repo_target.resolve_target(self.base, command)
            self.assertEqual(result, self.base, msg=command)

    def test_git_commit_message_matching_option_name_is_resolvable(self):
        """`-m` の値がたまたま --work-tree と同じ文字列でも option 指定ではない。"""
        result = repo_target.resolve_target(self.base, 'git commit -m "--work-tree"')
        self.assertEqual(result, self.base)


class ResolveCliTestCase(unittest.TestCase):
    """CLI 契約: stdin = CMD、resolve は絶対パス 1 行 / exit 0、解決不能は exit 2。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.base = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _run(self, args: list, command: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(SCRIPT), *args],
            input=command,
            capture_output=True,
            text=True,
            timeout=10,
        )

    def test_resolve_no_indicator_exits_zero_with_base(self):
        result = self._run(["resolve", "--base", str(self.base)], "git status")
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertEqual(Path(result.stdout.strip()), self.base.resolve())

    def test_resolve_unresolvable_exits_two_with_reason_on_stderr(self):
        result = self._run(["resolve", "--base", str(self.base)], "git --git-dir=/x push")
        self.assertEqual(result.returncode, 2)
        self.assertTrue(result.stderr.strip(), msg="理由が stderr に出ていない")
        self.assertEqual(result.stdout.strip(), "")

    def test_gh_target_no_override_exits_zero(self):
        result = self._run(
            ["gh-target", "--current-branch", "feature/x"], "gh pr create --fill"
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)

    def test_gh_target_repo_override_exits_two(self):
        result = self._run(
            ["gh-target", "--current-branch", "feature/x"],
            "gh pr create -R someone/other --fill",
        )
        self.assertEqual(result.returncode, 2)
        self.assertTrue(result.stderr.strip())


if __name__ == "__main__":
    unittest.main()
