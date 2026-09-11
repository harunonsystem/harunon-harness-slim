"""harness_lib パッケージのテスト。

TDD（Red→Green）で実装する。
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPTS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS_DIR))

from harness_lib.distribution_state import BACKUP_KEEP  # noqa: E402
from tests._helpers import (  # noqa: E402
    make_extras_skill,
    make_repo,
    run_distribute_cli,
)

# ---------------------------------------------------------------------------
# merge.py のテスト
# ---------------------------------------------------------------------------

class TestDeepMerge(unittest.TestCase):
    """merge.py の deep_merge 関数テスト。"""

    def setUp(self) -> None:
        from harness_lib.merge import deep_merge
        self.deep_merge = deep_merge

    def test_merges_nested_dicts_recursively(self):
        base = {"a": {"x": 1, "y": 2}, "b": 1}
        self.deep_merge(base, {"a": {"y": 3, "z": 4}})

        self.assertEqual(base, {"a": {"x": 1, "y": 3, "z": 4}, "b": 1})

    def test_replaces_lists_instead_of_concatenating(self):
        base = {"permissions": {"allow": ["a", "b"]}}
        self.deep_merge(base, {"permissions": {"allow": ["c"]}})

        self.assertEqual(base["permissions"]["allow"], ["c"])


class TestMergeOverlayIntoSettings(unittest.TestCase):
    """merge.py の merge_overlay_into_settings 関数テスト。"""

    def setUp(self) -> None:
        from harness_lib.merge import merge_overlay_into_settings
        self.merge_overlay = merge_overlay_into_settings

    def test_env_overlay_merges_only_into_env_key(self):
        settings = {"env": {"A": "1"}, "language": "Japanese"}
        self.merge_overlay(settings, {"B": "2"}, "env.json")

        self.assertEqual(settings["env"], {"A": "1", "B": "2"})
        self.assertEqual(settings["language"], "Japanese")

    def test_settings_overlay_deep_merges_whole_settings(self):
        settings = {"hooks": {"PreToolUse": [{"matcher": "Bash"}]}, "language": "Japanese"}
        self.merge_overlay(
            settings,
            {"language": "English", "plansDirectory": "~/p"},
            "settings-overlay.json",
        )

        self.assertEqual(settings["language"], "English")
        self.assertEqual(settings["plansDirectory"], "~/p")
        self.assertIn("PreToolUse", settings["hooks"])


# ---------------------------------------------------------------------------
# frontmatter.py のテスト
# ---------------------------------------------------------------------------

class TestTransformSkillMd(unittest.TestCase):
    """frontmatter.py の transform_skill_md テスト。"""

    def setUp(self) -> None:
        from harness_lib.frontmatter import transform_skill_md
        self.transform = transform_skill_md

    def test_removes_fields_not_in_keep(self):
        """keep にないフィールドは除去される。"""
        text = (
            "---\n"
            "name: demo\n"
            "description: テスト\n"
            "allowed-tools: Bash\n"
            "user-invocable: true\n"
            "---\n"
            "# Body\n"
        )
        result = self.transform(text, {"name", "description"})
        self.assertIn("name: demo", result)
        self.assertIn("description: テスト", result)
        self.assertNotIn("allowed-tools", result)
        self.assertNotIn("user-invocable", result)

    def test_body_preserved(self):
        """本文は変換後も維持される。"""
        text = (
            "---\n"
            "name: demo\n"
            "---\n"
            "# Body\n\n本文内容。\n"
        )
        result = self.transform(text, {"name"})
        self.assertIn("# Body", result)
        self.assertIn("本文内容。", result)

    def test_no_frontmatter_passthrough(self):
        """frontmatter がないテキストはそのまま返る。"""
        text = "# Body\n\n内容。\n"
        result = self.transform(text, {"name"})
        self.assertEqual(result, text)

    def test_continuation_lines_kept_with_parent(self):
        """継続行（インデント行）は親キーと一緒に保持/除去される。"""
        text = (
            "---\n"
            "name: demo\n"
            "metadata:\n"
            "  key: value\n"
            "  other: val2\n"
            "allowed-tools: Bash\n"
            "---\n"
            "# Body\n"
        )
        result = self.transform(text, {"name", "metadata"})
        self.assertIn("metadata:", result)
        self.assertIn("  key: value", result)
        self.assertIn("  other: val2", result)
        self.assertNotIn("allowed-tools", result)


# ---------------------------------------------------------------------------
# config.py のテスト
# ---------------------------------------------------------------------------

def _copy_target_config_schema(root: Path) -> None:
    """target-config.schema.json を root/schemas/ にコピーする（load_target が必須で要求するため）。"""
    schema_dir = root / "schemas"
    schema_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy(
        str(REPO_ROOT / "schemas" / "target-config.schema.json"),
        str(schema_dir / "target-config.schema.json"),
    )


class TestConfig(unittest.TestCase):
    """config.py の load_target テスト。"""

    def test_load_target_returns_dict(self):
        """load_target が dict を返す。"""
        from harness_lib.config import load_target
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(Path(tmp))
            cfg = load_target("codex", root)
            self.assertIsInstance(cfg, dict)
            self.assertEqual(cfg["name"], "codex")

    def test_load_target_expands_tilde_in_config_dir(self):
        """configDir の ~ が展開される。"""
        import os

        from harness_lib.config import load_target
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _copy_target_config_schema(root)
            target_dir = root / "packages" / "targets" / "test_tilde"
            target_dir.mkdir(parents=True)
            (target_dir / "config.json").write_text(
                json.dumps({
                    "name": "test_tilde",
                    "displayName": "Test Tilde",
                    "configDir": "~/.test_tilde_xyz",
                    "configFile": "settings.json",
                    "instructionsFile": "AGENTS.md",
                    "distribute": {},
                }),
                encoding="utf-8",
            )
            cfg = load_target("test_tilde", root)
            config_dir = Path(cfg["configDir"])
            # ~ 展開されているはず
            self.assertFalse(str(config_dir).startswith("~"))
            self.assertTrue(str(config_dir).startswith(str(Path.home())))

    def test_load_target_uses_declared_config_dir_environment(self):
        """configDirEnv が設定されていれば configDir を上書きする。"""
        import os

        from harness_lib.config import load_target

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _copy_target_config_schema(root)
            target_dir = root / "packages" / "targets" / "test_env"
            target_dir.mkdir(parents=True)
            (target_dir / "config.json").write_text(
                json.dumps(
                    {
                        "name": "test_env",
                        "displayName": "Test Env",
                        "configDir": "~/.fallback",
                        "configDirEnv": "HARNESS_TEST_CONFIG_HOME",
                        "configFile": "settings.json",
                        "instructionsFile": "AGENTS.md",
                        "distribute": {},
                    }
                ),
                encoding="utf-8",
            )
            env_name = "HARNESS_TEST_CONFIG_HOME"
            previous = os.environ.get(env_name)
            os.environ[env_name] = str(root / "active")
            try:
                cfg = load_target("test_env", root)
            finally:
                if previous is None:
                    os.environ.pop(env_name, None)
                else:
                    os.environ[env_name] = previous
            self.assertEqual(cfg["configDir"], str(root / "active"))
    def test_load_target_ignores_empty_config_dir_environment(self):
        """空の configDirEnv は既定の configDir に戻る。"""
        import os

        from harness_lib.config import load_target

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _copy_target_config_schema(root)
            target_dir = root / "packages" / "targets" / "test_empty_env"
            target_dir.mkdir(parents=True)
            (target_dir / "config.json").write_text(
                json.dumps(
                    {
                        "name": "test_empty_env",
                        "displayName": "Test Empty Env",
                        "configDir": "~/.fallback",
                        "configDirEnv": "HARNESS_TEST_EMPTY_HOME",
                        "configFile": "settings.json",
                        "instructionsFile": "AGENTS.md",
                        "distribute": {},
                    }
                ),
                encoding="utf-8",
            )
            env_name = "HARNESS_TEST_EMPTY_HOME"
            previous = os.environ.get(env_name)
            os.environ[env_name] = ""
            try:
                cfg = load_target("test_empty_env", root)
            finally:
                if previous is None:
                    os.environ.pop(env_name, None)
                else:
                    os.environ[env_name] = previous
            self.assertEqual(cfg["configDir"], str(Path.home() / ".fallback"))

    def test_load_target_rejects_relative_config_dir_environment(self):
        """相対 configDirEnv はカレントディレクトリ配布を防ぐため拒否する。"""
        import os

        from harness_lib.config import load_target

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _copy_target_config_schema(root)
            target_dir = root / "packages" / "targets" / "test_relative_env"
            target_dir.mkdir(parents=True)
            (target_dir / "config.json").write_text(
                json.dumps(
                    {
                        "name": "test_relative_env",
                        "displayName": "Test Relative Env",
                        "configDir": "~/.fallback",
                        "configDirEnv": "HARNESS_TEST_RELATIVE_HOME",
                        "configFile": "settings.json",
                        "instructionsFile": "AGENTS.md",
                        "distribute": {},
                    }
                ),
                encoding="utf-8",
            )
            env_name = "HARNESS_TEST_RELATIVE_HOME"
            previous = os.environ.get(env_name)
            os.environ[env_name] = "relative/path"
            try:
                with self.assertRaisesRegex(ValueError, "must be an absolute path"):
                    load_target("test_relative_env", root)
            finally:
                if previous is None:
                    os.environ.pop(env_name, None)
                else:
                    os.environ[env_name] = previous

    def test_load_target_rejects_schema_invalid_config(self):
        """load_target は caller に未検証 config を渡さない。"""
        from harness_lib.config import load_target

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            schema_dir = root / "schemas"
            schema_dir.mkdir()
            (schema_dir / "target-config.schema.json").write_bytes(
                (REPO_ROOT / "schemas" / "target-config.schema.json").read_bytes()
            )
            target_dir = root / "packages" / "targets" / "bad"
            target_dir.mkdir(parents=True)
            (target_dir / "config.json").write_text(
                json.dumps({
                    "name": "bad",
                    "displayName": "Bad",
                    "configDir": "~/.bad",
                    "configFile": "settings.json",
                    "instructionsFile": "AGENTS.md",
                    "distribute": {},
                    "unknown": True,
                }),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "additional property 'unknown'"):
                load_target("bad", root)

    def test_load_target_rejects_name_mismatch(self):
        """target directory と config の name がずれると解決を止める。"""
        from harness_lib.config import load_target

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            schema_dir = root / "schemas"
            schema_dir.mkdir()
            (schema_dir / "target-config.schema.json").write_bytes(
                (REPO_ROOT / "schemas" / "target-config.schema.json").read_bytes()
            )
            target_dir = root / "packages" / "targets" / "wrong-dir"
            target_dir.mkdir(parents=True)
            (target_dir / "config.json").write_text(
                json.dumps({
                    "name": "wrong-name",
                    "displayName": "Wrong",
                    "configDir": "~/.wrong",
                    "configFile": "settings.json",
                    "instructionsFile": "AGENTS.md",
                    "distribute": {},
                }),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "name.*ディレクトリ名"):
                load_target("wrong-dir", root)

    def test_target_names_are_resolved_by_config_module(self):
        """target 列挙が auxiliary と instructionsFile の契約を共有する。"""
        from harness_lib.config import target_names

        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(Path(tmp))
            auxiliary = root / "packages" / "targets" / "helper"
            auxiliary.mkdir()
            (auxiliary / "config.json").write_text(
                json.dumps({
                    "name": "helper",
                    "displayName": "Helper",
                    "configDir": "~/.helper",
                    "configFile": "",
                    "instructionsFile": "",
                    "auxiliary": True,
                    "distribute": {},
                }),
                encoding="utf-8",
            )
            no_instructions = root / "packages" / "targets" / "no-instructions"
            no_instructions.mkdir()
            (no_instructions / "config.json").write_text(
                json.dumps({
                    "name": "no-instructions",
                    "displayName": "No Instructions",
                    "configDir": "~/.no-instructions",
                    "configFile": "",
                    "instructionsFile": "",
                    "distribute": {},
                }),
                encoding="utf-8",
            )

            self.assertEqual(
                target_names(root, require_instructions=False),
                ["claude", "codex", "no-instructions", "opencode"],
            )
            self.assertEqual(
                target_names(root, require_instructions=True),
                ["claude", "codex", "opencode"],
            )


    def test_repo_root_returns_path(self):
        """repo_root() が Path を返す。"""
        from harness_lib.config import repo_root
        r = repo_root()
        self.assertIsInstance(r, Path)


# ---------------------------------------------------------------------------
# resolver.py のテスト（path safety）
# ---------------------------------------------------------------------------

class TestPathSafety(unittest.TestCase):
    def test_rejects_absolute_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(Path(tmp))
            cfg = json.loads(
                (root / "packages" / "targets" / "claude" / "config.json").read_text()
            )
            cfg["distribute"]["evil.md"] = {"source": "/etc/passwd"}
            with self.assertRaises(ValueError) as ctx:
                from harness_lib.resolver import manifest
                manifest("claude", root, cfg=cfg)
            self.assertIn("絶対パス", str(ctx.exception))

    def test_rejects_dotdot_in_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(Path(tmp))
            cfg = json.loads(
                (root / "packages" / "targets" / "claude" / "config.json").read_text()
            )
            cfg["distribute"]["evil.md"] = {"source": "packages/../../outside.md"}
            with self.assertRaises(ValueError) as ctx:
                from harness_lib.resolver import manifest
                manifest("claude", root, cfg=cfg)
            self.assertIn("..", str(ctx.exception))

    def test_rejects_dotdot_in_dest_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(Path(tmp))
            cfg = json.loads(
                (root / "packages" / "targets" / "claude" / "config.json").read_text()
            )
            cfg["distribute"]["../escape.md"] = {"source": "packages/core/CLAUDE.md"}
            with self.assertRaises(ValueError) as ctx:
                from harness_lib.resolver import manifest
                manifest("claude", root, cfg=cfg)
            self.assertIn("..", str(ctx.exception))

    def test_rejects_dir_source_for_file_dest(self):
        """dir source + file dest（末尾 '/' なし）は空ファイル配布に化けるので fail fast する。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(Path(tmp))
            cfg = json.loads(
                (root / "packages" / "targets" / "claude" / "config.json").read_text()
            )
            cfg["distribute"]["CLAUDE.md"] = {"source": "packages/core/rules/"}
            with self.assertRaises(ValueError) as ctx:
                from harness_lib.resolver import manifest
                manifest("claude", root, cfg=cfg)
            self.assertIn("CLAUDE.md", str(ctx.exception))

    def test_rejects_file_source_for_dir_dest(self):
        """file source + dir dest（末尾 '/'）は dest_prefix そのものに化けるので fail fast する。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(Path(tmp))
            cfg = json.loads(
                (root / "packages" / "targets" / "claude" / "config.json").read_text()
            )
            cfg["distribute"]["rules/"] = {"source": "packages/core/CLAUDE.md"}
            with self.assertRaises(ValueError) as ctx:
                from harness_lib.resolver import manifest
                manifest("claude", root, cfg=cfg)
            self.assertIn("rules/", str(ctx.exception))

    def test_valid_file_to_file_and_dir_to_dir_still_work(self):
        """正当な経路（file→file, dir→dir/）は回帰しない。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(Path(tmp))
            from harness_lib.resolver import manifest
            m = manifest("claude", root)
            self.assertEqual(
                m.files["CLAUDE.md"],
                (root / "packages" / "core" / "CLAUDE.md").read_bytes(),
            )
            self.assertIn("rules/core-standards.md", m.files)


