#!/usr/bin/env python3
"""claude の settingsSync で autoMode.hard_deny / autoMode.soft_deny を同期し、
autoMode.environment は live 専用（同期・drift 検出の対象外）として保持されることを
検証する移行テスト。

autoMode は danger-rules.json の rule.autoMode から
scripts/sync-auto-mode-rules.py が投影する生成物（SSOT は danger-rules.json）。
/auto-mode-setup が live の settings.json にマシン固有の autoMode.environment を
書き足すため、settingsSync.keys は autoMode 丸ごとではなく
autoMode.hard_deny / autoMode.soft_deny のドット区切りキーで宣言する
（2026-09-05）。
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from tests._helpers import make_repo, run_distribute_cli  # noqa: E402


def _write_claude_config_with_automode_keys(repo: Path) -> None:
    """claude config.json の settingsSync.keys に autoMode.hard_deny / soft_deny を追加する。"""
    cfg_path = repo / "packages" / "targets" / "claude" / "config.json"
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    keys = cfg["settingsSync"]["keys"]
    for key in ("autoMode.hard_deny", "autoMode.soft_deny"):
        if key not in keys:
            keys.append(key)
    cfg_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_template_settings_with_automode(repo: Path) -> None:
    """packages/core/settings.json（SSOT テンプレート）に autoMode.hard_deny / soft_deny を追加する。

    make_repo() の既定テンプレートは autoMode を持たないため、本物の
    packages/core/settings.json（sync-auto-mode-rules.py の投影先）を模す。
    """
    template_path = repo / "packages" / "core" / "settings.json"
    template = json.loads(template_path.read_text(encoding="utf-8"))
    template["autoMode"] = {
        "hard_deny": ["$defaults"],
        "soft_deny": ["$defaults", "template-rule"],
    }
    template_path.write_text(
        json.dumps(template, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def _write_live_settings(repo: Path, data: dict) -> Path:
    live_dir = repo / "live" / "claude"
    live_dir.mkdir(parents=True, exist_ok=True)
    live_path = live_dir / "settings.json"
    live_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return live_path


class ClaudeAutoModeEnvironmentLivePreservationTestCase(unittest.TestCase):
    """live の autoMode.environment が同期・drift 検出の対象外として保持されるか検証する。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = make_repo(Path(self._tmp.name))
        _write_claude_config_with_automode_keys(self.repo)
        _write_template_settings_with_automode(self.repo)
        self.template_hooks = json.loads(
            (self.repo / "packages" / "core" / "settings.json").read_text(encoding="utf-8")
        )["hooks"]

    def tearDown(self):
        self._tmp.cleanup()

    def test_check_reports_drift_when_soft_deny_differs(self):
        """live の autoMode.soft_deny がテンプレートと違えば --check が drift として報告する。"""
        _write_live_settings(self.repo, {
            "hooks": self.template_hooks,
            "autoMode": {
                "hard_deny": ["$defaults"],
                "soft_deny": ["$defaults"],
                "environment": ["### Org-wide", "**Organization**: None configured"],
            },
        })

        code, output = run_distribute_cli(
            ["claude", "--check", "--repo-root", str(self.repo),
             "--live", str(self.repo / "live" / "claude")]
        )
        self.assertEqual(code, 1, output)
        self.assertIn("[changed] settings.json#autoMode.soft_deny", output)

    def test_push_updates_soft_deny_and_preserves_live_environment(self):
        """--push で autoMode.soft_deny がテンプレート値に置き換わり、
        live の autoMode.environment はそのまま残る。"""
        live_path = _write_live_settings(self.repo, {
            "hooks": self.template_hooks,
            "autoMode": {
                "hard_deny": ["$defaults"],
                "soft_deny": ["$defaults"],
                "environment": ["### Org-wide", "**Organization**: None configured"],
            },
        })

        code, output = run_distribute_cli(
            ["claude", "--push", "--repo-root", str(self.repo),
             "--dest", str(self.repo / "live" / "claude")]
        )
        self.assertEqual(code, 0, output)

        live_after = json.loads(live_path.read_text(encoding="utf-8"))
        self.assertEqual(
            live_after["autoMode"]["soft_deny"], ["$defaults", "template-rule"]
        )
        self.assertEqual(
            live_after["autoMode"]["environment"],
            ["### Org-wide", "**Organization**: None configured"],
        )

    def test_check_reports_no_automode_drift_when_hard_deny_and_soft_deny_match_with_environment_present(self):
        """live が hard_deny / soft_deny 一致 + environment ありの状態なら autoMode 関連の
        drift は報告されない（environment は drift 判定に含まれない）。

        fixture の live には配布ファイル（CLAUDE.md 等）が無く [missing] で exit 1 に
        なるため、autoMode の drift マーカーが出ないことだけを見る。
        """
        _write_live_settings(self.repo, {
            "hooks": self.template_hooks,
            "autoMode": {
                "hard_deny": ["$defaults"],
                "soft_deny": ["$defaults", "template-rule"],
                "environment": ["### Org-wide", "**Organization**: None configured"],
            },
        })

        _code, output = run_distribute_cli(
            ["claude", "--check", "--repo-root", str(self.repo),
             "--live", str(self.repo / "live" / "claude")]
        )
        self.assertNotIn("autoMode.hard_deny", output)
        self.assertNotIn("autoMode.soft_deny", output)
        self.assertNotIn("autoMode.environment", output)


if __name__ == "__main__":
    unittest.main()
