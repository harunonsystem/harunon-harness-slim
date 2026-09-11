#!/usr/bin/env python3
"""Executable command and path contracts in harness documentation."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


class TestHarnessCommandDocumentation(unittest.TestCase):
    def test_repository_python_commands_use_mise(self) -> None:
        paths = (
            "CLAUDE.md",
            "README.md",
            ".claude/skills/sync-settings/SKILL.md",
            ".claude/skills/add-skill-to-repo/SKILL.md",
        )
        command_markers = (
            "scripts/validate-harness.py",
            "scripts/distribute.py",
            "scripts/run-tests.py",
        )
        for relative_path in paths:
            text = (REPO_ROOT / relative_path).read_text(encoding="utf-8")
            for line in text.splitlines():
                if "python3" in line and any(
                    marker in line for marker in command_markers
                ):
                    with self.subTest(path=relative_path, line=line):
                        self.assertIn('"$(mise which python3)"', line)

    def test_core_workflow_paths_distinguish_source_and_install(self) -> None:
        run_change = (
            REPO_ROOT / "packages/core/skills/run-change/SKILL.md"
        ).read_text(encoding="utf-8")
        pi_agents = (REPO_ROOT / "packages/targets/pi/AGENTS.md").read_text(
            encoding="utf-8"
        )
        for text in (run_change, pi_agents):
            self.assertIn("packages/core/policy/harnessctl.py", text)
            self.assertIn("policy/harnessctl.py", text)
            self.assertIn("scripts/harness.py", text)

    def test_non_claude_agents_expose_verification_loop(self) -> None:
        sys.path.insert(0, str(REPO_ROOT / "scripts"))
        from harness_lib.resolver import manifest

        for target in ("codex", "opencode", "pi", "omp"):
            with self.subTest(target=target):
                agents = manifest(target, REPO_ROOT).files["AGENTS.md"].decode("utf-8")
                self.assertIn("run-tests.py", agents)


if __name__ == "__main__":
    unittest.main()