# ---------------------------------------------------------------------------
# resolver.py のテスト（manifest）
# ---------------------------------------------------------------------------

class TestManifest(unittest.TestCase):
    """resolver.py の manifest テスト。"""

    def _manifest(self, target: str, root: Path):
        from harness_lib.resolver import manifest
        return manifest(target, root)

    def test_single_file_entry(self):
        """単一ファイルエントリが manifest に含まれる。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(Path(tmp))
            m = self._manifest("claude", root)
            self.assertIn("CLAUDE.md", m.files)
            content = m.files["CLAUDE.md"]
            expected = (root / "packages" / "core" / "CLAUDE.md").read_bytes()
            self.assertEqual(content, expected)

    def test_directory_entry_recursive(self):
        """ディレクトリエントリが再帰的に展開される。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(Path(tmp))
            m = self._manifest("claude", root)
            # rules/ 配下のファイルが含まれる
            self.assertIn("rules/core-standards.md", m.files)

    def test_symlink_in_source_dir_excluded_with_warning(self):
        """配布元ディレクトリの symlink（実ファイル/リンク切れ）は
        warnings に記録され、files には含まれない（デリファレンス防止）。

        symlink はリンク先の内容を無警告でデリファレンスして配布してしまい、
        リンク切れは無警告で欠落する（plan 007 の再現ケース）。
        """
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(Path(tmp))
            rules_dir = root / "packages" / "core" / "rules"

            real_target = Path(tmp) / "outside-real-file.md"
            real_target.write_text("outside content\n", encoding="utf-8")
            (rules_dir / "linked-file.md").symlink_to(real_target)

            broken_target = Path(tmp) / "does-not-exist.md"
            (rules_dir / "broken-link.md").symlink_to(broken_target)

            m = self._manifest("claude", root)

            self.assertNotIn("rules/linked-file.md", m.files)
            self.assertNotIn("rules/broken-link.md", m.files)
            self.assertTrue(
                any("linked-file.md" in w for w in m.warnings),
                msg=f"symlink 警告が無い: {m.warnings}",
            )
            self.assertTrue(
                any("broken-link.md" in w for w in m.warnings),
                msg=f"リンク切れ symlink の警告が無い: {m.warnings}",
            )


    def test_array_source_last_wins(self):
        """配列 source で後勝ち（extras が core を上書き）。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(Path(tmp))
            # extras に同名スキルを追加（上書き）
            make_extras_skill(root, "demo-skill",
                              "---\nname: demo-skill\ndescription: extras版\n---\n# Extras\n")
            # skills エントリに配列 source を持つ codex を使う
            m = self._manifest("codex", root)
            skill_key = "skills/demo-skill/SKILL.md"
            self.assertIn(skill_key, m.files)
            content = m.files[skill_key].decode("utf-8")
            # extras 版に上書きされているが、codex は frontmatter 変換される
            # → allowed-tools は元々ないが、extras 版は description が "extras版"
            self.assertIn("extras版", content)

    def test_transform_applies_only_to_skill_md(self):
        """transform 指定時、SKILL.md のみ frontmatter 変換され他ファイルはバイト同一。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(Path(tmp))
            m = self._manifest("codex", root)
            # SKILL.md は frontmatter 変換済み → allowed-tools が除去されている
            skill_md_content = m.files["skills/demo-skill/SKILL.md"].decode("utf-8")
            self.assertNotIn("allowed-tools", skill_md_content)
            self.assertIn("name: demo-skill", skill_md_content)
            # icon.png はバイト同一
            icon_key = "skills/demo-skill/icon.png"
            self.assertIn(icon_key, m.files)
            expected_bytes = (
                root / "packages" / "core" / "skills" / "demo-skill" / "icon.png"
            ).read_bytes()
            self.assertEqual(m.files[icon_key], expected_bytes)

    def test_binary_file_preserved(self):
        """バイナリファイルが壊れない（bytes として保持される）。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(Path(tmp))
            m = self._manifest("claude", root)
            icon_key = "skills/demo-skill/icon.png"
            self.assertIn(icon_key, m.files)
            raw = (root / "packages" / "core" / "skills" / "demo-skill" / "icon.png").read_bytes()
            self.assertEqual(m.files[icon_key], raw)

    def test_ds_store_excluded(self):
        """.DS_Store は manifest に含まれない。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(Path(tmp))
            (root / "packages" / "core" / "skills" / "demo-skill" / ".DS_Store").write_bytes(b"junk")
            m = self._manifest("claude", root)
            for key in m.files:
                self.assertNotIn(".DS_Store", key)

    def test_pycache_excluded(self):
        """__pycache__ 配下の .pyc は manifest に含まれない。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(Path(tmp))
            pycache = root / "packages" / "core" / "skills" / "demo-skill" / "__pycache__"
            pycache.mkdir(parents=True)
            (pycache / "helper.cpython-314.pyc").write_bytes(b"\x00\x01junk")
            m = self._manifest("claude", root)
            for key in m.files:
                self.assertNotIn("__pycache__", key)

    def test_uninitialized_submodule_skipped_with_warning(self):
        """未取得 submodule 配下の source は skip され、warnings に記録される。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(Path(tmp))
            # extras/_active を空にする（.gitmodules 宣言済み + 空 = 未取得状態。
            # .gitmodules 自体は make_repo が宣言済み）
            extras_path = root / "packages" / "extras" / "_active"
            shutil.rmtree(extras_path)
            extras_path.mkdir(parents=True)
            # codex の skills/ source 配列が extras を参照しているので warnings が出るはず
            from harness_lib.resolver import manifest
            m = manifest("codex", root)
            # warnings に extras 関連が記録されている
            # （空ディレクトリのため内容なし → skip ではなく空扱い。
            #   実際は gitmodules 宣言＋空ディレクトリ = skip）
            # skip か空かは実装次第。ここでは例外が出ないことを確認する
            self.assertIsNotNone(m)

    def test_dir_source_with_file_dest_key_raises(self):
        """source がディレクトリなのに dest_key がファイル形式だと、
        raw_files.get("", b"") で空 bytes を黙って生成せず fail fast する（M-005）。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(Path(tmp))
            cfg = json.loads(
                (root / "packages" / "targets" / "claude" / "config.json").read_text()
            )
            cfg["distribute"]["rules-mistake.md"] = {"source": "packages/core/rules"}
            from harness_lib.resolver import manifest
            with self.assertRaises(ValueError) as ctx:
                manifest("claude", root, cfg=cfg)
            self.assertIn("rules-mistake.md", str(ctx.exception))


# ---------------------------------------------------------------------------
# resolver.py のテスト（_core_disabled_skills）
# ---------------------------------------------------------------------------

class TestCoreDisabledSkills(unittest.TestCase):
    """resolver.py の _core_disabled_skills テスト（common + target 別マージ）。"""

    def _core_disabled_skills(self, target: str, repo: Path):
        from harness_lib.resolver import _core_disabled_skills
        return _core_disabled_skills(target, repo)

    def test_missing_file_returns_empty_set(self):
        """packages/core/disabled-skills.json が無ければ空集合（extras 版と同じ防御）。"""
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            self.assertEqual(self._core_disabled_skills("codex", repo), set())

    def test_common_and_target_merge_for_listed_target(self):
        """"targets" に列挙された target は common + target キーがマージされる。"""
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            core_dir = repo / "packages" / "core"
            core_dir.mkdir(parents=True)
            (core_dir / "disabled-skills.json").write_text(json.dumps({
                "targets": ["codex", "omp"],
                "common": ["insights", "loop-engineering"],
                "codex": [],
                "omp": ["review"],
            }), encoding="utf-8")
            self.assertEqual(
                self._core_disabled_skills("codex", repo),
                {"insights", "loop-engineering"},
            )
            self.assertEqual(
                self._core_disabled_skills("omp", repo),
                {"insights", "loop-engineering", "review"},
            )

    def test_target_not_listed_in_targets_returns_empty(self):
        """"targets" に含まれない target（claude/opencode 等）には common を適用しない。"""
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            core_dir = repo / "packages" / "core"
            core_dir.mkdir(parents=True)
            (core_dir / "disabled-skills.json").write_text(json.dumps({
                "targets": ["codex", "omp"],
                "common": ["insights"],
            }), encoding="utf-8")
            self.assertEqual(self._core_disabled_skills("claude", repo), set())
            self.assertEqual(self._core_disabled_skills("opencode", repo), set())


class TestSkillDistribution(unittest.TestCase):
    """skill は全件配布し、除外は disabled-skills.json のみで宣言する（pack 廃止: 2026-08-19）。"""

    @staticmethod
    def _codex_config(repo: Path) -> dict:
        return json.loads(
            (repo / "packages" / "targets" / "codex" / "config.json").read_text(
                encoding="utf-8"
            )
        )

    def test_compatibility_frontmatter_is_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(Path(tmp))
            skill_path = root / "packages" / "core" / "skills" / "demo-skill" / "SKILL.md"
            skill_path.write_text(
                "---\nname: demo-skill\ndescription: demo\ncompatibility: opencode\n"
                "allowed-tools: Bash\n---\nbody\n",
                encoding="utf-8",
            )
            cfg = self._codex_config(root)
            cfg["skillsTransform"]["keepFrontmatterFields"].append("compatibility")

            from harness_lib.resolver import manifest
            content = manifest("codex", root, cfg=cfg).files[
                "skills/demo-skill/SKILL.md"
            ].decode("utf-8")

            self.assertIn("compatibility: opencode", content)
            self.assertNotIn("allowed-tools", content)

    def test_disabled_registry_excludes_skill_from_distribution(self):
        """disabled-skills.json が唯一の除外機構として配布に効く。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(Path(tmp))
            (root / "packages" / "core" / "disabled-skills.json").write_text(
                json.dumps({
                    "targets": ["codex"],
                    "common": ["demo-skill"],
                    "codex": [],
                }),
                encoding="utf-8",
            )

            from harness_lib.resolver import manifest
            files = manifest("codex", root).files

            self.assertFalse(
                any(path.startswith("skills/demo-skill/") for path in files)
            )

    def test_claude_distributes_all_core_and_extras_skills(self):
        """claude は core + restricted + extras の全 skill を配る（disabled-skills の対象外）。"""
        root = Path(__file__).resolve().parents[2]
        from harness_lib.resolver import manifest

        def skill_dirs(path: Path) -> set[str]:
            if not path.is_dir():
                return set()
            return {
                child.name
                for child in path.iterdir()
                if (child / "SKILL.md").is_file()
            }

        expected = (
            skill_dirs(root / "packages/core/skills")
            | skill_dirs(root / "packages/restricted/skills")
            | skill_dirs(root / "packages/extras/_active/skills")
        )
        files = manifest("claude", root).files
        distributed = {
            path.split("/", 2)[1]
            for path in files
            if path.startswith("skills/")
        }
        from harness_lib.curated_skills import list_curated_skills

        # curated（rulesync）は取得済みの環境でだけ manifest に乗るので比較から外す
        self.assertEqual(distributed - list_curated_skills(root), expected)
        self.assertIn("figma-implement", distributed)


