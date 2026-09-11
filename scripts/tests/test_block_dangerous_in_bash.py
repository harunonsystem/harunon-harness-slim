#!/usr/bin/env python3
"""block-dangerous-in-bash.sh hook のテスト。"""
import json
import os
import shutil
import subprocess
import tempfile
import time
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent.parent
HOOK = REPO_ROOT / "packages" / "core" / "hooks" / "block-dangerous-in-bash.sh"


# 承認フラグの名前空間を空の tempdir に隔離する。実 dir（~/.claude/review-gate）を見ると、
# 直前に開発者が取った push 承認（remote 到達か TTL まで残る）を拾って「承認なしの push は
# deny」を期待するテストが通ってしまう（2026-08-29 に pre-push gate で実際に落ちた）。
_ISOLATED_FLAG_DIR = tempfile.mkdtemp(prefix="review-gate-test-")


def _run(command: str, cwd: str = None, runtime: str = "claude") -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["HARNESS_RUNTIME"] = runtime
    env["CODEX_REVIEW_FLAG_DIR"] = _ISOLATED_FLAG_DIR
    env["TOOL_INPUT"] = json.dumps({"command": command})
    # denial-log.sh の配線テスト（test_denial_log.py）以外は実 ~/.claude/logs/ を
    # 汚染しないよう、deny 記録先を tmp に逃がす。
    env.setdefault(
        "HARNESS_DENIAL_LOG",
        str(Path(tempfile.gettempdir()) / "harness-test-block-dangerous-denial-log.jsonl"),
    )
    return subprocess.run(
        ["bash", str(HOOK)],
        capture_output=True,
        text=True,
        timeout=10,
        cwd=cwd,
        env=env,
    )


class TestBlockDangerousInBash(unittest.TestCase):
    def test_git_push_is_blocked(self):
        result = _run("git push origin main")
        self.assertEqual(result.returncode, 2)

    def test_git_push_via_chain_is_blocked(self):
        result = _run("git commit -m 'foo' && git push")
        self.assertEqual(result.returncode, 2)

    def test_git_rebase_warns_and_allows(self):
        result = _run("git rebase main")
        self.assertEqual(result.returncode, 0)
        self.assertIn("additionalContext", result.stdout)

    def test_git_pull_warns_and_allows(self):
        result = _run("git pull origin main")
        self.assertEqual(result.returncode, 0)
        self.assertIn("additionalContext", result.stdout)

    def test_git_remote_add_is_blocked(self):
        result = _run("git remote add upstream https://github.com/foo/bar")
        self.assertEqual(result.returncode, 2)

    def test_agent_cli_unpinned_install_is_blocked(self):
        for cmd in (
            "npm install -g @earendil-works/pi-coding-agent",
            "npm i -g @oh-my-pi/pi-coding-agent@latest",
            "mise use --global npm:@earendil-works/pi-coding-agent@latest",
            "mise upgrade --bump npm:@oh-my-pi/pi-coding-agent",
            "mise install npm:@earendil-works/pi-coding-agent@0.84.3",
        ):
            result = _run(cmd)
            self.assertEqual(result.returncode, 2, cmd)

    def test_agent_cli_update_task_and_other_npm_globals_are_allowed(self):
        for cmd in (
            "mise run agents:update -- pi 0.84.3",
            "mise run agents:outdated",
            "npm install -g typescript",
            "mise install",
            "mise use --global npm:difit@5.0.10",
        ):
            result = _run(cmd)
            self.assertEqual(result.returncode, 0, cmd)

    def test_git_remote_readonly_is_allowed(self):
        # `git remote -v` / `get-url` は読み取り専用。pi/codex が状況確認で毎回打つので誤検知させない
        for cmd in ("git remote -v", "git remote", "git remote get-url origin", "git remote show origin"):
            result = _run(cmd)
            self.assertEqual(result.returncode, 0, cmd)

    def test_gh_pr_comment_is_blocked(self):
        result = _run("gh pr comment 123 -b 'test'")
        self.assertEqual(result.returncode, 2)

    def test_gh_api_get_comments_is_allowed(self):
        result = _run("gh api repos/owner/repo/pulls/123/comments")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), "")

    def test_gh_api_post_comment_is_blocked(self):
        result = _run("gh api -X POST repos/owner/repo/pulls/123/comments -f body='test'")
        self.assertEqual(result.returncode, 2)

    def test_unrelated_command_is_allowed(self):
        result = _run("git status")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), "")

    def test_rtk_git_push_is_blocked(self):
        result = _run("rtk git push origin main")
        self.assertEqual(result.returncode, 2)

    def test_git_push_via_subshell_is_blocked(self):
        result = _run("echo done: $(git push origin main)")
        self.assertEqual(result.returncode, 2)

    def test_git_push_with_env_prefix_is_blocked(self):
        result = _run("GIT_TRACE=1 git push origin main")
        self.assertEqual(result.returncode, 2)

    def test_git_push_with_multiple_env_prefixes_is_blocked(self):
        result = _run("FOO=1 BAR=2 git push origin main")
        self.assertEqual(result.returncode, 2)

    def test_git_checkout_dash_b_via_subshell_is_blocked(self):
        # チェックアウト -b のガードは「メインリポジトリ（.git がディレクトリ）」
        # でのみ発火する。テスト実行環境自体が worktree の可能性があるため、
        # 決定的に再現するには専用の一時 git リポジトリを cwd にする。
        with tempfile.TemporaryDirectory() as tmp:
            subprocess.run(
                ["git", "init", "-q", tmp], check=True, capture_output=True
            )
            result = _run("echo $(git checkout -b feature)", cwd=tmp)
        self.assertEqual(result.returncode, 2)

    def test_git_push_mentioned_in_string_argument_is_allowed(self):
        # 現状の挙動を維持する（文字列引数内の "git push" はブロックされない。
        # echo の引数は起点 ^|\||&&|;|\$\( のいずれにもマッチしないため）。
        # 挙動を変えないことの確認であり、望ましい挙動という意味ではない。
        result = _run('echo "git push は禁止"')
        self.assertEqual(result.returncode, 0)

    # --- Plan 004: OpenCode 版 block-bash-dangerous-git.js の移植パターン ---

    def test_git_push_force_ref_is_blocked(self):
        result = _run("git push origin +feature-x")
        self.assertEqual(result.returncode, 2)

    def test_git_push_force_flag_is_blocked(self):
        result = _run("git push --force origin feature-x")
        self.assertEqual(result.returncode, 2)

    def test_git_merge_main_warns_and_allows(self):
        # ハードブロックではなく警告付き許可（pull/rebase と同様）。
        # feature ブランチへ main を取り込んで同期する正当な運用と衝突するため。
        result = _run("git merge main")
        self.assertEqual(result.returncode, 0)
        self.assertIn("additionalContext", result.stdout)

    def test_git_merge_origin_master_warns_and_allows(self):
        result = _run("git merge origin/master")
        self.assertEqual(result.returncode, 0)
        self.assertIn("additionalContext", result.stdout)

    def test_git_merge_feature_branch_is_allowed(self):
        result = _run("git merge feature-branch")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), "")

    def test_git_branch_dash_capital_d_main_is_blocked(self):
        result = _run("git branch -D main")
        self.assertEqual(result.returncode, 2)

    def test_git_branch_dash_capital_d_master_is_blocked(self):
        result = _run("git branch -D master")
        self.assertEqual(result.returncode, 2)

    def test_git_branch_dash_capital_d_feature_is_allowed(self):
        result = _run("git branch -D feature-x")
        self.assertEqual(result.returncode, 0)

    def test_git_update_ref_is_blocked(self):
        result = _run("git update-ref refs/heads/main HEAD~1")
        self.assertEqual(result.returncode, 2)

    def test_git_clean_dash_fd_is_blocked(self):
        result = _run("git clean -fd")
        self.assertEqual(result.returncode, 2)

    def test_git_clean_dash_n_dry_run_is_allowed(self):
        result = _run("git clean -n")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), "")

    def test_gh_pr_merge_is_blocked(self):
        result = _run("gh pr merge 123")
        self.assertEqual(result.returncode, 2)

    def test_gh_pr_close_is_blocked(self):
        result = _run("gh pr close 123")
        self.assertEqual(result.returncode, 2)

    def test_gh_pr_view_is_allowed(self):
        result = _run("gh pr view 123")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), "")

    def test_gh_repo_delete_is_blocked(self):
        result = _run("gh repo delete owner/repo")
        self.assertEqual(result.returncode, 2)

    def test_gh_repo_edit_is_blocked(self):
        result = _run("gh repo edit --description foo")
        self.assertEqual(result.returncode, 2)

    def test_gh_release_delete_is_blocked(self):
        result = _run("gh release delete v1.0.0")
        self.assertEqual(result.returncode, 2)

    def test_git_reset_hard_warns_and_allows(self):
        result = _run("git reset --hard HEAD~1")
        self.assertEqual(result.returncode, 0)
        self.assertIn("additionalContext", result.stdout)

    def test_git_checkout_dash_f_warns_and_allows(self):
        result = _run("git checkout -f")
        self.assertEqual(result.returncode, 0)
        self.assertIn("additionalContext", result.stdout)

    def test_git_checkout_dash_dash_force_warns_and_allows(self):
        result = _run("git checkout --force")
        self.assertEqual(result.returncode, 0)
        self.assertIn("additionalContext", result.stdout)

    def test_git_merge_main_via_subshell_warns_and_allows(self):
        result = _run("echo $(git merge main)")
        self.assertEqual(result.returncode, 0)
        self.assertIn("additionalContext", result.stdout)

    def test_git_reset_hard_with_env_prefix_warns_and_allows(self):
        result = _run("FOO=1 git reset --hard")
        self.assertEqual(result.returncode, 0)
        self.assertIn("additionalContext", result.stdout)

    # --- rm-ssot-source ---

    def test_rm_rf_packages_core_skills_is_blocked(self):
        result = _run("rm -rf packages/core/skills/foo")
        self.assertEqual(result.returncode, 2)

    def test_rm_packages_core_hooks_is_blocked(self):
        result = _run("rm packages/core/hooks/foo.sh")
        self.assertEqual(result.returncode, 2)

    def test_rm_r_claude_skills_is_blocked(self):
        result = _run("rm -r ~/.claude/skills/foo")
        self.assertEqual(result.returncode, 2)

    def test_rm_rf_quoted_packages_extras_is_blocked(self):
        result = _run('rm -rf "$R/packages/extras/_active/skills/bar"')
        self.assertEqual(result.returncode, 2)

    def test_rm_rf_scripts_pycache_is_allowed(self):
        result = _run("rm -rf scripts/__pycache__")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), "")

    def test_rm_f_tmpdir_file_is_allowed(self):
        result = _run('rm -f "$TMPDIR/x.json"')
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), "")

    def test_git_rm_apm_ledger_is_allowed(self):
        result = _run("/usr/bin/git rm -q apm-ledger.yml")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), "")

    def test_rm_rf_uv_tools_is_allowed(self):
        result = _run("rm -rf ~/.local/share/uv/tools/semble")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), "")

    def test_rm_rf_packages_core_without_trailing_slash_is_blocked(self):
        result = _run("rm -rf packages/core")
        self.assertEqual(result.returncode, 2)

    def test_bin_rm_rf_packages_core_foo_is_blocked(self):
        result = _run("/bin/rm -rf packages/core/foo")
        self.assertEqual(result.returncode, 2)

    def test_rm_rf_claude_hooks_no_trailing_slash_is_blocked(self):
        result = _run("rm -rf ~/.claude/hooks")
        self.assertEqual(result.returncode, 2)

    def test_sudo_rm_r_packages_extras_no_trailing_slash_is_blocked(self):
        result = _run("sudo rm -r packages/extras")
        self.assertEqual(result.returncode, 2)

    def test_rm_rf_packages_core_old_is_allowed(self):
        result = _run("rm -rf packages/core_old")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), "")

    def test_rm_rf_node_modules_hooks_lib_is_allowed(self):
        result = _run("rm -rf node_modules/hooks-lib")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), "")

    # --- git-stash-discard / git-stash / git-checkout-discard ---

    def test_git_stash_drop_is_blocked(self):
        result = _run("git stash drop")
        self.assertEqual(result.returncode, 2)

    def test_git_stash_clear_is_blocked(self):
        result = _run("git stash clear")
        self.assertEqual(result.returncode, 2)

    def test_rtk_git_stash_drop_with_ref_is_blocked(self):
        result = _run("rtk git stash drop stash@{0}")
        self.assertEqual(result.returncode, 2)

    def test_git_stash_bare_warns_and_allows(self):
        result = _run("git stash")
        self.assertEqual(result.returncode, 0)
        self.assertIn("additionalContext", result.stdout)

    def test_git_stash_push_warns_and_allows(self):
        result = _run('git stash push -m "wip"')
        self.assertEqual(result.returncode, 0)
        self.assertIn("additionalContext", result.stdout)

    def test_git_stash_dash_u_warns_and_allows(self):
        result = _run("git stash -u")
        self.assertEqual(result.returncode, 0)
        self.assertIn("additionalContext", result.stdout)

    def test_git_stash_with_env_prefix_warns_and_allows(self):
        result = _run("FOO=1 git stash")
        self.assertEqual(result.returncode, 0)
        self.assertIn("additionalContext", result.stdout)

    def test_git_checkout_dash_dash_path_warns_and_allows(self):
        result = _run("git checkout -- src/a.ts")
        self.assertEqual(result.returncode, 0)
        self.assertIn("additionalContext", result.stdout)

    def test_git_checkout_dot_warns_and_allows(self):
        result = _run("git checkout .")
        self.assertEqual(result.returncode, 0)
        self.assertIn("additionalContext", result.stdout)

    def test_git_restore_path_warns_and_allows(self):
        result = _run("git restore src/a.ts")
        self.assertEqual(result.returncode, 0)
        self.assertIn("additionalContext", result.stdout)

    def test_git_restore_worktree_flag_warns_and_allows(self):
        result = _run("git restore --worktree src/a.ts")
        self.assertEqual(result.returncode, 0)
        self.assertIn("additionalContext", result.stdout)

    def test_git_restore_source_flag_warns_and_allows(self):
        result = _run("git restore --source=HEAD src/a.ts")
        self.assertEqual(result.returncode, 0)
        self.assertIn("additionalContext", result.stdout)

    def test_git_restore_short_worktree_flag_warns_and_allows(self):
        result = _run("git restore -W src/a.ts")
        self.assertEqual(result.returncode, 0)
        self.assertIn("additionalContext", result.stdout)

    def test_git_checkout_treeish_dash_dash_path_warns_and_allows(self):
        result = _run("git checkout HEAD -- src/a.ts")
        self.assertEqual(result.returncode, 0)
        self.assertIn("additionalContext", result.stdout)


