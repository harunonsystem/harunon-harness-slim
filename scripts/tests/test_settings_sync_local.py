#!/usr/bin/env python3
"""distribute.py の settingsSync localSource / localKeys 機能テスト。"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from tests._helpers import make_repo, run_distribute_cli  # noqa: E402


def _write_codex_config_with_local(repo: Path, local_keys: list | None = None) -> None:
    """codex config.json に localSource / localKeys を追加し、SSOT keys から localKeys に移動する。

    _helpers.make_repo の codex config は sandbox_workspace_write.writable_roots を
    SSOT keys に持つが、local override テストでは localKeys 専用にする必要がある。
    """
    cfg_path = repo / "packages" / "targets" / "codex" / "config.json"
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    cfg["settingsSync"]["localSource"] = "packages/targets/codex/config.local.toml"
    if local_keys is not None:
        cfg["settingsSync"]["localKeys"] = local_keys
        # SSOT keys から localKeys に移動したキーを除外する
        cfg["settingsSync"]["keys"] = [
            k for k in cfg["settingsSync"]["keys"] if k not in local_keys
        ]
    cfg_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_local_toml(repo: Path, writable_roots: list) -> None:
    """packages/targets/codex/config.local.toml を作成する。"""
    roots = "\n".join(f'  "{p}",' for p in writable_roots)
    content = (
        "# machine-local\n"
        "[sandbox_workspace_write]\n"
        "writable_roots = [\n"
        f"{roots}\n"
        "]\n"
    )
    (repo / "packages" / "targets" / "codex" / "config.local.toml").write_text(
        content, encoding="utf-8"
    )


def _write_live_config_toml(live_dir: Path, text: str) -> None:
    live_dir.mkdir(parents=True, exist_ok=True)
    (live_dir / "config.toml").write_text(text, encoding="utf-8")


class LocalOverridePresentTestCase(unittest.TestCase):
    """config.local.toml が存在するとき localKeys が live にマージされる。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = make_repo(Path(self._tmp.name))

    def tearDown(self):
        self._tmp.cleanup()

    def test_local_keys_merged_into_live(self):
        """config.local.toml が存在 → localKeys の値が live config.toml に書き込まれる。"""
        _write_codex_config_with_local(
            self.repo,
            local_keys=["sandbox_workspace_write.writable_roots"],
        )
        _write_local_toml(self.repo, ["/my/worktrees", "/my/repo/.git"])

        live_dir = Path(self.repo / "live" / "codex")
        _write_live_config_toml(
            live_dir,
            (
                'model = "gpt-5.5"\n'
                "\n"
                "[features]\n"
                "hooks = true\n"
                "\n"
                "[sandbox_workspace_write]\n"
                'writable_roots = ["/old/path"]\n'
            ),
        )

        exit_code, output = run_distribute_cli([
            "codex", "--push",
            "--live", str(live_dir),
            "--repo-root", str(self.repo),
        ])
        self.assertEqual(exit_code, 0, msg=output)

        live_text = (live_dir / "config.toml").read_text(encoding="utf-8")
        self.assertIn("/my/worktrees", live_text)
        self.assertIn("/my/repo/.git", live_text)
        self.assertNotIn("/old/path", live_text)

    def test_remove_keys_deletes_obsolete_toml_key_and_table(self):
        """removeKeys は既存 TOML の retired key/section を削除し、他を保持する。"""
        cfg_path = self.repo / "packages" / "targets" / "codex" / "config.json"
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        cfg["settingsSync"]["removeKeys"] = [
            "features.voice_transcription",
            "features.network_proxy",
            "model_catalog_json",
        ]
        cfg_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
        live_dir = Path(self.repo / "live" / "codex")

        _write_live_config_toml(
            live_dir,
            (
                'model = "gpt-5.5"\n'
                'model_catalog_json = "/tmp/stale-catalog.json"\n'
                "\n"
                "[features]\n"
                "hooks = true\n"
                "voice_transcription = true\n"
                "\n"
                "[features.network_proxy]\n"
                "enabled = false\n"
            ),
        )
        exit_code, output = run_distribute_cli([
            "codex", "--push", "--live", str(live_dir), "--repo-root", str(self.repo),
        ])

        self.assertEqual(exit_code, 0, msg=output)
        written = (live_dir / "config.toml").read_text(encoding="utf-8")
        self.assertNotIn("voice_transcription", written)
        self.assertNotIn("[features.network_proxy]", written)
        self.assertNotIn("model_catalog_json", written)
        self.assertIn("hooks = true", written)

    def test_ssot_keys_still_synced_when_local_present(self):
        """localSource が存在しても SSOT keys（features.hooks）は通常どおり同期される。"""
        _write_codex_config_with_local(
            self.repo,
            local_keys=["sandbox_workspace_write.writable_roots"],
        )
        _write_local_toml(self.repo, ["/my/worktrees"])

        live_dir = Path(self.repo / "live" / "codex")
        _write_live_config_toml(
            live_dir,
            (
                'model = "gpt-5.5"\n'
                "\n"
                "[features]\n"
                "hooks = false\n"  # SSOT は true → drift
                "\n"
                "[sandbox_workspace_write]\n"
                'writable_roots = ["/my/worktrees"]\n'
            ),
        )

        exit_code, output = run_distribute_cli([
            "codex", "--push",
            "--live", str(live_dir),
            "--repo-root", str(self.repo),
        ])
        self.assertEqual(exit_code, 0, msg=output)

        live_text = (live_dir / "config.toml").read_text(encoding="utf-8")
        # features.hooks が true に同期されていること
        self.assertIn("hooks = true", live_text)


