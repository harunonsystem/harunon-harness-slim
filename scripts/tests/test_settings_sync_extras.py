#!/usr/bin/env python3
"""distribute.py の settingsSync extrasSource / extrasKeys 機能テスト。

extras overlay は localSource と同じ意味論を持つ:
- extrasSource が存在すれば extrasKeys を live に同期し、drift 比較対象にする
- extrasSource が不在（CI で extras submodule 未取得等）なら黙ってスキップする
違いは置き場所の意図のみ（local = マシン固有 / extras = 会社・契約固有の private submodule）。
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from tests._helpers import make_repo, run_distribute_cli  # noqa: E402

EXTRAS_TOML_REL = "packages/extras/_active/targets/codex/config.toml"


def _write_codex_config_with_extras(repo: Path, extras_keys: list) -> None:
    """codex config.json に extrasSource / extrasKeys を追加する。"""
    cfg_path = repo / "packages" / "targets" / "codex" / "config.json"
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    cfg["settingsSync"]["extrasSource"] = EXTRAS_TOML_REL
    cfg["settingsSync"]["extrasKeys"] = extras_keys
    cfg["settingsSync"]["keys"] = [
        k for k in cfg["settingsSync"]["keys"] if k not in extras_keys
    ]
    cfg_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_extras_toml(repo: Path, dictionary: list) -> None:
    words = ", ".join(f'"{w}"' for w in dictionary)
    content = (
        "# company-specific\n"
        "[desktop]\n"
        f"dictationDictionary = [{words}]\n"
    )
    path = repo / EXTRAS_TOML_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _write_live_config_toml(live_dir: Path, dictionary_line: str) -> None:
    live_dir.mkdir(parents=True, exist_ok=True)
    (live_dir / "config.toml").write_text(
        (
            'model = "gpt-5.5"\n'
            "\n"
            "[features]\n"
            "hooks = true\n"
            "\n"
            "[desktop]\n"
            f"{dictionary_line}\n"
        ),
        encoding="utf-8",
    )


class ExtrasOverlayPresentTestCase(unittest.TestCase):
    """extrasSource が存在するとき extrasKeys が live にマージされる。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = make_repo(Path(self._tmp.name))

    def tearDown(self):
        self._tmp.cleanup()

    def test_extras_keys_merged_into_live(self):
        _write_codex_config_with_extras(
            self.repo, extras_keys=["desktop.dictationDictionary"]
        )
        _write_extras_toml(self.repo, ["acme-dashboard", "acme"])

        live_dir = Path(self.repo / "live" / "codex")
        _write_live_config_toml(live_dir, 'dictationDictionary = ["old-word"]')

        exit_code, output = run_distribute_cli([
            "codex", "--push",
            "--live", str(live_dir),
            "--repo-root", str(self.repo),
        ])
        self.assertEqual(exit_code, 0, msg=output)

        live_text = (live_dir / "config.toml").read_text(encoding="utf-8")
        self.assertIn("acme-dashboard", live_text)
        self.assertNotIn("old-word", live_text)

    def test_drift_detected_when_extras_differs_from_live(self):
        _write_codex_config_with_extras(
            self.repo, extras_keys=["desktop.dictationDictionary"]
        )
        _write_extras_toml(self.repo, ["acme"])
        live_dir = Path(self.repo / "live" / "codex")
        exit_code, output = run_distribute_cli([
            "codex", "--push",
            "--live", str(live_dir),
            "--repo-root", str(self.repo),
        ])
        self.assertEqual(exit_code, 0, msg=output)

        _write_extras_toml(self.repo, ["acme", "new-word"])

        exit_code, output = run_distribute_cli([
            "codex", "--check",
            "--live", str(live_dir),
            "--repo-root", str(self.repo),
        ])
        self.assertEqual(exit_code, 1, msg=output)
        self.assertIn("desktop.dictationDictionary", output)


class ExtrasOverlayAbsentTestCase(unittest.TestCase):
    """extrasSource が不在（extras submodule 未取得）なら黙ってスキップされる。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = make_repo(Path(self._tmp.name))

    def tearDown(self):
        self._tmp.cleanup()

    def test_no_error_and_no_drift_when_extras_absent(self):
        _write_codex_config_with_extras(
            self.repo, extras_keys=["desktop.dictationDictionary"]
        )
        # extras toml を作らない

        live_dir = Path(self.repo / "live" / "codex")
        _write_live_config_toml(live_dir, 'dictationDictionary = ["whatever"]')

        exit_code, output = run_distribute_cli([
            "codex", "--push",
            "--live", str(live_dir),
            "--repo-root", str(self.repo),
        ])
        self.assertEqual(exit_code, 0, msg=output)
        # live の値は変更されない
        live_text = (live_dir / "config.toml").read_text(encoding="utf-8")
        self.assertIn("whatever", live_text)

        exit_code, output = run_distribute_cli([
            "codex", "--check",
            "--live", str(live_dir),
            "--repo-root", str(self.repo),
        ])
        self.assertEqual(exit_code, 0, msg=output)


if __name__ == "__main__":
    unittest.main()