# --- danger-rules.json 移行後の挙動パリティ: table 由来ルールのメッセージ厳密一致 ---
# (command, expected_returncode, expected_message) — message は table の message
# フィールド（旧ハードコード文言）と逐語一致することを確認する。
TABLE_RULE_MESSAGE_CASES = [
    # 保護 ref 指定や承認フラグ有りの経路は message に理由 suffix が付くため、
    # parity は主 deny 経路（承認なしの素の push）で確認する。
    ("git push", 2,
     "git push はユーザーの明示的な許可を得てから実行してください。"
     '許可を得たら承認スクリプト `approve-push.sh "理由"`（Claude: `~/.claude/hooks/`、pi: `~/.pi/agent/claude-hooks/`、omp: `~/.omp/agent/claude-hooks/`）を実行してから、'
     "単独の push コマンドを実行してください"),
    ("git branch -D main", 2,
     "main/master ブランチの強制削除はユーザーの明示的な許可を得てから実行してください"),
    ("git update-ref refs/heads/main HEAD~1", 2,
     "git update-ref はユーザーの明示的な許可を得てから実行してください"),
    ("git clean -fd", 2,
     "git clean -fd はユーザーの明示的な許可を得てから実行してください"),
    ("gh pr merge 123", 2,
     "PR の merge/close はユーザーの明示的な許可を得てから実行してください。許可を得たら `~/.claude/hooks/approve-pr.sh <PR番号> \"理由\"` を実行してから、番号を明示した単独の gh pr merge / close を実行してください"),
    ("gh pr close 123", 2,
     "PR の merge/close はユーザーの明示的な許可を得てから実行してください。許可を得たら `~/.claude/hooks/approve-pr.sh <PR番号> \"理由\"` を実行してから、番号を明示した単独の gh pr merge / close を実行してください"),
    ("gh repo delete owner/repo", 2,
     "リポジトリの delete/edit はユーザーの明示的な許可を得てから実行してください"),
    ("gh repo edit --description foo", 2,
     "リポジトリの delete/edit はユーザーの明示的な許可を得てから実行してください"),
    ("gh release delete v1.0.0", 2,
     "リリースの削除はユーザーの明示的な許可を得てから実行してください"),
    ("git rebase main", 0,
     "git rebase を実行しようとしています。ユーザーの許可を確認してください。"),
    ("git pull origin main", 0,
     "git pull を実行しようとしています。意図しない merge commit が作られる可能性があります。"
     "ユーザーの許可を確認してください。"),
    ("git merge main", 0,
     "main/master を merge しようとしています。ユーザーの許可を確認してください。"),
    ("git reset --hard HEAD~1", 0,
     "git reset --hard を実行しようとしています。ユーザー指示によるロールバックか確認してください。"),
    ("git checkout --force", 0,
     "git checkout --force を実行しようとしています。ユーザー指示によるロールバックか確認してください。"),
    ("git remote add upstream https://example.com/foo.git", 2,
     "git remote の変更はユーザーの明示的な許可を得てから実行してください"),
    ("gh pr comment 123 -b test", 2,
     "PR へのコメント投稿はユーザーの明示的な許可を得てから実行してください"),
    ("git stash drop", 2,
     "git stash drop / clear は退避した変更を復元不能に消します。ユーザーの明示的な許可を得てから実行してください"),
]

