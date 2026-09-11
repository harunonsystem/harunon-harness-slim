"""omp ターゲットのマニフェスト解決と AGENTS.md fragments 展開を検証する。"""
import json
import subprocess
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


class TestDistributeOmp(unittest.TestCase):
    def run_distribute(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(REPO_ROOT / "scripts" / "distribute.py"), "omp", *args],
            capture_output=True,
            text=True,
            timeout=60,
        )

    def test_omp_distributes_no_skills_of_its_own(self):
        """omp は ~/.agents/skills（shared-agents の配布先）も読むため、自 configDir に skill を置かない。

        shared-agents が全 skill を配布する（skill pack 廃止: 2026-08-19）ようになり、
        旧 include で配っていた 2 件も ~/.agents 経由で届く。自前配布が復活すると
        omp から同名 skill が二重に見える。
        """
        sys.path.insert(0, str(REPO_ROOT / "scripts"))
        from harness_lib.resolver import manifest

        files = manifest("omp", REPO_ROOT).files
        omp_skills = {p.split("/")[1] for p in files if p.startswith("skills/")}
        self.assertEqual(omp_skills, set())

    def test_disabled_skills_are_declared_as_ignored_in_config(self):
        """配布除外では隠せないので、disabled-skills.json から
        skills.ignoredSkills を計算して config.yml に載せる。

        期待値は core と extras の両方の宣言から組む。計算側は core | extras の
        union なので、core だけを期待値にすると extras を取得済みの環境
        （main checkout 等）でだけ落ちる環境依存テストになる。
        """
        sys.path.insert(0, str(REPO_ROOT / "scripts"))
        import tempfile

        import yaml
        from harness_lib import settings_sync
        from harness_lib.config import load_target

        cfg = load_target("omp", REPO_ROOT)
        # configFile 不在の live に compose すると、計算 overlay 込みの template が seed される
        with tempfile.TemporaryDirectory() as empty_live:
            composed = settings_sync.compose(cfg, REPO_ROOT, Path(empty_live))
        self.assertTrue(composed.seeded)
        ignored = yaml.safe_load(composed.text)["skills"]["ignoredSkills"]

        def read_json(path: Path) -> dict:
            """不在（extras 未取得）なら空 dict。resolver を呼ばず JSON を直接読み、
            計算側との同語反復を避ける。"""
            if not path.is_file():
                return {}
            return json.loads(path.read_text(encoding="utf-8"))

        # core は targets ゲート + common マージ、extras は {target: [...]} のフラット形式
        core = read_json(REPO_ROOT / "packages/core/disabled-skills.json")
        expected = set()
        if "omp" in set(core.get("targets", [])):
            expected |= set(core.get("common", [])) | set(core.get("omp", []))
        extras = read_json(REPO_ROOT / "packages/extras/_active/disabled-skills.json")
        expected |= set(extras.get("omp", []))
        self.assertEqual(set(ignored), expected)
        self.assertEqual(ignored, sorted(ignored))  # 決定的な並び

    def test_agents_md_sourced_from_omp_template(self):
        """omp の AGENTS.md は薄型テンプレート由来（core/CLAUDE.md ではない）。"""
        sys.path.insert(0, str(REPO_ROOT / "scripts"))
        from harness_lib.config import load_target

        cfg = load_target("omp", REPO_ROOT)
        entry = cfg["distribute"]["AGENTS.md"]
        self.assertEqual(entry["source"], "packages/targets/omp/AGENTS.md")
        self.assertTrue(entry.get("expandIncludes"))

    def test_agents_md_is_thin(self):
        """薄型化: 巨大な共通ルール全文・TDD 全文・文体全文が混入しないこと。"""
        sys.path.insert(0, str(REPO_ROOT / "scripts"))
        from harness_lib.resolver import manifest

        agents = manifest("omp", REPO_ROOT).files["AGENTS.md"].decode("utf-8")
        self.assertNotIn("正確さはスピードに優先", agents)  # core-standards 全文
        self.assertNotIn("Red: 失敗するテスト", agents)      # TDD 全文
        self.assertNotIn("空虚な強調", agents)              # 文体全文
        self.assertNotIn("Model Tiering", agents)
        # 共有 fragment が展開され、未展開の include マーカーが残らないこと
        self.assertNotIn("<!-- include:", agents)
        self.assertIn("## 常駐ルール（最小）", agents)
        self.assertIn("rules/core-standards.md", agents)
        self.assertIn("ユーザーの入力言語にかかわらず日本語で出力する", agents)
        self.assertIn("bash.patterns", agents)
        self.assertIn("harness-policy.js", agents)
        self.assertIn("tools.approvalMode=yolo", agents)
        self.assertIn("git push *", agents)
        self.assertIn("git commit *", agents)
        # 検証ループの本文は共有 fragment（loop-engineering.md）が担う。omp 固有の
        # 文言は「解除は SSOT を直して検証ループを再実行」だけ
        self.assertIn("run-tests.py -k <module>", agents)
        self.assertIn("validate-harness.py", agents)
        self.assertIn("distribute.py <target> --check", agents)
        self.assertIn("shellcheck -S warning", agents)
        self.assertIn("runtime bypass", agents)

    def test_denial_reason_extension_and_guard_hook_are_distributed_together(self):
        """omp-denial-reason.js は ../hook-runner/hook-runner.js 経由で
        ../claude-hooks/block-dangerous-in-bash.sh を呼び、hookRunner は ../policy/hook-pipeline.json、
        hook は ../policy/danger-rules.json と lib/ を読む。どれか 1 つ欠けると全 bash を
        block（required hook 欠落）するので、同じ manifest に揃っていること。"""
        sys.path.insert(0, str(REPO_ROOT / "scripts"))
        from harness_lib.resolver import manifest

        files = manifest("omp", REPO_ROOT).files
        for rel in (
            "extensions/omp-denial-reason.js",
            "hook-runner/hook-runner.js",
            "policy/hook-pipeline.json",
            "claude-hooks/block-dangerous-in-bash.sh",
            "claude-hooks/lib/command-normalize.sh",
            "claude-hooks/lib/review-gate.sh",
            "claude-hooks/approve-push.sh",
            "claude-hooks/approve-pr.sh",
            "policy/danger-rules.json",
        ):
            self.assertIn(rel, files)
        agents = files["AGENTS.md"].decode("utf-8")
        self.assertIn("omp-denial-reason.js", agents)
        self.assertIn("approve-push.sh", agents)

    def test_post_edit_checks_extension_and_shell_are_distributed(self):
        """L1 inner loop: omp extension とそれが呼ぶ runtime 中立 shell が隣接配置で配られる。"""
        sys.path.insert(0, str(REPO_ROOT / "scripts"))
        from harness_lib.resolver import manifest

        files = manifest("omp", REPO_ROOT).files
        for rel in (
            "extensions/post-edit-checks.js",
            "hook-runner/post-edit.js",
            "claude-hooks/post-edit-checks.sh",
            "claude-hooks/fix_gfm_tables.py",
        ):
            self.assertIn(rel, files)
        # pi 専用の adapter / 退役した双子は omp に配らない
        self.assertNotIn("extensions/claude-hooks-bridge.ts", files)
        self.assertNotIn("extensions/post-edit-checks.ts", files)

    def test_approval_mode_yolo_is_managed_by_settings_sync(self):
        cfg = json.loads((REPO_ROOT / "packages/targets/omp/config.json").read_text(encoding="utf-8"))
        self.assertIn("tools.approvalMode", cfg["settingsSync"]["keys"])
        self.assertIn("approvalMode: yolo", (REPO_ROOT / "packages/targets/omp/config.yml").read_text(encoding="utf-8"))

    def test_plan_does_not_start_on_every_omp_session(self):
        cfg = json.loads((REPO_ROOT / "packages/targets/omp/config.json").read_text(encoding="utf-8"))
        source = (REPO_ROOT / "packages/targets/omp/config.yml").read_text(encoding="utf-8")
        self.assertIn("plan.defaultOnStartup", cfg["settingsSync"]["keys"])
        self.assertIn("defaultOnStartup: false", source)

    def test_omp_projection_covers_rtk_bare_and_global_variants(self):
        sys.path.insert(0, str(REPO_ROOT / "scripts"))
        from harness_lib import danger_rules

        table = json.loads(
            (REPO_ROOT / "packages/core/policy/danger-rules.json").read_text(encoding="utf-8")
        )
        projected = danger_rules.permission_globs(table, "omp")
        for glob in projected:
            if glob.startswith("git "):
                with self.subTest(glob=glob):
                    self.assertIn("rtk " + glob, projected)
                    if glob.endswith(" *"):
                        self.assertIn(glob[:-2], projected)
        for command in ("install", "i", "add"):
            with self.subTest(command=command):
                self.assertIn(f"npm {command} --global *pi-coding-agent*", projected)

    def test_omp_owns_pi_destructive_rules_with_prompt_patterns(self):
        sys.path.insert(0, str(REPO_ROOT / "scripts"))
        from harness_lib import danger_rules

        table = json.loads(
            (REPO_ROOT / "packages/core/policy/danger-rules.json").read_text(encoding="utf-8")
        )
        expected = {
            "rm-recursive-force": (
                "rm -*r*f*", "rm -*f*r*", "rm -*R*f*", "rm -*f*R*",
                "sudo rm -*r*f*", "sudo rm -*f*r*", "sudo rm -*R*f*", "sudo rm -*f*R*",
            ),
            "sudo": ("sudo *",),
            "pipe-to-shell": (
                "*| sh*", "*|sh*", "*| bash*", "*|bash*",
                "*| zsh*", "*|zsh*", "*| dash*", "*|dash*",
            ),
            "dd-device-write": ("dd *of=/dev/*",),
            "mkfs": ("*mkfs*",),
            "sql-drop": (
                "*DROP TABLE*", "*DROP DATABASE*", "*drop table*", "*drop database*",
                "*Drop Table*", "*Drop Database*",
            ),
        }
        rules = {rule["id"]: rule for rule in table["rules"]}
        projected = danger_rules.permission_globs(table, "omp")
        for rule_id, patterns in expected.items():
            with self.subTest(rule=rule_id):
                self.assertIn("omp", rules[rule_id]["targets"])
                for pattern in patterns:
                    self.assertEqual(projected.get(pattern), "prompt")


if __name__ == "__main__":
    unittest.main()
