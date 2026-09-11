#!/usr/bin/env python3
"""実行ビット（mode）drift の検出と補正のテスト。

内容一致でスキップされたファイルは chmod まで到達せず、live 側が 644 のまま
取り残される穴があった（2026-07-26 に check-plan-model.sh の SessionStart hook が
Permission denied で起動できていなかった）。push の補正と --check の検出を固定する。
"""
from __future__ import annotations

import json
import stat
import sys
import tempfile
import unittest
from pathlib import Path

# 兄弟テストは `scripts.distribute` の import 副作用（sys.path.insert）に相乗りして
# `tests._helpers` を解決している。このモジュールは distribute を直接 import しない
# ため、単独実行でも通るよう明示的に scripts/ を通す。
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tests._helpers import make_repo, run_distribute_cli  # noqa: E402


HOOK_REL = "hooks/demo-hook.sh"


class ExecModeTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = make_repo(Path(self._tmp.name))
        self.live = self.repo / "live/claude"
        self.live.mkdir(parents=True)

        (self.repo / "packages/core/hooks/demo-hook.sh").write_text(
            "#!/usr/bin/env bash\nexit 0\n", encoding="utf-8"
        )
        config = self.repo / "packages/targets/claude/config.json"
        cfg = json.loads(config.read_text(encoding="utf-8"))
        cfg["distribute"]["hooks/"] = {"source": ["packages/core/hooks/"]}
        config.write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def push(self, *extra: str) -> tuple[int, str]:
        return run_distribute_cli([
            "claude", "--push", "--live", str(self.live),
            "--repo-root", str(self.repo), *extra,
        ])

    def check(self) -> tuple[int, str]:
        return run_distribute_cli([
            "claude", "--check", "--live", str(self.live),
            "--repo-root", str(self.repo),
        ])

    def hook(self) -> Path:
        return self.live / HOOK_REL

    def is_executable(self, path: Path) -> bool:
        return bool(path.stat().st_mode & stat.S_IXUSR)

    def test_first_push_makes_hook_executable(self) -> None:
        code, output = self.push()

        self.assertEqual(code, 0, msg=output)
        self.assertTrue(self.is_executable(self.hook()))

    def test_push_fixes_exec_bit_when_content_is_unchanged(self) -> None:
        self.push()
        self.hook().chmod(0o644)

        code, output = self.push()

        self.assertEqual(code, 0, msg=output)
        self.assertTrue(self.is_executable(self.hook()))
        self.assertIn("mode fixed: 1", output)
        self.assertIn(f"[mode]    {HOOK_REL}", output)

    def test_check_reports_mode_drift(self) -> None:
        self.push()
        code, output = self.check()
        self.assertEqual(code, 0, msg=output)

        self.hook().chmod(0o644)

        code, output = self.check()

        self.assertEqual(code, 1, msg=output)
        self.assertIn(f"[mode] {HOOK_REL}", output)
        self.assertIn("mode: 1", output)

    def test_dry_run_reports_mode_fix_without_chmod(self) -> None:
        self.push()
        self.hook().chmod(0o644)

        code, output = self.push("--dry-run")

        self.assertEqual(code, 0, msg=output)
        self.assertIn(f"DRY: chmod +x {HOOK_REL}", output)
        self.assertFalse(self.is_executable(self.hook()))

    def test_content_drift_is_reported_as_changed_not_mode(self) -> None:
        self.push()
        self.hook().write_text("#!/usr/bin/env bash\nexit 1\n", encoding="utf-8")
        self.hook().chmod(0o644)

        code, output = self.check()

        self.assertEqual(code, 1, msg=output)
        self.assertIn(f"[changed] {HOOK_REL}", output)
        self.assertNotIn("[mode]", output)

    def test_non_executable_file_is_not_flagged(self) -> None:
        self.push()
        (self.live / "CLAUDE.md").chmod(0o644)

        code, output = self.check()

        self.assertEqual(code, 0, msg=output)

    def test_symlinked_live_file_is_reported_but_not_chmodded(self) -> None:
        self.push()
        source = self.repo / "packages/core/hooks/demo-hook.sh"
        source.chmod(0o644)
        self.hook().unlink()
        self.hook().symlink_to(source)

        code, output = self.push()

        self.assertEqual(code, 0, msg=output)
        self.assertIn("mode fixed: 0", output)
        self.assertIn(f"WARN: {HOOK_REL} は symlink", output)
        self.assertFalse(self.is_executable(source))

    def test_check_reports_mode_drift_through_symlink(self) -> None:
        self.push()
        source = self.repo / "packages/core/hooks/demo-hook.sh"
        source.chmod(0o644)
        self.hook().unlink()
        self.hook().symlink_to(source)

        code, output = self.check()

        self.assertEqual(code, 1, msg=output)
        self.assertIn(f"[mode] {HOOK_REL}", output)


if __name__ == "__main__":
    unittest.main()
