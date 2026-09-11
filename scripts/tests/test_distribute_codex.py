"""codex ターゲットのマニフェスト解決と AGENTS.md 薄型化を検証する。

Codex 常駐（AGENTS.md）は「最小ルール + 必要時参照のルーティング」だけを持ち、
共通ルール全文（core-standards / TDD 哲学全文 / 長い文体ルール）を常時ロードしない。
外した詳細は rules/ にファイルとして配布され、必要時に読める状態を保つ。
"""
import subprocess
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from harness_lib.resolver import manifest  # noqa: E402


class TestDistributeCodex(unittest.TestCase):
    def setUp(self):
        self.manifest = manifest("codex", REPO_ROOT)
        self.shared_agents_manifest = manifest("shared-agents", REPO_ROOT)
        self.agents_md = self.manifest.files["AGENTS.md"].decode("utf-8")

    def run_distribute(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            # PATH の python3 ではなくテストを走らせている interpreter を使う。
            # PATH 先頭が system python3（3.9）だと runtime.py の 3.11+ ガードで
            # 落ち、mise 経由で走らせても subprocess だけ失敗する。
            [sys.executable, str(REPO_ROOT / "scripts" / "distribute.py"), "codex", *args],
            capture_output=True,
            text=True,
            timeout=60,
        )

    def test_list_resolves_manifest(self):
        result = self.run_distribute("--list")
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        expected_paths = ["AGENTS.md", "rules/core-standards.md", "commands.md"]
        # RTK.md は public slim では SSOT から外れる（packages/public-slim/manifest.json）。
        # SSOT が持つときだけ配布を要求する
        if (REPO_ROOT / "packages/core/RTK.md").is_file():
            expected_paths.append("RTK.md")
        for expected in expected_paths:
            self.assertIn(expected, result.stdout)

    def test_agents_md_sourced_from_codex_template(self):
        """AGENTS.md の source は Codex 専用テンプレート（core/CLAUDE.md ではない）。"""
        from harness_lib.config import load_target

        cfg = load_target("codex", REPO_ROOT)
        entry = cfg["distribute"]["AGENTS.md"]
        self.assertEqual(entry["source"], "packages/targets/codex/AGENTS.md")

    def test_no_giant_core_standards_inlined(self):
        """巨大な共通ルール全文が AGENTS.md に混入しないこと。"""
        # rules/core-standards.md の代表フレーズ
        self.assertNotIn("正確さはスピードに優先", self.agents_md)
        # TDD 哲学全文（Red-Green-Refactor の逐条）
        self.assertNotIn("Red: 失敗するテスト", self.agents_md)
        # 長い文体ルールの逐条
        self.assertNotIn("空虚な強調", self.agents_md)
        self.assertNotIn("無情報の接続", self.agents_md)
        # Claude 固有節（本来 codex には不要）
        self.assertNotIn("Model Tiering", self.agents_md)
        self.assertNotIn("Startup Self-Check", self.agents_md)

    def test_minimal_residency_rules_present(self):
        """常駐に残すべき最小ルールが AGENTS.md に含まれること。"""
        # 質問にはまず答える / 明示的な変更依頼まで編集しない
        self.assertIn("まず答える", self.agents_md)
        self.assertIn("Edit/Write しない", self.agents_md)
        # copy-from-existing
        self.assertIn("copy-from-existing", self.agents_md)
        # 破壊的操作の確認
        self.assertIn("commit", self.agents_md)
        self.assertIn("push", self.agents_md)
        # ルーティングの存在
        self.assertIn("Routing", self.agents_md)
        self.assertIn("error connecting to api.github.com", self.agents_md)
        self.assertIn("明示的に PR 作成を依頼", self.agents_md)

    def test_routing_points_to_distributed_files(self):
        """ルーティング先が実際に codex に配布されるファイル/skill であること。"""
        self.assertIn("rules/core-standards.md", self.agents_md)
        self.assertIn("rules/review-policy.md", self.agents_md)
        # 参照先が manifest に実在（dangling でない）
        self.assertIn("rules/core-standards.md", self.manifest.files)
        self.assertIn("rules/review-policy.md", self.manifest.files)
        self.assertIn("rules/codex-review-policy.md", self.manifest.files)
        self.assertIn("skills/grill-implementation/SKILL.md", self.shared_agents_manifest.files)
        self.assertIn("skills/codex-reset-credits/SKILL.md", self.manifest.files)
        self.assertIn("skills/run-change/SKILL.md", self.shared_agents_manifest.files)

    def test_disabled_skills_excluded_from_manifest(self):
        """Claude 専用・MCP 依存 skill（disabled-skills.json の common）は ~/.agents に配布しない。

        skill pack 廃止（2026-08-19）後、除外は互換性理由の disabled-skills.json のみ。
        それ以外の core skill は全件 ~/.agents 経由で codex から見える。
        """
        for excluded in [
            "skills/figma-implement/",
            "skills/efficient-fable/",
            "skills/sentry-fix/",
        ]:
            self.assertFalse(
                any(k.startswith(excluded) for k in self.shared_agents_manifest.files),
                msg=f"{excluded} は disabledSkills のはず",
            )
        self.assertIn("skills/frontend-verify/SKILL.md", self.shared_agents_manifest.files)
        # opencli-usage は外部 skill（upstream 正本。ADR-011）に移したので SSOT 配布には出てこない
        self.assertIn("skills/similarity-check/SKILL.md", self.shared_agents_manifest.files)

    def test_custom_subagents_distributed(self):
        """カスタムサブエージェント TOML（explorer/worker/reviewer）が manifest に含まれること。"""
        for expected in [
            "agents/explorer.toml",
            "agents/worker.toml",
            "agents/reviewer.toml",
        ]:
            self.assertIn(expected, self.manifest.files)

    def test_subagents_have_cost_aware_explicit_models(self):
        expected = {
            "agents/explorer.toml": ('model = "gpt-5.6-luna"', 'model_reasoning_effort = "max"'),
            "agents/worker.toml": ('model = "gpt-5.6-luna"', 'model_reasoning_effort = "max"'),
            "agents/reviewer.toml": ('model = "gpt-5.6-sol"', 'model_reasoning_effort = "medium"'),
        }
        for path, fragments in expected.items():
            body = self.manifest.files[path].decode("utf-8")
            for fragment in fragments:
                self.assertIn(fragment, body, msg=f"{path}: {fragment}")

    def test_rtk_rewrite_hook_is_enabled_for_codex(self):
        self.assertNotIn("hooks.json", self.manifest.files)
        self.assertFalse(any(path.startswith("hooks/") for path in self.manifest.files))
        # dispatcher は hook 名を持たず hook-pipeline.json から導出するため、
        # 配線されているかは table 側で確認する
        sys.path.insert(0, str(REPO_ROOT / "scripts"))
        from harness_lib.hook_pipeline import load, pipeline

        self.assertIn("rtk-rewrite.sh", pipeline(load(REPO_ROOT), "codex"))
        self.assertNotIn("updatedInput rewrite が未対応", self.agents_md)

    def test_legacy_codex_hooks_are_declared_for_removal(self):
        from harness_lib.config import load_target

        obsolete = load_target("codex", REPO_ROOT).get("obsoleteFiles", [])
        self.assertIn("hooks.json", obsolete)
        self.assertIn("hooks/block-pr-without-codex-review.sh", obsolete)
        self.assertIn("hooks/block-repeated-codex-review.sh", obsolete)

    def test_run_change_is_owned_by_the_codex_plugin_only(self):
        self.assertFalse(
            any(path.startswith("skills/run-change/") for path in self.manifest.files)
        )
        from harness_lib.resolver import manifest
        self.assertIn("skills/run-change/SKILL.md", manifest("shared-agents", REPO_ROOT).files)

    def test_codex_features_only_declare_non_default_flags(self):
        """[features] に書くのは codex の default off を明示的に有効化したものだけ。

        codex-cli 0.153.4 の `codex features list` を空の CODEX_HOME で実測:
        - hooks / guardian_approval / multi_agent / goals は stable かつ default true
        - network_proxy / chronicle は default false
        - terminal_resize_reflow / js_repl は stage removed
        いずれも書いても実効値が変わらないので SSOT に残さない。

        multi_agent_v2 だけは table のまま残す。bool にすると codex 既定の
        tool_namespace = "collaboration" / hide_spawn_agent_metadata = true に戻り、
        この target が明示している値が失われる。

        context_management も table で持つ。bool true と同義だが、公式が案内している
        表記に合わせる（このスキーマは experimental_mode だけを受け付け、enabled は拒否する）。
        """
        import tomllib

        raw = self.manifest.files["config.toml"].decode("utf-8") if "config.toml" in self.manifest.files else (
            REPO_ROOT / "packages/targets/codex/config.toml"
        ).read_text(encoding="utf-8")
        features = tomllib.loads(raw)["features"]

        self.assertEqual(
            {
                "memories": True,
                "context_management": {"experimental_mode": True},
                "multi_agent_v2": {
                    "enabled": True,
                    "hide_spawn_agent_metadata": False,
                    "tool_namespace": "agents",
                    "usage_hint_enabled": True,
                },
            },
            features,
        )
        # enabled が無い table は bool として解釈され、config 読み込み自体が失敗する。
        self.assertTrue(features["multi_agent_v2"]["enabled"])
        self.assertIn("[agents]", raw)

    def test_codex_settings_sync_retires_the_dropped_feature_flags(self):
        """SSOT から外したフラグは live にも残さない。

        keys / removeKeys の features.* は feature table（declare フラグ）からの導出で、
        config.json には列挙しない。ここでは導出後の実効値を見る。
        """
        from harness_lib.config import load_target
        from harness_lib.settings_sync import _computed_feature_keys

        cfg = load_target("codex", REPO_ROOT)
        declared, retired = _computed_feature_keys(cfg, REPO_ROOT)
        for key in (
            "features.hooks",
            "features.guardian_approval",
            "features.multi_agent",
            "features.network_proxy",
            "features.terminal_resize_reflow",
            "features.goals",
            "features.js_repl",
            "features.chronicle",
            "features.voice_transcription",
        ):
            self.assertNotIn(key, declared, msg=key)
            self.assertIn(key, retired, msg=key)
        for key in ("features.memories", "features.multi_agent_v2", "features.context_management"):
            self.assertIn(key, declared, msg=key)
            self.assertNotIn(key, cfg["settingsSync"]["keys"], msg=key)


    def test_enabled_skill_bodies_do_not_use_claude_interactive_tool_names(self):
        forbidden = ("AskUserQuestion", "EnterPlanMode", "Task(", "TaskCreate", "TaskUpdate")
        for path, content in self.shared_agents_manifest.files.items():
            if not path.startswith("skills/") or not path.endswith("SKILL.md"):
                continue
            body = content.decode("utf-8")
            for token in forbidden:
                self.assertNotIn(token, body, msg=f"{path}: {token}")

    def test_no_dangling_headroom_reference(self):
        """HEADROOM.md は codex に配布しないので @参照を残さないこと。"""
        self.assertNotIn("HEADROOM.md", self.agents_md)
        self.assertNotIn("HEADROOM.md", self.manifest.files)

    def test_agents_md_is_thinner_than_shared_source(self):
        """薄型 AGENTS.md は共通 source（core/CLAUDE.md）より十分小さいこと。"""
        shared = (REPO_ROOT / "packages/core/CLAUDE.md").read_text(encoding="utf-8")
        self.assertLess(len(self.agents_md), len(shared) * 0.6)


if __name__ == "__main__":
    unittest.main()