# --- table 由来ルールの「マッチしない入力」（block/warn どちらも発火しない） ---
TABLE_RULE_NEGATIVE_CASES = [
    "git log --oneline",
    "git branch -D feature-x",
    "gh pr view 123",
    "gh repo view owner/repo",
    "gh release view v1.0.0",
    "git log -p",
    "git fetch origin",
    "git reset HEAD~1",
    "git checkout feature-x",
    # `git checkout -b` は git-checkout-discard の対象外だが、main repo 上では
    # git-checkout-new-branch-in-main-repo が block するため negative case に置かない
    "git stash list",
    "git stash pop",
    "git stash apply",
    "git stash show -p",
    "git restore --staged src/a.ts",
    "git restore -S src/a.ts",
    "git checkout main",
]


class TableRuleMessageParityTestCase(unittest.TestCase):
    """table 由来ルールの stderr メッセージ / additionalContext が table の message と逐語一致するか検証する。"""

    def test_block_message_matches_table_exactly(self):
        for command, expected_code, expected_message in TABLE_RULE_MESSAGE_CASES:
            if expected_code != 2:
                continue
            with self.subTest(command=command):
                result = _run(command)
                self.assertEqual(result.returncode, 2)
                self.assertEqual(result.stderr.strip(), expected_message)

    def test_warn_additional_context_matches_table_exactly(self):
        for command, expected_code, expected_message in TABLE_RULE_MESSAGE_CASES:
            if expected_code != 0:
                continue
            with self.subTest(command=command):
                result = _run(command)
                self.assertEqual(result.returncode, 0)
                payload = json.loads(result.stdout)
                self.assertEqual(
                    payload["hookSpecificOutput"]["additionalContext"], expected_message
                )


class TableRuleNegativeCaseTestCase(unittest.TestCase):
    """table 由来ルールにマッチしない入力が exit 0 かつ無出力で許可されるか検証する。"""

    def test_unmatched_commands_are_allowed_silently(self):
        for command in TABLE_RULE_NEGATIVE_CASES:
            with self.subTest(command=command):
                result = _run(command)
                self.assertEqual(result.returncode, 0)
                self.assertEqual(result.stdout.strip(), "")


class MalformedInputFailsClosedTestCase(unittest.TestCase):
    """入力 JSON が壊れているとき、exit 1（protocol error = 継続）ではなく deny（exit 2）に倒す。

    set -e に jq の失敗を任せると exit 1 で終わり、壊れた入力を送るだけで危険コマンド
    判定を素通りできた（2026-08-29 Codex 監査 P1）。
    """

    def _run_raw(self, raw_input: str) -> subprocess.CompletedProcess:
        env = dict(os.environ)
        env["HARNESS_RUNTIME"] = "claude"
        env["CODEX_REVIEW_FLAG_DIR"] = _ISOLATED_FLAG_DIR
        env["TOOL_INPUT"] = raw_input
        return subprocess.run(
            ["bash", str(HOOK)], capture_output=True, text=True, timeout=10, env=env
        )

    def test_malformed_json_exits_2(self):
        for raw in ("not json at all", '{"command": "git status"', "[1, 2"):
            with self.subTest(raw=raw):
                result = self._run_raw(raw)
                self.assertEqual(result.returncode, 2, msg=result.stderr)
                self.assertIn("解析できません", result.stderr)


