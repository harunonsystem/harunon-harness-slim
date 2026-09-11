#!/usr/bin/env python3
"""Codex レビューゲート hooks のフィクスチャテスト。

各 hook を subprocess として実行し、stdin から JSON を渡して
exit code / stdout / フラグファイルを検証する。

対象:
- block-pr-without-codex-review.sh （PR ゲート）
- block-repeated-codex-review.sh  （再レビューゲート）
- set-codex-review-flag.sh        （done + gate フラグ設定）
- codex-review-reminder.sh        （commit 後リマインダー）
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
HARNESSCTL = REPO_ROOT / "packages" / "core" / "policy" / "harnessctl.py"
PR_GATE_HOOK = HOOKS_DIR / "block-pr-without-codex-review.sh"
REPEAT_GATE_HOOK = HOOKS_DIR / "block-repeated-codex-review.sh"
SET_FLAG_HOOK = HOOKS_DIR / "set-codex-review-flag.sh"
REMINDER_HOOK = HOOKS_DIR / "codex-review-reminder.sh"
RESET_HOOK = HOOKS_DIR / "codex-review-reset.sh"


def _review_key(git_root: str, branch: str) -> str:
    """lib/review-gate.sh の KEY 算出（SHA-1 第 1 フィールド）を Python で再現する。

    printf '%s\\n%s\\n' "<git_root>" "<branch>" | shasum と等価。
    """
    data = f"{git_root}\n{branch}\n".encode()
    return hashlib.sha1(data).hexdigest()


def _run_hook(
    hook: Path,
    json_input: str,
    cwd: Optional[str] = None,
    args: Optional[list] = None,
    home: Optional[str] = None,
) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    if home is not None:
        env["HOME"] = home
    # denial-log.sh の配線テスト（test_denial_log.py）以外は実 ~/.claude/logs/ を
    # 汚染しないよう、deny 記録先を tmp に逃がす。
    env.setdefault(
        "HARNESS_DENIAL_LOG",
        str(Path(tempfile.gettempdir()) / "harness-test-review-gate-denial-log.jsonl"),
    )
    return subprocess.run(
        ["bash", str(hook), *(args or [])],
        input=json_input,
        capture_output=True,
        text=True,
        timeout=30,
        cwd=cwd,
        env=env,
    )


def _make_git_repo(parent: Path) -> Path:
    """空コミットを含む git リポジトリを作成して返す。"""
    repo = parent / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)
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
        ["git", "-C", str(repo), "commit", "--allow-empty", "-m", "init"],
        check=True,
        capture_output=True,
    )
    return repo


def _git_out(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def _gh_pr_create_input() -> str:
    return json.dumps({"tool_input": {"command": "gh pr create --title 'test'"}})


def _review_command_input(extra: str = "") -> str:
    """review コマンドの hook 入力。

    `--base` は付けない。付けると companion は dirty でも branch mode を選ぶため
    （lib/git.mjs resolveReviewTarget の第 1 分岐）、空対象ガードの判定が変わり、
    再レビューゲート等「flag の有無」を見たいテストの意図がぶれる。explicit base /
    scope の挙動は TestReviewEmptyTargetGate が専用に検証する。
    """
    command = "node codex-companion.mjs review"
    if extra:
        command = f"{command} {extra}"
    return json.dumps({"tool_input": {"command": command}})


class ReviewGateTestCase(unittest.TestCase):
    """git repo フィクスチャと branch 込み KEY のフラグパスを用意する基底クラス。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.repo = _make_git_repo(self.root)
        # git rev-parse --show-toplevel は realpath を返すことがある
        self.git_root = _git_out(self.repo, "rev-parse", "--show-toplevel")
        self.branch = _git_out(self.repo, "rev-parse", "--abbrev-ref", "HEAD")
        # フラグ名前空間を tempdir に隔離する（実 /tmp を汚染せず、TMPDIR が
        # /tmp 配下でも書き込める。CODEX_REVIEW_FLAG_DIR は review-gate.sh の注入点）。
        self.flag_dir = self.root / "flags"
        self.flag_dir.mkdir(exist_ok=True)
        self._prev_flag_dir = os.environ.get("CODEX_REVIEW_FLAG_DIR")
        os.environ["CODEX_REVIEW_FLAG_DIR"] = str(self.flag_dir)
        self._prev_reset_log = os.environ.get("CODEX_REVIEW_RESET_LOG")
        os.environ["CODEX_REVIEW_RESET_LOG"] = str(self.root / "reset.log")

    def tearDown(self):
        if self._prev_flag_dir is None:
            os.environ.pop("CODEX_REVIEW_FLAG_DIR", None)
        else:
            os.environ["CODEX_REVIEW_FLAG_DIR"] = self._prev_flag_dir
        if self._prev_reset_log is None:
            os.environ.pop("CODEX_REVIEW_RESET_LOG", None)
        else:
            os.environ["CODEX_REVIEW_RESET_LOG"] = self._prev_reset_log
        self._tmp.cleanup()

    def gate_flag(self, branch: Optional[str] = None) -> Path:
        key = _review_key(self.git_root, branch or self.branch)
        return self.flag_dir / f".codex-review-gate-{key}"

    def done_flag(self, branch: Optional[str] = None) -> Path:
        key = _review_key(self.git_root, branch or self.branch)
        return self.flag_dir / f".codex-review-done-{key}"