class LocalOverrideAbsentTestCase(unittest.TestCase):
    """config.local.toml が不在のとき、エラーにならず SSOT keys は通常どおり同期される。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = make_repo(Path(self._tmp.name))

    def tearDown(self):
        self._tmp.cleanup()

    def test_no_error_when_local_absent(self):
        """config.local.toml が不在 → エラーにならない。"""
        _write_codex_config_with_local(
            self.repo,
            local_keys=["sandbox_workspace_write.writable_roots"],
        )
        # config.local.toml を作らない

        live_dir = Path(self.repo / "live" / "codex")
        _write_live_config_toml(
            live_dir,
            (
                'model = "gpt-5.5"\n'
                "\n"
                "[features]\n"
                "hooks = true\n"
                "\n"
                "[sandbox_workspace_write]\n"
                'writable_roots = ["/existing/path"]\n'
            ),
        )

        exit_code, output = run_distribute_cli([
            "codex", "--push",
            "--live", str(live_dir),
            "--repo-root", str(self.repo),
        ])
        self.assertEqual(exit_code, 0, msg=output)

    def test_ssot_keys_synced_when_local_absent(self):
        """config.local.toml が不在でも SSOT keys（features.hooks）は同期される。"""
        _write_codex_config_with_local(
            self.repo,
            local_keys=["sandbox_workspace_write.writable_roots"],
        )
        # config.local.toml を作らない

        live_dir = Path(self.repo / "live" / "codex")
        _write_live_config_toml(
            live_dir,
            (
                'model = "gpt-5.5"\n'
                "\n"
                "[features]\n"
                "hooks = false\n"  # SSOT は true → drift
                "\n"
                "[sandbox_workspace_write]\n"
                'writable_roots = ["/existing/path"]\n'
            ),
        )

        exit_code, output = run_distribute_cli([
            "codex", "--push",
            "--live", str(live_dir),
            "--repo-root", str(self.repo),
        ])
        self.assertEqual(exit_code, 0, msg=output)

        live_text = (live_dir / "config.toml").read_text(encoding="utf-8")
        self.assertIn("hooks = true", live_text)
        # local が不在なので writable_roots は変わらない
        self.assertIn("/existing/path", live_text)


class LocalDriftDetectionTestCase(unittest.TestCase):
    """config.local.toml が存在するとき、live との差分が drift として検出される。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = make_repo(Path(self._tmp.name))

    def tearDown(self):
        self._tmp.cleanup()

    def _push_codex(self, live_dir: Path) -> None:
        """--push で live_dir を初期化する（distribute ファイルを配置してから check する前提）。"""
        exit_code, output = run_distribute_cli([
            "codex", "--push",
            "--live", str(live_dir),
            "--repo-root", str(self.repo),
        ])
        self.assertEqual(exit_code, 0, msg=output)

    def test_drift_detected_when_local_differs_from_live(self):
        """local ファイルと live の localKeys が異なれば Drift が返る。"""
        _write_codex_config_with_local(
            self.repo,
            local_keys=["sandbox_workspace_write.writable_roots"],
        )
        # push で live_dir を一旦 /new/worktrees で同期
        _write_local_toml(self.repo, ["/new/worktrees"])
        live_dir = Path(self.repo / "live" / "codex")
        self._push_codex(live_dir)

        # local を別の値に差し替えて drift を作る
        _write_local_toml(self.repo, ["/changed/worktrees"])

        exit_code, output = run_distribute_cli([
            "codex", "--check",
            "--live", str(live_dir),
            "--repo-root", str(self.repo),
        ])
        # drift あり → exit 1
        self.assertEqual(exit_code, 1, msg=output)
        self.assertIn("sandbox_workspace_write.writable_roots", output)

    def test_no_drift_when_local_matches_live(self):
        """local ファイルと live の localKeys が一致すれば Drift なし。"""
        _write_codex_config_with_local(
            self.repo,
            local_keys=["sandbox_workspace_write.writable_roots"],
        )
        _write_local_toml(self.repo, ["/my/worktrees"])

        live_dir = Path(self.repo / "live" / "codex")
        # push で live_dir に /my/worktrees を書き込み → check では一致する
        self._push_codex(live_dir)

        exit_code, output = run_distribute_cli([
            "codex", "--check",
            "--live", str(live_dir),
            "--repo-root", str(self.repo),
        ])
        self.assertEqual(exit_code, 0, msg=output)

    def test_no_drift_reported_when_local_absent(self):
        """config.local.toml が不在なら localKeys は drift 比較対象外。"""
        _write_codex_config_with_local(
            self.repo,
            local_keys=["sandbox_workspace_write.writable_roots"],
        )
        # config.local.toml を作らない

        live_dir = Path(self.repo / "live" / "codex")
        # push で live_dir を初期化（writable_roots は SSOT config.toml の値が入る）
        self._push_codex(live_dir)

        # live の writable_roots を変更して local との差分を作る（local が不在なので drift 対象外）
        live_toml = (live_dir / "config.toml").read_text(encoding="utf-8")
        lines = live_toml.splitlines()
        start = lines.index("[sandbox_workspace_write]")
        key_line = next(
            i for i in range(start + 1, len(lines))
            if lines[i].split("=", 1)[0].strip() == "writable_roots"
        )
        end = key_line + 1
        if lines[key_line].rstrip().endswith("["):
            end = next(i for i in range(key_line + 1, len(lines)) if lines[i].strip().endswith("]")) + 1
        lines[key_line:end] = ['writable_roots = ["/whatever/path"]']
        (live_dir / "config.toml").write_text("\n".join(lines) + "\n", encoding="utf-8")

        exit_code, output = run_distribute_cli([
            "codex", "--check",
            "--live", str(live_dir),
            "--repo-root", str(self.repo),
        ])
        # local 不在なので writable_roots は drift 対象外 → exit 0
        self.assertEqual(exit_code, 0, msg=output)