class TableMissingFailsClosedTestCase(unittest.TestCase):
    """danger-rules.json が読めないとき、hook が fail-closed（exit 2）するか検証する。"""

    def test_exits_2_when_table_file_is_absent(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            hooks_dir = tmp_path / "hooks"
            hooks_dir.mkdir()
            # policy/ ディレクトリ自体を作らない（table 不在を再現）
            hook_copy = _copy_hook_with_lib(hooks_dir)

            env = dict(os.environ)
            env["HARNESS_RUNTIME"] = "claude"
            env["TOOL_INPUT"] = json.dumps({"command": "git status"})
            result = subprocess.run(
                ["bash", str(hook_copy)],
                capture_output=True, text=True, timeout=10, env=env,
            )
        self.assertEqual(result.returncode, 2)
        self.assertIn("table", result.stderr)

    def test_exits_2_when_table_has_no_rules(self):
        """rules が欠落した valid JSON の table では、ループが空回りして fail-open に
        なってはならない（constants 読み込み成功後の明示チェックを検証する）。"""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            hooks_dir = tmp_path / "hooks"
            policy_dir = tmp_path / "policy"
            hooks_dir.mkdir()
            policy_dir.mkdir()
            table = json.loads(
                (REPO_ROOT / "packages" / "core" / "policy" / "danger-rules.json").read_text(
                    encoding="utf-8"
                )
            )
            table["rules"] = []
            (policy_dir / "danger-rules.json").write_text(json.dumps(table), encoding="utf-8")
            hook_copy = _copy_hook_with_lib(hooks_dir)

            env = dict(os.environ)
            env["HARNESS_RUNTIME"] = "claude"
            env["TOOL_INPUT"] = json.dumps({"command": "git status"})
            result = subprocess.run(
                ["bash", str(hook_copy)],
                capture_output=True, text=True, timeout=10, env=env,
            )
        self.assertEqual(result.returncode, 2)
        self.assertIn("rules", result.stderr)

    def test_runtime_with_zero_effective_rules_allows_commands(self):
        """rules はあるが現在の runtime を targets に持つ rule が 1 つも無い table では、
        判定対象が無いので exit 0 で通す。table 読み込みを jq 1 回に畳んだ際、targets 欠落
        id の行が空だと `$( )` の末尾改行除去で消え、constants 行がその位置にずれて全
        コマンドが exit 2 になった（codex review PERF-HOOK-TABLE-001）。"""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            hooks_dir = tmp_path / "hooks"
            policy_dir = tmp_path / "policy"
            hooks_dir.mkdir()
            policy_dir.mkdir()
            table = json.loads(
                (REPO_ROOT / "packages" / "core" / "policy" / "danger-rules.json").read_text(
                    encoding="utf-8"
                )
            )
            for rule in table["rules"]:
                rule["targets"] = [t for t in rule["targets"] if t != "claude"] or ["pi"]
                rule.pop("absent", None)
                rule.pop("overrides", None)
            (policy_dir / "danger-rules.json").write_text(json.dumps(table), encoding="utf-8")
            hook_copy = _copy_hook_with_lib(hooks_dir)

            env = dict(os.environ)
            env["HARNESS_RUNTIME"] = "claude"
            env["TOOL_INPUT"] = json.dumps({"command": "ls -la"})
            result = subprocess.run(
                ["bash", str(hook_copy)],
                capture_output=True, text=True, timeout=10, env=env,
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "")


class PushApprovalFlagTestCase(unittest.TestCase):
    """approve-push で発行した承認フラグの有効条件と失効条件を検証する。

    承認は HEAD に紐づき、guard 通過時には消費しない（pre-push で落ちても再承認を
    強いない）。失効は「HEAD が remote-tracking ref に到達した」か「TTL 超過」。
    実 repo の HEAD は origin/main に到達済みで常に失効扱いになるため、bare remote 付きの
    一時 repo を cwd にして判定する。
    """

    # 検査対象文字列は分割して組み立てる。このテストファイル自体を編集する
    # セッションの hook が検体に反応しないようにするため。
    PUSH = "git " + "push"
    LATER_BLOCK = "git " + "bra" + "nch " + "-" + "D " + "ma" + "in"

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self._env = dict(os.environ)
        self._env["HARNESS_RUNTIME"] = "claude"
        self._env["CODEX_REVIEW_FLAG_DIR"] = self._tmpdir.name
        self.remote = Path(self._tmpdir.name) / "remote.git"
        self.repo = Path(self._tmpdir.name) / "repo"
        self._init_repo_with_remote()
        self.flag = Path(self._flag_path())

    def tearDown(self):
        self._tmpdir.cleanup()

    def _git(self, *args: str, cwd: Path = None) -> str:
        return subprocess.run(
            ["git", "-C", str(cwd or self.repo), *args],
            capture_output=True, text=True, timeout=10, check=True,
        ).stdout.strip()

    def _init_repo_with_remote(self) -> None:
        subprocess.run(["git", "init", "-q", "--bare", str(self.remote)], check=True, capture_output=True)
        self.repo.mkdir()
        subprocess.run(["git", "init", "-q", "-b", "feature", str(self.repo)], check=True, capture_output=True)
        self._git("config", "user.email", "test@example.com")
        self._git("config", "user.name", "Test")
        self._git("remote", "add", "origin", str(self.remote))
        self._git("commit", "-q", "--allow-empty", "-m", "init")

    def _flag_path(self) -> str:
        result = subprocess.run(
            ["bash", "-c",
             f"source {REPO_ROOT}/packages/core/hooks/lib/review-gate.sh; push_approved_flag"],
            cwd=str(self.repo), capture_output=True, text=True,
            timeout=10, env=self._env, check=True,
        )
        return result.stdout.strip()

    def _head(self) -> str:
        return self._git("rev-parse", "HEAD")

    def _approve(self, head: str = None):
        self.flag.write_text((head if head is not None else self._head()) + "\n")

    def _run(self, command: str) -> subprocess.CompletedProcess:
        env = dict(self._env)
        env["TOOL_INPUT"] = json.dumps({"command": command})
        return subprocess.run(
            ["bash", str(HOOK)], cwd=str(self.repo),
            capture_output=True, text=True, timeout=10, env=env,
        )

    def test_returns_error_and_suggests_approve_push_when_flag_is_absent(self):
        result = self._run(self.PUSH)
        self.assertEqual(result.returncode, 2)
        self.assertIn("approve-push", result.stderr)

    def test_allows_push_and_keeps_flag_when_approval_matches_head(self):
        # guard 通過時に消費しない: 後続の pre-push hook が落ちても同じ承認で再 push できる。
        self._approve()
        result = self._run(self.PUSH)
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("push 承認を確認", result.stdout)
        self.assertTrue(self.flag.exists())

    def test_same_approval_is_reusable_until_head_reaches_remote(self):
        self._approve()
        self.assertEqual(self._run(self.PUSH).returncode, 0)
        self.assertEqual(self._run(self.PUSH).returncode, 0)
        self.assertTrue(self.flag.exists())

    def test_denies_and_expires_flag_once_head_has_reached_remote(self):
        # push 成功 = remote-tracking ref が HEAD を指す。同じ HEAD への承認は使い切り。
        self._approve()
        self._git("push", "-q", "origin", "feature")
        result = self._run(self.PUSH)
        self.assertEqual(result.returncode, 2, msg=result.stdout)
        self.assertIn("remote に到達済み", result.stderr)
        self.assertFalse(self.flag.exists())

    def test_denies_and_expires_flag_after_ttl(self):
        self._approve()
        old = 10_000
        os.utime(self.flag, (old, old))
        result = self._run(self.PUSH)
        self.assertEqual(result.returncode, 2, msg=result.stdout)
        self.assertIn("失効", result.stderr)
        self.assertFalse(self.flag.exists())

    def test_ttl_is_configurable_via_environment(self):
        self._approve()
        self._env["PUSH_APPROVAL_TTL_SECONDS"] = "0"
        past = int(time.time()) - 5
        os.utime(self.flag, (past, past))
        result = self._run(self.PUSH)
        self.assertEqual(result.returncode, 2, msg=result.stdout)
        self.assertIn("失効", result.stderr)

    def test_returns_error_when_approval_was_recorded_for_another_head(self):
        self._approve(head="0" * 40)
        result = self._run(self.PUSH)
        self.assertEqual(result.returncode, 2)
        self.assertIn("HEAD が変わった", result.stderr)
        self.assertTrue(self.flag.exists())

    def test_returns_error_when_approved_push_is_chained_with_another_command(self):
        # チェインを許すと (a) switch 後の未承認 HEAD の push (b) 1 コマンドで承認外の
        # ref も同時に push が成立するため、単独 push に限定する。
        self._approve()
        result = self._run(f"{self.PUSH} && {self.LATER_BLOCK}")
        self.assertEqual(result.returncode, 2)
        self.assertIn("単独の push", result.stderr)

    def test_keeps_approval_flag_when_the_command_is_denied(self):
        # deny された場合は承認を消費しない（再承認を強いない）。
        self._approve()
        self._run(f"{self.PUSH} && {self.LATER_BLOCK}")
        self.assertTrue(self.flag.exists())

    def test_returns_error_when_approved_command_pushes_twice(self):
        self._approve()
        result = self._run(f"{self.PUSH} origin one && {self.PUSH} origin two")
        self.assertEqual(result.returncode, 2)
        self.assertIn("単独の push", result.stderr)
        self.assertTrue(self.flag.exists())

    def test_returns_error_when_approved_push_targets_a_protected_ref(self):
        # table の git-push-protected は match.ere を持たず opencode/omp 専用なので、
        # claude 側の保護は custom_git_push が担う。
        protected = "ma" + "in"
        for command in (f"{self.PUSH} origin {protected}",
                        f"{self.PUSH} --force",
                        f"{self.PUSH} origin +HEAD"):
            with self.subTest(command=command):
                self._approve()
                result = self._run(command)
                self.assertEqual(result.returncode, 2)
                self.assertIn("保護 ref", result.stderr)
                self.assertTrue(self.flag.exists())

    def test_allows_force_with_lease_to_a_feature_branch(self):
        # rules/git-safety.md: feature branch への force-with-lease は許容。
        self._approve()
        result = self._run(f"{self.PUSH} --force-with-lease origin feature-x")
        self.assertEqual(result.returncode, 0)
        self.assertTrue(self.flag.exists())

    # --- 候補 A 5-2: 誤検知解消（承認あり）---

    def test_allows_push_piped_to_tee(self):
        self._approve()
        result = self._run(f"{self.PUSH} origin feature 2>&1 | tee /tmp/l")
        self.assertEqual(result.returncode, 0, msg=result.stderr)

    def test_allows_push_piped_to_cat(self):
        self._approve()
        result = self._run(f"{self.PUSH} origin feature | cat")
        self.assertEqual(result.returncode, 0, msg=result.stderr)

    def test_allows_push_with_trailing_comment(self):
        self._approve()
        result = self._run(f"{self.PUSH} origin feature # sync with main")
        self.assertEqual(result.returncode, 0, msg=result.stderr)

    def test_allows_push_option_value_containing_plus(self):
        self._approve()
        result = self._run(f'{self.PUSH} origin feature -o "a + b"')
        self.assertEqual(result.returncode, 0, msg=result.stderr)

    def test_allows_push_option_value_mentioning_protected_ref_name(self):
        # 回帰防止: -o の値に main が現れても保護 ref 判定には使わない。
        self._approve()
        result = self._run(f'{self.PUSH} origin feature -o "note about main"')
        self.assertEqual(result.returncode, 0, msg=result.stderr)

    def test_allows_push_with_repo_option_value_mentioning_protected_ref_name(self):
        # 回帰防止: --repo の値に main が現れても保護 ref 判定には使わない。
        self._approve()
        result = self._run(f"{self.PUSH} --repo /Users/x/main origin feature")
        self.assertEqual(result.returncode, 0, msg=result.stderr)

    # --- 候補 A 5-3: 真陽性維持（承認あり）---

    def test_denies_quoted_force_refspec(self):
        # FN 修正: quote 越しの +HEAD も保護 ref 判定に載る。
        self._approve()
        result = self._run(f'{self.PUSH} origin "+HEAD"')
        self.assertEqual(result.returncode, 2, msg=result.stdout)
        self.assertIn("保護 ref", result.stderr)

    def test_denies_push_with_branch_colon_main_refspec(self):
        # FN 修正: 宛先側（コロン以降）が保護 ref。
        self._approve()
        result = self._run(f"{self.PUSH} origin feature:main")
        self.assertEqual(result.returncode, 2, msg=result.stdout)
        self.assertIn("保護 ref", result.stderr)

    def test_denies_push_with_full_ref_colon_refspec_to_main(self):
        self._approve()
        result = self._run(f"{self.PUSH} origin HEAD:refs/heads/main")
        self.assertEqual(result.returncode, 2, msg=result.stdout)
        self.assertIn("保護 ref", result.stderr)

    def test_denies_push_deleting_main_via_empty_source_refspec(self):
        self._approve()
        result = self._run(f"{self.PUSH} origin :main")
        self.assertEqual(result.returncode, 2, msg=result.stdout)
        self.assertIn("保護 ref", result.stderr)

    def test_denies_combined_force_update_shorthand(self):
        # FN 修正: -fu のような結合ショートオプションも force として拾う。
        self._approve()
        result = self._run(f"{self.PUSH} -fu origin feature")
        self.assertEqual(result.returncode, 2, msg=result.stdout)
        self.assertIn("保護 ref", result.stderr)

    def test_denies_push_piped_to_non_allowlisted_sink(self):
        # allowlist（grep/tee/cat 等）以外へのパイプは単独扱いしない。
        result_command = f"{self.PUSH} origin f | xargs rm -rf"
        self._approve()
        result = self._run(result_command)
        self.assertEqual(result.returncode, 2, msg=result.stdout)
        self.assertIn("単独の push", result.stderr)

    def test_denies_push_with_command_substitution_refspec(self):
        self._approve()
        result = self._run(f"{self.PUSH} origin HEAD:$({self.PUSH[:3]} branch --show-current)")
        self.assertEqual(result.returncode, 2, msg=result.stdout)


class GitDashCTargetSwapTestCase(unittest.TestCase):
    """`git -C <repo-b> push` による対象 repo すり替えの回帰テスト（セキュリティ C-002）。

    push 承認フラグは cwd 基準の repo+branch で発行されるが、`git -C <path> push`
    は cwd ではなく -C の対象 repo に作用する。repo A の cwd で発行した承認が、
    -C 経由で repo B への push を通してはならない。
    """

    GIT = "gi" + "t"
    PUSH = "pus" + "h"

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self._env = dict(os.environ)
        self._env["HARNESS_RUNTIME"] = "claude"
        self._env["CODEX_REVIEW_FLAG_DIR"] = self._tmpdir.name

        self.repo_a = Path(self._tmpdir.name) / "repo-a"
        self.repo_b = Path(self._tmpdir.name) / "repo-b"
        for repo in (self.repo_a, self.repo_b):
            self._init_repo(repo)

    def tearDown(self):
        self._tmpdir.cleanup()

    @staticmethod
    def _init_repo(repo: Path) -> None:
        repo.mkdir()
        subprocess.run(["git", "init", "-q", str(repo)], check=True, capture_output=True)
        subprocess.run(
            ["git", "-C", str(repo), "config", "user.email", "test@example.com"],
            check=True, capture_output=True,
        )
        subprocess.run(
            ["git", "-C", str(repo), "config", "user.name", "Test"],
            check=True, capture_output=True,
        )
        (repo / "file.txt").write_text("x")
        subprocess.run(["git", "-C", str(repo), "add", "file.txt"], check=True, capture_output=True)
        subprocess.run(
            ["git", "-C", str(repo), "commit", "-q", "-m", "init"],
            check=True, capture_output=True,
        )

    @staticmethod
    def _head(repo: Path) -> str:
        result = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=10, check=True,
        )
        return result.stdout.strip()

    def _flag_path(self, repo: Path) -> Path:
        # codex_review_key は実行時 cwd の git root+branch から算出されるため、
        # 対象 repo を cwd にして解決する（REPO_ROOT 固定では repo ごとの
        # フラグパスを再現できない）。
        script = f'source "{REPO_ROOT}/packages/core/hooks/lib/review-gate.sh"; push_approved_flag'
        result = subprocess.run(
            ["bash", "-c", script],
            cwd=str(repo), capture_output=True, text=True, timeout=10,
            env=self._env, check=True,
        )
        return Path(result.stdout.strip())

    def _approve(self, repo: Path) -> None:
        self._flag_path(repo).write_text(self._head(repo) + "\n")

    def _run(self, command: str, cwd: Path) -> subprocess.CompletedProcess:
        env = dict(self._env)
        env["TOOL_INPUT"] = json.dumps({"command": command})
        return subprocess.run(
            ["bash", str(HOOK)], cwd=str(cwd),
            capture_output=True, text=True, timeout=10, env=env,
        )

    def test_denies_push_to_other_repo_via_dash_c_using_this_repos_approval(self):
        # repo A で承認済みでも、-C で repo B（未承認）へ向けた push は通らない。
        self._approve(self.repo_a)
        result = self._run(
            f"{self.GIT} -C {self.repo_b} {self.PUSH} origin feature", cwd=self.repo_a
        )
        self.assertEqual(result.returncode, 2)
        self.assertTrue(self._flag_path(self.repo_a).exists())

    def test_allows_push_via_dash_c_when_target_repo_itself_is_approved(self):
        # -C の対象 repo（B）が自身の承認を持っていれば、cwd（A）に承認が
        # なくても正しく通る（承認は remote 到達まで残る）。
        self._approve(self.repo_b)
        result = self._run(
            f"{self.GIT} -C {self.repo_b} {self.PUSH} origin feature", cwd=self.repo_a
        )
        self.assertEqual(result.returncode, 0)
        self.assertTrue(self._flag_path(self.repo_b).exists())
        self.assertFalse(self._flag_path(self.repo_a).exists())

    def test_denies_when_dash_c_appears_twice(self):
        self._approve(self.repo_a)
        result = self._run(
            f"{self.GIT} -C {self.repo_a} -C {self.repo_b} {self.PUSH} origin feature",
            cwd=self.repo_a,
        )
        self.assertEqual(result.returncode, 2)

    def test_denies_when_dash_c_value_is_quoted(self):
        # quote-aware resolver は安全に対象を解決できるため、対象 repo B を明示し、
        # repo A の承認が流用されないことを検証する。
        self._approve(self.repo_a)
        result = self._run(
            f'{self.GIT} -C "{self.repo_b}" {self.PUSH} origin feature', cwd=self.repo_a
        )
        self.assertEqual(result.returncode, 2)

    def test_denies_push_to_other_repo_via_git_dir_equals_form(self):
        # command-normalize.sh は判定用 $NORMALIZED から --git-dir=<path> を剥がすが、
        # 実行対象の解決には使っていない。repo A の承認で --git-dir 経由の
        # repo B への push が通ってはならない。
        self._approve(self.repo_a)
        result = self._run(
            f"{self.GIT} --git-dir={self.repo_b}/.git {self.PUSH} origin feature",
            cwd=self.repo_a,
        )
        self.assertEqual(result.returncode, 2)

    def test_denies_push_to_other_repo_via_git_dir_space_form(self):
        self._approve(self.repo_a)
        result = self._run(
            f"{self.GIT} --git-dir {self.repo_b}/.git {self.PUSH} origin feature",
            cwd=self.repo_a,
        )
        self.assertEqual(result.returncode, 2)

    def test_denies_push_to_other_repo_via_work_tree_equals_form(self):
        self._approve(self.repo_a)
        result = self._run(
            f"{self.GIT} --work-tree={self.repo_b} {self.PUSH} origin feature",
            cwd=self.repo_a,
        )
        self.assertEqual(result.returncode, 2)

    def test_denies_push_to_other_repo_via_work_tree_space_form(self):
        self._approve(self.repo_a)
        result = self._run(
            f"{self.GIT} --work-tree {self.repo_b} {self.PUSH} origin feature",
            cwd=self.repo_a,
        )
        self.assertEqual(result.returncode, 2)

    def test_allows_plain_push_within_single_repo_unaffected_by_dash_c_handling(self):
        # -C を使わない従来の正常系（cwd の repo への単独 push）が壊れていないこと。
        self._approve(self.repo_a)
        result = self._run(f"{self.GIT} {self.PUSH} origin feature", cwd=self.repo_a)
        self.assertEqual(result.returncode, 0)
        self.assertTrue(self._flag_path(self.repo_a).exists())


