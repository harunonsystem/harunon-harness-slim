#!/usr/bin/env python3
"""Contracts for retired harness skills."""

from __future__ import annotations

import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


class TestRetiredHarnessSkills(unittest.TestCase):
    def test_retired_global_skill_names_are_not_reintroduced(self) -> None:
        commands = (REPO_ROOT / "packages/core/commands.md").read_text(
            encoding="utf-8"
        )
        for command in ("/caveman", "/ponytail-debt"):
            with self.subTest(command=command):
                self.assertNotIn(command, commands)

        for skill in ("caveman", "ponytail-debt"):
            with self.subTest(skill=skill):
                self.assertFalse(
                    (REPO_ROOT / "packages/core/skills" / skill).exists(),
                    f"retired skill must stay outside the Harness core: {skill}",
                )

    def test_insights_is_owned_by_claude(self) -> None:
        self.assertFalse(
            (REPO_ROOT / "packages/core/skills/insights").exists(),
            "Claude native /insights must not be vendored by the harness",
        )
        self.assertNotIn(
            "/insights",
            (REPO_ROOT / "packages/core/commands.md").read_text(encoding="utf-8"),
        )
        self.assertNotIn(
            "/insights",
            (REPO_ROOT / ".claude/skills/sync-settings/SKILL.md").read_text(
                encoding="utf-8"
            ),
        )

    def test_harness_publish_and_update_are_folded_into_sync_settings(self) -> None:
        """配布運用 skill は sync-settings 1 本に集約した（2026-08-28）。

        harness-publish / harness-update は sync-settings と同じ 3 本のスクリプトを
        別の入口から呼ぶだけで、固有の中身が腐って残る面積になっていた。
        publish.sh は配布先が 3 ターゲット固定・curated 層を配らず、
        `origin main` 直 push 前提が PR 運用と噛み合わないため同時に廃止した。
        """
        for path in (
            ".claude/skills/harness-publish",
            ".claude/skills/harness-update",
            "scripts/publish.sh",
            "scripts/tests/test_publish.py",
        ):
            with self.subTest(path=path):
                self.assertFalse(
                    (REPO_ROOT / path).exists(),
                    f"retired harness tooling must not come back: {path}",
                )

        survivor = (REPO_ROOT / ".claude/skills/sync-settings/SKILL.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("--update", survivor, "更新チェックの吸収先が失われている")

    def test_loop_engineering_is_retired(self) -> None:
        self.assertFalse(
            (REPO_ROOT / "packages/core/skills/loop-engineering").exists()
        )
        self.assertNotIn(
            "/loop-engineering",
            (REPO_ROOT / "packages/core/commands.md").read_text(encoding="utf-8"),
        )
        self.assertNotIn(
            '"loop-engineering"',
            (REPO_ROOT / "packages/core/disabled-skills.json").read_text(
                encoding="utf-8"
            ),
        )


if __name__ == "__main__":
    unittest.main()