class TestBlockPrWithoutCodexReview(ReviewGateTestCase):
    def _install_fake_kernel(self, *, allowed: bool) -> Path:
        kernel = self.root / "fake-harnessctl.py"
        self.kernel_request_log = self.root / "kernel-request.json"
        kernel.write_text(
            """#!/usr/bin/env python3
import json
import sys
request = json.load(sys.stdin)
assert sys.argv[1] == "authorize"
assert request["action"] == "pr.create"
with open(%s, "w", encoding="utf-8") as f:
    json.dump(request, f)
allowed = %s
print(json.dumps({"allowed": allowed, "code": "TEST_DECISION"}))
raise SystemExit(0 if allowed else 2)
""" % (repr(str(self.kernel_request_log)), repr(allowed)),
            encoding="utf-8",
        )
        git_dir = Path(_git_out(self.repo, "rev-parse", "--absolute-git-dir"))
        (git_dir / "harness").mkdir()
        (git_dir / "harness" / "state.json").write_text("{}\n", encoding="utf-8")
        return kernel

    def test_gh_pr_create_without_flag_is_denied(self):
        """フラグ無しで gh pr create → permissionDecision: deny を含む JSON"""
        result = _run_hook(PR_GATE_HOOK, _gh_pr_create_input(), cwd=str(self.repo))
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("permissionDecision", result.stdout)
        self.assertIn("deny", result.stdout)

    def test_unreviewed_deny_tells_the_agent_to_rerun_the_same_command(self):
        """deny 理由が「同じコマンドを再実行」まで言う。

        cclens 実測で、ブロック後に --head / --repo を付け替えて通そうとする
        再試行が 22 セッションで起きていた。deny の事実だけを検証していると
        この案内が消えてもテストが通ってしまう。
        """
        result = _run_hook(PR_GATE_HOOK, _gh_pr_create_input(), cwd=str(self.repo))
        self.assertIn("同じコマンド", result.stdout)
        self.assertIn("--head", result.stdout)

    def test_stale_head_deny_does_not_instruct_an_unattended_re_review(self):
        """stale 側は独断での再レビューを促さない。

        rules/codex-review-policy.md は「レビューは 1 回まで・独断再実行禁止」
        と定めており、hook が再実行を指示するとポリシー違反を教えることになる。
        """
        self.gate_flag().write_text("0" * 40 + "\n")

        result = _run_hook(PR_GATE_HOOK, _gh_pr_create_input(), cwd=str(self.repo))
        self.assertIn("ユーザー", result.stdout)
        self.assertIn("独断", result.stdout)

    def test_gh_pr_create_with_valid_flag_is_allowed(self):
        """HEAD と一致するフラグがあれば exit 0 で出力なし"""
        head = _git_out(self.repo, "rev-parse", "HEAD")
        self.gate_flag().write_text(head + "\n")

        result = _run_hook(PR_GATE_HOOK, _gh_pr_create_input(), cwd=str(self.repo))
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertEqual(result.stdout.strip(), "", msg="allow 時は出力なし")

    def test_gh_pr_create_with_stale_head_is_denied(self):
        """フラグの HEAD が古い（レビュー後に commit）→ deny"""
        self.gate_flag().write_text("0" * 40 + "\n")

        result = _run_hook(PR_GATE_HOOK, _gh_pr_create_input(), cwd=str(self.repo))
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("deny", result.stdout)

    def test_non_pr_create_command_is_noop(self):
        """gh pr create 以外のコマンドは即 exit 0"""
        json_input = json.dumps({"tool_input": {"command": "git status"}})
        result = _run_hook(PR_GATE_HOOK, json_input, cwd=str(self.repo))
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertEqual(result.stdout.strip(), "", msg="noop 時は出力なし")

    def test_core_workflow_authorize_allows_without_legacy_flag(self):
        kernel = self._install_fake_kernel(allowed=True)
        previous = os.environ.get("HARNESS_POLICY_KERNEL")
        os.environ["HARNESS_POLICY_KERNEL"] = str(kernel)
        try:
            result = _run_hook(PR_GATE_HOOK, _gh_pr_create_input(), cwd=str(self.repo))
        finally:
            if previous is None:
                os.environ.pop("HARNESS_POLICY_KERNEL", None)
            else:
                os.environ["HARNESS_POLICY_KERNEL"] = previous
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertEqual(result.stdout.strip(), "")

    def test_core_workflow_authorize_denial_is_fail_closed(self):
        kernel = self._install_fake_kernel(allowed=False)
        previous = os.environ.get("HARNESS_POLICY_KERNEL")
        os.environ["HARNESS_POLICY_KERNEL"] = str(kernel)
        try:
            result = _run_hook(PR_GATE_HOOK, _gh_pr_create_input(), cwd=str(self.repo))
        finally:
            if previous is None:
                os.environ.pop("HARNESS_POLICY_KERNEL", None)
            else:
                os.environ["HARNESS_POLICY_KERNEL"] = previous
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("permissionDecision", result.stdout)
        self.assertIn("deny", result.stdout)
        self.assertIn("TEST_DECISION", result.stdout)

    def test_core_workflow_inactive_falls_through_to_legacy_gate(self):
        """complete 済み state（WORKFLOW_INACTIVE）は state 無しと同じ扱い: kernel では
        deny せず legacy の Codex レビュー gate で判定する。"""
        kernel = self.root / "fake-harnessctl.py"
        kernel.write_text(
            """#!/usr/bin/env python3
import json
print(json.dumps({"code": "WORKFLOW_INACTIVE", "phase": "complete", "revision": 9}))
raise SystemExit(2)
""",
            encoding="utf-8",
        )
        git_dir = Path(_git_out(self.repo, "rev-parse", "--absolute-git-dir"))
        (git_dir / "harness").mkdir()
        (git_dir / "harness" / "state.json").write_text("{}\n", encoding="utf-8")
        previous = os.environ.get("HARNESS_POLICY_KERNEL")
        os.environ["HARNESS_POLICY_KERNEL"] = str(kernel)
        try:
            result = _run_hook(PR_GATE_HOOK, _gh_pr_create_input(), cwd=str(self.repo))
        finally:
            if previous is None:
                os.environ.pop("HARNESS_POLICY_KERNEL", None)
            else:
                os.environ["HARNESS_POLICY_KERNEL"] = previous
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("deny", result.stdout)
        self.assertIn("Codexレビュー未実施", result.stdout)
        self.assertNotIn("Core Workflow", result.stdout)

    def test_core_workflow_kernel_receives_resolved_repo_and_command(self):
        """kernel 呼び出しはプロセス cwd 依存をやめ、解決済み repo と command を明示的に渡す。"""
        kernel = self._install_fake_kernel(allowed=True)
        previous = os.environ.get("HARNESS_POLICY_KERNEL")
        os.environ["HARNESS_POLICY_KERNEL"] = str(kernel)
        try:
            result = _run_hook(PR_GATE_HOOK, _gh_pr_create_input(), cwd=str(self.repo))
        finally:
            if previous is None:
                os.environ.pop("HARNESS_POLICY_KERNEL", None)
            else:
                os.environ["HARNESS_POLICY_KERNEL"] = previous
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        request = json.loads(self.kernel_request_log.read_text())
        self.assertEqual(request["repo"], self.git_root, msg="repo は解決後の toplevel であるべき")
        self.assertIn("pr create", request["command"], msg="command が payload に入っていない")

    def _checkout_feature_branch(self, name: str) -> None:
        subprocess.run(
            ["git", "-C", str(self.repo), "checkout", "-b", name],
            check=True,
            capture_output=True,
        )
        self.branch = name

    def _commit_file(self, rel_path: str, content: str, message: str) -> None:
        target = self.repo / rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        subprocess.run(["git", "-C", str(self.repo), "add", rel_path], check=True, capture_output=True)
        subprocess.run(
            ["git", "-C", str(self.repo), "commit", "-m", message],
            check=True,
            capture_output=True,
        )

    def test_docs_only_diff_is_auto_allowed_without_flag(self):
        """review-router: 全ファイルが docs/ 配下 → none route → legacy flag なしで allow"""
        self._checkout_feature_branch("feature/docs")
        self._commit_file("docs/plan.md", "# plan\n", "add plan doc")

        result = _run_hook(PR_GATE_HOOK, _gh_pr_create_input(), cwd=str(self.repo))
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertEqual(result.stdout.strip(), "", msg="none route は flag なしでも allow")
        self.assertFalse(self.gate_flag().exists(), msg="none route は gate flag を書かない")

    def test_lockfile_only_diff_is_auto_bypassed_and_logged(self):
        """review-router: 全ファイルが lockfile → bypass route → gate flag 自動設定 + ログ記録"""
        fake_home = self.root / "home"
        (fake_home / ".claude").mkdir(parents=True)
        self._checkout_feature_branch("feature/lockfile")
        self._commit_file("pnpm-lock.yaml", "lockfile\n", "bump lockfile")

        result = _run_hook(
            PR_GATE_HOOK, _gh_pr_create_input(), cwd=str(self.repo), home=str(fake_home)
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertEqual(result.stdout.strip(), "", msg="bypass route は allow で出力なし")

        head = _git_out(self.repo, "rev-parse", "HEAD")
        self.assertEqual(self.gate_flag().read_text().strip(), head, msg="gate flag に HEAD が書かれていない")

        log = fake_home / ".claude" / "codex-review-bypass.log"
        self.assertTrue(log.exists())
        self.assertIn("auto: bypass", log.read_text())

    def test_code_diff_on_feature_branch_still_requires_flag(self):
        """review-router: code diff → review route → 従来どおり legacy flag が必要"""
        self._checkout_feature_branch("feature/code")
        self._commit_file("src/foo.ts", "export const foo = 1;\n", "add foo")

        result = _run_hook(PR_GATE_HOOK, _gh_pr_create_input(), cwd=str(self.repo))
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("deny", result.stdout, msg="review route はflagなしでdenyのまま")


class TestGhTargetChecks(ReviewGateTestCase):
    """gh pr create の -R/--repo/GH_REPO= 検査（対象 repo と無関係な GitHub repo への
    PR 作成はレビュー証跡と対応付けられないため deny する）。"""

    def _run_gh(self, command: str) -> subprocess.CompletedProcess:
        json_input = json.dumps({"tool_input": {"command": command}})
        return _run_hook(PR_GATE_HOOK, json_input, cwd=str(self.repo))

    def test_dash_capital_r_owner_repo_is_denied(self):
        result = self._run_gh("gh pr create -R someone/other --fill")
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("deny", result.stdout)

    def test_repo_equals_owner_repo_is_denied(self):
        result = self._run_gh("gh pr create --repo=someone/other --fill")
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("deny", result.stdout)

    def test_gh_repo_env_prefix_is_denied(self):
        result = self._run_gh("GH_REPO=someone/other gh pr create --fill")
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("deny", result.stdout)

    def test_plain_pr_create_is_not_denied_by_gh_target_check(self):
        """-R/--repo/GH_REPO= を含まない通常呼び出しは、gh 検査自体では deny されない
        （legacy flag 未設定の別理由で deny されるのは既存挙動）。"""
        result = self._run_gh("gh pr create --fill")
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("Codexレビュー未実施", result.stdout)


class TestCrossRepoTargetResolution(unittest.TestCase):
    """cd で他 repo へ移動する CMD は、その repo の状態で判定する。

    サブディレクトリへの cd は同一 repo のままなので影響しない（回帰ガード）。
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / "a").mkdir()
        (self.root / "b").mkdir()
        self.repo_a = _make_git_repo(self.root / "a")
        self.repo_b = _make_git_repo(self.root / "b")
        self.flag_dir = self.root / "flags"
        self.flag_dir.mkdir()
        self._prev_flag_dir = os.environ.get("CODEX_REVIEW_FLAG_DIR")
        os.environ["CODEX_REVIEW_FLAG_DIR"] = str(self.flag_dir)

    def tearDown(self):
        if self._prev_flag_dir is None:
            os.environ.pop("CODEX_REVIEW_FLAG_DIR", None)
        else:
            os.environ["CODEX_REVIEW_FLAG_DIR"] = self._prev_flag_dir
        self._tmp.cleanup()

    def _gate_flag_for(self, repo: Path) -> Path:
        git_root = _git_out(repo, "rev-parse", "--show-toplevel")
        branch = _git_out(repo, "rev-parse", "--abbrev-ref", "HEAD")
        return self.flag_dir / f".codex-review-gate-{_review_key(git_root, branch)}"

    def test_cd_into_other_repo_is_judged_on_that_repo_state(self):
        """repo A の cwd から repo B に cd → 判定は repo B の状態（未レビューなら deny）。"""
        json_input = json.dumps(
            {"tool_input": {"command": f'cd "{self.repo_b}" && gh pr create --fill'}}
        )
        result = _run_hook(PR_GATE_HOOK, json_input, cwd=str(self.repo_a))
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("deny", result.stdout, msg="repo B は未レビューなので deny になるはず")

    def test_cd_into_subdirectory_of_same_repo_is_allowed(self):
        """repo A のサブディレクトリへの cd は同一 repo 扱いのまま allow される（回帰ガード）。"""
        subdir = self.repo_a / "packages"
        subdir.mkdir()
        head = _git_out(self.repo_a, "rev-parse", "HEAD")
        self._gate_flag_for(self.repo_a).write_text(head + "\n")

        json_input = json.dumps({"tool_input": {"command": f"cd {subdir} && gh pr create --fill"}})
        result = _run_hook(PR_GATE_HOOK, json_input, cwd=str(self.repo_a))
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertEqual(result.stdout.strip(), "", msg="同一 repo のサブディレクトリは allow のはず")


class TestRigorProfileOrderAfterResolve(unittest.TestCase):
    """P2: rigor profile は解決後の対象 repo で判定する。

    解決前の repo（casual）で判定すると、casual repo に cd するだけでレビュー
    ゲートごと消えてしまう（2026-07-26 に実測した不正な bypass 経路）。
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / "a").mkdir()
        (self.root / "b").mkdir()
        self.repo_a = _make_git_repo(self.root / "a")  # casual
        self.repo_b = _make_git_repo(self.root / "b")  # rigorous（デフォルト）
        self.patterns_file = self.root / "rigor-patterns.json"
        self.local_file = self.root / "rigor.local.json"

        git_root_a = _git_out(self.repo_a, "rev-parse", "--show-toplevel")
        self.patterns_file.write_text(
            json.dumps([{"pattern": git_root_a, "profile": "casual"}]), encoding="utf-8"
        )

    def tearDown(self):
        self._tmp.cleanup()

    def test_cd_from_casual_repo_to_rigorous_repo_still_denies(self):
        env = dict(os.environ)
        env["RIGOR_PATTERNS_FILE"] = str(self.patterns_file)
        env["RIGOR_LOCAL_FILE"] = str(self.local_file)
        env["CODEX_REVIEW_FLAG_DIR"] = str(self.root / "flags")
        # denial-log.sh の配線テスト以外は実 ~/.claude/logs/ を汚染しないよう、
        # deny 記録先を tmp に逃がす。
        env.setdefault("HARNESS_DENIAL_LOG", str(self.root / "denial-log.jsonl"))
        json_input = json.dumps(
            {"tool_input": {"command": f'cd "{self.repo_b}" && gh pr create --fill'}}
        )
        result = subprocess.run(
            ["bash", str(PR_GATE_HOOK)],
            input=json_input,
            capture_output=True,
            text=True,
            timeout=30,
            cwd=str(self.repo_a),
            env=env,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn(
            "deny",
            result.stdout,
            msg="repo A（casual）から cd した repo B（rigorous）では引き続き deny されるべき",
        )


class TestBlockRepeatedCodexReview(ReviewGateTestCase):
    def setUp(self):
        super().setUp()
        # 再レビューゲートの検証対象は「flag の有無」。空対象ガード
        # （codex_review_target_is_empty）に先に捕まらないよう、レビュー対象が
        # 存在する状態を作る。scope 未指定 + dirty なので companion は
        # working-tree mode を選び、対象ありと判定される。
        (self.repo / "work.txt").write_text("change\n", encoding="utf-8")

    def test_first_review_is_allowed(self):
        """done フラグ無し（初回）→ 出力なしで通す"""
        result = _run_hook(REPEAT_GATE_HOOK, _review_command_input(), cwd=str(self.repo))
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertEqual(result.stdout.strip(), "")

    def test_second_review_is_denied(self):
        """done フラグあり（2 回目）→ deny"""
        self.done_flag().write_text("2026-01-01T00:00:00Z\n")

        result = _run_hook(REPEAT_GATE_HOOK, _review_command_input(), cwd=str(self.repo))
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("deny", result.stdout)

    def test_other_branch_flag_does_not_block(self):
        """KEY は branch 込み: 別ブランチで実施済みのレビューは現ブランチをブロックしない"""
        self.done_flag().write_text("2026-01-01T00:00:00Z\n")
        subprocess.run(
            ["git", "-C", str(self.repo), "checkout", "-b", "feature/x"],
            check=True,
            capture_output=True,
        )
        self.branch = "feature/x"

        result = _run_hook(REPEAT_GATE_HOOK, _review_command_input(), cwd=str(self.repo))
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertEqual(result.stdout.strip(), "", msg="別ブランチはブロックしない")

    def test_stale_flag_after_branch_recreation_does_not_block(self):
        """同名ブランチを削除→再作成した新サイクルの初回は deny しない（stale flag は自動失効）"""
        base_branch = self.branch

        # 旧サイクル: feature/reused を作成しレビュー実施（flag に当時の HEAD を記録）
        subprocess.run(
            ["git", "-C", str(self.repo), "checkout", "-b", "feature/reused"],
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "-C", str(self.repo), "commit", "--allow-empty", "-m", "old cycle commit"],
            check=True,
            capture_output=True,
        )
        old_reviewed_head = _git_out(self.repo, "rev-parse", "HEAD")
        self.done_flag(branch="feature/reused").write_text(
            f"2026-01-01T00:00:00Z\n{old_reviewed_head}\n"
        )

        # ブランチ削除（旧サイクルの HEAD は main の系譜に含まれない）
        subprocess.run(
            ["git", "-C", str(self.repo), "checkout", base_branch],
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "-C", str(self.repo), "branch", "-D", "feature/reused"],
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "-C", str(self.repo), "commit", "--allow-empty", "-m", "unrelated work"],
            check=True,
            capture_output=True,
        )

        # 同名ブランチを再作成（新サイクル。旧 HEAD は新 HEAD の祖先ではない）
        subprocess.run(
            ["git", "-C", str(self.repo), "checkout", "-b", "feature/reused"],
            check=True,
            capture_output=True,
        )
        self.branch = "feature/reused"

        result = _run_hook(REPEAT_GATE_HOOK, _review_command_input(), cwd=str(self.repo))
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertEqual(
            result.stdout.strip(),
            "",
            msg="ブランチ再作成後の初回レビューは deny しない",
        )

    def test_flag_after_new_commit_on_same_branch_still_blocks(self):
        """レビュー後に同ブランチで commit を積んだだけ（再作成ではない）は依然 deny"""
        old_head = _git_out(self.repo, "rev-parse", "HEAD")
        self.done_flag().write_text(f"2026-01-01T00:00:00Z\n{old_head}\n")

        subprocess.run(
            ["git", "-C", str(self.repo), "commit", "--allow-empty", "-m", "fix after review"],
            check=True,
            capture_output=True,
        )

        result = _run_hook(REPEAT_GATE_HOOK, _review_command_input(), cwd=str(self.repo))
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("deny", result.stdout, msg="同一サイクルの追加コミットは依然 deny")

    def test_legacy_flag_format_without_head_still_blocks(self):
        """旧フォーマット（タイムスタンプのみ）flag は後方互換で deny"""
        self.done_flag().write_text("2026-01-01T00:00:00Z\n")

        result = _run_hook(REPEAT_GATE_HOOK, _review_command_input(), cwd=str(self.repo))
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("deny", result.stdout, msg="旧フォーマット flag は後方互換で deny")