def _copy_hook_with_lib(hooks_dir: Path) -> Path:
    """hook を lib ごとコピーする。lib は hook の実行時依存なので同伴させる。"""
    hook_copy = hooks_dir / HOOK.name
    hook_copy.write_text(HOOK.read_text(encoding="utf-8"), encoding="utf-8")
    hook_copy.chmod(0o755)
    lib_dir = hooks_dir / "lib"
    lib_dir.mkdir(exist_ok=True)
    for lib in (HOOK.parent / "lib").glob("*.sh"):
        (lib_dir / lib.name).write_text(lib.read_text(encoding="utf-8"), encoding="utf-8")
    return hook_copy


def _minimal_path(*binaries: str) -> tempfile.TemporaryDirectory:
    """指定バイナリだけを symlink した PATH ディレクトリを作る（列挙外は不在扱いになる）。"""
    tmpdir = tempfile.TemporaryDirectory()
    for name in binaries:
        resolved = shutil.which(name)
        if resolved:
            os.symlink(resolved, Path(tmpdir.name) / name)
    return tmpdir


class TestFailsClosedWithoutNormalizeLib(unittest.TestCase):
    """lib/command-normalize.sh の配布漏れは deny に倒す。

    source 失敗で exit 1 になると hook protocol では「エラーだが継続」と解釈され、
    配線漏れが安全層の消失として静かに通ってしまう。
    """

    def test_missing_lib_denies_instead_of_erroring(self):
        with tempfile.TemporaryDirectory() as tmp:
            hooks_dir = Path(tmp) / "hooks"
            hooks_dir.mkdir()
            policy_dir = Path(tmp) / "policy"
            policy_dir.mkdir()
            (policy_dir / "danger-rules.json").write_text(
                (REPO_ROOT / "packages" / "core" / "policy" / "danger-rules.json").read_text(
                    encoding="utf-8"
                ),
                encoding="utf-8",
            )
            # lib/ を作らずに hook だけ置く（配布漏れの再現）
            hook_copy = hooks_dir / HOOK.name
            hook_copy.write_text(HOOK.read_text(encoding="utf-8"), encoding="utf-8")
            hook_copy.chmod(0o755)

            env = dict(os.environ)
            env["HARNESS_RUNTIME"] = "claude"
            env["TOOL_INPUT"] = json.dumps({"command": "git status"})
            result = subprocess.run(
                ["bash", str(hook_copy)],
                capture_output=True, text=True, timeout=10, env=env,
            )
        self.assertEqual(result.returncode, 2, msg=result.stderr)
        self.assertIn("lib", result.stderr)


class TestFailsClosedWithoutJq(unittest.TestCase):
    """jq 不在は table 不在と同じく deny に倒す。

    exit 127 で終わると hook protocol では「エラーだが継続」と解釈され、
    危険コマンド判定という安全層がまるごと消える。
    """

    def test_missing_jq_denies_instead_of_erroring(self):
        with _minimal_path("bash", "grep", "git", "shasum", "cat", "readlink") as binpath:
            env = dict(os.environ)
            env["PATH"] = binpath
            env["HARNESS_RUNTIME"] = "claude"
            env["TOOL_INPUT"] = json.dumps({"command": "git push origin main"})
            result = subprocess.run(
                ["bash", str(HOOK)],
                capture_output=True,
                text=True,
                timeout=10,
                env=env,
            )
        self.assertEqual(result.returncode, 2, msg=result.stderr)
        self.assertIn("jq", result.stderr)