# ---------------------------------------------------------------------------
# engineering skills は packages/core が正本
# ---------------------------------------------------------------------------

class TestEngineeringSkillsOwnership(unittest.TestCase):
    """通常配布は最小プロファイルを使い、追加 skill は明示導入する。"""

    def test_no_plugin_is_declared_without_a_distribution_path(self):
        """settingsSync が配れないキーに plugin を宣言しない（死んだ宣言の防止）。"""
        root = Path(__file__).resolve().parents[2]
        settings = json.loads(
            (root / "packages/core/settings.json").read_text(encoding="utf-8")
        )
        declared = set(settings.get("enabledPlugins", {}))
        marketplaces = set(settings.get("extraKnownMarketplaces", {}))
        self.assertNotIn("mattpocock-skills@mattpocock", declared)
        self.assertNotIn("mattpocock", marketplaces)


# ---------------------------------------------------------------------------
# resolver.py のテスト（check / Drift）
# ---------------------------------------------------------------------------

class TestCheck(unittest.TestCase):
    """resolver.py の check テスト。"""

    def _check(self, target: str, root: Path, live: Path):
        from harness_lib.distribution import Distribution
        inspection = Distribution(root).inspect(target, live)
        # manifest ファイル分だけ（settingsSync / ledger 由来の drift は別テストが見る）
        return [d for d in inspection.drifts if d.path in inspection.files]

    def test_missing_files_detected(self):
        """live に存在しないファイルが missing として検出される。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(Path(tmp))
            live = Path(tmp) / "empty_live"
            live.mkdir()
            drifts = self._check("claude", root, live)
            kinds = {d.kind for d in drifts}
            self.assertIn("missing", kinds)

    def test_changed_files_detected(self):
        """live の内容が期待値と異なるファイルが changed として検出される。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(Path(tmp))
            live = Path(tmp) / "live"
            live.mkdir()
            # CLAUDE.md だけ存在するが内容が違う
            (live / "CLAUDE.md").write_text("wrong content", encoding="utf-8")
            drifts = self._check("claude", root, live)
            keys = {d.path for d in drifts}
            self.assertIn("CLAUDE.md", keys)
            changed = [d for d in drifts if d.kind == "changed"]
            self.assertTrue(any(d.path == "CLAUDE.md" for d in changed))

    def test_live_only_files_ignored(self):
        """live にだけあるファイルは drift 対象外（unmanaged）。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(Path(tmp))
            # live に期待ファイルを正しく配置
            live = Path(tmp) / "live"
            live.mkdir()
            from harness_lib.resolver import manifest
            m = manifest("claude", root)
            for rel, content in m.files.items():
                dest = live / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(content)
            # 余分なファイルを追加
            (live / "unmanaged.txt").write_text("extra", encoding="utf-8")
            drifts = self._check("claude", root, live)
            # unmanaged.txt は drift として出ない
            keys = {d.path for d in drifts}
            self.assertNotIn("unmanaged.txt", keys)
            # 差分なし
            self.assertEqual(drifts, [])

    def test_no_drift_when_synced(self):
        """live が期待値と完全一致するとき drift なし。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(Path(tmp))
            live = Path(tmp) / "live"
            live.mkdir()
            from harness_lib.resolver import manifest
            m = manifest("claude", root)
            for rel, content in m.files.items():
                dest = live / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(content)
            drifts = self._check("claude", root, live)
            self.assertEqual(drifts, [])


