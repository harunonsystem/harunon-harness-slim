#!/usr/bin/env python3
"""harness_lib.mise_global のテスト。"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from harness_lib import mise_global  # noqa: E402


class LoadExpectedTestCase(unittest.TestCase):
    def test_reads_env_and_tool_names(self):
        with tempfile.TemporaryDirectory() as tmp:
            example = Path(tmp) / "example.toml"
            example.write_text(
                '[tools]\npnpm = "1.0"\nprek = "0.4.12"\n\n'
                '[env]\nPI_FFF_MODE = "override"\n',
                encoding="utf-8",
            )
            expected = mise_global.load_expected(example)
            self.assertEqual(expected.env, {"PI_FFF_MODE": "override"})
            self.assertEqual(expected.tools, frozenset({"pnpm", "prek"}))


class LoadLiveTestCase(unittest.TestCase):
    def test_missing_file_returns_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "does-not-exist.toml"
            live = mise_global.load_live(missing)
            self.assertEqual(live.env, {})
            self.assertEqual(live.tools, frozenset())

    def test_corrupt_toml_raises_value_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "config.toml"
            bad.write_text("[env\nnot valid toml", encoding="utf-8")
            with self.assertRaises(ValueError):
                mise_global.load_live(bad)


class CompareTestCase(unittest.TestCase):
    def test_no_drift_when_matching(self):
        expected = mise_global.Expected(env={"A": "1"}, tools=frozenset({"pnpm"}))
        live = mise_global.Expected(env={"A": "1"}, tools=frozenset({"pnpm"}))
        self.assertEqual(mise_global.compare(expected, live), [])

    def test_env_missing(self):
        expected = mise_global.Expected(env={"A": "1"}, tools=frozenset())
        live = mise_global.Expected(env={}, tools=frozenset())
        findings = mise_global.compare(expected, live)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].kind, "env-missing")
        self.assertEqual(findings[0].key, "A")
        self.assertEqual(findings[0].expected, "1")

    def test_env_differs(self):
        expected = mise_global.Expected(env={"A": "1"}, tools=frozenset())
        live = mise_global.Expected(env={"A": "2"}, tools=frozenset())
        findings = mise_global.compare(expected, live)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].kind, "env-differs")
        self.assertEqual(findings[0].expected, "1")
        self.assertEqual(findings[0].actual, "2")

    def test_tool_missing(self):
        expected = mise_global.Expected(env={}, tools=frozenset({"pnpm"}))
        live = mise_global.Expected(env={}, tools=frozenset())
        findings = mise_global.compare(expected, live)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].kind, "tool-missing")
        self.assertEqual(findings[0].key, "pnpm")

    def test_tool_version_differences_are_not_drift(self):
        # tools は名前集合の frozenset なのでバージョンは元々比較対象に入らない。
        expected = mise_global.Expected(env={}, tools=frozenset({"pnpm"}))
        live = mise_global.Expected(env={}, tools=frozenset({"pnpm"}))
        self.assertEqual(mise_global.compare(expected, live), [])

    def test_extra_live_entries_are_not_flagged(self):
        expected = mise_global.Expected(env={"A": "1"}, tools=frozenset({"pnpm"}))
        live = mise_global.Expected(
            env={"A": "1", "EXTRA": "x"}, tools=frozenset({"pnpm", "extra-tool"})
        )
        self.assertEqual(mise_global.compare(expected, live), [])


class RenderTestCase(unittest.TestCase):
    def test_empty_findings_render_empty_string(self):
        self.assertEqual(mise_global.render([]), "")

    def test_renders_each_kind(self):
        findings = [
            mise_global.Finding("env-missing", "A", expected="1"),
            mise_global.Finding("env-differs", "B", expected="1", actual="2"),
            mise_global.Finding("tool-missing", "pnpm"),
        ]
        text = mise_global.render(findings)
        self.assertIn("env 未設定: A (期待値: 1)", text)
        self.assertIn("env 不一致: B (期待値: 1 / 実際: 2)", text)
        self.assertIn("tool 未インストール: pnpm", text)


class ApplyEnvKeyTestCase(unittest.TestCase):
    def test_appends_env_section_when_absent(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = Path(tmp) / "config.toml"
            cfg.write_text('[tools]\npnpm = "1.0"\n', encoding="utf-8")
            mise_global.apply_env_key(cfg, "PI_FFF_MODE", "override")
            text = cfg.read_text(encoding="utf-8")
            self.assertIn('[tools]\npnpm = "1.0"', text)
            self.assertIn("[env]", text)
            self.assertIn('PI_FFF_MODE = "override"', text)

    def test_appends_key_to_existing_env_section(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = Path(tmp) / "config.toml"
            cfg.write_text('[env]\nEXISTING = "keep"\n\n[tools]\npnpm = "1.0"\n', encoding="utf-8")
            mise_global.apply_env_key(cfg, "PI_FFF_MODE", "override")
            text = cfg.read_text(encoding="utf-8")
            self.assertIn('EXISTING = "keep"', text)
            self.assertIn('PI_FFF_MODE = "override"', text)
            self.assertIn('[tools]\npnpm = "1.0"', text)

    def test_replaces_existing_key_value_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = Path(tmp) / "config.toml"
            cfg.write_text(
                '# comment kept\n[env]\nPI_FFF_MODE = "tools-and-ui"\nOTHER = "x"\n',
                encoding="utf-8",
            )
            mise_global.apply_env_key(cfg, "PI_FFF_MODE", "override")
            text = cfg.read_text(encoding="utf-8")
            self.assertIn("# comment kept", text)
            self.assertIn('PI_FFF_MODE = "override"', text)
            self.assertNotIn("tools-and-ui", text)
            self.assertIn('OTHER = "x"', text)


if __name__ == "__main__":
    unittest.main()