class PushApprovalRepoBoundaryTestCase(unittest.TestCase):
    """承認フラグは発行した repo に閉じる。

    フラグの KEY は repo root + branch、内容は HEAD。判定時に対象 repo へ解決しないと、
    repo A の承認で `git -C <repo-b> push` が通る。HEAD 照合も cwd 側で
    rev-parse するため素通りしてしまう（2026-07-26 に実測）。
    """

    PUSH = "git " + "push"

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        base = Path(self._tmpdir.name)
        self.flag_dir = base / "flags"
        self.flag_dir.mkdir()
        self.repo_a = self._make_repo(base / "repo-a")
        self.repo_b = self._make_repo(base / "repo-b", extra_commit=True)

    def tearDown(self):
        self._tmpdir.cleanup()

    def _git(self, cwd: Path, *args: str) -> str:
        result = subprocess.run(
            ["git", "-c", "user.email=t@t", "-c", "user.name=t", *args],
            cwd=str(cwd), capture_output=True, text=True, timeout=20, check=True,
        )
        return result.stdout.strip()

    def _make_repo(self, path: Path, extra_commit: bool = False) -> Path:
        path.mkdir(parents=True)
        self._git(path, "init", "-q", "-b", "feature", ".")
        self._git(path, "commit", "-q", "--allow-empty", "-m", "init")
        if extra_commit:
            # HEAD が偶然一致しないようにする（一致すると検証が甘くなる）
            self._git(path, "commit", "-q", "--allow-empty", "-m", "diverge")
        return path

    def _approve(self, repo: Path) -> Path:
        env = dict(os.environ)
        env["CODEX_REVIEW_FLAG_DIR"] = str(self.flag_dir)
        flag = subprocess.run(
            ["bash", "-c",
             f"source {REPO_ROOT}/packages/core/hooks/lib/review-gate.sh; push_approved_flag"],
            cwd=str(repo), capture_output=True, text=True, timeout=10, env=env, check=True,
        ).stdout.strip()
        path = Path(flag)
        path.write_text(self._git(repo, "rev-parse", "HEAD") + "\n", encoding="utf-8")
        return path

    def _run(self, command: str, cwd: Path) -> subprocess.CompletedProcess:
        env = dict(os.environ)
        env["HARNESS_RUNTIME"] = "claude"
        env["CODEX_REVIEW_FLAG_DIR"] = str(self.flag_dir)
        env["TOOL_INPUT"] = json.dumps({"command": command})
        return subprocess.run(
            ["bash", str(HOOK)],
            cwd=str(cwd), capture_output=True, text=True, timeout=20, env=env,
        )

    def test_approval_does_not_cross_into_another_repo(self):
        self._approve(self.repo_a)
        result = self._run(f"{self.PUSH} -C {self.repo_b} origin feature", self.repo_a)
        self.assertEqual(result.returncode, 2, msg=result.stdout)

    def test_git_dash_c_form_is_recognised(self):
        # 正規化が -C を剥がすため、対象 repo の解決は生コマンド側で行う必要がある
        self._approve(self.repo_a)
        result = self._run(f"git -C {self.repo_b} push origin feature", self.repo_a)
        self.assertEqual(result.returncode, 2, msg=result.stdout)

    def test_approval_still_works_for_the_same_repo_via_dash_c(self):
        self._approve(self.repo_a)
        result = self._run(f"git -C {self.repo_a} push origin feature", self.repo_a)
        self.assertEqual(result.returncode, 0, msg=result.stderr)

    def test_approval_still_works_without_repo_options(self):
        self._approve(self.repo_a)
        result = self._run(f"{self.PUSH} origin feature", self.repo_a)
        self.assertEqual(result.returncode, 0, msg=result.stderr)

    def test_unresolvable_repo_options_are_denied(self):
        for option in (f"--git-dir={self.repo_b}/.git", f"--work-tree={self.repo_b}"):
            with self.subTest(option=option):
                self._approve(self.repo_a)
                result = self._run(f"git {option} push origin feature", self.repo_a)
                self.assertEqual(result.returncode, 2, msg=result.stdout)

    def test_approval_still_works_for_subdirectory_of_same_repo(self):
        """git -C <repo-a のサブディレクトリ> は同一 repo 扱いのまま allow される（回帰ガード）。"""
        subdir = self.repo_a / "sub"
        subdir.mkdir()
        self._approve(self.repo_a)
        result = self._run(f"git -C {subdir} push origin feature", self.repo_a)
        self.assertEqual(result.returncode, 0, msg=result.stderr)

    def test_double_quoted_repo_path_denied_across_repo(self):
        """P0-B: `git -C "<repo-b>"` は quote 越しでも repo-b の承認境界を越えて通らない。"""
        self._approve(self.repo_a)
        result = self._run(f'{self.PUSH} -C "{self.repo_b}" origin feature', self.repo_a)
        self.assertEqual(result.returncode, 2, msg=result.stdout)

    def test_single_quoted_repo_path_denied_across_repo(self):
        """P0-B: `git -C '<repo-b>'` も同様に deny する。"""
        self._approve(self.repo_a)
        result = self._run(f"{self.PUSH} -C '{self.repo_b}' origin feature", self.repo_a)
        self.assertEqual(result.returncode, 2, msg=result.stdout)

    def test_variable_repo_path_is_unresolvable_and_denied(self):
        """P0-B: `$VAR` はシェル展開を推測せず解決不能として deny する。"""
        self._approve(self.repo_a)
        result = self._run(f"{self.PUSH} -C $REPO_B origin feature", self.repo_a)
        self.assertEqual(result.returncode, 2, msg=result.stdout)

    def test_nonexistent_repo_path_is_unresolvable_and_denied(self):
        """P0-B: 存在しないパスへの -C は無言フォールバックせず deny する。"""
        self._approve(self.repo_a)
        result = self._run(f"{self.PUSH} -C /nonexistent-zzz-repo origin feature", self.repo_a)
        self.assertEqual(result.returncode, 2, msg=result.stdout)


def _path_with_fake_perl(perl_script: str) -> tempfile.TemporaryDirectory:
    """本物の perl を差し替えた PATH ディレクトリを作る（前処理の異常応答を再現する）。"""
    tmpdir = _minimal_path(
        "bash", "jq", "git", "cat", "readlink", "grep", "shasum", "python3", "dirname",
    )
    fake_perl = Path(tmpdir.name) / "perl"
    fake_perl.write_text(perl_script, encoding="utf-8")
    fake_perl.chmod(0o755)
    return tmpdir


class NormalizePreprocessingFailsClosedTestCase(unittest.TestCase):
    """前処理（normalize_command）の異常応答を allow に倒さない（5-4）。

    perl 呼び出しが失敗する／空を返すケースは、正規化という判定層そのものが
    機能していない状態なので、旧実装のように fail-open（exit 0 で素通り）に
    してはならない。
    """

    def test_perl_exit_failure_is_denied_with_preprocessing_message(self):
        with _path_with_fake_perl("#!/bin/sh\nexit 1\n") as binpath:
            env = dict(os.environ)
            env["PATH"] = binpath
            env["HARNESS_RUNTIME"] = "claude"
            env["TOOL_INPUT"] = json.dumps({"command": "git status"})
            result = subprocess.run(
                ["bash", str(HOOK)], capture_output=True, text=True, timeout=10, env=env,
            )
        self.assertEqual(result.returncode, 2, msg=result.stdout)
        self.assertIn("前処理", result.stderr)

    # 検体は分割して組み立てる（このテストを編集するセッション自身の hook が
    # 検体に反応するのを防ぐ規約）。
    PUSH_COMMAND = "git " + "push" + " origin main"

    def test_perl_empty_output_is_denied_instead_of_passing_through(self):
        # 現状は perl が空出力を返すと NORMALIZED="" になり、判定対象が空文字列
        # になるため危険コマンドが未検出のまま exit 0 で通ってしまう（fail-open）。
        with _path_with_fake_perl("#!/bin/sh\nexit 0\n") as binpath:
            env = dict(os.environ)
            env["PATH"] = binpath
            env["HARNESS_RUNTIME"] = "claude"
            env["TOOL_INPUT"] = json.dumps({"command": self.PUSH_COMMAND})
            result = subprocess.run(
                ["bash", str(HOOK)], capture_output=True, text=True, timeout=10, env=env,
            )
        self.assertEqual(result.returncode, 2, msg=result.stdout)


class GitGlobalOptionNormalizationTestCase(unittest.TestCase):
    """P0-A: git のグローバルオプションを剥がした後、承認が対象 repo を確定できるか。

    オプション剥がし自体の述語カバレッジ（--no-pager 等が push 判定に載るか）は
    test_command_shape.py の GitGlobalOptionStrippingTestCase に移した。ここに
    残すのは --git-dir / --work-tree のように「対象 repo が解決不能」なため
    承認では通せない、という hook 全体の wire protocol（承認フラグ・deny
    メッセージ）依存のケース。
    """

    P = "git"
    PUSH = P + " push"

    def test_git_dir_space_form_is_unresolvable_with_approval(self):
        self._assert_unresolvable_with_approval("--git-dir")

    def test_work_tree_space_form_is_unresolvable_with_approval(self):
        self._assert_unresolvable_with_approval("--work-tree")

    def _assert_unresolvable_with_approval(self, option: str):
        with tempfile.TemporaryDirectory() as flag_dir:
            env = dict(os.environ)
            env["HARNESS_RUNTIME"] = "claude"
            env["CODEX_REVIEW_FLAG_DIR"] = flag_dir
            flag = subprocess.run(
                ["bash", "-c",
                 "source packages/core/hooks/lib/review-gate.sh; push_approved_flag"],
                cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=10, env=env, check=True,
            ).stdout.strip()
            head = subprocess.run(
                ["git", "rev-parse", "HEAD"], cwd=str(REPO_ROOT),
                capture_output=True, text=True, timeout=10, check=True,
            ).stdout.strip()
            Path(flag).write_text(head + "\n", encoding="utf-8")

            env["TOOL_INPUT"] = json.dumps(
                {"command": f"{self.P} {option} /tmp/normalize-test-x push origin feature"}
            )
            result = subprocess.run(
                ["bash", str(HOOK)], cwd=str(REPO_ROOT),
                capture_output=True, text=True, timeout=10, env=env,
            )
        self.assertEqual(result.returncode, 2, msg=result.stdout)
        self.assertIn("確定できません", result.stderr)