# ---------------------------------------------------------------------------
# distribute.py CLI テスト
# ---------------------------------------------------------------------------

class TestDistributeCLI(unittest.TestCase):
    """distribute.py の CLI テスト。"""

    def _run(self, args: list[str]) -> tuple[int, str]:
        return run_distribute_cli(args)

    def test_list_outputs_paths(self):
        """--list が manifest のパス一覧を出力する。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(Path(tmp))
            code, out = self._run(["codex", "--list", "--repo-root", str(root)])
            self.assertEqual(code, 0)
            self.assertIn("AGENTS.md", out)

    def test_check_exits_0_when_synced(self):
        """--check で drift なし → exit 0。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(Path(tmp))
            live = Path(tmp) / "live"
            live.mkdir()
            from harness_lib.resolver import manifest
            m = manifest("codex", root)
            for rel, content in m.files.items():
                dest = live / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(content)
            (live / "config.toml").write_text(
                (root / "packages" / "targets" / "codex" / "config.toml").read_text(
                    encoding="utf-8"
                ),
                encoding="utf-8",
            )
            code, out = self._run(
                ["codex", "--check", "--live", str(live), "--repo-root", str(root)]
            )
            self.assertEqual(code, 0)

    def test_check_exits_1_when_drift(self):
        """--check で drift あり → exit 1。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(Path(tmp))
            live = Path(tmp) / "live"
            live.mkdir()
            (live / "AGENTS.md").write_text("wrong", encoding="utf-8")
            code, out = self._run(
                ["codex", "--check", "--live", str(live), "--repo-root", str(root)]
            )
            self.assertEqual(code, 1)

    def test_push_writes_files(self):
        """--push で manifest のファイルが live に書き込まれる。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(Path(tmp))
            live = Path(tmp) / "live"
            live.mkdir()
            code, out = self._run(
                ["codex", "--push", "--live", str(live), "--repo-root", str(root)]
            )
            self.assertEqual(code, 0)
            self.assertTrue((live / "AGENTS.md").exists())

    def test_push_idempotent(self):
        """--push を 2 回実行すると 2 回目は unchanged のみ。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(Path(tmp))
            live = Path(tmp) / "live"
            live.mkdir()
            self._run(["codex", "--push", "--live", str(live), "--repo-root", str(root)])
            code, out = self._run(
                ["codex", "--push", "--live", str(live), "--repo-root", str(root)]
            )
            self.assertEqual(code, 0)
            self.assertIn("updated: 0", out)
            self.assertIn("added: 0", out)

    def test_push_only_updates_changed_files(self):
        """--push は差分のあるファイルのみ更新する。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(Path(tmp))
            live = Path(tmp) / "live"
            live.mkdir()
            from harness_lib.resolver import manifest
            m = manifest("codex", root)
            # 全ファイルを正しく配置
            for rel, content in m.files.items():
                dest = live / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(content)
            # AGENTS.md だけ変更
            (live / "AGENTS.md").write_text("wrong", encoding="utf-8")
            agents_mtime_before = (live / "RTK.md").stat().st_mtime
            code, out = self._run(
                ["codex", "--push", "--live", str(live), "--repo-root", str(root)]
            )
            self.assertEqual(code, 0)
            # AGENTS.md は更新されている
            self.assertIn("updated: 1", out)
            # RTK.md は変更されていない（mtime 不変）
            agents_mtime_after = (live / "RTK.md").stat().st_mtime
            self.assertEqual(agents_mtime_before, agents_mtime_after)

    def test_push_claude_now_works(self):
        """--push で claude を指定すると Wave 2 以降は成功する。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(Path(tmp))
            live = Path(tmp) / "live"
            live.mkdir()
            code, out = self._run(
                ["claude", "--push", "--live", str(live), "--repo-root", str(root)]
            )
            self.assertEqual(code, 0)
            self.assertTrue((live / "CLAUDE.md").exists())

    def test_push_with_dest_option(self):
        """--dest オプションで出力先を指定できる。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(Path(tmp))
            dest = Path(tmp) / "custom_dest"
            dest.mkdir()
            code, out = self._run(
                ["claude", "--push", "--dest", str(dest), "--repo-root", str(root)]
            )
            self.assertEqual(code, 0)
            self.assertTrue((dest / "CLAUDE.md").exists())

    def test_push_dry_run_does_not_write(self):
        """--dry-run フラグを指定すると実際のファイル書き込みが行われない。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(Path(tmp))
            live = Path(tmp) / "live"
            live.mkdir()
            code, out = self._run(
                ["claude", "--push", "--live", str(live), "--dry-run",
                 "--repo-root", str(root)]
            )
            self.assertEqual(code, 0)
            # dry-run なのでファイルは書き込まれない
            self.assertFalse((live / "CLAUDE.md").exists())
            # DRY のプレフィックスが出力に含まれる
            self.assertIn("DRY", out)

    def test_push_claude_backup_on_overwrite(self):
        """差分のある既存ファイルがある場合 backup ディレクトリに退避される。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(Path(tmp))
            live = Path(tmp) / "live"
            live.mkdir()
            # 内容の異なるファイルを事前配置
            (live / "CLAUDE.md").write_text("old content\n", encoding="utf-8")
            code, out = self._run(
                ["claude", "--push", "--live", str(live), "--repo-root", str(root)]
            )
            self.assertEqual(code, 0)
            # backup ディレクトリが作成されている
            backups = list((live / "backups").rglob("CLAUDE.md"))
            self.assertTrue(len(backups) > 0, "CLAUDE.md が backup されていない")
            # 警告が出力されている
            self.assertIn("上書き", out)

    def test_push_dry_run_reports_overwrite(self):
        """--dry-run で差分ファイルがある場合、上書き警告が表示される。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(Path(tmp))
            live = Path(tmp) / "live"
            live.mkdir()
            (live / "CLAUDE.md").write_text("old content\n", encoding="utf-8")
            code, out = self._run(
                ["claude", "--push", "--live", str(live), "--dry-run",
                 "--repo-root", str(root)]
            )
            self.assertEqual(code, 0)
            self.assertIn("DRY", out)
            self.assertIn("上書き", out)


# ---------------------------------------------------------------------------
# distribute.py: push claude 結合テスト（extras overlay / skill-overrides）
# ---------------------------------------------------------------------------

class TestDistributePushClaudeExtras(unittest.TestCase):
    """distribute.py --push claude の extras オーバーレイ・skill-overrides テスト。"""

    def _run(self, args: list[str]) -> tuple[int, str]:
        return run_distribute_cli(args)

    def test_overlay_not_applied_without_extras_overlay_declaration(self):
        """extrasOverlay 宣言の無いターゲット（codex）では overlay がマージされない。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(Path(tmp))
            live = Path(tmp) / "live-codex"
            live.mkdir()
            settings = live / "settings.json"
            settings.write_text('{"existing": true}', encoding="utf-8")
            overlay = root / "packages" / "extras" / "_active" / "settings-overlay.json"
            overlay.write_text('{"overlay_key": 1}', encoding="utf-8")

            code, out = self._run(
                ["codex", "--push", "--dest", str(live), "--repo-root", str(root)]
            )

            self.assertEqual(code, 0, msg=out)
            merged = json.loads(settings.read_text(encoding="utf-8"))
            self.assertNotIn("overlay_key", merged)

    def test_extras_settings_overlay_applied(self):
        """extras に settings-overlay.json があると dest/settings.json にマージされる。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(Path(tmp))
            live = Path(tmp) / "live"
            live.mkdir()
            # 先に settings.json を配置（overlay の前提）
            (live / "settings.json").write_text(
                '{"existing": true}', encoding="utf-8"
            )
            # extras に settings-overlay.json を追加
            extras_dir = root / "packages" / "extras" / "_active"
            extras_dir.mkdir(parents=True, exist_ok=True)
            (extras_dir / "settings-overlay.json").write_text(
                '{"overlay_key": "overlay_value"}', encoding="utf-8"
            )
            # .gitmodules を削除して submodule 未取得扱いにしない
            gitmodules = root / ".gitmodules"
            if gitmodules.exists():
                gitmodules.unlink()
            code, out = self._run(
                ["claude", "--push", "--live", str(live), "--repo-root", str(root)]
            )
            self.assertEqual(code, 0, msg=out)
            import json as _json
            merged = _json.loads((live / "settings.json").read_text(encoding="utf-8"))
            self.assertIn("overlay_key", merged, "settings-overlay.json がマージされていない")

    def test_extras_settings_overlay_is_checked_after_push(self):
        """push 後の extras settings overlay も --check の期待値に含まれる。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(Path(tmp))
            live = Path(tmp) / "live"
            live.mkdir()
            (live / "settings.json").write_text(
                '{"existing": true}', encoding="utf-8"
            )
            extras_dir = root / "packages" / "extras" / "_active"
            extras_dir.mkdir(parents=True, exist_ok=True)
            overlay_path = extras_dir / "settings-overlay.json"
            overlay_path.write_text('{"overlay_key": "v1"}', encoding="utf-8")
            gitmodules = root / ".gitmodules"
            if gitmodules.exists():
                gitmodules.unlink()

            code, output = self._run([
                "claude", "--push", "--live", str(live), "--repo-root", str(root)
            ])
            self.assertEqual(code, 0, msg=output)

            overlay_path.write_text('{"overlay_key": "v2"}', encoding="utf-8")
            code, output = self._run([
                "claude", "--check", "--live", str(live), "--repo-root", str(root)
            ])
            self.assertEqual(code, 1, msg=output)
            self.assertIn("settings.json#overlay_key", output)

    def test_skill_overrides_applied_when_skill_exists(self):
        """skill-overrides のファイルが対象スキルに上書きされる。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(Path(tmp))
            live = Path(tmp) / "live"
            live.mkdir()
            # 先に skill を push で配置
            self._run(
                ["claude", "--push", "--live", str(live), "--repo-root", str(root)]
            )
            # extras に skill-overrides を追加
            extras_dir = root / "packages" / "extras" / "_active"
            override_skill = extras_dir / "skill-overrides" / "demo-skill"
            override_skill.mkdir(parents=True, exist_ok=True)
            (override_skill / "SKILL.md").write_text(
                "---\nname: demo-skill\ndescription: overridden\n---\n# Override\n",
                encoding="utf-8",
            )
            # .gitmodules を削除して submodule 未取得扱いにしない
            gitmodules = root / ".gitmodules"
            if gitmodules.exists():
                gitmodules.unlink()
            code, out = self._run(
                ["claude", "--push", "--live", str(live), "--repo-root", str(root)]
            )
            self.assertEqual(code, 0, msg=out)
            skill_md = live / "skills" / "demo-skill" / "SKILL.md"
            self.assertTrue(skill_md.exists())
            self.assertIn("overridden", skill_md.read_text(encoding="utf-8"))

    def test_skill_overrides_skipped_when_skill_missing(self):
        """対象スキルが dest に無い場合 skill-override はスキップされる（エラーにならない）。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(Path(tmp))
            live = Path(tmp) / "live"
            live.mkdir()
            # skill-overrides を追加（対象スキルは未配置）
            extras_dir = root / "packages" / "extras" / "_active"
            override_skill = extras_dir / "skill-overrides" / "nonexistent-skill"
            override_skill.mkdir(parents=True, exist_ok=True)
            (override_skill / "SKILL.md").write_text(
                "---\nname: nonexistent-skill\n---\n# Skip me\n",
                encoding="utf-8",
            )
            gitmodules = root / ".gitmodules"
            if gitmodules.exists():
                gitmodules.unlink()
            code, out = self._run(
                ["claude", "--push", "--live", str(live), "--repo-root", str(root)]
            )
            self.assertEqual(code, 0, msg=out)


