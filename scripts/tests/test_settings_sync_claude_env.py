#!/usr/bin/env python3
"""claude の settingsSync に env.HARNESS_RUNTIME を追従させる移行テスト。

danger-rules hook（block-dangerous-in-bash.sh）は HARNESS_RUNTIME が未設定だと
fail-closed で全 Bash を deny する（#100 フェーズ1）。hooks/ は配布されるのに
settingsSync.keys が env.HARNESS_RUNTIME を持たないと、live settings.json に
env.HARNESS_RUNTIME が届かず bootstrap 直後から live Claude の全 Bash が
exit 2 になる（Codex review P1）。ここでは既存 live（env に別キーあり、
HARNESS_RUNTIME 無し）からの移行を検証する。
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from tests._helpers import make_repo, run_distribute_cli  # noqa: E402


def _write_claude_config_with_env_key(repo: Path) -> None:
    """claude config.json の settingsSync.keys に env.HARNESS_RUNTIME を追加する。"""
    cfg_path = repo / "packages" / "targets" / "claude" / "config.json"
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    if "env.HARNESS_RUNTIME" not in cfg["settingsSync"]["keys"]:
        cfg["settingsSync"]["keys"].append("env.HARNESS_RUNTIME")
    cfg_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_template_settings_with_harness_runtime(repo: Path) -> None:
    """packages/core/settings.json（SSOT テンプレート）の env に HARNESS_RUNTIME を追加する。

    make_repo() の既定テンプレートは env.TEMPLATE_ENV のみを持つ（本物の
    packages/core/settings.json の env.HARNESS_RUNTIME を模す）。
    """
    template_path = repo / "packages" / "core" / "settings.json"
    template = json.loads(template_path.read_text(encoding="utf-8"))
    template.setdefault("env", {})["HARNESS_RUNTIME"] = "claude"
    template_path.write_text(
        json.dumps(template, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def _write_live_settings(repo: Path, data: dict) -> Path:
    live_dir = repo / "live" / "claude"
    live_dir.mkdir(parents=True, exist_ok=True)
    live_path = live_dir / "settings.json"
    live_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return live_path


class ClaudeEnvHarnessRuntimeMigrationTestCase(unittest.TestCase):
    """live settings.json に env.HARNESS_RUNTIME が無い状態からの移行を検証する。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = make_repo(Path(self._tmp.name))
        _write_claude_config_with_env_key(self.repo)
        _write_template_settings_with_harness_runtime(self.repo)
        self.template_hooks = json.loads(
            (self.repo / "packages" / "core" / "settings.json").read_text(encoding="utf-8")
        )["hooks"]

    def tearDown(self):
        self._tmp.cleanup()

    def test_check_reports_drift_when_harness_runtime_is_missing_from_live(self):
        """live に env.HARNESS_RUNTIME が無ければ --check が drift として報告する。"""
        _write_live_settings(self.repo, {
            "hooks": self.template_hooks,
            "env": {"OTHER_LOCAL_VAR": "keep-me"},
        })

        code, output = run_distribute_cli(
            ["claude", "--check", "--repo-root", str(self.repo),
             "--live", str(self.repo / "live" / "claude")]
        )
        self.assertEqual(code, 1, output)
        self.assertIn("[changed] settings.json#env.HARNESS_RUNTIME", output)

    def test_push_sets_harness_runtime_and_preserves_other_env_keys(self):
        """--push で env.HARNESS_RUNTIME が入り、live 側の他の env キーは保持される。"""
        live_path = _write_live_settings(self.repo, {
            "hooks": self.template_hooks,
            "env": {"OTHER_LOCAL_VAR": "keep-me"},
        })

        code, output = run_distribute_cli(
            ["claude", "--push", "--repo-root", str(self.repo),
             "--dest", str(self.repo / "live" / "claude")]
        )
        self.assertEqual(code, 0, output)

        live_after = json.loads(live_path.read_text(encoding="utf-8"))
        self.assertEqual(live_after["env"]["HARNESS_RUNTIME"], "claude")
        self.assertEqual(live_after["env"]["OTHER_LOCAL_VAR"], "keep-me")

    def test_push_is_a_noop_when_already_synced(self):
        """live が既に template と一致していれば --push で書き換えが起きない。"""
        _write_live_settings(self.repo, {
            "hooks": self.template_hooks,
            "env": {"HARNESS_RUNTIME": "claude", "OTHER_LOCAL_VAR": "keep-me"},
        })

        code, output = run_distribute_cli(
            ["claude", "--push", "--repo-root", str(self.repo),
             "--dest", str(self.repo / "live" / "claude")]
        )
        self.assertEqual(code, 0, output)
        self.assertNotIn("settings-sync:", output)


if __name__ == "__main__":
    unittest.main()