class TestReviewEmptyTargetGate(ReviewGateTestCase):
    """レビュー対象が空のまま /codex:review を回すのを止めるガード。

    base 取り違え等で diff が空のままレビューを回すと、Codex は何も見ずに返り
    done フラグだけが立つ（= 未レビューのまま PR gate を通過できてしまう）。
    """

    def test_clean_tree_with_no_diff_is_denied(self):
        """作業ツリーがクリーンで base との diff も無い → deny"""
        result = _run_hook(REPEAT_GATE_HOOK, _review_command_input(), cwd=str(self.repo))
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("deny", result.stdout)
        self.assertIn("レビュー対象が空", result.stdout)

    def test_deny_reason_names_the_commands_to_check(self):
        """deny 理由が確認すべき実コマンドまで示す（「対象を確認しろ」で終わらせない）"""
        result = _run_hook(REPEAT_GATE_HOOK, _review_command_input(), cwd=str(self.repo))
        self.assertIn("git status --porcelain", result.stdout)
        self.assertIn("git diff", result.stdout)

    def test_uncommitted_change_is_allowed(self):
        """scope 未指定 + 未 commit の変更 → companion は working-tree mode → 通す"""
        (self.repo / "work.txt").write_text("change\n", encoding="utf-8")

        result = _run_hook(REPEAT_GATE_HOOK, _review_command_input(), cwd=str(self.repo))
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertEqual(result.stdout.strip(), "")

    def _commit_on_branch(self, branch: str) -> None:
        subprocess.run(
            ["git", "-C", str(self.repo), "checkout", "-b", branch],
            check=True,
            capture_output=True,
        )
        (self.repo / "work.txt").write_text("change\n", encoding="utf-8")
        subprocess.run(
            ["git", "-C", str(self.repo), "add", "work.txt"], check=True, capture_output=True
        )
        subprocess.run(
            ["git", "-C", str(self.repo), "commit", "-m", "work"], check=True, capture_output=True
        )

    def test_committed_diff_against_default_branch_is_allowed(self):
        """クリーンなツリー + デフォルトブランチとの差 → branch mode で対象あり → 通す"""
        self._commit_on_branch("feature/y")

        result = _run_hook(REPEAT_GATE_HOOK, _review_command_input(), cwd=str(self.repo))
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertEqual(result.stdout.strip(), "")

    def test_explicit_base_head_is_denied_even_with_branch_commits(self):
        """`--base HEAD` は explicit base として branch mode を選ばせ、diff は空になる。

        companion は `--base` があれば dirty かどうかに関係なく branch mode を選ぶ
        （lib/git.mjs resolveReviewTarget の第 1 分岐）。gate が CMD を無視して
        独自に base を決めていると、この空レビューが通ってフラグだけが立つ。
        """
        self._commit_on_branch("feature/base-head")
        (self.repo / "dirty.txt").write_text("dirty\n", encoding="utf-8")

        result = _run_hook(
            REPEAT_GATE_HOOK, _review_command_input("--base HEAD"), cwd=str(self.repo)
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("レビュー対象が空", result.stdout)

    def test_explicit_working_tree_scope_on_clean_tree_is_denied(self):
        """`--scope working-tree` + クリーンなツリー → branch に commit があっても空。"""
        self._commit_on_branch("feature/scope-wt")

        result = _run_hook(
            REPEAT_GATE_HOOK,
            _review_command_input("--scope working-tree"),
            cwd=str(self.repo),
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("レビュー対象が空", result.stdout)

    def test_flag_value_accepts_equals_form(self):
        """`--scope=working-tree` の = 形式も解析する（空白区切りだけ見て素通りしない）"""
        self._commit_on_branch("feature/scope-eq")

        result = _run_hook(
            REPEAT_GATE_HOOK,
            _review_command_input("--scope=working-tree"),
            cwd=str(self.repo),
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("レビュー対象が空", result.stdout)

    def _init_origin(self) -> None:
        origin = self.root / "origin.git"
        subprocess.run(
            ["git", "init", "--bare", str(origin)], check=True, capture_output=True
        )
        subprocess.run(
            ["git", "-C", str(self.repo), "remote", "add", "origin", str(origin)],
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "-C", str(self.repo), "push", "-u", "origin", self.branch],
            check=True,
            capture_output=True,
        )

    def _commit_unpushed(self) -> None:
        (self.repo / "work.txt").write_text("change\n", encoding="utf-8")
        subprocess.run(
            ["git", "-C", str(self.repo), "add", "work.txt"], check=True, capture_output=True
        )
        subprocess.run(
            ["git", "-C", str(self.repo), "commit", "-m", "unpushed"],
            check=True,
            capture_output=True,
        )

    def test_unpushed_commit_on_default_branch_is_denied(self):
        """origin/HEAD 不在時、companion は **ローカル** main を base に選ぶ。

        その場合 HEAD == main なので companion のレビュー対象は実際に空になる。
        gate が origin/main を優先すると「対象あり」と誤判定し、companion 側は
        何も見ないままフラグが立つ。gate は companion の解決順に従う。
        """
        self._init_origin()
        self._commit_unpushed()

        result = _run_hook(REPEAT_GATE_HOOK, _review_command_input(), cwd=str(self.repo))
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn(
            "レビュー対象が空",
            result.stdout,
            msg="companion がローカル main を base に選ぶ以上、対象は空",
        )

    def test_explicit_origin_base_on_default_branch_is_allowed(self):
        """未 push コミットを見せたいなら `--base origin/<default>` を渡す運用になる。"""
        self._init_origin()
        self._commit_unpushed()

        result = _run_hook(
            REPEAT_GATE_HOOK,
            _review_command_input(f"--base origin/{self.branch}"),
            cwd=str(self.repo),
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertEqual(result.stdout.strip(), "")


class TestSetCodexReviewFlag(ReviewGateTestCase):
    def test_review_command_sets_done_and_gate_flags(self):
        """レビューコマンド完了で done フラグと gate フラグ（HEAD）が立つ"""
        result = _run_hook(SET_FLAG_HOOK, _review_command_input(), cwd=str(self.repo))
        self.assertEqual(result.returncode, 0, msg=result.stderr)

        self.assertTrue(self.done_flag().exists(), msg="done フラグが無い")
        gate = self.gate_flag()
        self.assertTrue(gate.exists(), msg="gate フラグが無い")
        head = _git_out(self.repo, "rev-parse", "HEAD")
        self.assertEqual(gate.read_text().strip(), head, msg="gate フラグは HEAD を持つ")

    def test_companion_variable_review_command_sets_flags(self):
        """node \"$COMPANION\" review 形式でも flag が立つ"""
        json_input = json.dumps(
            {
                "tool_input": {
                    "command": 'COMPANION=/tmp/codex-companion.mjs && node "$COMPANION" review --base main'
                }
            }
        )
        result = _run_hook(SET_FLAG_HOOK, json_input, cwd=str(self.repo))
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertTrue(self.done_flag().exists(), msg="done フラグが無い")
        self.assertTrue(self.gate_flag().exists(), msg="gate フラグが無い")

    def test_non_review_command_is_noop(self):
        result = _run_hook(
            SET_FLAG_HOOK,
            json.dumps({"tool_input": {"command": "git status"}}),
            cwd=str(self.repo),
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertFalse(self.done_flag().exists())
        self.assertFalse(self.gate_flag().exists())

    def _failed_review_input(self, tool_response: dict) -> str:
        return json.dumps(
            {
                "tool_input": {"command": "node codex-companion.mjs review --base main"},
                "tool_response": tool_response,
            }
        )

    def test_failed_review_env_error_does_not_set_flags(self):
        """環境エラー（sqlite runtime 初期化失敗）では flag を立てず additionalContext を出す"""
        json_input = self._failed_review_input(
            {
                "stdout": "",
                "stderr": "Error: failed to initialize sqlite state runtime under /Users/x/.codex",
            }
        )
        result = _run_hook(SET_FLAG_HOOK, json_input, cwd=str(self.repo))
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertFalse(self.done_flag().exists(), msg="失敗時に done フラグが立った")
        self.assertFalse(self.gate_flag().exists(), msg="失敗時に gate フラグが立った")
        self.assertIn("additionalContext", result.stdout)
        self.assertIn("flag は立てていません", result.stdout)

    def test_failed_review_app_server_crash_does_not_set_flags(self):
        json_input = self._failed_review_input(
            {"stdout": "codex app-server exited unexpectedly (exit 1)", "stderr": ""}
        )
        result = _run_hook(SET_FLAG_HOOK, json_input, cwd=str(self.repo))
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertFalse(self.done_flag().exists())

    def test_failed_review_nonzero_exit_code_does_not_set_flags(self):
        json_input = self._failed_review_input(
            {"stdout": "some output", "stderr": "", "exitCode": 1}
        )
        result = _run_hook(SET_FLAG_HOOK, json_input, cwd=str(self.repo))
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertFalse(self.done_flag().exists())

    def test_interrupted_review_does_not_set_flags(self):
        json_input = self._failed_review_input(
            {"stdout": "", "stderr": "", "interrupted": True}
        )
        result = _run_hook(SET_FLAG_HOOK, json_input, cwd=str(self.repo))
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertFalse(self.done_flag().exists())

    def test_successful_review_with_tool_response_sets_flags(self):
        """正常出力 + exitCode 0 では従来どおり flag が立つ"""
        json_input = self._failed_review_input(
            {"stdout": "Review completed. 2 findings.", "stderr": "", "exitCode": 0}
        )
        result = _run_hook(SET_FLAG_HOOK, json_input, cwd=str(self.repo))
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertTrue(self.done_flag().exists(), msg="成功時に done フラグが立たない")
        self.assertTrue(self.gate_flag().exists())


class TestCodexReviewReset(ReviewGateTestCase):
    """codex-review-reset.sh — done flag を repo+branch KEY で正しく削除する。

    旧実装（repo のみの独自 shasum）は現行 KEY と不一致で空振りしていた。
    """

    def test_reset_removes_done_flag(self):
        self.done_flag().write_text("2026-07-10T00:00:00Z\nabc123\n")
        result = _run_hook(RESET_HOOK, "", cwd=str(self.repo), args=["再レビュー承認"])
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertFalse(self.done_flag().exists(), msg="done フラグが消えていない")
        self.assertIn("リセットしました", result.stdout)

    def test_reset_without_reason_fails(self):
        result = _run_hook(RESET_HOOK, "", cwd=str(self.repo), args=[])
        self.assertEqual(result.returncode, 1)

    def test_reset_without_flag_is_noop(self):
        result = _run_hook(RESET_HOOK, "", cwd=str(self.repo), args=["理由"])
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("存在しません", result.stdout)


class TestCodexReviewReminder(ReviewGateTestCase):
    def test_successful_commit_emits_additional_context(self):
        """commit 成功の stdout（tool_response）→ additionalContext でリマインド"""
        json_input = json.dumps(
            {
                "tool_input": {"command": "git commit -m 'x'"},
                "tool_response": {"stdout": " 1 file changed, 2 insertions(+)"},
            }
        )
        result = _run_hook(REMINDER_HOOK, json_input, cwd=str(self.repo))
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("additionalContext", result.stdout)
        self.assertIn("codex:review", result.stdout)

    def test_non_commit_command_is_noop(self):
        json_input = json.dumps(
            {
                "tool_input": {"command": "git status"},
                "tool_response": {"stdout": "On branch main"},
            }
        )
        result = _run_hook(REMINDER_HOOK, json_input, cwd=str(self.repo))
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertEqual(result.stdout.strip(), "")

    def test_failed_commit_is_noop(self):
        """commit 失敗（成功痕跡なし）→ リマインドしない"""
        json_input = json.dumps(
            {
                "tool_input": {"command": "git commit -m 'x'"},
                "tool_response": {"stdout": "nothing to commit"},
            }
        )
        result = _run_hook(REMINDER_HOOK, json_input, cwd=str(self.repo))
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertEqual(result.stdout.strip(), "")


if __name__ == "__main__":
    unittest.main()
