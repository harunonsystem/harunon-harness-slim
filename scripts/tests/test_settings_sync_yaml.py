#!/usr/bin/env python3
"""distribute.py の settingsSync format="yaml" 対応テスト。"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from tests._helpers import make_repo, run_distribute_cli  # noqa: E402

try:
    import yaml  # noqa: F401
    _HAS_YAML = True
except ImportError:
    _HAS_YAML = False


def _write_opencode_config_with_yaml_sync(repo: Path) -> None:
    """opencode config.json に configFile + settingsSync(format=yaml) を追加する。"""
    cfg_path = repo / "packages" / "targets" / "opencode" / "config.json"
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    cfg["configFile"] = "config.yml"
    cfg["settingsSync"] = {
        "source": "packages/targets/opencode/config.yml",
        "format": "yaml",
        "keys": ["enabledModels", "permissions"],
    }
    cfg_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_template_yaml(repo: Path) -> None:
    """packages/targets/opencode/config.yml（SSOT テンプレート）を作成する。"""
    target_dir = repo / "packages" / "targets" / "opencode"
    target_dir.mkdir(parents=True, exist_ok=True)
    (target_dir / "config.yml").write_text(
        "enabledModels:\n"
        "  - model-a\n"
        "  - model-b\n"
        "permissions:\n"
        "  default: ask\n"
        "  bash:\n"
        "    allow:\n"
        "      - ls *\n",
        encoding="utf-8",
    )


def _write_live_config_yaml(live_dir: Path, text: str) -> None:
    live_dir.mkdir(parents=True, exist_ok=True)
    (live_dir / "config.yml").write_text(text, encoding="utf-8")


def _write_opencode_config_with_yaml_local_overlay(repo: Path) -> None:
    """opencode config.json の settingsSync に localSource/localKeys overlay を追加する。"""
    cfg_path = repo / "packages" / "targets" / "opencode" / "config.json"
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    cfg["settingsSync"]["localSource"] = "packages/targets/opencode/config.local.yml"
    cfg["settingsSync"]["localKeys"] = ["customLocalKey"]
    cfg_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_local_overlay_yaml(repo: Path, value: str) -> None:
    """packages/targets/opencode/config.local.yml（overlay source）を作成する。"""
    (repo / "packages" / "targets" / "opencode" / "config.local.yml").write_text(
        f"customLocalKey: {value}\n", encoding="utf-8",
    )


@unittest.skipUnless(_HAS_YAML, "PyYAML 未インストール")
class YamlSettingsSyncDriftTestCase(unittest.TestCase):
    """format=yaml で template と live の宣言キー差分が drift として検出されるか検証する。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = make_repo(Path(self._tmp.name))
        _write_opencode_config_with_yaml_sync(self.repo)
        _write_template_yaml(self.repo)

    def tearDown(self):
        self._tmp.cleanup()

    def test_drift_detected_when_enabled_models_differ(self):
        """live の enabledModels が template と異なれば drift として検出される。"""
        live_dir = Path(self.repo / "live" / "opencode")
        _write_live_config_yaml(
            live_dir,
            (
                "enabledModels:\n"
                "  - model-old\n"
                "permissions:\n"
                "  default: ask\n"
                "  bash:\n"
                "    allow:\n"
                "      - ls *\n"
                "customLocalKey: keep-me\n"
            ),
        )

        exit_code, output = run_distribute_cli([
            "opencode", "--check",
            "--live", str(live_dir),
            "--repo-root", str(self.repo),
        ])
        self.assertEqual(exit_code, 1, msg=output)
        self.assertIn("config.yml#enabledModels", output)

    def test_no_drift_when_keys_match(self):
        """live の宣言キーが template と一致すれば drift なし。"""
        live_dir = Path(self.repo / "live" / "opencode")
        live_dir.mkdir(parents=True, exist_ok=True)

        # --push で他の distribute ファイル一式 + config.yml（template そのまま）を揃える
        exit_code, output = run_distribute_cli([
            "opencode", "--push",
            "--live", str(live_dir),
            "--repo-root", str(self.repo),
        ])
        self.assertEqual(exit_code, 0, msg=output)

        exit_code, output = run_distribute_cli([
            "opencode", "--check",
            "--live", str(live_dir),
            "--repo-root", str(self.repo),
        ])
        self.assertEqual(exit_code, 0, msg=output)


