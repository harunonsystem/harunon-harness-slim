"""scripts/pi-packages-update.py の契約テスト。

pin 正規表現・textual rewrite・outdated 表示だけを検証する。ネットワーク（npm
registry / git ls-remote）と重い検証コマンド（validate-harness.py /
bootstrap.sh）はすべて monkeypatch し、実ネットワーク・実サブプロセスは呼ばない。
"""
from __future__ import annotations

import contextlib
import importlib.util
import io
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "pi-packages-update.py"

# ハイフン入りファイル名は `import` できないため、パスから直接ロードする
# （scripts/pi-doctor.py 同様のスクリプト名の都合。テストは importlib で対応する）。
_spec = importlib.util.spec_from_file_location("pi_packages_update", SCRIPT_PATH)
assert _spec and _spec.loader
ppu = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = ppu  # dataclass の型解決が sys.modules 登録を前提にするため必要
_spec.loader.exec_module(ppu)


FIXTURE = """\
{
\t"packages": [
\t\t"npm:@narumitw/pi-subagents@2.1.4",
\t\t"npm:pi-lens@4.1.3",
\t\t"git:github.com/elpapi42/pi-observational-memory@ce9fc982b3a219a7839f07c9f4a3e054e81a2b21"
\t],
\t"other": true
}
"""
SOL_OLD_SHA = "8f8c13916c97fb54c32008e41c05421f9b69ac3b"
SOL_NEW_SHA = "1" * 40
SOL_SPEC = f"git:{ppu.SOL_PI_GIT_NAME}@{SOL_OLD_SHA}"
SOL_FIXTURE = f'''{{
\t"packages": [
\t\t"{SOL_SPEC}",
\t\t"npm:pi-lens@4.1.3"
\t]
}}
'''
SUBAGENTS_FIXTURE = f'''{{
\t"maxConcurrent": 8,
\t"excludedExtensionPackages": [
\t\t"{SOL_SPEC}"
\t]
}}
'''


class ParseSpecTest(unittest.TestCase):
    def test_npm_scoped(self) -> None:
        self.assertEqual(
            ppu.parse_spec("npm:@narumitw/pi-subagents@2.1.4"),
            ("npm", "@narumitw/pi-subagents", "2.1.4"),
        )

    def test_npm_unscoped(self) -> None:
        self.assertEqual(ppu.parse_spec("npm:pi-lens@4.1.3"), ("npm", "pi-lens", "4.1.3"))

    def test_git(self) -> None:
        sha = "ce9fc982b3a219a7839f07c9f4a3e054e81a2b21"
        self.assertEqual(
            ppu.parse_spec(f"git:github.com/elpapi42/pi-observational-memory@{sha}"),
            ("git", "github.com/elpapi42/pi-observational-memory", sha),
        )

    def test_rejects_semver_range(self) -> None:
        with self.assertRaises(ValueError):
            ppu.parse_spec("npm:pi-lens@^4.1.3")

    def test_rejects_missing_version(self) -> None:
        with self.assertRaises(ValueError):
            ppu.parse_spec("npm:pi-lens")

    def test_rejects_short_git_sha(self) -> None:
        with self.assertRaises(ValueError):
            ppu.parse_spec("git:github.com/example/package@abcdef")


class LoadPackagesTest(unittest.TestCase):
    def test_parses_lines_with_correct_line_numbers(self) -> None:
        packages = ppu.load_packages(FIXTURE)

        self.assertEqual([p.name for p in packages], [
            "@narumitw/pi-subagents",
            "pi-lens",
            "github.com/elpapi42/pi-observational-memory",
        ])
        self.assertEqual([p.line_no for p in packages], [3, 4, 5])
        self.assertEqual(packages[0].kind, "npm")
        self.assertEqual(packages[2].kind, "git")


class OutdatedTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="pi-packages-update-test-")
        self.addCleanup(self.temp.cleanup)
        self.settings_path = Path(self.temp.name) / "settings.json"
        self.settings_path.write_text(FIXTURE, encoding="utf-8")

        self._orig_settings_path = ppu.SETTINGS_PATH
        self._orig_latest_of = ppu.latest_of
        ppu.SETTINGS_PATH = self.settings_path
        self.addCleanup(self._restore)

    def _restore(self) -> None:
        ppu.SETTINGS_PATH = self._orig_settings_path
        ppu.latest_of = self._orig_latest_of

    def test_reports_stale_count_without_network(self) -> None:
        latest_by_name = {
            "@narumitw/pi-subagents": "2.1.4",  # 変化なし
            "pi-lens": "5.0.0",  # stale
            "github.com/elpapi42/pi-observational-memory": "0" * 40,  # stale
        }
        ppu.latest_of = lambda pkg: latest_by_name[pkg.name]

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = ppu.cmd_outdated(SimpleNamespace())

        output = buf.getvalue()
        self.assertEqual(rc, 0)
        self.assertIn("pi-lens", output)
        self.assertIn("2 stale", output)


class UpdateRewriteTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="pi-packages-update-test-")
        self.addCleanup(self.temp.cleanup)
        self.settings_path = Path(self.temp.name) / "settings.json"
        self.subagents_path = Path(self.temp.name) / "subagents.json"
        self.settings_path.write_text(FIXTURE, encoding="utf-8")

        self._orig_settings_path = ppu.SETTINGS_PATH
        self._orig_subagents_settings_path = ppu.SUBAGENTS_SETTINGS_PATH
        self._orig_latest_of = ppu.latest_of
        self._orig_verify = ppu.verify
        ppu.SETTINGS_PATH = self.settings_path
        ppu.SUBAGENTS_SETTINGS_PATH = self.subagents_path
        ppu.verify = lambda: True  # validate-harness.py / bootstrap.sh は unit test で呼ばない
        self.addCleanup(self._restore)

    def _restore(self) -> None:
        ppu.SETTINGS_PATH = self._orig_settings_path
        ppu.SUBAGENTS_SETTINGS_PATH = self._orig_subagents_settings_path
        ppu.latest_of = self._orig_latest_of
        ppu.verify = self._orig_verify

    def test_rewrites_only_targeted_pin_preserving_tabs_and_order(self) -> None:
        ppu.latest_of = lambda pkg: "5.0.0" if pkg.name == "pi-lens" else pkg.version

        rc = ppu.cmd_update(SimpleNamespace(names=["pi-lens"]))

        self.assertEqual(rc, 0)
        new_text = self.settings_path.read_text(encoding="utf-8")
        new_lines = new_text.splitlines(keepends=True)
        old_lines = FIXTURE.splitlines(keepends=True)

        self.assertEqual(len(new_lines), len(old_lines))
        self.assertEqual(new_lines[3], '\t\t"npm:pi-lens@5.0.0",\n')
        # 変更対象以外は完全に一致（タブ・カンマ・行順を保持）
        for i in (0, 1, 2, 4, 5, 6):
            self.assertEqual(new_lines[i], old_lines[i])

    def test_update_without_names_bumps_all_stale(self) -> None:
        latest_by_name = {
            "@narumitw/pi-subagents": "2.1.4",
            "pi-lens": "5.0.0",
            "github.com/elpapi42/pi-observational-memory": "1" * 40,
        }
        ppu.latest_of = lambda pkg: latest_by_name[pkg.name]

        rc = ppu.cmd_update(SimpleNamespace(names=[]))

        self.assertEqual(rc, 0)
        new_text = self.settings_path.read_text(encoding="utf-8")
        self.assertIn('"npm:pi-lens@5.0.0"', new_text)
        self.assertIn(f'"git:github.com/elpapi42/pi-observational-memory@{"1" * 40}"', new_text)
        self.assertIn('"npm:@narumitw/pi-subagents@2.1.4"', new_text)

    def test_sol_pi_bump_updates_subagent_exclusion_preserving_other_settings(self) -> None:
        self.settings_path.write_text(SOL_FIXTURE, encoding="utf-8")
        self.subagents_path.write_text(SUBAGENTS_FIXTURE, encoding="utf-8")
        ppu.latest_of = lambda pkg: SOL_NEW_SHA if pkg.name == ppu.SOL_PI_GIT_NAME else pkg.version

        rc = ppu.cmd_update(SimpleNamespace(names=[ppu.SOL_PI_GIT_NAME]))

        self.assertEqual(rc, 0)
        new_spec = f"git:{ppu.SOL_PI_GIT_NAME}@{SOL_NEW_SHA}"
        self.assertIn(new_spec, self.settings_path.read_text(encoding="utf-8"))
        subagents = self.subagents_path.read_text(encoding="utf-8")
        self.assertIn(new_spec, subagents)
        self.assertIn('"maxConcurrent": 8', subagents)
        self.assertNotIn(SOL_SPEC, subagents)

    def test_unknown_name_raises(self) -> None:
        with self.assertRaises(SystemExit):
            ppu.cmd_update(SimpleNamespace(names=["not-a-real-package"]))

    def test_verify_failure_restores_original_file(self) -> None:
        ppu.latest_of = lambda pkg: "5.0.0" if pkg.name == "pi-lens" else pkg.version
        ppu.verify = lambda: False

        rc = ppu.cmd_update(SimpleNamespace(names=["pi-lens"]))

        self.assertEqual(rc, 1)
        self.assertEqual(self.settings_path.read_text(encoding="utf-8"), FIXTURE)

    def test_verify_failure_restores_sol_pi_exclusion_too(self) -> None:
        self.settings_path.write_text(SOL_FIXTURE, encoding="utf-8")
        self.subagents_path.write_text(SUBAGENTS_FIXTURE, encoding="utf-8")
        ppu.latest_of = lambda pkg: SOL_NEW_SHA if pkg.name == ppu.SOL_PI_GIT_NAME else pkg.version
        ppu.verify = lambda: False

        rc = ppu.cmd_update(SimpleNamespace(names=[ppu.SOL_PI_GIT_NAME]))

        self.assertEqual(rc, 1)
        self.assertEqual(self.settings_path.read_text(encoding="utf-8"), SOL_FIXTURE)
        self.assertEqual(self.subagents_path.read_text(encoding="utf-8"), SUBAGENTS_FIXTURE)


if __name__ == "__main__":
    unittest.main()