class _ComposeFixture(unittest.TestCase):
    """settings_sync.compose を template / live テキストから直接叩くための最小 repo。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.repo = self.root / "repo"
        self.live = self.root / "live"
        self.repo.mkdir()
        self.live.mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def compose(self, settings_format: str, template_text: str, live_text: str | None, keys: list):
        from harness_lib import settings_sync

        source = f"template.{settings_format}"
        (self.repo / source).write_text(template_text, encoding="utf-8")
        config_file = f"config.{settings_format}"
        if live_text is not None:
            (self.live / config_file).write_text(live_text, encoding="utf-8")
        cfg = {
            "configFile": config_file,
            "settingsSync": {"source": source, "keys": keys, "format": settings_format},
        }
        return settings_sync.compose(cfg, self.repo, self.live)


class TestTomlTableValues(_ComposeFixture):
    """dict 値の dotted key を TOML に書くとき、Codex が読める形（section / inline table）になる。

    dict 分岐が無いと Python repr（{'enabled': True}）が live config.toml に
    書き込まれ、次回 push の tomllib.loads が落ちる（2026-07-15 に実発生）。
    """

    def test_table_value_serializes_as_toml_section(self):
        import tomllib

        composed = self.compose(
            "toml",
            "[features]\nmulti_agent = true\n\n[features.multi_agent_v2]\n"
            "hide_spawn_agent_metadata = false\ntool_namespace = \"agents\"\n",
            "[features]\nmulti_agent = true\n",
            ["features.multi_agent_v2"],
        )
        data = tomllib.loads(composed.text)
        self.assertEqual(data["features"]["multi_agent_v2"]["tool_namespace"], "agents")
        self.assertEqual([step.change.changed for step in composed.steps], [("features.multi_agent_v2",)])

    def test_table_value_replaces_legacy_inline_table(self):
        import tomllib

        composed = self.compose(
            "toml",
            "[features]\nmulti_agent = true\n\n[features.multi_agent_v2]\n"
            "hide_spawn_agent_metadata = false\ntool_namespace = \"agents\"\n",
            "[features]\n"
            "multi_agent = true\n"
            "multi_agent_v2 = { enabled = true, tool_namespace = \"agents\" }\n",
            ["features.multi_agent_v2"],
        )
        data = tomllib.loads(composed.text)
        self.assertEqual(data["features"]["multi_agent_v2"]["tool_namespace"], "agents")
        self.assertNotIn("multi_agent_v2 =", composed.text)

    def test_table_value_replaces_legacy_scalar_flag(self):
        """親セクションに同名の bool が残っていたら、table 宣言に畳み替える。

        codex の features は bool と table の両方を受け付けるものがある
        （context_management は bool true と { experimental_mode = true } が同義）。
        SSOT を table 形に寄せたとき、live に残った bool を消さないと同じキーが
        二重定義される。
        """
        import tomllib

        composed = self.compose(
            "toml",
            "[features]\nmemories = true\n\n[features.context_management]\nexperimental_mode = true\n",
            "[features]\nmemories = true\ncontext_management = true\n",
            ["features.context_management"],
        )
        data = tomllib.loads(composed.text)
        self.assertEqual({"experimental_mode": True}, data["features"]["context_management"])
        self.assertNotIn("context_management = true", composed.text)

    def test_scalar_value_replaces_legacy_child_table(self):
        """旧宣言の子テーブルが残ったままスカラーを書くと、同じキーが二重定義される。

        codex 0.153.4 は features 配下を bool で読む。live に旧宣言の
        [features.context_management] が残った状態でスカラーを書き足すと
        Codex が "Cannot overwrite a value" で config 全体を読めなくなる
        （2026-09-06 に実発生。bootstrap が push の途中で停止した）。
        """
        import tomllib

        composed = self.compose(
            "toml",
            "[features]\nmemories = true\ncontext_management = true\n",
            "[features]\nmemories = true\n\n[features.context_management]\nexperimental_mode = true\n",
            ["features.context_management"],
        )
        data = tomllib.loads(composed.text)
        self.assertIs(data["features"]["context_management"], True)
        self.assertNotIn("[features.context_management]", composed.text)

    def test_nested_dict_and_list_inside_table_roundtrip(self):
        import tomllib

        composed = self.compose(
            "toml",
            "[a]\n[a.outer]\nflag = false\npaths = [\"/a\", \"/b\"]\n[a.outer.inner]\nenabled = true\n",
            "[a]\nother = 1\n",
            ["a.outer"],
        )
        self.assertEqual(
            tomllib.loads(composed.text)["a"],
            {"other": 1, "outer": {"flag": False, "paths": ["/a", "/b"], "inner": {"enabled": True}}},
        )


class TestSettingsFormatContract(_ComposeFixture):
    """format 差を越えて compose が宣言キーだけを更新し、他キーを保持する契約。"""

    def test_json_toml_and_yaml_update_declared_keys_only(self):
        from harness_lib.settings_sync import SettingsChange

        cases = [
            (
                "json",
                '{"managed": "new"}\n',
                '{"managed": "old", "local": "keep"}\n',
                '{\n  "managed": "new",\n  "local": "keep"\n}\n',
                json.loads,
            ),
            (
                "toml",
                'managed = "new"\n',
                'managed = "old"\nlocal = "keep"\n',
                None,
                __import__("tomllib").loads,
            ),
        ]
        try:
            import yaml
        except ImportError:
            yaml = None
        if yaml is not None:
            cases.append(("yaml", "managed: new\n", "managed: old\nlocal: keep\n", None, yaml.safe_load))

        for settings_format, template_text, live_text, expected_text, parse in cases:
            with self.subTest(settings_format=settings_format):
                composed = self.compose(settings_format, template_text, live_text, ["managed"])
                self.assertFalse(composed.seeded)
                self.assertEqual(parse(composed.text), {"managed": "new", "local": "keep"})
                self.assertEqual(
                    [(step.kind, step.change) for step in composed.steps],
                    [("settings-sync", SettingsChange("", ("managed",), ()))],
                )
                if expected_text is not None:
                    self.assertEqual(composed.text, expected_text)

    def test_compose_is_a_noop_when_live_already_matches(self):
        live_text = '{"managed": "new", "local": "keep"}\n'
        composed = self.compose("json", '{"managed": "new"}\n', live_text, ["managed"])
        self.assertEqual(composed.steps, ())
        self.assertEqual(composed.text, live_text)

    def test_compose_seeds_template_when_live_is_absent(self):
        composed = self.compose("json", '{"managed": "new"}\n', None, ["managed"])
        self.assertTrue(composed.seeded)
        self.assertEqual([step.kind for step in composed.steps], ["settings-template"])
        self.assertEqual(composed.text, '{"managed": "new"}\n')


if __name__ == "__main__":
    unittest.main()