@unittest.skipUnless(_HAS_YAML, "PyYAML 未インストール")
class YamlSettingsSyncPushTestCase(unittest.TestCase):
    """--push で宣言キーだけが template 値に更新され、非管理キーが保持されるか検証する。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = make_repo(Path(self._tmp.name))
        _write_opencode_config_with_yaml_sync(self.repo)
        _write_template_yaml(self.repo)

    def tearDown(self):
        self._tmp.cleanup()

    def test_push_updates_only_declared_keys(self):
        """--push で enabledModels/permissions のみ template 値に更新され、他キーは保持される。"""
        live_dir = Path(self.repo / "live" / "opencode")
        _write_live_config_yaml(
            live_dir,
            (
                "enabledModels:\n"
                "  - model-old\n"
                "permissions:\n"
                "  default: allow\n"
                "customLocalKey: keep-me\n"
            ),
        )

        exit_code, output = run_distribute_cli([
            "opencode", "--push",
            "--live", str(live_dir),
            "--repo-root", str(self.repo),
        ])
        self.assertEqual(exit_code, 0, msg=output)

        import yaml
        live_after = yaml.safe_load((live_dir / "config.yml").read_text(encoding="utf-8"))

        # 宣言キーが template 値に更新されている
        self.assertEqual(live_after["enabledModels"], ["model-a", "model-b"])
        self.assertEqual(live_after["permissions"]["default"], "ask")
        self.assertEqual(live_after["permissions"]["bash"]["allow"], ["ls *"])

        # 非管理キーは保持される
        self.assertEqual(live_after["customLocalKey"], "keep-me")

    def test_push_no_change_when_already_synced(self):
        """既に template と一致していれば --push で書き換えが起きない。"""
        live_dir = Path(self.repo / "live" / "opencode")
        _write_live_config_yaml(
            live_dir,
            (
                "enabledModels:\n"
                "  - model-a\n"
                "  - model-b\n"
                "permissions:\n"
                "  default: ask\n"
                "  bash:\n"
                "    allow:\n"
                "      - ls *\n"
            ),
        )

        exit_code, output = run_distribute_cli([
            "opencode", "--push",
            "--live", str(live_dir),
            "--repo-root", str(self.repo),
        ])
        self.assertEqual(exit_code, 0, msg=output)
        self.assertNotIn("settings-sync:", output)


@unittest.skipUnless(_HAS_YAML, "PyYAML 未インストール")
class YamlOverlaySettingsSyncPushTestCase(unittest.TestCase):
    """format=yaml の overlay（localSource/localKeys）が --push で live に同期されるか検証する。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = make_repo(Path(self._tmp.name))
        _write_opencode_config_with_yaml_sync(self.repo)
        _write_opencode_config_with_yaml_local_overlay(self.repo)
        _write_template_yaml(self.repo)
        _write_local_overlay_yaml(self.repo, "from-local")

    def tearDown(self):
        self._tmp.cleanup()

    def test_push_syncs_overlay_key_into_live_yaml(self):
        """overlay（local）の customLocalKey が --push で live config.yml に同期される。"""
        live_dir = Path(self.repo / "live" / "opencode")
        _write_live_config_yaml(
            live_dir,
            (
                "enabledModels:\n"
                "  - model-a\n"
                "  - model-b\n"
                "permissions:\n"
                "  default: ask\n"
                "  bash:\n"
                "    allow:\n"
                "      - ls *\n"
                "customLocalKey: old-value\n"
            ),
        )

        exit_code, output = run_distribute_cli([
            "opencode", "--push",
            "--live", str(live_dir),
            "--repo-root", str(self.repo),
        ])
        self.assertEqual(exit_code, 0, msg=output)

        import yaml
        live_after = yaml.safe_load((live_dir / "config.yml").read_text(encoding="utf-8"))
        self.assertEqual(live_after["customLocalKey"], "from-local")


if __name__ == "__main__":
    unittest.main()