class TestInsights2026August(unittest.TestCase):
    """insights 2026-08 の実インシデント由来のルール（新規 repo 作成 / BSD xargs）。"""

    def test_gh_repo_create_is_blocked(self):
        result = _run("gh repo create myorg/new-repo --private")
        self.assertEqual(result.returncode, 2)

    def test_gh_repo_create_via_chain_is_blocked(self):
        result = _run("cd /tmp && gh repo create myorg/new-repo")
        self.assertEqual(result.returncode, 2)

    def test_gh_repo_view_is_allowed(self):
        result = _run("gh repo view myorg/repo")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), "")

    def test_xargs_dash_a_warns_and_allows(self):
        result = _run("xargs -a files.txt wc -l")
        self.assertEqual(result.returncode, 0)
        self.assertIn("additionalContext", result.stdout)

    def test_xargs_from_stdin_is_allowed(self):
        result = _run("ls | xargs wc -l")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), "")

    def test_xargs_dash_a_after_other_options_warns(self):
        # BSD xargs では -0 等の先行オプションがあっても -a は未対応（codex review P2）
        result = _run("xargs -0 -a files.txt rm")
        self.assertEqual(result.returncode, 0)
        self.assertIn("additionalContext", result.stdout)

    def test_block_rule_wins_over_earlier_warn_rule(self):
        # warn（git-rebase）が先に一致しても、後続の block（git-remote）を
        # 評価せず全体を許可してはならない（codex review P1）
        result = _run("git rebase main && git remote add upstream https://github.com/foo/bar")
        self.assertEqual(result.returncode, 2)

    def test_warn_only_command_still_warns_and_allows(self):
        result = _run("git rebase main && git pull origin main")
        self.assertEqual(result.returncode, 0)
        self.assertIn("additionalContext", result.stdout)


class GhApiCommentRuleTestCase(unittest.TestCase):
    """gh api コメント系 table rule と xargs ラップの wire-protocol 回帰。

    predicate seam（test_command_shape.py）には移せない table rule 経路なので
    subprocess で残す。
    """

    def test_gh_api_patch_with_comment_word_in_value_is_allowed(self):
        result = _run("gh api -X PATCH repos/o/r/issues/1 -f body='no comment here'")
        self.assertEqual(result.returncode, 0, msg=result.stderr)

    def test_gh_api_post_labels_with_comment_in_value_is_allowed_regression(self):
        result = _run("gh api -X POST repos/o/r/issues/1/labels -f name=comment-bot")
        self.assertEqual(result.returncode, 0, msg=result.stderr)

    def test_gh_api_method_post_comments_is_blocked(self):
        # FP-4 FN 修正: -X ではなく --method を使う形。
        result = _run("gh api --method POST repos/o/r/issues/1/comments -f body=x")
        self.assertEqual(result.returncode, 2, msg=result.stdout)

    def test_gh_api_post_pulls_comments_is_blocked(self):
        result = _run("gh api -X POST repos/o/r/pulls/1/comments -f body=x")
        self.assertEqual(result.returncode, 2, msg=result.stdout)

    def test_gh_api_graphql_add_comment_mutation_is_blocked(self):
        result = _run("gh api graphql -f query='mutation{addComment(input:{})}'")
        self.assertEqual(result.returncode, 2, msg=result.stdout)

    def test_gh_api_graphql_read_query_with_comments_is_allowed(self):
        # reviewThreads の comments を読む query。pi が PR コメント確認で毎回打ち、誤検知していた
        result = _run(
            "gh api graphql -f query='query($n:Int!){repository{pullRequest(number:$n)"
            "{reviewThreads{nodes{comments{nodes{body}}}}}}}' -F n=1"
        )
        self.assertEqual(result.returncode, 0, msg=result.stdout)

    def test_gh_api_graphql_mutation_with_spaces_is_blocked(self):
        result = _run("gh api graphql -f query='mutation { addPullRequestReviewComment(input:{}) }'")
        self.assertEqual(result.returncode, 2, msg=result.stdout)

    def test_xargs_wrapped_sh_dash_c_is_blocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "list").write_text("x\n", encoding="utf-8")
            result = _run(f"xargs -I{{}} sh -c 'git push' < {tmp}/list", cwd=tmp)
        self.assertEqual(result.returncode, 2, msg=result.stdout)


class GitNoVerifyTestCase(unittest.TestCase):
    """rule: git-no-verify（commit の --no-verify / -n、push の --no-verify を block）。"""

    def test_commit_with_long_flag_is_blocked(self):
        result = _run("git commit -m foo --no-verify")
        self.assertEqual(result.returncode, 2)
        self.assertIn("--no-verify", result.stderr)

    def test_commit_with_bare_short_flag_is_blocked(self):
        result = _run("git commit -n -m foo")
        self.assertEqual(result.returncode, 2)

    def test_commit_with_short_flag_bundled_with_others_is_blocked(self):
        result = _run("git commit -an -m foo")
        self.assertEqual(result.returncode, 2)

    def test_rtk_git_commit_with_no_verify_is_blocked(self):
        result = _run("rtk git commit -m foo --no-verify")
        self.assertEqual(result.returncode, 2)

    def test_commit_without_no_verify_is_allowed(self):
        result = _run("git commit -am foo")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), "")

    def test_commit_message_containing_letter_n_is_not_a_false_positive(self):
        # quote 内の空白は normalize で中和されるため、メッセージ本文の
        # 語（'n' を含む単語）を独立トークンとして誤検知しない。
        result = _run('git commit -m "fix normalizer bug in nine files"')
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), "")


class GitPushNoVerifyWithApprovalTestCase(unittest.TestCase):
    """承認済み push でも --no-verify は通さない（承認は「push すること」だけを許可する）。"""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self._env = dict(os.environ)
        self._env["HARNESS_RUNTIME"] = "claude"
        self._env["CODEX_REVIEW_FLAG_DIR"] = self._tmpdir.name

    def tearDown(self):
        self._tmpdir.cleanup()

    def _flag_path(self) -> str:
        result = subprocess.run(
            ["bash", "-c",
             "source packages/core/hooks/lib/review-gate.sh; push_approved_flag"],
            cwd=str(REPO_ROOT), capture_output=True, text=True,
            timeout=10, env=self._env, check=True,
        )
        return result.stdout.strip()

    def _approve(self):
        head = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=str(REPO_ROOT),
            capture_output=True, text=True, timeout=10, check=True,
        ).stdout.strip()
        Path(self._flag_path()).write_text(head + "\n")

    def test_approved_push_with_no_verify_to_feature_branch_is_still_blocked(self):
        self._approve()
        env = dict(self._env)
        env["TOOL_INPUT"] = json.dumps({"command": "git push origin feature-x --no-verify"})
        result = subprocess.run(
            ["bash", str(HOOK)], cwd=str(REPO_ROOT),
            capture_output=True, text=True, timeout=10, env=env,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("--no-verify", result.stderr)

    def test_approved_push_with_no_verify_does_not_consume_the_approval_flag(self):
        # git-no-verify は git-push より前に評価されなければならない。逆順だと
        # git-push が deny の前に承認フラグを消費してしまい、原因を直して
        # 再実行しても再承認が必要になる（2026-08 レビュー指摘）。
        self._approve()
        flag = Path(self._flag_path())
        self.assertTrue(flag.is_file())
        env = dict(self._env)
        env["TOOL_INPUT"] = json.dumps({"command": "git push origin feature-x --no-verify"})
        result = subprocess.run(
            ["bash", str(HOOK)], cwd=str(REPO_ROOT),
            capture_output=True, text=True, timeout=10, env=env,
        )
        self.assertEqual(result.returncode, 2)
        self.assertTrue(flag.is_file(), "承認フラグが --no-verify の deny で消費されてしまった")


class RtkInitGlobalTestCase(unittest.TestCase):
    """rule: rtk-init-global（~/.claude/RTK.md を上書きするため block）。"""

    def test_short_flag_is_blocked(self):
        result = _run("rtk init -g")
        self.assertEqual(result.returncode, 2)
        self.assertIn("RTK.md", result.stderr)

    def test_long_flag_is_blocked(self):
        result = _run("rtk init --global")
        self.assertEqual(result.returncode, 2)

    def test_global_flag_with_other_options_between_is_blocked(self):
        # init と -g/--global の間に他オプションが挟まっても検出する。
        result = _run("rtk init --agent claude --global")
        self.assertEqual(result.returncode, 2)

    def test_plain_init_is_allowed(self):
        result = _run("rtk init")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), "")