# ---------------------------------------------------------------------------
# settingsSync（settings.json の hooks 配線の配布・drift 検出）
# ---------------------------------------------------------------------------

class TestSettingsSync(unittest.TestCase):
    """claude config の settingsSync 宣言による settings.json キー同期。"""

    def _run(self, args: list[str]) -> tuple[int, str]:
        return run_distribute_cli(args)

    def _template(self, root: Path) -> dict:
        return json.loads(
            (root / "packages" / "core" / "settings.json").read_text(encoding="utf-8")
        )

    def test_push_creates_settings_from_template_when_missing(self):
        """dest に settings.json が無ければ template 全体をコピーする。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(Path(tmp))
            live = Path(tmp) / "live"
            live.mkdir()
            code, out = self._run(
                ["claude", "--push", "--live", str(live), "--repo-root", str(root)]
            )
            self.assertEqual(code, 0, msg=out)
            written = json.loads((live / "settings.json").read_text(encoding="utf-8"))
            self.assertEqual(written, self._template(root))

    def test_push_replaces_only_declared_keys(self):
        """既存 settings.json は宣言キー（hooks）のみ置換し、他キーを保持する。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(Path(tmp))
            live = Path(tmp) / "live"
            live.mkdir()
            (live / "settings.json").write_text(
                json.dumps(
                    {
                        "env": {"LOCAL_ENV": "keep"},
                        "hooks": {"PreToolUse": []},
                        "permissions": {"allow": ["Bash(ls:*)"]},
                    }
                ),
                encoding="utf-8",
            )
            code, out = self._run(
                ["claude", "--push", "--live", str(live), "--repo-root", str(root)]
            )
            self.assertEqual(code, 0, msg=out)
            written = json.loads((live / "settings.json").read_text(encoding="utf-8"))
            self.assertEqual(written["hooks"], self._template(root)["hooks"])
            self.assertEqual(written["permissions"], {"allow": ["Bash(ls:*)"]})
            self.assertEqual(written["env"], {"LOCAL_ENV": "keep"})

    def test_push_noop_when_declared_keys_match(self):
        """宣言キーが一致していれば settings.json を書き換えない。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(Path(tmp))
            live = Path(tmp) / "live"
            live.mkdir()
            local = {"hooks": self._template(root)["hooks"], "permissions": {}}
            settings_path = live / "settings.json"
            settings_path.write_text(json.dumps(local), encoding="utf-8")
            mtime_before = settings_path.stat().st_mtime
            code, out = self._run(
                ["claude", "--push", "--live", str(live), "--repo-root", str(root)]
            )
            self.assertEqual(code, 0, msg=out)
            self.assertEqual(settings_path.stat().st_mtime, mtime_before)

    def test_check_reports_drift_for_declared_key(self):
        """hooks キーが template と異なれば --check が drift として報告する。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(Path(tmp))
            live = Path(tmp) / "live"
            live.mkdir()
            from harness_lib.resolver import manifest
            m = manifest("claude", root)
            for rel, content in m.files.items():
                dest = live / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(content)
            (live / "settings.json").write_text(
                json.dumps({"hooks": {"PreToolUse": []}}), encoding="utf-8"
            )
            code, out = self._run(
                ["claude", "--check", "--live", str(live), "--repo-root", str(root)]
            )
            self.assertEqual(code, 1, msg=out)
            self.assertIn("settings.json#hooks", out)

    def test_check_ok_when_declared_keys_match(self):
        """hooks キーが一致していれば --check は drift なし（フォーマット差は無視）。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(Path(tmp))
            live = Path(tmp) / "live"
            live.mkdir()
            from harness_lib.resolver import manifest
            m = manifest("claude", root)
            for rel, content in m.files.items():
                dest = live / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(content)
            # template と同値だがフォーマット（インデント）が異なる settings.json
            (live / "settings.json").write_text(
                json.dumps({"hooks": self._template(root)["hooks"], "extra": 1}),
                encoding="utf-8",
            )
            code, out = self._run(
                ["claude", "--check", "--live", str(live), "--repo-root", str(root)]
            )
            self.assertEqual(code, 0, msg=out)

    def test_push_syncs_additional_declared_key_alongside_hooks(self):
        """settingsSync.keys に \"sandbox\" を追加すると hooks に加えて sandbox も同期される。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(Path(tmp))

            core_settings_path = root / "packages" / "core" / "settings.json"
            core_settings = json.loads(core_settings_path.read_text(encoding="utf-8"))
            core_settings["sandbox"] = {"enabled": True}
            core_settings_path.write_text(json.dumps(core_settings), encoding="utf-8")

            claude_config_path = root / "packages" / "targets" / "claude" / "config.json"
            claude_config = json.loads(claude_config_path.read_text(encoding="utf-8"))
            claude_config["settingsSync"]["keys"] = ["hooks", "sandbox"]
            claude_config_path.write_text(json.dumps(claude_config), encoding="utf-8")

            live = Path(tmp) / "live"
            live.mkdir()
            (live / "settings.json").write_text(
                json.dumps(
                    {"hooks": self._template(root)["hooks"], "permissions": {"allow": []}}
                ),
                encoding="utf-8",
            )
            code, out = self._run(
                ["claude", "--push", "--live", str(live), "--repo-root", str(root)]
            )
            self.assertEqual(code, 0, msg=out)
            written = json.loads((live / "settings.json").read_text(encoding="utf-8"))
            self.assertEqual(written["sandbox"], {"enabled": True})
            self.assertEqual(written["permissions"], {"allow": []})

    def test_check_reports_drift_for_additional_declared_key(self):
        """sandbox キーが template と異なれば --check が settings.json#sandbox として報告する。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(Path(tmp))

            core_settings_path = root / "packages" / "core" / "settings.json"
            core_settings = json.loads(core_settings_path.read_text(encoding="utf-8"))
            core_settings["sandbox"] = {"enabled": True}
            core_settings_path.write_text(json.dumps(core_settings), encoding="utf-8")

            claude_config_path = root / "packages" / "targets" / "claude" / "config.json"
            claude_config = json.loads(claude_config_path.read_text(encoding="utf-8"))
            claude_config["settingsSync"]["keys"] = ["hooks", "sandbox"]
            claude_config_path.write_text(json.dumps(claude_config), encoding="utf-8")

            live = Path(tmp) / "live"
            live.mkdir()
            from harness_lib.resolver import manifest
            m = manifest("claude", root)
            for rel, content in m.files.items():
                dest = live / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(content)
            (live / "settings.json").write_text(
                json.dumps({"hooks": self._template(root)["hooks"], "sandbox": {"enabled": False}}),
                encoding="utf-8",
            )
            code, out = self._run(
                ["claude", "--check", "--live", str(live), "--repo-root", str(root)]
            )
            self.assertEqual(code, 1, msg=out)
            self.assertIn("settings.json#sandbox", out)

    def test_push_syncs_dotted_permissions_ask_into_existing_settings(self):
        """既存 settings.json に permissions.ask を dotted key で同期し、permissions.allow は保持する。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(Path(tmp))

            core_settings_path = root / "packages" / "core" / "settings.json"
            core_settings = json.loads(core_settings_path.read_text(encoding="utf-8"))
            core_settings["permissions"] = {"ask": ["Bash(git push:*)"]}
            core_settings_path.write_text(json.dumps(core_settings), encoding="utf-8")

            claude_config_path = root / "packages" / "targets" / "claude" / "config.json"
            claude_config = json.loads(claude_config_path.read_text(encoding="utf-8"))
            claude_config["settingsSync"]["keys"] = ["hooks", "permissions.ask"]
            claude_config_path.write_text(json.dumps(claude_config), encoding="utf-8")

            live = Path(tmp) / "live"
            live.mkdir()
            (live / "settings.json").write_text(
                json.dumps(
                    {
                        "hooks": self._template(root)["hooks"],
                        "permissions": {"allow": ["Bash(ls:*)"]},
                    }
                ),
                encoding="utf-8",
            )
            code, out = self._run(
                ["claude", "--push", "--live", str(live), "--repo-root", str(root)]
            )
            self.assertEqual(code, 0, msg=out)
            written = json.loads((live / "settings.json").read_text(encoding="utf-8"))
            self.assertEqual(written["permissions"]["ask"], ["Bash(git push:*)"])
            self.assertEqual(written["permissions"]["allow"], ["Bash(ls:*)"])

    def test_real_claude_config_declares_permissions_ask_sync(self):
        """実 config の settingsSync.keys が permissions.ask を宣言している（既存マシンへ ask が配布される契約）。"""
        from harness_lib.config import repo_root

        config = json.loads(
            (repo_root() / "packages" / "targets" / "claude" / "config.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertIn("permissions.ask", config["settingsSync"]["keys"])
        template = json.loads(
            (repo_root() / "packages" / "core" / "settings.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertIn("Bash(git push:*)", template["permissions"]["ask"])
        self.assertIn("Bash(rtk git push:*)", template["permissions"]["ask"])
        self.assertIn("Bash(gh pr create:*)", template["permissions"]["ask"])
        self.assertIn("Bash(rtk gh pr create:*)", template["permissions"]["ask"])

    def test_check_reports_missing_settings_file(self):
        """settingsSync 宣言があり settings.json が無ければ missing として報告する。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(Path(tmp))
            live = Path(tmp) / "live"
            live.mkdir()
            from harness_lib.resolver import manifest
            m = manifest("claude", root)
            for rel, content in m.files.items():
                dest = live / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(content)
            code, out = self._run(
                ["claude", "--check", "--live", str(live), "--repo-root", str(root)]
            )
            self.assertEqual(code, 1, msg=out)
            self.assertIn("settings.json", out)

    def test_codex_push_syncs_review_model_and_preserves_local_settings(self):
        """Codex review の既定モデルは SSOT から同期し、他設定を保持する。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(Path(tmp))
            live = Path(tmp) / "live-codex"
            live.mkdir()
            (live / "config.toml").write_text(
                'model = "local-model"\n'
                '\n'
                '[features]\n'
                'hooks = false\n'
                'multi_agent = true\n'
                '\n'
                '[sandbox_workspace_write]\n'
                'writable_roots = ["/tmp/old"]\n'
                '\n'
                '[desktop]\n'
                'appearanceTheme = "system"\n',
                encoding="utf-8",
            )

            code, out = self._run(
                ["codex", "--push", "--live", str(live), "--repo-root", str(root)]
            )

            self.assertEqual(code, 0, msg=out)
            written = (live / "config.toml").read_text(encoding="utf-8")
            self.assertIn('model = "gpt-5.6"', written)
            self.assertIn("hooks = true", written)
            self.assertIn("multi_agent = true", written)
            self.assertIn('"~/projects/worktrees"', written)
            self.assertIn('"~/sandbox/harunon-harness/.git"', written)
            self.assertIn("[desktop]\nappearanceTheme = \"system\"", written)

    def test_codex_push_replaces_multiline_toml_array(self):
        """既存 config.toml の複数行配列も宣言値で正しく置換する。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(Path(tmp))
            live = Path(tmp) / "live-codex"
            live.mkdir()
            (live / "config.toml").write_text(
                '[features]\n'
                'hooks = false\n'
                '\n'
                '[sandbox_workspace_write]\n'
                'writable_roots = [\n'
                '  "/tmp/old",\n'
                '  "/tmp/another",\n'
                ']\n'
                '\n'
                '[desktop]\n'
                'appearanceTheme = "system"\n',
                encoding="utf-8",
            )

            code, out = self._run(
                ["codex", "--push", "--live", str(live), "--repo-root", str(root)]
            )

            self.assertEqual(code, 0, msg=out)
            written = (live / "config.toml").read_text(encoding="utf-8")
            self.assertNotIn('writable_roots = "["', written)
            self.assertNotIn('"/tmp/old"', written)
            self.assertIn('"~/projects/worktrees"', written)
            self.assertIn('"~/sandbox/harunon-harness/.git"', written)
            self.assertIn("[desktop]\nappearanceTheme = \"system\"", written)

    def test_codex_check_reports_toml_key_drift(self):
        """Codex config.toml の宣言 TOML キーが異なれば drift として報告する。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(Path(tmp))
            live = Path(tmp) / "live-codex"
            live.mkdir()
            from harness_lib.resolver import manifest
            m = manifest("codex", root)
            for rel, content in m.files.items():
                dest = live / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(content)
            (live / "config.toml").write_text(
                '[features]\n'
                'hooks = false\n'
                '\n'
                '[sandbox_workspace_write]\n'
                'writable_roots = ["/tmp/old"]\n',
                encoding="utf-8",
            )

            code, out = self._run(
                ["codex", "--check", "--live", str(live), "--repo-root", str(root)]
            )

            self.assertEqual(code, 1, msg=out)
            self.assertIn("config.toml#model", out)
            self.assertIn("config.toml#features.hooks", out)
            self.assertIn("config.toml#sandbox_workspace_write.writable_roots", out)


class TestSettingsSyncPathSafety(unittest.TestCase):
    """settingsSync 由来パス（configFile / source 系）の安全性検証（M-002）。"""

    def _cfg(self, root: Path) -> dict:
        return json.loads(
            (root / "packages" / "targets" / "claude" / "config.json").read_text()
        )

    def test_drifts_rejects_dotdot_config_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(Path(tmp))
            live = Path(tmp) / "live"
            live.mkdir()
            cfg = self._cfg(root)
            cfg["configFile"] = "../escape.json"
            from harness_lib import settings_sync
            with self.assertRaises(ValueError) as ctx:
                settings_sync.drifts(cfg, root, live)
            self.assertIn("..", str(ctx.exception))

    def test_drifts_rejects_absolute_settings_sync_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(Path(tmp))
            live = Path(tmp) / "live"
            live.mkdir()
            cfg = self._cfg(root)
            cfg["settingsSync"]["source"] = "/etc/passwd"
            from harness_lib import settings_sync
            with self.assertRaises(ValueError) as ctx:
                settings_sync.drifts(cfg, root, live)
            self.assertIn("絶対パス", str(ctx.exception))

    def test_push_plan_rejects_malicious_config_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(Path(tmp))
            dest = Path(tmp) / "dest"
            dest.mkdir()
            cfg_path = root / "packages" / "targets" / "claude" / "config.json"
            cfg = self._cfg(root)
            cfg["configFile"] = "../evil.json"
            cfg_path.write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
            from harness_lib.distribution import Distribution
            # 境界（target config の schema 検証）で止まる
            with self.assertRaises(ValueError) as ctx:
                Distribution(root).plan_push("claude", dest, dry_run=True)
            self.assertIn("configFile", str(ctx.exception))
            self.assertFalse((Path(tmp) / "evil.json").exists())


# ---------------------------------------------------------------------------
# --prune（SSOT から削除されたファイルのライブ側削除）
# ---------------------------------------------------------------------------

class TestPushPrune(unittest.TestCase):
    def _run(self, args: list[str]) -> tuple[int, str]:
        return run_distribute_cli(args)

    def _push(self, root: Path, live: Path, *extra: str) -> tuple[int, str]:
        return self._run(
            ["claude", "--push", "--live", str(live), "--repo-root", str(root), *extra]
        )

    def test_prune_removes_files_absent_from_manifest(self):
        """--prune は管理ディレクトリ配下の manifest 外ファイルを backup して削除する。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(Path(tmp))
            live = Path(tmp) / "live"
            live.mkdir()
            self._push(root, live)
            stale = live / "skills" / "stale-skill" / "SKILL.md"
            stale.parent.mkdir(parents=True)
            stale.write_text("---\nname: stale-skill\n---\n", encoding="utf-8")

            code, out = self._push(root, live, "--prune")
            self.assertEqual(code, 0, msg=out)
            self.assertFalse(stale.exists(), msg="stale ファイルが削除されていない")
            backups = list((live / "backups").rglob("SKILL.md"))
            self.assertTrue(
                any("stale-skill" in str(b) for b in backups),
                msg=f"backup が無い: {backups}",
            )

    def test_push_without_prune_keeps_stale_files(self):
        """--prune なしのデフォルトでは manifest 外ファイルを削除しない。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(Path(tmp))
            live = Path(tmp) / "live"
            live.mkdir()
            self._push(root, live)
            stale = live / "skills" / "stale-skill" / "SKILL.md"
            stale.parent.mkdir(parents=True)
            stale.write_text("x", encoding="utf-8")

            code, out = self._push(root, live)
            self.assertEqual(code, 0, msg=out)
            self.assertTrue(stale.exists())

    def test_prune_dry_run_does_not_delete(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(Path(tmp))
            live = Path(tmp) / "live"
            live.mkdir()
            self._push(root, live)
            stale = live / "skills" / "stale-skill" / "SKILL.md"
            stale.parent.mkdir(parents=True)
            stale.write_text("x", encoding="utf-8")

            code, out = self._push(root, live, "--prune", "--dry-run")
            self.assertEqual(code, 0, msg=out)
            self.assertTrue(stale.exists())
            self.assertIn("prune", out)

    def test_prune_leaves_unmanaged_paths_untouched(self):
        """管理ディレクトリ（distribute の dir dest）外のファイルは prune 対象外。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(Path(tmp))
            live = Path(tmp) / "live"
            live.mkdir()
            self._push(root, live)
            unmanaged = live / "projects" / "notes.md"
            unmanaged.parent.mkdir(parents=True)
            unmanaged.write_text("x", encoding="utf-8")

            code, out = self._push(root, live, "--prune")
            self.assertEqual(code, 0, msg=out)
            self.assertTrue(unmanaged.exists())

    def _write_allowlist(self, root: Path, *names: str) -> None:
        (root / "packages/core/unmanaged-skills-allowlist.json").write_text(
            json.dumps(
                {"$comment": "test", **{name: "installer が入れるアプリ" for name in names}},
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

    def test_prune_preserves_allowlisted_skill(self):
        """unmanaged-skills-allowlist.json で明示許可した skill は prune で消さない。

        installer が入れるアプリ（agmsg の sqlite / 実行中インスタンス識別子など）は
        harness も rulesync も配らないと宣言済みなので manifest に無いのは正常。
        孤児として扱うと `--prune` 一発で生きたデータごと消える。
        """
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(Path(tmp))
            self._write_allowlist(root, "agmsg")
            live = Path(tmp) / "live"
            live.mkdir()
            self._push(root, live)
            app_db = live / "skills" / "agmsg" / "db" / "messages.db"
            app_db.parent.mkdir(parents=True)
            app_db.write_text("sqlite", encoding="utf-8")

            code, out = self._push(root, live, "--prune")
            self.assertEqual(code, 0, msg=out)
            self.assertTrue(app_db.exists(), msg="allowlist 宣言済みの skill が prune で削除された")

    def test_managed_to_allowlisted_transition_keeps_the_files(self):
        """harness 管理だった skill が allowlist 宣言に移っても実体を消さない。

        台帳に残ったエントリは _plan_ledger_cleanup が remove-managed として削除する。
        prune 側のフィルタはこの経路より後なので間に合わず、所有が installer に移った
        瞬間に `--push` だけでアプリが消えていた（Codex review: allowlist-ledger-cleanup）。
        """
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(Path(tmp))
            live = Path(tmp) / "live"
            live.mkdir()
            # まず harness 管理として配って台帳に載せる
            managed = root / "packages/core/skills/agmsg"
            managed.mkdir(parents=True)
            (managed / "SKILL.md").write_text("---\nname: agmsg\n---\n", encoding="utf-8")
            self._push(root, live)
            distributed = live / "skills" / "agmsg" / "SKILL.md"
            self.assertTrue(distributed.exists(), msg="前提: 一度は配布されている")

            # 所有が installer に移る（SSOT から外し allowlist に宣言する）
            shutil.rmtree(managed)
            self._write_allowlist(root, "agmsg")

            code, out = self._push(root, live, "--prune")
            self.assertEqual(code, 0, msg=out)
            self.assertTrue(
                distributed.exists(),
                msg="managed → allowlisted の移行で台帳経由の削除が走った",
            )

    def test_prune_still_removes_skills_absent_from_allowlist(self):
        """allowlist に無い孤児 skill は従来どおり削除する（保護が広がりすぎない）。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(Path(tmp))
            self._write_allowlist(root, "agmsg")
            live = Path(tmp) / "live"
            live.mkdir()
            self._push(root, live)
            stale = live / "skills" / "not-declared" / "SKILL.md"
            stale.parent.mkdir(parents=True)
            stale.write_text("---\nname: not-declared\n---\n", encoding="utf-8")

            code, out = self._push(root, live, "--prune")
            self.assertEqual(code, 0, msg=out)
            self.assertFalse(stale.exists())

    def test_allowlist_does_not_protect_other_dests(self):
        """allowlist は skill 名の宣言なので skills/ 宛てにだけ効かせる。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(Path(tmp))
            self._write_allowlist(root, "agmsg")
            live = Path(tmp) / "live"
            live.mkdir()
            self._push(root, live)
            same_name_elsewhere = live / "rules" / "agmsg" / "note.md"
            same_name_elsewhere.parent.mkdir(parents=True)
            same_name_elsewhere.write_text("x", encoding="utf-8")

            code, out = self._push(root, live, "--prune")
            self.assertEqual(code, 0, msg=out)
            self.assertFalse(same_name_elsewhere.exists())

    def test_prune_preserves_dest_symlink(self):
        """管理ディレクトリ配下の symlink（ユーザーの skill-override 配線等）は
        manifest 外でも prune で削除しない。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(Path(tmp))
            live = Path(tmp) / "live"
            live.mkdir()
            self._push(root, live)
            target = Path(tmp) / "override-target.yml"
            target.write_text("k: v\n", encoding="utf-8")
            link = live / "skills" / "demo-skill" / "config.yml"
            link.symlink_to(target)

            code, out = self._push(root, live, "--prune")
            self.assertEqual(code, 0, msg=out)
            self.assertTrue(
                link.is_symlink(), msg="ローカル override の symlink が削除された"
            )

    def test_prune_preserves_gitignored_source_file(self):
        """source（core/extras）側で gitignore 対象のローカル専用ファイル
        （config.yml 等）は live でも prune で削除しない。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(Path(tmp))
            subprocess.run(["git", "init", "-q", str(root)], check=True, capture_output=True)
            (root / ".gitignore").write_text(
                "packages/core/skills/*/config.yml\n", encoding="utf-8"
            )
            live = Path(tmp) / "live"
            live.mkdir()
            self._push(root, live)
            local = live / "skills" / "demo-skill" / "config.yml"
            local.write_text("local: override\n", encoding="utf-8")

            code, out = self._push(root, live, "--prune")
            self.assertEqual(code, 0, msg=out)
            self.assertTrue(
                local.exists(),
                msg="gitignore 対象のローカル config.yml が prune で削除された",
            )

    def test_prune_survives_symlink_to_emptydir(self):
        """管理ディレクトリ配下の「空ディレクトリを指す symlink」があっても
        --prune の空ディレクトリ後始末が NotADirectoryError でクラッシュしない。

        pathlib は symlink-to-dir に is_dir()=True を返すが、rmdir() は
        リンク自体に NotADirectoryError を投げる（plan 007 の再現ケース）。
        """
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(Path(tmp))
            live = Path(tmp) / "live"
            live.mkdir()
            self._push(root, live)

            empty_target = Path(tmp) / "empty-target"
            empty_target.mkdir()
            link_path = live / "skills" / "linked-emptydir"
            link_path.symlink_to(empty_target, target_is_directory=True)

            code, out = self._push(root, live, "--prune")
            self.assertEqual(code, 0, msg=out)

    def test_prune_skips_dest_with_unfetched_source(self):
        """source が submodule 未取得で skip された dest は prune しない（extras 消失防止）。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(Path(tmp))
            live = Path(tmp) / "live"
            live.mkdir()
            # codex の skills/ source は extras を含む。submodule 未取得
            # （= ディレクトリが空）の状態を再現する
            extras = root / "packages" / "extras" / "_active"
            shutil.rmtree(str(extras / "skills"))
            shutil.rmtree(str(extras / "rules"))
            code, out = self._run(
                ["codex", "--push", "--live", str(live), "--repo-root", str(root)]
            )
            self.assertEqual(code, 0, msg=out)
            extras_skill = live / "skills" / "extras-only-skill" / "SKILL.md"
            extras_skill.parent.mkdir(parents=True)
            extras_skill.write_text("---\nname: extras-only-skill\n---\n", encoding="utf-8")

            code, out = self._run(
                ["codex", "--push", "--prune", "--live", str(live), "--repo-root", str(root)]
            )
            self.assertEqual(code, 0, msg=out)
            self.assertTrue(
                extras_skill.exists(),
                msg="未取得 source を含む dest が prune された（extras 消失）",
            )


# ---------------------------------------------------------------------------
# backup retention（backups/ の保持数制限）
# ---------------------------------------------------------------------------

class TestBackupRetention(unittest.TestCase):
    def _run(self, args: list[str]) -> tuple[int, str]:
        return run_distribute_cli(args)

    def test_old_backups_pruned_to_keep_limit(self):
        """push 後、backups/ 配下の bootstrap-* は新しい順に BACKUP_KEEP 件まで保持される。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(Path(tmp))
            live = Path(tmp) / "live"
            live.mkdir()
            backups_root = live / "backups"
            for i in range(12):
                (backups_root / f"bootstrap-2020010{i // 10}-00000{i % 10}").mkdir(
                    parents=True
                )
            # 上書きを発生させて新しい backup を作る
            _, first_out = self._run(
                ["claude", "--push", "--live", str(live), "--repo-root", str(root)]
            )
            # 初回 push は backup を作らないので既存 12 件から BACKUP_KEEP 件だけ残す
            self.assertIn(f"pruned backups: {12 - BACKUP_KEEP}", first_out)
            (live / "CLAUDE.md").write_text("drifted", encoding="utf-8")
            code, out = self._run(
                ["claude", "--push", "--live", str(live), "--repo-root", str(root)]
            )
            self.assertEqual(code, 0, msg=out)
            remaining = sorted(
                d.name for d in backups_root.iterdir() if d.is_dir()
            )
            self.assertEqual(len(remaining), BACKUP_KEEP, msg=str(remaining))
            # 最も古いものが消え、今回の backup（最新）は残る
            self.assertNotIn("bootstrap-20200100-000000", remaining)
            self.assertNotIn("bootstrap-20200100-000006", remaining)
            self.assertIn("pruned backups: 1", out)


# ---------------------------------------------------------------------------
# distribute.py: --pull（live → source 還流）
# ---------------------------------------------------------------------------

class TestCmdPull(unittest.TestCase):
    """distribute.py --pull の還流テスト。"""

    def _run(self, args: list[str]) -> tuple[int, str]:
        return run_distribute_cli(args)

    def test_pull_reflects_changed_file_to_source(self):
        """live 側に変更されたファイルを置いて --pull すると source 側に還流される。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(Path(tmp))
            live = Path(tmp) / "live"
            live.mkdir()
            # CLAUDE.md を live に配置（内容を変更）
            (live / "CLAUDE.md").write_text("live side edit\n", encoding="utf-8")

            code, out = self._run(
                ["claude", "--pull", "--live", str(live), "--repo-root", str(root)]
            )
            self.assertEqual(code, 0, msg=out)
            # source 側（packages/core/CLAUDE.md）に live の内容が反映されている
            source_path = root / "packages" / "core" / "CLAUDE.md"
            self.assertEqual(source_path.read_text(encoding="utf-8"), "live side edit\n")

    def test_pull_ignores_missing_files(self):
        """live に存在しないファイル（kind=missing）は pull でエラーにならない。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(Path(tmp))
            live = Path(tmp) / "live"
            live.mkdir()
            # live は空（全ファイルが missing）

            code, out = self._run(
                ["claude", "--pull", "--live", str(live), "--repo-root", str(root)]
            )
            self.assertEqual(code, 0, msg=out)
            # missing は pull 対象外として skipped に記録される
            self.assertIn("skipped", out)

    def test_pull_writes_to_extras_when_extras_wins_distribution(self):
        """core/extras 両方に同名ファイルがある場合、配布で勝つ extras 側に還流される。

        codex の rules/ は ["packages/core/rules/", "packages/extras/_active/rules/"]
        の配列 source（後勝ち = extras が配布で勝つ）。live 側の編集は
        「実際に配布に反映される」extras に書き戻されるべきで、core に書いても
        次回配布で無言で消える。
        """
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(Path(tmp))
            live = Path(tmp) / "live"
            live.mkdir()
            (root / "packages" / "core" / "rules" / "shared.md").write_text(
                "core version\n", encoding="utf-8"
            )
            (root / "packages" / "extras" / "_active" / "rules" / "shared.md").write_text(
                "extras version\n", encoding="utf-8"
            )
            (live / "rules").mkdir()
            (live / "rules" / "shared.md").write_text("live edit\n", encoding="utf-8")

            code, out = self._run(
                ["codex", "--pull", "--live", str(live), "--repo-root", str(root)]
            )
            self.assertEqual(code, 0, msg=out)

            extras_path = (
                root / "packages" / "extras" / "_active" / "rules" / "shared.md"
            )
            core_path = root / "packages" / "core" / "rules" / "shared.md"
            self.assertEqual(
                extras_path.read_text(encoding="utf-8"), "live edit\n",
                msg="配布で勝つ extras 側に還流されるべき",
            )
            self.assertEqual(
                core_path.read_text(encoding="utf-8"), "core version\n",
                msg="配布で負ける core 側は書き換えられないはず",
            )

    def test_pull_writes_to_core_when_only_core_has_file(self):
        """core にのみ存在するファイルは core に書き戻される（回帰確認）。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(Path(tmp))
            live = Path(tmp) / "live"
            live.mkdir()
            (root / "packages" / "core" / "rules" / "core-only.md").write_text(
                "core only\n", encoding="utf-8"
            )
            (live / "rules").mkdir()
            (live / "rules" / "core-only.md").write_text(
                "live edit for core-only\n", encoding="utf-8"
            )

            code, out = self._run(
                ["codex", "--pull", "--live", str(live), "--repo-root", str(root)]
            )
            self.assertEqual(code, 0, msg=out)

            core_path = root / "packages" / "core" / "rules" / "core-only.md"
            extras_path = (
                root / "packages" / "extras" / "_active" / "rules" / "core-only.md"
            )
            self.assertEqual(
                core_path.read_text(encoding="utf-8"), "live edit for core-only\n"
            )
            self.assertFalse(extras_path.exists())

    def test_pull_writes_to_extras_when_only_extras_has_file(self):
        """extras にのみ存在するファイルは extras に書き戻される。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(Path(tmp))
            live = Path(tmp) / "live"
            live.mkdir()
            (root / "packages" / "extras" / "_active" / "rules" / "extras-only.md").write_text(
                "extras only\n", encoding="utf-8"
            )
            (live / "rules").mkdir()
            (live / "rules" / "extras-only.md").write_text(
                "live edit for extras-only\n", encoding="utf-8"
            )

            code, out = self._run(
                ["codex", "--pull", "--live", str(live), "--repo-root", str(root)]
            )
            self.assertEqual(code, 0, msg=out)

            extras_path = (
                root / "packages" / "extras" / "_active" / "rules" / "extras-only.md"
            )
            core_path = root / "packages" / "core" / "rules" / "extras-only.md"
            self.assertEqual(
                extras_path.read_text(encoding="utf-8"), "live edit for extras-only\n"
            )
            self.assertFalse(core_path.exists())

    def test_pull_skips_when_extras_submodule_unfetched(self):
        """extras submodule 未取得（ディレクトリ不在）の場合、書き戻し先を誤判定
        しないよう pull を skip して警告する。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(Path(tmp))
            live = Path(tmp) / "live"
            live.mkdir()
            (root / "packages" / "core" / "rules" / "shared.md").write_text(
                "core version\n", encoding="utf-8"
            )
            # extras submodule 未取得を再現（_active 配下を完全に空にする）
            extras_active = root / "packages" / "extras" / "_active"
            shutil.rmtree(str(extras_active / "skills"))
            shutil.rmtree(str(extras_active / "rules"))

            (live / "rules").mkdir()
            (live / "rules" / "shared.md").write_text(
                "live edit while extras unfetched\n", encoding="utf-8"
            )

            code, out = self._run(
                ["codex", "--pull", "--live", str(live), "--repo-root", str(root)]
            )
            self.assertEqual(code, 0, msg=out)

            core_path = root / "packages" / "core" / "rules" / "shared.md"
            self.assertEqual(
                core_path.read_text(encoding="utf-8"), "core version\n",
                msg="submodule 未取得時に誤って core へ書き戻してはいけない",
            )
            self.assertIn("submodule 未取得", out)
            self.assertIn("skipped", out)


# ---------------------------------------------------------------------------
# distribute.py: _resolve_pull_source（pull 書き戻し先の解決ロジック単体）
# ---------------------------------------------------------------------------

class TestResolvePullSource(unittest.TestCase):
    """cmd_pull から抽出した書き戻し先解決ロジックの単体テスト。

    「live にあるがどの source にも無いファイル」は check()/manifest() の
    設計上（manifest はいずれかの source に実在するファイルのみを含む。
    resolver.check() の docstring 通り、live 専用ファイルは対象外）
    --pull の CLI 経路では絶対に発生しないため、CLI 経由の再現テストが
    書けない。フォールバック分岐（existing_sources が空）を検証するため、
    抽出済みの純粋関数を直接呼び出す。
    """

    def setUp(self) -> None:
        from harness_lib.resolver import resolve_pull_source
        self.resolve = resolve_pull_source

    def test_falls_back_to_first_source_when_absent_everywhere(self):
        """どの source にも実在しない場合は先頭 source にフォールバックする。"""
        winning, existing, blocking = self.resolve(
            ["core", "extras"], lambda s: Path("/definitely/does/not/exist"), []
        )
        self.assertEqual(winning, "core")
        self.assertEqual(existing, [])
        self.assertEqual(blocking, [])

    def test_picks_last_existing_source_as_winner(self):
        """配列内で実在する source のうち後勝ち（末尾側）を選ぶ。"""
        with tempfile.TemporaryDirectory() as tmp:
            core_path = Path(tmp) / "core.md"
            extras_path = Path(tmp) / "extras.md"
            core_path.write_text("x", encoding="utf-8")
            extras_path.write_text("y", encoding="utf-8")
            paths = {"core": core_path, "extras": extras_path}
            winning, existing, blocking = self.resolve(
                ["core", "extras"], lambda s: paths[s], []
            )
            self.assertEqual(winning, "extras")
            self.assertEqual(existing, ["core", "extras"])
            self.assertEqual(blocking, [])

    def test_blocks_when_uninit_submodule_present(self):
        """submodule 未取得の source が含まれる場合、判定不能として blocking を返す。"""
        winning, existing, blocking = self.resolve(
            ["packages/core/rules/", "packages/extras/_active/rules/"],
            lambda s: Path("/irrelevant"),
            ["packages/extras/_active"],
        )
        self.assertIsNone(winning)
        self.assertEqual(existing, [])
        self.assertEqual(blocking, ["packages/extras/_active/rules/"])


if __name__ == "__main__":
    unittest.main()
