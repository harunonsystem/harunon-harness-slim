#!/usr/bin/env python3
"""distribute.py の disabledPlugins / settingsSync 拡張テスト。"""
from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from tests._helpers import make_repo, run_distribute_cli  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


class DisabledPluginsTestCase(unittest.TestCase):
    """disabledPlugins が plugins/ ファイルの copy / check / pull をスキップするか検証する。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = make_repo(Path(self._tmp.name))

    def tearDown(self):
        self._tmp.cleanup()

    def _write_opencode_config(self, disabled: list) -> None:
        """opencode config.json に plugins/ 配布 + disabledPlugins を追加する。"""
        cfg_path = self.repo / "packages" / "targets" / "opencode" / "config.json"
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))

        # ダミープラグインファイルを core に配置
        plugins_dir = self.repo / "packages" / "core" / "opencode-plugins"
        plugins_dir.mkdir(parents=True, exist_ok=True)
        (plugins_dir / "plugin-a.js").write_text("// plugin a\n", encoding="utf-8")
        (plugins_dir / "plugin-b.js").write_text("// plugin b\n", encoding="utf-8")

        # distribute に plugins/ を追加
        cfg["distribute"]["plugins/"] = {
            "source": "packages/core/opencode-plugins/",
        }
        cfg["disabledPlugins"] = disabled

        cfg_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")

    def test_disabled_plugin_not_copied(self):
        """disabledPlugins に含まれるプラグインは push されない。"""
        self._write_opencode_config(disabled=["plugin-b"])
        live_dir = Path(self.repo / "live" / "opencode")
        live_dir.mkdir(parents=True, exist_ok=True)

        exit_code, output = run_distribute_cli([
            "opencode", "--push", "--live", str(live_dir), "--repo-root", str(self.repo),
        ])
        self.assertEqual(exit_code, 0, msg=output)

        # plugin-a は配布される
        self.assertTrue((live_dir / "plugins" / "plugin-a.js").exists())
        # plugin-b はスキップされる
        self.assertFalse((live_dir / "plugins" / "plugin-b.js").exists())

    def test_enabled_plugin_not_affected(self):
        """disabledPlugins が空なら全プラグインが配布される。"""
        self._write_opencode_config(disabled=[])
        live_dir = Path(self.repo / "live" / "opencode")
        live_dir.mkdir(parents=True, exist_ok=True)

        exit_code, output = run_distribute_cli([
            "opencode", "--push", "--live", str(live_dir), "--repo-root", str(self.repo),
        ])
        self.assertEqual(exit_code, 0, msg=output)

        self.assertTrue((live_dir / "plugins" / "plugin-a.js").exists())
        self.assertTrue((live_dir / "plugins" / "plugin-b.js").exists())

    def test_push_removes_only_declared_obsolete_files(self):
        self._write_opencode_config(disabled=[])
        cfg_path = self.repo / "packages" / "targets" / "opencode" / "config.json"
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        cfg["obsoleteFiles"] = ["plugins/legacy.js"]
        cfg_path.write_text(json.dumps(cfg), encoding="utf-8")
        live_dir = self.repo / "live" / "opencode"
        plugins = live_dir / "plugins"
        plugins.mkdir(parents=True)
        (plugins / "legacy.js").write_text("legacy\n", encoding="utf-8")
        (plugins / "user-plugin.js").write_text("user\n", encoding="utf-8")

        exit_code, output = run_distribute_cli([
            "opencode", "--push", "--live", str(live_dir), "--repo-root", str(self.repo),
        ])

        self.assertEqual(exit_code, 0, msg=output)
        self.assertFalse((plugins / "legacy.js").exists())
        self.assertTrue((plugins / "user-plugin.js").exists())
        self.assertTrue(any((live_dir / "backups").rglob("legacy.js")))

    def test_check_reports_declared_obsolete_file(self):
        self._write_opencode_config(disabled=[])
        cfg_path = self.repo / "packages" / "targets" / "opencode" / "config.json"
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        cfg["obsoleteFiles"] = ["plugins/legacy.js"]
        cfg_path.write_text(json.dumps(cfg), encoding="utf-8")
        live_dir = self.repo / "live" / "opencode"
        run_distribute_cli([
            "opencode", "--push", "--live", str(live_dir), "--repo-root", str(self.repo),
        ])
        (live_dir / "plugins" / "legacy.js").write_text("legacy\n", encoding="utf-8")

        exit_code, output = run_distribute_cli([
            "opencode", "--check", "--live", str(live_dir), "--repo-root", str(self.repo),
        ])

        self.assertEqual(exit_code, 1)
        self.assertIn("[obsolete] plugins/legacy.js", output)

    def test_check_excludes_disabled_plugins(self):
        """disabledPlugins に含まれるプラグインの drift は check で無視される。"""
        self._write_opencode_config(disabled=["plugin-b"])
        live_dir = Path(self.repo / "live" / "opencode")
        live_dir.mkdir(parents=True, exist_ok=True)

        # plugin-a のみ配布（plugin-b は disabled）
        run_distribute_cli([
            "opencode", "--push", "--live", str(live_dir), "--repo-root", str(self.repo),
        ])

        # plugin-a を削除（drift に見える状態にする）
        (live_dir / "plugins" / "plugin-a.js").unlink()

        exit_code, output = run_distribute_cli([
            "opencode", "--check", "--live", str(live_dir), "--repo-root", str(self.repo),
        ])

        # plugin-a の drift は検出される
        self.assertEqual(exit_code, 1, msg=output)
        self.assertIn("plugin-a.js", output)
        # plugin-b は drift に含まれない（未配布 + disabled）
        self.assertNotIn("plugin-b.js", output)

    def test_disabled_plugin_pruned_by_push_prune(self):
        """一度配布済みのプラグインを disabledPlugins に追加すると --prune で削除される。

        manifest() が disabledPlugins を反映していない現状は、
        _prune_stale_files() が「manifest 内 = 管理対象」として保護してしまい、
        無効化後も live 側に残り続ける（Plan 006 の再現ケース）。
        """
        self._write_opencode_config(disabled=[])
        live_dir = Path(self.repo / "live" / "opencode")
        live_dir.mkdir(parents=True, exist_ok=True)

        # まず両方とも有効な状態で配布
        exit_code, output = run_distribute_cli([
            "opencode", "--push", "--live", str(live_dir), "--repo-root", str(self.repo),
        ])
        self.assertEqual(exit_code, 0, msg=output)
        self.assertTrue((live_dir / "plugins" / "plugin-a.js").exists())
        self.assertTrue((live_dir / "plugins" / "plugin-b.js").exists())

        # plugin-b を無効化してから --prune 付きで再配布
        self._write_opencode_config(disabled=["plugin-b"])
        exit_code, output = run_distribute_cli([
            "opencode", "--push", "--prune", "--live", str(live_dir),
            "--repo-root", str(self.repo),
        ])
        self.assertEqual(exit_code, 0, msg=output)

        # 無効化された plugin-b は prune（backup + 削除）される
        self.assertFalse(
            (live_dir / "plugins" / "plugin-b.js").exists(),
            msg="disabled plugin は prune で削除されるべき",
        )
        # plugin-a は引き続き配布される
        self.assertTrue((live_dir / "plugins" / "plugin-a.js").exists())

    def test_prune_preserves_hidden_internal_dirs(self):
        """管理ディレクトリ配下の隠しディレクトリ（. 始まり）は prune しない。

        codex の skills/.system/（ツール内部管理の system skills）を --prune が
        削除した実害（2026-07-10）の再発防止。
        """
        self._write_opencode_config(disabled=[])
        live_dir = Path(self.repo / "live" / "opencode")
        internal = live_dir / "plugins" / ".internal"
        internal.mkdir(parents=True, exist_ok=True)
        (internal / "marker.txt").write_text("tool-managed\n", encoding="utf-8")
        (live_dir / "plugins" / ".hidden-file").write_text("x\n", encoding="utf-8")

        exit_code, output = run_distribute_cli([
            "opencode", "--push", "--prune", "--live", str(live_dir),
            "--repo-root", str(self.repo),
        ])
        self.assertEqual(exit_code, 0, msg=output)

        self.assertTrue(
            (internal / "marker.txt").exists(),
            msg="隠しディレクトリ配下は prune されないべき",
        )
        self.assertTrue((live_dir / "plugins" / ".hidden-file").exists())

    def test_all_disabled_passes_check(self):
        """全プラグインが disabledPlugins にあれば check は OK を返す（AGENTS.md のみ配布）。"""
        self._write_opencode_config(disabled=["plugin-a", "plugin-b"])
        live_dir = Path(self.repo / "live" / "opencode")
        live_dir.mkdir(parents=True, exist_ok=True)

        # AGENTS.md を事前に配置（openencode の distribute に含まれる）
        from harness_lib.resolver import manifest
        m = manifest("opencode", self.repo)
        for rel, content in m.files.items():
            dest = live_dir / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(content)

        # settings.json も配置（settingsSync で同期される）
        settings_src = self.repo / "packages" / "targets" / "opencode" / "permission-overlay.json"
        if settings_src.exists():
            (live_dir / "opencode.json").write_text(
                settings_src.read_text(encoding="utf-8"), encoding="utf-8"
            )

        exit_code, output = run_distribute_cli([
            "opencode", "--check", "--live", str(live_dir), "--repo-root", str(self.repo),
        ])
        self.assertEqual(exit_code, 0, msg=output)


class SettingsSyncExtensionsTestCase(unittest.TestCase):
    """settingsSync に instructions / skills.paths / env が追加された場合の検証。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = make_repo(Path(self._tmp.name))

    def tearDown(self):
        self._tmp.cleanup()

    def _write_opencode_overlay(self, keys: list) -> None:
        """permission-overlay.json に指定キーの同期フィールドを追加する。"""
        overlay_path = self.repo / "packages" / "targets" / "opencode" / "permission-overlay.json"
        overlay = {
            "instructions": ["~/.config/opencode/rules/*.md"],
            "skills": {
                "paths": ["~/.config/opencode/skills"],
            },
            "env": {
                "HARNESS_EXPECTED_PLAN": "plan-file.md",
            },
        }
        overlay_path.write_text(json.dumps(overlay, ensure_ascii=False, indent=2), encoding="utf-8")

        # config.json に settingsSync + configFile を追加
        cfg_path = self.repo / "packages" / "targets" / "opencode" / "config.json"
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        cfg["configFile"] = "opencode.json"
        cfg["settingsSync"] = {
            "source": "packages/targets/opencode/permission-overlay.json",
            "keys": keys,
        }
        cfg_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")

    def _write_live_config(self, **kwargs) -> Path:
        """ライブ側の opencode.json を作成する。"""
        live_dir = self.repo / "live" / "opencode"
        live_dir.mkdir(parents=True, exist_ok=True)
        (live_dir / "opencode.json").write_text(
            json.dumps(kwargs, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return live_dir

    def test_instructions_key_synced(self):
        """settingsSync.keys に instructions がある場合、permission-overlay の instructions が同期される。"""
        self._write_opencode_overlay(keys=["instructions"])
        live_dir = self._write_live_config()

        exit_code, output = run_distribute_cli([
            "opencode", "--push", "--live", str(live_dir), "--repo-root", str(self.repo),
        ])
        self.assertEqual(exit_code, 0, msg=output)

        config = json.loads((live_dir / "opencode.json").read_text(encoding="utf-8"))
        self.assertEqual(config.get("instructions"), ["~/.config/opencode/rules/*.md"])

    def test_skills_paths_key_synced(self):
        """settingsSync.keys に skills.paths がある場合、permission-overlay の skills.paths が同期される。"""
        self._write_opencode_overlay(keys=["skills.paths"])
        live_dir = self._write_live_config()

        exit_code, output = run_distribute_cli([
            "opencode", "--push", "--live", str(live_dir), "--repo-root", str(self.repo),
        ])
        self.assertEqual(exit_code, 0, msg=output)

        config = json.loads((live_dir / "opencode.json").read_text(encoding="utf-8"))
        self.assertEqual(config.get("skills", {}).get("paths"), ["~/.config/opencode/skills"])

    def test_env_key_synced(self):
        """settingsSync.keys に env がある場合、permission-overlay の env が同期される。"""
        self._write_opencode_overlay(keys=["env"])
        live_dir = self._write_live_config()

        exit_code, output = run_distribute_cli([
            "opencode", "--push", "--live", str(live_dir), "--repo-root", str(self.repo),
        ])
        self.assertEqual(exit_code, 0, msg=output)

        config = json.loads((live_dir / "opencode.json").read_text(encoding="utf-8"))
        self.assertEqual(config.get("env", {}).get("HARNESS_EXPECTED_PLAN"), "plan-file.md")

    def test_all_new_keys_synced(self):
        """3 つの新キーを全て指定した場合、すべて同期される。"""
        self._write_opencode_overlay(keys=["instructions", "skills.paths", "env"])
        live_dir = self._write_live_config()

        exit_code, output = run_distribute_cli([
            "opencode", "--push", "--live", str(live_dir), "--repo-root", str(self.repo),
        ])
        self.assertEqual(exit_code, 0, msg=output)

        config = json.loads((live_dir / "opencode.json").read_text(encoding="utf-8"))
        self.assertEqual(config.get("instructions"), ["~/.config/opencode/rules/*.md"])
        self.assertEqual(config.get("skills", {}).get("paths"), ["~/.config/opencode/skills"])
        self.assertEqual(config.get("env", {}).get("HARNESS_EXPECTED_PLAN"), "plan-file.md")

    def test_remove_keys_deletes_obsolete_config_key(self):
        self._write_opencode_overlay(keys=["instructions"])
        cfg_path = self.repo / "packages" / "targets" / "opencode" / "config.json"
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        cfg["settingsSync"]["removeKeys"] = ["env"]
        cfg_path.write_text(json.dumps(cfg), encoding="utf-8")
        live_dir = self._write_live_config()
        live_path = live_dir / "opencode.json"
        live = json.loads(live_path.read_text(encoding="utf-8"))
        live["env"] = {"INVALID": "1"}
        live_path.write_text(json.dumps(live), encoding="utf-8")

        exit_code, output = run_distribute_cli([
            "opencode", "--push", "--live", str(live_dir), "--repo-root", str(self.repo),
        ])

        self.assertEqual(exit_code, 0, msg=output)
        self.assertNotIn("env", json.loads(live_path.read_text(encoding="utf-8")))


class ThinResidencyTestCase(unittest.TestCase):
    """OpenCode 常駐（AGENTS.md + instructions）の薄型化を実 config で検証する。

    共通ルール全文を常時ロードせず、最小ルール + 安全ガード + Routing のみ常駐。
    外した詳細は rules/ にファイル配布され on-demand で読める状態を保つ。
    """

    def setUp(self):
        from harness_lib.resolver import manifest

        self.manifest = manifest("opencode", REPO_ROOT)
        self.shared_agents_manifest = manifest("shared-agents", REPO_ROOT)
        self.agents_md = self.manifest.files["AGENTS.md"].decode("utf-8")

    def test_agents_md_sourced_from_opencode_template(self):
        from harness_lib.config import load_target

        cfg = load_target("opencode", REPO_ROOT)
        entry = cfg["distribute"]["AGENTS.md"]
        self.assertEqual(entry["source"], "packages/targets/opencode/AGENTS.md")

    def test_no_giant_rules_inlined(self):
        """rules 全文・TDD 全文・文体全文が AGENTS.md に混入しないこと。"""
        self.assertNotIn("正確さはスピードに優先", self.agents_md)  # core-standards
        self.assertNotIn("Red: 失敗するテスト", self.agents_md)      # TDD 全文
        self.assertNotIn("空虚な強調", self.agents_md)              # 文体全文
        self.assertNotIn("Model Tiering", self.agents_md)
        self.assertNotIn("Startup Self-Check", self.agents_md)

    def test_safety_and_language_residency_preserved(self):
        """OpenCode 固有の安全ガードと日本語必須は常駐に残ること。"""
        self.assertIn("必ず日本語で応答", self.agents_md)
        self.assertIn("絶対禁止リスト", self.agents_md)
        self.assertIn("git push origin main", self.agents_md)
        self.assertIn("Routing", self.agents_md)

    def test_routing_points_to_distributed_files(self):
        self.assertIn("rules/core-standards.md", self.agents_md)
        self.assertIn("rules/core-standards.md", self.manifest.files)
        self.assertIn("rules/review-policy.md", self.manifest.files)
        self.assertIn("commands.md", self.manifest.files)
        # RTK.md は public slim では SSOT から外れる（packages/public-slim/manifest.json）
        if (REPO_ROOT / "packages/core/RTK.md").is_file():
            self.assertIn("RTK.md", self.manifest.files)

    def test_approval_flow_is_native_ask_not_script(self):
        """push / PR merge・close は OpenCode の native permission ask で承認する。

        deny message が指す approve-*.sh は Claude / pi 用で、OpenCode の permission
        deny は script では解除できない。常駐は ask → 承認後に単独 1 回実行を示し、
        承認スクリプトを OpenCode の経路として案内しない。
        """
        self.assertNotIn("approve-push.sh", self.agents_md)
        self.assertNotIn("approve-pr.sh", self.agents_md)
        self.assertNotIn("runtime/claude-hooks/approve-push.sh", self.manifest.files)
        self.assertIn("ask", self.agents_md)
        self.assertIn("単独で 1 回", self.agents_md)
        self.assertNotIn("ユーザーに状況を報告して指示を仰ぐ", self.agents_md)

    def test_pr_merge_close_projects_to_native_ask(self):
        """gh pr merge / close は permission-overlay の computed globs で ask になる。"""
        from harness_lib import danger_rules

        table = json.loads(
            (REPO_ROOT / "packages/core/policy/danger-rules.json").read_text(encoding="utf-8")
        )
        globs = danger_rules.permission_globs(table, "opencode")
        self.assertEqual(globs["gh pr merge*"], "ask")
        self.assertEqual(globs["gh pr close*"], "ask")
        self.assertEqual(globs["git push"], "ask")

    def test_instructions_glob_dropped(self):
        """permission-overlay の instructions は rules/*.md glob を常駐させないこと。"""
        overlay = json.loads(
            (REPO_ROOT / "packages/targets/opencode/permission-overlay.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertNotIn("~/.config/opencode/rules/*.md", overlay.get("instructions", []))

    def test_agents_md_is_thinner_than_shared_source(self):
        shared = (REPO_ROOT / "packages/core/CLAUDE.md").read_text(encoding="utf-8")
        self.assertLess(len(self.agents_md), len(shared))

    def test_custom_subagents_distributed(self):
        """カスタムサブエージェント md（explorer/worker/reviewer）が manifest に含まれること。"""
        for expected in [
            "agents/explorer.md",
            "agents/worker.md",
            "agents/reviewer.md",
        ]:
            self.assertIn(expected, self.manifest.files)

    def test_enabled_skill_bodies_do_not_use_claude_interactive_tool_names(self):
        forbidden = ("AskUserQuestion", "EnterPlanMode", "Task(")
        for path, content in self.shared_agents_manifest.files.items():
            if not path.startswith("skills/") or not path.endswith("SKILL.md"):
                continue
            body = content.decode("utf-8")
            for token in forbidden:
                self.assertNotIn(token, body, msg=f"{path}: {token}")

    def test_default_agent_is_build_for_autonomous_work(self):
        overlay = json.loads(
            (REPO_ROOT / "packages/targets/opencode/permission-overlay.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(overlay["default_agent"], "build")

    def test_hook_runner_is_distributed_next_to_the_bridge(self):
        """claude-hooks-bridge.js / post-edit-checks.js は ../hook-runner/ を import し、hookRunner は
        ../claude-hooks/ と ../policy/hook-pipeline.json を相対参照する。runtime/ 配下に 4 つが揃うこと。"""
        for rel in (
            "runtime/harunon-opencode/claude-hooks-bridge.js",
            "runtime/hook-runner/hook-runner.js",
            "runtime/hook-runner/post-edit.js",
            "runtime/claude-hooks/block-dangerous-in-bash.sh",
            "runtime/policy/hook-pipeline.json",
        ):
            self.assertIn(rel, self.manifest.files)

    def test_all_opencode_runtime_modules_parse_as_javascript(self):
        paths = [REPO_ROOT / "packages/runtimes/opencode/harunon.js"]
        paths.extend((REPO_ROOT / "packages/core/opencode-plugins").glob("*.js"))
        paths.extend((REPO_ROOT / "packages/core/hook-runner").glob("*.js"))
        for path in paths:
            result = subprocess.run(
                ["node", "--check", str(path)], capture_output=True, text=True
            )
            self.assertEqual(result.returncode, 0, msg=f"{path}: {result.stderr}")
        result = subprocess.run(
            [
                "node",
                "--input-type=module",
                "-e",
                f'import("{(REPO_ROOT / "packages/core/opencode-plugins/scan-new-skills.js").as_uri()}")',
            ],
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)

    def test_claude_skill_discovery_is_disabled_to_avoid_duplicates(self):
        overlay = json.loads(
            (REPO_ROOT / "packages/targets/opencode/permission-overlay.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertNotIn("env", overlay)
        launcher = (REPO_ROOT / "packages/runtimes/opencode-launcher/opencode").read_text(
            encoding="utf-8"
        )
        self.assertIn("OPENCODE_DISABLE_CLAUDE_CODE_SKILLS", launcher)

    def test_subagents_have_bounded_steps(self):
        expected = {
            "agents/explorer.md": "steps: 12",
            "agents/reviewer.md": "steps: 8",
            "agents/worker.md": "steps: 40",
        }
        for path, fragment in expected.items():
            body = self.manifest.files[path].decode("utf-8")
            self.assertIn(fragment, body, msg=path)

    def test_only_one_top_level_plugin_is_auto_loaded(self):
        top_level = [
            path
            for path in self.manifest.files
            if path.startswith("plugins/") and path.count("/") == 1 and path.endswith(".js")
        ]
        self.assertEqual(top_level, ["plugins/harunon.js"])
        self.assertIn("runtime/harunon-opencode/harness-policy.js", self.manifest.files)

    def test_umbrella_plugin_declares_deterministic_order(self):
        body = self.manifest.files["plugins/harunon.js"].decode("utf-8")
        expected = [
            "HarnessPolicy",
            "HarnessWorkflow",
            "ClaudeHooksBridge",
            "FixGfmTables",
            "ScanNewSkills",
            "ModelProviders",
        ]
        positions = [body.index(name) for name in expected]
        self.assertEqual(positions, sorted(positions))


if __name__ == "__main__":
    unittest.main()