class CodexCompanionSandboxTestCase(unittest.TestCase):
    """rule: codex-companion-sandbox（sandbox 内実行を dangerouslyDisableSandbox なしで block）。"""

    def _run_with_flag(self, command: str, dangerously_disable_sandbox: bool = False):
        env = dict(os.environ)
        env["HARNESS_RUNTIME"] = "claude"
        env["TOOL_INPUT"] = json.dumps({
            "command": command,
            "dangerouslyDisableSandbox": dangerously_disable_sandbox,
        })
        return subprocess.run(
            ["bash", str(HOOK)], capture_output=True, text=True, timeout=10, env=env,
        )

    def test_companion_mjs_without_flag_is_blocked(self):
        result = self._run_with_flag("node codex-companion.mjs review")
        self.assertEqual(result.returncode, 2)

    def test_app_server_without_flag_is_blocked(self):
        result = self._run_with_flag("codex app-server --port 1234")
        self.assertEqual(result.returncode, 2)

    def test_companion_mjs_with_flag_is_allowed(self):
        result = self._run_with_flag("node codex-companion.mjs review", dangerously_disable_sandbox=True)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), "")

    def test_unrelated_command_is_allowed(self):
        result = _run("node other-script.mjs")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), "")

    def test_viewing_companion_mjs_with_rg_is_allowed(self):
        # substring マッチだと rg/cat の引数に現れるだけの codex-companion.mjs を
        # 誤検知していた。実行位置（node の後）でなければ block しない。
        result = _run("rg codex-companion.mjs")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), "")

    def test_viewing_companion_mjs_with_cat_is_allowed(self):
        result = _run("cat codex-companion.mjs")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), "")

    def test_app_server_with_global_option_between_is_blocked(self):
        # codex にグローバルオプション（--flag value）を挟んでも app-server の
        # 実行を見逃さない。
        result = self._run_with_flag("codex --profile p app-server")
        self.assertEqual(result.returncode, 2)

    def test_app_server_with_boolean_flag_between_is_blocked(self):
        result = self._run_with_flag("codex --json app-server")
        self.assertEqual(result.returncode, 2)


_EXTRAS_TABLE = (
    REPO_ROOT / "packages" / "extras" / "_active" / "policy" / "danger-rules.extra.json"
)


class HarnessRuntimeSelectionTestCase(unittest.TestCase):
    """HARNESS_RUNTIME による rule 選別（targets / 実効 action）の runtime 別挙動。"""

    def test_missing_harness_runtime_exits_2(self):
        env = dict(os.environ)
        env.pop("HARNESS_RUNTIME", None)
        env["TOOL_INPUT"] = json.dumps({"command": "git status"})
        result = subprocess.run(
            ["bash", str(HOOK)], capture_output=True, text=True, timeout=10, env=env,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("HARNESS_RUNTIME", result.stderr)

    def test_unknown_harness_runtime_exits_2(self):
        result = _run("git status", runtime="not-a-real-runtime")
        self.assertEqual(result.returncode, 2)
        self.assertIn("HARNESS_RUNTIME", result.stderr)

    def test_codex_allows_push(self):
        # codex は push 承認を native permissions / guardian_approval に委譲する
        # （danger-rules.json の git-push.absent.codex）。
        result = _run("git push -u origin feature", runtime="codex")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), "")

    def test_codex_blocks_commit_with_no_verify_long_flag(self):
        result = _run("git commit --no-verify -m x", runtime="codex")
        self.assertEqual(result.returncode, 2)

    def test_codex_blocks_commit_with_no_verify_short_flag(self):
        result = _run("git commit -n -m x", runtime="codex")
        self.assertEqual(result.returncode, 2)

    def test_codex_allows_git_rebase_because_it_is_outside_targets(self):
        result = _run("git rebase main", runtime="codex")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), "")

    def test_opencode_allows_codex_companion_sandbox_command(self):
        # codex-companion-sandbox の targets は claude のみなので opencode では
        # そもそも選別されず、dangerouslyDisableSandbox の有無に関わらず allow。
        result = _run("node codex-companion.mjs review", runtime="opencode")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), "")

    def test_pi_allows_codex_companion_sandbox_command(self):
        result = _run("node codex-companion.mjs review", runtime="pi")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), "")

    def test_opencode_allows_standalone_push_without_approval_flag(self):
        # git-push の opencode override action は confirm。hook は対話確認できず
        # ask は opencode 側の native 層が持つため、選別段階でスキップして allow する
        # （承認フラグが無くても hook 単体では block しない、従来 block だった意図的変更）。
        result = _run("git push origin feature", runtime="opencode")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), "")

    def test_opencode_blocks_git_rebase_because_override_block_beats_warn(self):
        # git-rebase の base action は warn だが、opencode override は block。
        # override が warn より強く効くのは意図的変更（overlay の deny と揃える）。
        result = _run("git rebase main", runtime="opencode")
        self.assertEqual(result.returncode, 2)

    def test_pi_blocks_commit_with_no_verify(self):
        # pi は base action（block）のまま、従来動作を維持する。
        result = _run("git commit --no-verify -m x", runtime="pi")
        self.assertEqual(result.returncode, 2)


class TestExtrasDangerRules(unittest.TestCase):
    """extras table（danger-rules.extra.json）の合流を配布後レイアウトの再現で検証する。

    in-repo では packages/core/policy/ に extras table が無いため、hooks/ と policy/ が
    兄弟になる配布後のレイアウトを temp dir に組み立てて hook を実行する。
    """

    def _deploy(self, extra_content: str | None) -> Path:
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        shutil.copytree(REPO_ROOT / "packages" / "core" / "hooks", tmp / "hooks")
        shutil.copytree(REPO_ROOT / "packages" / "core" / "policy", tmp / "policy")
        if extra_content is not None:
            (tmp / "policy" / "danger-rules.extra.json").write_text(
                extra_content, encoding="utf-8"
            )
        return tmp / "hooks" / "block-dangerous-in-bash.sh"

    def _run_deployed(self, hook: Path, command: str) -> subprocess.CompletedProcess:
        env = dict(os.environ)
        env["HARNESS_RUNTIME"] = "claude"
        env["TOOL_INPUT"] = json.dumps({"command": command})
        return subprocess.run(
            ["bash", str(hook)], capture_output=True, text=True, timeout=10, env=env,
        )

    _SYNTHETIC_EXTRA = json.dumps({
        "version": 1,
        "rules": [
            {
                "id": "extras-sample-block",
                "action": "block",
                "impl": "table",
                "targets": ["claude"],
                "message": "extras 由来のサンプル block ルール",
                "match": {
                    "ere": "frobnicate[[:space:]]+--nuke",
                    "origin": "none",
                    "wordEnd": True,
                },
            }
        ],
    })

    def test_extra_rule_is_enforced(self):
        hook = self._deploy(self._SYNTHETIC_EXTRA)
        result = self._run_deployed(hook, "pnpm frobnicate --nuke")
        self.assertEqual(result.returncode, 2, msg=result.stderr)
        self.assertIn("extras 由来", result.stderr)

    def test_core_rules_still_apply_with_extra_table(self):
        hook = self._deploy(self._SYNTHETIC_EXTRA)
        result = self._run_deployed(hook, "git push origin main")
        self.assertEqual(result.returncode, 2)

    def test_extra_block_wins_over_earlier_core_warn(self):
        # core の warn（git-rebase）で短絡すると末尾に合流した extras の block が
        # 素通りする（codex review P1 のバイパス経路）
        hook = self._deploy(self._SYNTHETIC_EXTRA)
        result = self._run_deployed(hook, "git rebase main && pnpm frobnicate --nuke")
        self.assertEqual(result.returncode, 2, msg=result.stdout)

    def test_absent_extra_table_is_fine(self):
        hook = self._deploy(None)
        result = self._run_deployed(hook, "pnpm frobnicate --nuke")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), "")

    def test_corrupt_extra_table_fails_closed(self):
        hook = self._deploy("{ this is not json")
        result = self._run_deployed(hook, "git status")
        self.assertEqual(result.returncode, 2)
        self.assertIn("extras 危険コマンドルール table", result.stderr)

    @unittest.skipUnless(_EXTRAS_TABLE.is_file(), "extras submodule 未取得（CI 等）")
    def test_real_extras_doc2notion_init_is_blocked(self):
        hook = self._deploy(_EXTRAS_TABLE.read_text(encoding="utf-8"))
        for command in (
            "doc2notion init",
            # pnpm / npx 経由は origin（セグメント先頭）に doc2notion が来ないため origin: none で拾う
            "pnpm doc2notion init --force",
            "npx doc2notion reset",
            "doc2notion --config .doc2notion.yml init",
        ):
            with self.subTest(command=command):
                result = self._run_deployed(hook, command)
                self.assertEqual(result.returncode, 2, msg=result.stderr)

    @unittest.skipUnless(_EXTRAS_TABLE.is_file(), "extras submodule 未取得（CI 等）")
    def test_real_extras_doc2notion_safe_commands_are_allowed(self):
        hook = self._deploy(_EXTRAS_TABLE.read_text(encoding="utf-8"))
        for command in (
            "pnpm doc2notion push --dry-run",
            "doc2notion pull",
            # wordEnd により initialize / initial-sync のような語は誤検知しない
            "doc2notion push --message initial-sync",
        ):
            with self.subTest(command=command):
                result = self._run_deployed(hook, command)
                self.assertEqual(result.returncode, 0, msg=result.stderr)
                self.assertEqual(result.stdout.strip(), "")


if __name__ == "__main__":
    unittest.main()
