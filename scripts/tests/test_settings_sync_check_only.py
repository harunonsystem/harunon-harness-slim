#!/usr/bin/env python3
"""distribute.py の settingsSync checkOnlyKeys 機能テスト。

checkOnlyKeys は plugin の有効化など「live-first で変わり、push で SSOT が
上書きしてはいけない」キーの還流漏れ検出。live にだけ存在するエントリ
（= SSOT テンプレートへの還流忘れ）を --check が [unreconciled] として報告する。
2026-08-09 に cloudflare plugin の還流漏れが数週間気づかれなかった対策。
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from tests._helpers import make_repo, run_distribute_cli  # noqa: E402


def _declare_check_only(repo: Path, keys: list) -> None:
    cfg_path = repo / "packages" / "targets" / "claude" / "config.json"
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    cfg["settingsSync"]["checkOnlyKeys"] = keys
    cfg_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_template_plugins(repo: Path, plugins: dict) -> None:
    template_path = repo / "packages" / "core" / "settings.json"
    template = json.loads(template_path.read_text(encoding="utf-8"))
    template["enabledPlugins"] = plugins
    template_path.write_text(
        json.dumps(template, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def _write_live_settings(repo: Path, data: dict) -> Path:
    live_dir = repo / "live" / "claude"
    live_dir.mkdir(parents=True, exist_ok=True)
    live_path = live_dir / "settings.json"
    live_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return live_path


class CheckOnlyKeysDriftTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = make_repo(Path(self._tmp.name))
        _declare_check_only(self.repo, ["enabledPlugins"])
        # hooks は SSOT keys の比較対象なので template と揃えて drift ノイズを消す
        self.template_hooks = json.loads(
            (self.repo / "packages" / "core" / "settings.json").read_text(encoding="utf-8")
        )["hooks"]

    def tearDown(self):
        self._tmp.cleanup()

    def _live_dir(self) -> Path:
        return self.repo / "live" / "claude"

    def _check(self) -> tuple:
        return run_distribute_cli(
            ["claude", "--check", "--repo-root", str(self.repo), "--live", str(self._live_dir())]
        )

    def test_live_only_entry_is_reported_as_unreconciled(self):
        """live にだけある plugin エントリ → [unreconciled] で drift 検出。"""
        _write_template_plugins(self.repo, {"codex@openai-codex": True})
        _write_live_settings(self.repo, {
            "hooks": self.template_hooks,
            "enabledPlugins": {
                "codex@openai-codex": True,
                "cloudflare@cloudflare": True,
            },
        })

        code, output = self._check()
        self.assertEqual(code, 1, output)
        self.assertIn("[unreconciled]", output)
        self.assertIn("settings.json#enabledPlugins.cloudflare@cloudflare", output)

    def test_template_only_entry_is_not_drift(self):
        """テンプレートにだけあるエントリは新マシン用 seed 既定値なので drift にしない。"""
        _write_template_plugins(self.repo, {
            "codex@openai-codex": True,
            "sentry-mcp@sentry-mcp": True,
        })
        _write_live_settings(self.repo, {
            "hooks": self.template_hooks,
            "enabledPlugins": {"codex@openai-codex": True},
        })

        # fixture の live には配布ファイルが無く [missing] で exit 1 になるため、
        # unreconciled が出ないことだけを見る
        _code, output = self._check()
        self.assertNotIn("unreconciled", output)

    def test_value_difference_on_shared_entry_is_not_drift(self):
        """共有エントリの true/false 差はマシン側の自由（push でも触らない）なので drift にしない。"""
        _write_template_plugins(self.repo, {"codex@openai-codex": True})
        _write_live_settings(self.repo, {
            "hooks": self.template_hooks,
            "enabledPlugins": {"codex@openai-codex": False},
        })

        _code, output = self._check()
        self.assertNotIn("unreconciled", output)

    def test_push_never_writes_check_only_keys(self):
        """--push は checkOnlyKeys に触らない。live の値がそのまま残る。"""
        _write_template_plugins(self.repo, {"codex@openai-codex": True})
        live_path = _write_live_settings(self.repo, {
            "hooks": self.template_hooks,
            "enabledPlugins": {"cloudflare@cloudflare": True},
        })

        code, output = run_distribute_cli(
            ["claude", "--push", "--repo-root", str(self.repo), "--dest", str(self._live_dir())]
        )
        self.assertEqual(code, 0, output)

        live = json.loads(live_path.read_text(encoding="utf-8"))
        self.assertEqual(live["enabledPlugins"], {"cloudflare@cloudflare": True})

    def test_non_dict_check_only_key_uses_equality(self):
        """dict 以外の checkOnlyKeys は素朴な不一致で報告する。"""
        _declare_check_only(self.repo, ["statusLine"])
        template_path = self.repo / "packages" / "core" / "settings.json"
        template = json.loads(template_path.read_text(encoding="utf-8"))
        template["statusLine"] = "ssot"
        template_path.write_text(
            json.dumps(template, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        _write_live_settings(self.repo, {
            "hooks": self.template_hooks,
            "statusLine": "live-edited",
        })

        code, output = self._check()
        self.assertEqual(code, 1, output)
        self.assertIn("[unreconciled] settings.json#statusLine", output)


if __name__ == "__main__":
    unittest.main()
