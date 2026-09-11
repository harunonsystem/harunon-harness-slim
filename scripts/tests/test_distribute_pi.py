"""pi ターゲットのマニフェスト解決と AGENTS.md 薄型化を検証する。"""
import json
import subprocess
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


class TestDistributePi(unittest.TestCase):
    def run_distribute(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(REPO_ROOT / "scripts" / "distribute.py"), "pi", *args],
            capture_output=True,
            text=True,
            timeout=60,
        )

    def test_list_resolves_manifest(self):
        result = self.run_distribute("--list")
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        for expected in [
            "AGENTS.md",
            "extensions/harness-fff-mode.js",
            "extensions/claude-hooks-bridge.ts",
            "extensions/post-edit-checks.js",
            "hook-runner/hook-runner.js",
            "hook-runner/post-edit.js",
            "claude-hooks/post-edit-checks.sh",
            "claude-hooks/fix_gfm_tables.py",
            "claude-hooks/rtk-rewrite.sh",
            "agents/scout.md",
            "agents/planner.md",
            "agents/worker.md",
            "agents/reviewer.md",
            "pi-codex-conversion.json",
            "web-search.json",
        ]:
            self.assertIn(expected, result.stdout)

    def test_pi_clarify_package_is_pinned_in_ssot(self):
        settings = json.loads(
            (REPO_ROOT / "packages" / "targets" / "pi" / "settings.json").read_text(
                encoding="utf-8"
            )
        )
        package = "npm:pi-clarify@1.0.1"
        self.assertEqual(settings["packages"].count(package), 1)

    def test_core_workflow_kernel_distributed(self):
        """Core Workflow kernel（policy / workflows / native gate）が配布されること。

        run-change skill は shared-agents ターゲット（~/.agents）経由で届く
        （test_distribute_shared_agents.py が担保）。
        """
        result = self.run_distribute("--list")
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        for expected in [
            "policy/harnessctl.py",
            "workflows/change.json",
            "extensions/harness-policy.js",
        ]:
            self.assertIn(expected, result.stdout)

    def test_omp_keybindings_are_not_distributed_to_pi(self):
        """keybindings.yml は omp 用（pi は keybindings.json しか読まない）。配布せず、live の stale copy は obsoleteFiles で掃除する。"""
        result = self.run_distribute("--list")
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertNotIn("keybindings.yml", result.stdout)

        sys.path.insert(0, str(REPO_ROOT / "scripts"))
        from harness_lib.config import load_target

        config = load_target("pi", REPO_ROOT)
        self.assertNotIn("keybindings.yml", config["distribute"])
        self.assertIn("keybindings.yml", config["obsoleteFiles"])

    def test_retired_hook_bridge_files_are_pruned_not_distributed(self):
        """hookRunner 化（2026-09-03）で退役した 3 件は配らず、live の stale copy を obsoleteFiles で掃除する。

        - hooks.json: pi 側の hook 一覧。hookRunner が policy/hook-pipeline.json を実行時に読む
        - extensions/omp-denial-reason.js: omp 専用 adapter。pi-extensions/ に置かれていた間は
          pi の extensions/ にも配られ、bash ごとに guard が二重実行されていた
        - extensions/post-edit-checks.ts: post-edit-checks.sh と同じ 3 判定を再実装していた双子
        """
        result = self.run_distribute("--list")
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        sys.path.insert(0, str(REPO_ROOT / "scripts"))
        from harness_lib.config import load_target

        config = load_target("pi", REPO_ROOT)
        for retired in (
            "hooks.json",
            "extensions/omp-denial-reason.js",
            "extensions/post-edit-checks.ts",
        ):
            with self.subTest(retired=retired):
                self.assertNotIn(retired, result.stdout)
                self.assertIn(retired, config["obsoleteFiles"])

    def test_codex_review_hooks_excluded_from_pi_manifest(self):
        """ADR-009 rigor profile 軸3（pi routing trim）: codex-review 系は pi の配線
        （当時は hooks.json、今は hook-pipeline.json の runtimes）から外し、config.json の
        配布 entry も同時に削除した。

        旧アサーション（review gate 系が配布に含まれること）は PR #14 時点の決定を
        encode したものだったが、ADR-009 がこれを明示的に覆したため反転させる。
        併せて、配線が無いのに配布だけされていた取りこぼし（block-commit-without-difit /
        set-difit-flag / pr-desc-sync-check と、それらが依存する lib/review-router）も
        「配布は配線済みファイル単位に限定」方針に沿って削除した。

        enforce-gwm-for-worktree.sh は当初 ADR-009 の routing trim 対象だったが、
        2026-08-14 に pi の apply_patch が block-edit-on-main をすり抜けたインシデント
        対応で pi の Bash matcher に配線し直した。ADR-009 は「rigor_profile 判定が
        hook 本体に実装されるまでの暫定措置として pi から外す」と明記しており
        （本文 46 行目）、block-edit-on-main.sh と同様に enforce-gwm-for-worktree.sh
        も既に `rigor_profile` 自己判定（casual なら即 exit 0）を実装済みのため、
        暫定措置を維持する理由がない。pi 側は guard 4本（block-grep-in-bash /
        block-dangerous-in-bash / enforce-gwm-for-worktree / rtk-rewrite）
        + block-edit-on-main + lib/rigor-profile.sh を配布する。

        例外: lib/review-gate.sh は配布する。block-dangerous-in-bash.sh が push 承認
        ゲート（C-002。2026-07-26 の 442e415 以降）で push_approved_flag /
        review_gate_resolve_target_repo を fail-closed に hard-require しており、
        これが欠けると pi の Bash が全コマンドブロックになる（2026-08-01 実測）。
        codex-review 系 hook 本体（block-pr-without-codex-review 等）は依然として
        配線・配布しない。lib/review-router.sh はどの配布 hook からも参照されないため
        引き続き除外する。
        """
        result = self.run_distribute("--list")
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        for excluded in [
            "claude-hooks/block-repeated-codex-review.sh",
            "claude-hooks/block-pr-without-codex-review.sh",
            "claude-hooks/set-codex-review-flag.sh",
            "claude-hooks/codex-review-reminder.sh",
            "claude-hooks/block-commit-without-difit.sh",
            "claude-hooks/set-difit-flag.sh",
            "claude-hooks/pr-desc-sync-check.sh",
            "claude-hooks/lib/review-router.sh",
        ]:
            self.assertNotIn(excluded, result.stdout)
        for expected in [
            "claude-hooks/block-grep-in-bash.sh",
            "claude-hooks/approve-push.sh",
            "claude-hooks/approve-pr.sh",
            "claude-hooks/block-dangerous-in-bash.sh",
            "claude-hooks/enforce-gwm-for-worktree.sh",
            "claude-hooks/rtk-rewrite.sh",
            "claude-hooks/block-edit-on-main.sh",
            "claude-hooks/lib/rigor-profile.sh",
            "claude-hooks/lib/review-gate.sh",
        ]:
            self.assertIn(expected, result.stdout)

    def test_no_skills_in_manifest(self):
        """skills は pi に直接配布しない（~/.agents/skills を pi がネイティブスキャンするため、
        二重配布すると起動時に collision 警告が出る。配布は shared-agents ターゲットに一本化）。"""
        result = self.run_distribute("--list")
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertNotIn("skills/", result.stdout)

    def test_claude_specific_docs_not_distributed(self):
        result = self.run_distribute("--list")
        self.assertNotIn("HEADROOM.md", result.stdout)

    def test_agents_md_sourced_from_pi_template(self):
        """pi の AGENTS.md は薄型テンプレート由来（core/CLAUDE.md ではない）。"""
        sys.path.insert(0, str(REPO_ROOT / "scripts"))
        from harness_lib.config import load_target

        cfg = load_target("pi", REPO_ROOT)
        entry = cfg["distribute"]["AGENTS.md"]
        self.assertEqual(entry["source"], "packages/targets/pi/AGENTS.md")
        self.assertTrue(entry.get("expandIncludes"))

    def test_agents_md_is_thin(self):
        """薄型化: 巨大な共通ルール全文・TDD 全文・文体全文が混入しないこと。"""
        sys.path.insert(0, str(REPO_ROOT / "scripts"))
        from harness_lib.resolver import manifest

        agents = manifest("pi", REPO_ROOT).files["AGENTS.md"].decode("utf-8")
        self.assertNotIn("正確さはスピードに優先", agents)  # core-standards 全文
        self.assertNotIn("Red: 失敗するテスト", agents)      # TDD 全文
        self.assertNotIn("空虚な強調", agents)              # 文体全文
        self.assertNotIn("Model Tiering", agents)
        # 共有 fragment が展開され、未展開の include マーカーが残らないこと
        self.assertNotIn("<!-- include:", agents)
        self.assertIn("## 常駐ルール（最小）", agents)
        self.assertIn("rules/core-standards.md", agents)


    def test_pi_tool_display_leaves_fff_owned_builtin_names_alone(self):
        """PI_FFF_MODE=override で FFF が所有する built-in 名を再登録しない。"""
        config = json.loads(
            (REPO_ROOT / "packages/targets/pi/pi-tool-display.json").read_text(
                encoding="utf-8"
            )
        )

        self.assertFalse(config["registerToolOverrides"]["grep"])
        self.assertFalse(config["registerToolOverrides"]["find"])

    def test_pi_fff_default_mode_extension_sets_portable_default(self):
        extension = (
            REPO_ROOT
            / "packages"
            / "targets"
            / "pi"
            / "pi-extensions"
            / "harness-fff-mode.js"
        ).read_text(encoding="utf-8")
        self.assertIn('process.env.PI_FFF_MODE ??= "override";', extension)

if __name__ == "__main__":
    unittest.main()
