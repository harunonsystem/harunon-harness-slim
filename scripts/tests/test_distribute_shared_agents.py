#!/usr/bin/env python3
"""Shared-agents skill target contract tests."""

from __future__ import annotations

import json
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def _skill_dirs(path: Path) -> set[str]:
    if not path.is_dir():
        return set()
    return {child.name for child in path.iterdir() if (child / "SKILL.md").is_file()}


def _shared_agents_disabled() -> set[str]:
    """shared-agents の除外集合を disabled-skills SSOT（core + extras）から組み立てる。"""
    core = json.loads(
        (REPO_ROOT / "packages/core/disabled-skills.json").read_text(encoding="utf-8")
    )
    disabled = set(core.get("common", [])) | set(core.get("shared-agents", []))
    extras_path = REPO_ROOT / "packages/extras/_active/disabled-skills.json"
    if extras_path.is_file():
        extras = json.loads(extras_path.read_text(encoding="utf-8"))
        disabled |= set(extras.get("shared-agents", []))
    return disabled


class TestSharedAgentsTarget(unittest.TestCase):
    def test_all_skills_are_distributed_except_disabled(self) -> None:
        """core + extras の全 skill から disabled-skills 宣言分だけを除いて配る。

        skill pack によるキュレーションは 2026-08-19 に廃止（『SSOT にはあるが
        配布されていない』ズレの解消）。除外は互換性理由の disabled-skills.json のみ。
        """
        from scripts.harness_lib.curated_skills import list_curated_skills
        from scripts.harness_lib.resolver import manifest

        expected = (
            _skill_dirs(REPO_ROOT / "packages/core/skills")
            | _skill_dirs(REPO_ROOT / "packages/extras/_active/skills")
        ) - _shared_agents_disabled()

        result = manifest("shared-agents", REPO_ROOT)
        skills = {
            path.split("/")[1]
            for path in result.files
            if path.startswith("skills/") and path.endswith("/SKILL.md")
        }
        # curated（rulesync）は取得済みの環境でだけ manifest に乗るので比較から外す
        self.assertEqual(skills - list_curated_skills(REPO_ROOT), expected)
        # 旧 pack 外だった skill も配る
        self.assertIn("upgrade", skills)
        self.assertIn("grill-implementation", skills)
        # Claude 専用（common disabled）の skill は配らない
        self.assertNotIn("figma-implement", skills)
        self.assertNotIn("sentry-fix", skills)
        self.assertNotIn("codex-reset-credits", skills)

    def test_frontmatter_transform_and_shared_assets(self) -> None:
        from scripts.harness_lib.resolver import manifest

        result = manifest("shared-agents", REPO_ROOT)
        body = result.files["skills/run-change/SKILL.md"].decode("utf-8")
        self.assertIn("compatibility:", body)
        self.assertNotIn("allowed-tools:", body)
        self.assertIn("policy/harnessctl.py", result.files)
        self.assertIn("workflows/change.json", result.files)

    def test_lesson_ledger_is_distributed(self) -> None:
        from scripts.harness_lib.resolver import manifest

        result = manifest("shared-agents", REPO_ROOT)
        self.assertIn("lessons/README.md", result.files)
        self.assertIn("lessons/lessons.json", result.files)

    def test_runtime_targets_do_not_duplicate_shared_agents_skills(self) -> None:
        from scripts.harness_lib.resolver import manifest

        expected_target_skills = {
            "codex": {"bm25-code-search", "codex-reset-credits"},
            "opencode": set(),
            "omp": set(),
            "pi": set(),
        }
        for target, expected in expected_target_skills.items():
            with self.subTest(target=target):
                result = manifest(target, REPO_ROOT)
                target_skills = {
                    path.split("/", 2)[1]
                    for path in result.files
                    if path.startswith("skills/")
                }
                self.assertEqual(target_skills, expected)


if __name__ == "__main__":
    unittest.main()
