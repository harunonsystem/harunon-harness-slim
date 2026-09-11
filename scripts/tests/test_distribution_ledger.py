#!/usr/bin/env python3
"""Hardened distribution ledger tests."""

from __future__ import annotations

import hashlib
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

# 単体実行でも harness_lib を解決できるよう scripts/ を通す（他テストの import 順に依存しない）
_SCRIPTS_DIR = Path(__file__).resolve().parent.parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from harness_lib.distribution_state import LEDGER_FILENAME, PathFileSystem, _plan_ledger_cleanup  # noqa: E402
from tests._helpers import make_repo, run_distribute_cli  # noqa: E402


class DistributionLedgerTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = make_repo(Path(self._tmp.name))
        self.live = self.repo / "live/claude"
        self.live.mkdir(parents=True)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def push(self, *extra: str) -> tuple[int, str]:
        return run_distribute_cli([
            "claude", "--push", "--live", str(self.live),
            "--repo-root", str(self.repo), *extra,
        ])

    def ledger(self) -> dict:
        return json.loads((self.live / LEDGER_FILENAME).read_text(encoding="utf-8"))

    def test_first_push_writes_target_bound_hash_ledger_without_deleting_unmanaged(self) -> None:
        manual = self.live / "manual.txt"
        manual.write_text("manual\n", encoding="utf-8")

        code, output = self.push()

        self.assertEqual(code, 0, msg=output)
        data = self.ledger()
        self.assertEqual(data["schemaVersion"], 1)
        self.assertEqual(data["target"], "claude")
        self.assertIsInstance(data["files"], dict)
        self.assertEqual(len(data["files"]["CLAUDE.md"]), 64)
        self.assertTrue(manual.exists())

    def test_unchanged_file_removed_from_ssot_is_backed_up_and_deleted(self) -> None:
        self.push()
        source = self.repo / "packages/core/skills/demo-skill"
        shutil.rmtree(source)

        code, output = self.push()

        self.assertEqual(code, 0, msg=output)
        self.assertFalse((self.live / "skills/demo-skill/SKILL.md").exists())
        self.assertIn("[removed-managed] skills/demo-skill/SKILL.md", output)
        self.assertTrue(any((self.live / "backups").rglob("SKILL.md")))

    def test_user_modified_stale_file_is_preserved_and_remains_pending(self) -> None:
        self.push()
        live_skill = self.live / "skills/demo-skill/SKILL.md"
        live_skill.write_text("user modified\n", encoding="utf-8")
        shutil.rmtree(self.repo / "packages/core/skills/demo-skill")

        code, output = self.push()

        self.assertEqual(code, 0, msg=output)
        self.assertEqual(live_skill.read_text(encoding="utf-8"), "user modified\n")
        self.assertIn("[preserved-modified] skills/demo-skill/SKILL.md", output)
        self.assertIn("skills/demo-skill/SKILL.md", self.ledger()["files"])

    def test_ledger_written_under_legacy_target_alias_is_accepted_and_rewritten(self) -> None:
        """target 改名（portable → shared-agents）後も旧名 ledger を読み、次の push で新名に書き直す。"""
        from harness_lib import distribution_state

        self.push()
        ledger_path = self.live / LEDGER_FILENAME
        data = json.loads(ledger_path.read_text(encoding="utf-8"))
        data["target"] = "legacy-claude"
        ledger_path.write_text(json.dumps(data) + "\n", encoding="utf-8")
        original = distribution_state.LEDGER_TARGET_ALIASES
        distribution_state.LEDGER_TARGET_ALIASES = {"claude": ("legacy-claude",)}
        try:
            self.assertEqual(
                distribution_state._read_ledger(PathFileSystem(), self.live, "claude"), data["files"]
            )
        finally:
            distribution_state.LEDGER_TARGET_ALIASES = original
        # 本物の alias 表（shared-agents ← portable）は subprocess 経由で検証する
        data["target"] = "portable"
        ledger_path.write_text(json.dumps(data) + "\n", encoding="utf-8")
        code, output = run_distribute_cli([
            "claude", "--push", "--live", str(self.live), "--repo-root", str(self.repo),
        ])
        self.assertEqual(code, 2, msg=output)
        self.assertIn("target mismatch", output)

    def test_corrupt_or_wrong_target_ledger_fails_before_overwrite(self) -> None:
        self.push()
        live_claude = self.live / "CLAUDE.md"
        live_claude.write_text("local edit\n", encoding="utf-8")
        ledger_path = self.live / LEDGER_FILENAME
        ledger_path.write_text('{"schemaVersion":1,"target":"other","files":{}}\n')

        code, output = self.push()

        self.assertEqual(code, 2)
        self.assertIn("target mismatch", output)
        self.assertEqual(live_claude.read_text(encoding="utf-8"), "local edit\n")

    def test_malformed_ledger_root_fails_closed(self) -> None:
        """root が object でない ledger は AttributeError ではなく ValueError で止まる。"""
        self.push()
        (self.live / "CLAUDE.md").write_text("local edit\n", encoding="utf-8")
        for raw in ("null\n", "[]\n", '"text"\n'):
            with self.subTest(raw=raw):
                (self.live / LEDGER_FILENAME).write_text(raw, encoding="utf-8")
                code, output = self.push()
                self.assertEqual(code, 2, msg=output)
                self.assertIn("distribution ledger", output)
                self.assertEqual((self.live / "CLAUDE.md").read_text(encoding="utf-8"), "local edit\n")

    def test_traversal_entry_is_rejected(self) -> None:
        outside = self.live.parent / "outside.txt"
        outside.write_text("safe\n", encoding="utf-8")
        digest = hashlib.sha256(b"safe\n").hexdigest()
        (self.live / LEDGER_FILENAME).write_text(json.dumps({
            "schemaVersion": 1,
            "target": "claude",
            "files": {"../outside.txt": digest},
        }))

        code, output = self.push()

        self.assertEqual(code, 2)
        self.assertIn("distribution ledger", output)
        self.assertIn("..", output)
        self.assertEqual(outside.read_text(encoding="utf-8"), "safe\n")

    def test_incomplete_destination_is_never_planned_for_removal(self) -> None:
        stale = self.live / "skills/private/SKILL.md"
        stale.parent.mkdir(parents=True)
        stale.write_text("private\n", encoding="utf-8")
        digest = hashlib.sha256(b"private\n").hexdigest()

        removable, pending, modified = _plan_ledger_cleanup(
            {"skills/private/SKILL.md": digest}, {}, {"skills/"}, self.live, PathFileSystem()
        )

        self.assertEqual(removable, [])
        self.assertEqual(pending, {"skills/private/SKILL.md": digest})
        self.assertEqual(modified, [])

    def test_file_in_both_obsolete_and_ledger_is_removed_once(self) -> None:
        """obsoleteFiles 宣言済みのパスが ledger にも残っている場合、
        obsolete ループだけが退避を所有し、ledger cleanup と二重処理しない。"""
        self.push()
        shutil.rmtree(self.repo / "packages/core/skills/demo-skill")
        cfg_path = self.repo / "packages/targets/claude/config.json"
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        cfg["obsoleteFiles"] = ["skills/demo-skill/SKILL.md"]
        cfg_path.write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")

        code, output = self.push()

        self.assertEqual(code, 0, msg=output)
        self.assertFalse((self.live / "skills/demo-skill/SKILL.md").exists())
        self.assertIn("[obsolete] skills/demo-skill/SKILL.md", output)
        self.assertNotIn("[removed-managed] skills/demo-skill/SKILL.md", output)
        self.assertNotIn("skills/demo-skill/SKILL.md", self.ledger()["files"])

    def test_check_reports_stale_managed_file(self) -> None:
        self.push()
        shutil.rmtree(self.repo / "packages/core/skills/demo-skill")

        code, output = run_distribute_cli([
            "claude", "--check", "--live", str(self.live),
            "--repo-root", str(self.repo),
        ])

        self.assertEqual(code, 1)
        self.assertIn("[stale-managed] skills/demo-skill/SKILL.md", output)

    def test_skill_override_is_checked_and_hashed_as_distributed_bytes(self) -> None:
        override = (
            "---\n"
            "name: demo-skill\n"
            "description: overridden\n"
            "---\n"
            "# Override\n"
        )
        override_path = (
            self.repo / "packages/extras/_active/skill-overrides/demo-skill/SKILL.md"
        )
        override_path.parent.mkdir(parents=True)
        override_path.write_text(override, encoding="utf-8")

        code, output = self.push()

        self.assertEqual(code, 0, msg=output)
        check_code, check_output = run_distribute_cli([
            "claude", "--check", "--live", str(self.live),
            "--repo-root", str(self.repo),
        ])
        self.assertEqual(check_code, 0, msg=check_output)
        expected_digest = hashlib.sha256(override.encode("utf-8")).hexdigest()
        self.assertEqual(
            self.ledger()["files"]["skills/demo-skill/SKILL.md"],
            expected_digest,
        )


if __name__ == "__main__":
    unittest.main()
