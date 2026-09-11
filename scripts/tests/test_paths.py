#!/usr/bin/env python3
"""harness_lib.paths（safe_relative / relative_name）と、settingsSync・distribute のパス検証。

宣言由来のパスが基準の外へ出ないことを保証する。検証が無いと config を書き換えるだけで
repo 外の読み込みと dest 外への書き込みができた（2026-07-26 に実測）。
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from harness_lib import settings_sync  # noqa: E402
from harness_lib.paths import relative_name, safe_relative  # noqa: E402
from harness_lib.resolver import manifest  # noqa: E402
from tests._helpers import make_repo  # noqa: E402


class TestRelativeName(unittest.TestCase):
    def test_accepts_plain_relative_paths(self):
        for value in ("settings.json", "packages/core/settings.json", "a/b/c.toml"):
            with self.subTest(value=value):
                self.assertEqual(relative_name(value, "x"), value)

    def test_rejects_absolute_parent_and_empty(self):
        for value in ("/etc/hosts", "../secret", "a/../../b", "", "   ", ".", "./"):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    relative_name(value, "x")


class TestSafeRelative(unittest.TestCase):
    def test_accepts_plain_relative_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            for value in ("settings.json", "packages/core/settings.json", "a/b/c.toml"):
                with self.subTest(value=value):
                    self.assertEqual(safe_relative(value, "x", base=base), value)

    def test_rejects_absolute_parent_and_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            for value in ("/etc/hosts", "../secret", "a/../../b", "", "   ", ".", "./"):
                with self.subTest(value=value):
                    with self.assertRaises(ValueError):
                        safe_relative(value, "x", base=Path(tmp))

    def test_base_is_required(self):
        """base 省略で文字列検査だけに落ちる経路を残さない。"""
        with self.assertRaises(TypeError):
            safe_relative("a.txt", "x")  # type: ignore[call-arg]

    def test_rejects_symlink_escaping_the_base(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / "base"
            base.mkdir()
            outside = Path(tmp) / "outside.txt"
            outside.write_text("SECRET\n", encoding="utf-8")
            (base / "link.txt").symlink_to(outside)

            with self.assertRaises(ValueError):
                safe_relative("link.txt", "x", base=base)

    def test_allows_symlink_inside_the_base(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            (base / "real.txt").write_text("ok\n", encoding="utf-8")
            (base / "link.txt").symlink_to(base / "real.txt")
            self.assertEqual(safe_relative("link.txt", "x", base=base), "link.txt")


class TestSettingsSyncPathValidation(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.base = Path(self._tmp.name)
        self.repo = self.base / "repo"
        self.dest = self.base / "dest"
        for d in (self.repo, self.dest):
            d.mkdir()
        (self.repo / "template.json").write_text(json.dumps({"k": "v"}), encoding="utf-8")
        (self.dest / "settings.json").write_text(json.dumps({"k": "local"}), encoding="utf-8")
        (self.base / "outside.json").write_text(json.dumps({"k": "SECRET"}), encoding="utf-8")

    def tearDown(self):
        self._tmp.cleanup()

    def _cfg(self, **overrides) -> dict:
        cfg = {
            "name": "probe",
            "configFile": "settings.json",
            "settingsSync": {"source": "template.json", "keys": ["k"], "format": "json"},
        }
        cfg.update(overrides)
        return cfg

    def test_valid_declaration_still_works(self):
        drifts = settings_sync.drifts(self._cfg(), self.repo, self.dest)
        self.assertEqual([d.path for d in drifts], ["settings.json#k"])

    def test_source_cannot_escape_the_repo(self):
        cfg = self._cfg()
        cfg["settingsSync"]["source"] = "../outside.json"
        with self.assertRaises(ValueError):
            settings_sync.drifts(cfg, self.repo, self.dest)

    def test_absolute_source_is_rejected(self):
        cfg = self._cfg()
        cfg["settingsSync"]["source"] = str(self.base / "outside.json")
        with self.assertRaises(ValueError):
            settings_sync.drifts(cfg, self.repo, self.dest)

    def test_symlinked_source_escaping_the_repo_is_rejected(self):
        """repo 内の symlink が repo 外を指すとき、字面は相対でも読まない。"""
        (self.repo / "link.json").symlink_to(self.base / "outside.json")
        cfg = self._cfg()
        cfg["settingsSync"]["source"] = "link.json"
        with self.assertRaises(ValueError) as ctx:
            settings_sync.drifts(cfg, self.repo, self.dest)
        self.assertIn("symlink", str(ctx.exception))

    def test_config_file_cannot_escape_the_destination(self):
        cfg = self._cfg(configFile="../escaped.json")
        with self.assertRaises(ValueError):
            settings_sync.drifts(cfg, self.repo, self.dest)
        self.assertFalse((self.base / "escaped.json").exists())

    def test_overlay_sources_are_validated(self):
        for key in ("localSource", "extrasSource"):
            with self.subTest(key=key):
                cfg = self._cfg()
                cfg["settingsSync"][key] = "../outside.json"
                cfg["settingsSync"][key.replace("Source", "Keys")] = ["k"]
                with self.assertRaises(ValueError):
                    settings_sync.drifts(cfg, self.repo, self.dest)

    def test_unknown_format_is_an_error_not_json(self):
        cfg = self._cfg()
        cfg["settingsSync"]["format"] = "tomll"
        with self.assertRaises(ValueError) as ctx:
            settings_sync.drifts(cfg, self.repo, self.dest)
        self.assertIn("settingsSync.format", str(ctx.exception))


class TestDistributeSourcePathValidation(unittest.TestCase):
    """distribute 宣言の source が repo 外を読む経路を閉じる。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.repo = make_repo(self.tmp)
        self.outside = self.tmp / "outside"
        self.outside.mkdir()
        (self.outside / "SECRET.md").write_text("secret\n", encoding="utf-8")

    def tearDown(self):
        self._tmp.cleanup()

    def _cfg(self) -> dict:
        return json.loads((self.repo / "packages/targets/claude/config.json").read_text(encoding="utf-8"))

    def test_symlinked_directory_source_is_rejected(self):
        (self.repo / "packages/core/linked").symlink_to(self.outside, target_is_directory=True)
        cfg = self._cfg()
        cfg["distribute"]["leak/"] = {"source": "packages/core/linked/"}
        with self.assertRaises(ValueError) as ctx:
            manifest("claude", self.repo, cfg=cfg)
        self.assertIn("symlink", str(ctx.exception))

    def test_symlinked_file_source_is_rejected_even_inside_repo(self):
        real = self.repo / "packages/core/real.md"
        real.write_text("real\n", encoding="utf-8")
        (self.repo / "packages/core/alias.md").symlink_to(real)
        cfg = self._cfg()
        cfg["distribute"]["alias.md"] = {"source": "packages/core/alias.md"}
        with self.assertRaises(ValueError) as ctx:
            manifest("claude", self.repo, cfg=cfg)
        self.assertIn("symlink", str(ctx.exception))

    def test_mixed_file_and_directory_sources_are_rejected(self):
        """file dest に directory source を混ぜると "" キーだけ採用され残りが黙って消える。"""
        (self.repo / "packages/core/single.md").write_text("single\n", encoding="utf-8")
        cfg = self._cfg()
        cfg["distribute"]["mixed.md"] = {
            "source": ["packages/core/single.md", "packages/core/skills/"],
        }
        with self.assertRaises(ValueError) as ctx:
            manifest("claude", self.repo, cfg=cfg)
        self.assertIn("混在", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
