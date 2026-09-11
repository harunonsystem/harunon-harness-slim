#!/usr/bin/env python3
"""distribution_state の plan 構造（typed summary / FileSystem seam / 順序）を検証する。"""

from __future__ import annotations

import json
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path

_SCRIPTS_DIR = Path(__file__).resolve().parent.parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from harness_lib.distribution import Distribution  # noqa: E402
from harness_lib.distribution_state import (  # noqa: E402
    Operation,
    PathFileSystem,
    PlanSummary,
    SettingsChange,
)
from tests._helpers import make_repo  # noqa: E402


class RecordingFileSystem:
    """PathFileSystem に委譲しつつ呼び出しを記録する adapter（parity 検証用）。"""

    def __init__(self) -> None:
        self._inner = PathFileSystem()
        self.calls: list[str] = []

    def __getattr__(self, name: str):
        method = getattr(self._inner, name)

        def recorded(*args, **kwargs):
            self.calls.append(name)
            return method(*args, **kwargs)

        return recorded


class PlanFixture(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.repo = make_repo(self.tmp)
        self.live = self.tmp / "live"
        self.live.mkdir()

    def tearDown(self) -> None:
        self._tmp.cleanup()


class InspectParityTestCase(PlanFixture):
    def test_cli_does_not_bypass_distribution_interface(self) -> None:
        cli = (_SCRIPTS_DIR / "distribute.py").read_text(encoding="utf-8")
        self.assertNotIn("harness_lib.distribution_state", cli)

    def test_inspect_reports_identical_drifts_through_any_adapter(self) -> None:
        """drift 計算は 1 実装。host adapter と注入 adapter で結果が一致する。"""
        Distribution(self.repo).push("claude", self.live)
        (self.live / "CLAUDE.md").write_text("edited\n", encoding="utf-8")
        settings_path = self.live / "settings.json"
        settings = json.loads(settings_path.read_text(encoding="utf-8"))
        settings["hooks"] = {}
        settings_path.write_text(json.dumps(settings), encoding="utf-8")

        host = Distribution(self.repo).inspect("claude", self.live)
        recording = RecordingFileSystem()
        injected = Distribution(self.repo, fs=recording).inspect("claude", self.live)

        self.assertEqual(host.drifts, injected.drifts)
        self.assertIn("CLAUDE.md", [d.path for d in host.drifts])
        self.assertIn("settings.json#hooks", [d.path for d in host.drifts])
        self.assertIn("observe", recording.calls)

    def test_missing_destination_is_answered_from_the_inspection(self) -> None:
        inspection = Distribution(self.repo).inspect("claude", self.tmp / "absent")
        self.assertFalse(inspection.destination_exists)
        self.assertEqual([d.kind for d in inspection.drifts], ["missing"])


class PushPlanShapeTestCase(PlanFixture):
    def _extras_ready(self) -> Path:
        extras = self.repo / "packages/extras/_active"
        gitmodules = self.repo / ".gitmodules"
        if gitmodules.exists():
            gitmodules.unlink()
        return extras

    def test_summary_is_typed(self) -> None:
        plan = Distribution(self.repo).plan_push("claude", self.live, dry_run=True)
        self.assertIsInstance(plan.summary, PlanSummary)
        self.assertEqual(plan.summary.manifest_entries, len(Distribution(self.repo).manifest("claude").files))
        self.assertEqual(plan.summary.unchanged_count, 0)

    def test_settings_sync_operation_carries_a_typed_change(self) -> None:
        Distribution(self.repo).push("claude", self.live)
        settings_path = self.live / "settings.json"
        settings = json.loads(settings_path.read_text(encoding="utf-8"))
        settings["hooks"] = {}
        settings_path.write_text(json.dumps(settings), encoding="utf-8")

        plan = Distribution(self.repo).plan_push("claude", self.live, dry_run=True)

        sync_ops = [op for op in plan.operations if op.kind == "settings-sync"]
        self.assertEqual(len(sync_ops), 1)
        self.assertEqual(sync_ops[0].change, SettingsChange("", ("hooks",), ()))
        self.assertIsNone(sync_ops[0].reason)

    def test_skill_override_is_written_exactly_once(self) -> None:
        """override は manifest に合成済み。別 operation で二重に書かない。"""
        Distribution(self.repo).push("claude", self.live)
        extras = self._extras_ready()
        override = extras / "skill-overrides/demo-skill/SKILL.md"
        override.parent.mkdir(parents=True)
        override.write_text("---\nname: demo-skill\ndescription: overridden\n---\n", encoding="utf-8")

        plan = Distribution(self.repo).plan_push("claude", self.live, dry_run=True)

        writes = [op for op in plan.operations if op.path == "skills/demo-skill/SKILL.md" and op.payload is not None]
        self.assertEqual([op.kind for op in writes], ["overwrite"])
        self.assertNotIn("skill-overrides", {op.kind for op in plan.operations})

    def test_same_path_is_backed_up_once_across_manifest_and_settings(self) -> None:
        """settings.json が manifest と settingsSync の両方に触られても backup は 1 回。"""
        Distribution(self.repo).push("claude", self.live)
        settings_path = self.live / "settings.json"
        settings = json.loads(settings_path.read_text(encoding="utf-8"))
        settings["hooks"] = {}
        settings_path.write_text(json.dumps(settings), encoding="utf-8")
        extras = self._extras_ready()
        (extras / "settings-overlay.json").write_text('{"overlay_key": "v"}', encoding="utf-8")

        plan = Distribution(self.repo).plan_push("claude", self.live, dry_run=True)

        backups = [op for op in plan.operations if op.kind == "backup" and op.path == "settings.json"]
        self.assertEqual(len(backups), 1)

    def test_operations_are_ordered_by_replay_phase(self) -> None:
        Distribution(self.repo).push("claude", self.live)
        (self.live / "CLAUDE.md").write_text("edited\n", encoding="utf-8")
        cfg_path = self.repo / "packages/targets/claude/config.json"
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        cfg["obsoleteFiles"] = ["legacy.md"]
        cfg_path.write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
        (self.live / "legacy.md").write_text("old\n", encoding="utf-8")

        plan = Distribution(self.repo).plan_push("claude", self.live, dry_run=True)

        kinds = [op.kind for op in plan.operations]
        self.assertLess(kinds.index("backup"), kinds.index("overwrite"))
        self.assertLess(kinds.index("overwrite"), kinds.index("remove-obsolete"))
        self.assertLess(kinds.index("remove-obsolete"), kinds.index("ledger"))
        self.assertEqual(kinds[-1], "cleanup-backups")
        cleanup = plan.operations[-1]
        self.assertIsInstance(cleanup, Operation)
        self.assertEqual(cleanup.paths, ())


class PathFileSystemTestCase(unittest.TestCase):
    def test_atomic_write_preserves_existing_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "hook.sh"
            path.write_text("#!/bin/sh\n", encoding="utf-8")
            path.chmod(0o755)

            PathFileSystem().atomic_write(path, b"#!/bin/sh\nexit 0\n")

            self.assertEqual(path.read_bytes(), b"#!/bin/sh\nexit 0\n")
            self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o755)

    def test_remove_tree_handles_files_and_directories(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "dir/sub").mkdir(parents=True)
            (root / "dir/sub/f").write_text("x", encoding="utf-8")
            (root / "file").write_text("x", encoding="utf-8")
            fs = PathFileSystem()
            fs.remove_tree(root / "dir")
            fs.remove_tree(root / "file")
            self.assertEqual(list(root.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
