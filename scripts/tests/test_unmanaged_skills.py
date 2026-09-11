#!/usr/bin/env python3
"""harness_lib/unmanaged_skills.py（未管理スキル判定）のテスト。

管理下 = core + extras + rulesync.lock + allowlist、対象 = Claude と ~/.agents。
判定は pre-push（警告）と harness-doctor.sh（FAIL）が共有する。
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
CLI = REPO_ROOT / "scripts" / "harness_lib" / "unmanaged_skills.py"

sys.path.insert(0, str(REPO_ROOT / "scripts"))
from harness_lib.unmanaged_skills import find_unmanaged  # noqa: E402


class UnmanagedSkillsFixture(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.repo = self.root / "repo"
        (self.repo / "packages" / "core" / "skills" / "core-skill").mkdir(parents=True)
        self.extras_skills = self.repo / "packages" / "extras" / "_active" / "skills"
        (self.extras_skills / "extras-skill").mkdir(parents=True)
        self.claude_dir = self.root / "claude"
        (self.claude_dir / "skills").mkdir(parents=True)
        self.agents_dir = self.root / "agents-skills"
        self.agents_dir.mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def write_allowlist(self, *names: str) -> None:
        (self.repo / "packages" / "core" / "unmanaged-skills-allowlist.json").write_text(
            json.dumps({"$comment": "test", **{n: "reason" for n in names}}), encoding="utf-8"
        )

    def write_lock(self, *names: str) -> None:
        (self.repo / "rulesync.lock").write_text(
            json.dumps({
                "lockfileVersion": 1,
                "sources": {"owner/repo": {"skills": {n: {"integrity": "sha256-x"} for n in names}}},
            }),
            encoding="utf-8",
        )

    def report(self):
        return find_unmanaged(self.repo, [self.claude_dir / "skills", self.agents_dir])

    def run_cli(self) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(CLI), "--repo-root", str(self.repo),
             "--claude-dir", str(self.claude_dir), "--agents-skills-dir", str(self.agents_dir)],
            capture_output=True, text=True, timeout=30,
        )


class TestFindUnmanaged(UnmanagedSkillsFixture):
    def test_core_extras_curated_and_allowlisted_are_managed(self):
        self.write_lock("curated-skill")
        self.write_allowlist("installer-app")
        for name in ("core-skill", "curated-skill"):
            (self.claude_dir / "skills" / name).mkdir()
        for name in ("extras-skill", "installer-app"):
            (self.agents_dir / name).mkdir()

        report = self.report()

        self.assertTrue(report.extras_known)
        self.assertEqual(report.unmanaged, ())
        self.assertFalse(report.blocking)

    def test_undeclared_skills_in_both_dirs_are_reported_with_paths(self):
        self.write_lock()
        (self.claude_dir / "skills" / "rogue-skill").mkdir()
        (self.agents_dir / "npx-installed").mkdir()

        report = self.report()

        self.assertEqual(
            report.unmanaged,
            (self.claude_dir / "skills" / "rogue-skill", self.agents_dir / "npx-installed"),
        )
        self.assertTrue(report.blocking)

    def test_missing_lock_and_allowlist_are_tolerated(self):
        (self.agents_dir / "rogue").mkdir()

        report = self.report()

        self.assertEqual(len(report.unmanaged), 1)

    def test_dot_entries_are_not_skills(self):
        # 旧 bash 実装は `ls` が隠しファイルを出さないことで .DS_Store / .claude を暗黙に除外していた
        (self.claude_dir / "skills" / ".DS_Store").write_text("", encoding="utf-8")
        (self.claude_dir / "skills" / ".claude").mkdir()
        (self.agents_dir / ".git").mkdir()

        report = self.report()

        self.assertEqual(report.unmanaged, ())

    def test_uninitialized_extras_is_never_blocking(self):
        shutil.rmtree(self.repo / "packages" / "extras")
        (self.agents_dir / "maybe-extras").mkdir()

        report = self.report()

        self.assertFalse(report.extras_known)
        self.assertEqual(len(report.unmanaged), 1)
        self.assertFalse(report.blocking)


class TestCli(UnmanagedSkillsFixture):
    def test_exit_1_with_extras_state_header_and_paths(self):
        (self.claude_dir / "skills" / "rogue-skill").mkdir()

        result = self.run_cli()

        self.assertEqual(result.returncode, 1, msg=result.stderr)
        lines = result.stdout.splitlines()
        self.assertEqual(lines[0], "extras=known")
        self.assertEqual(lines[1:], [str(self.claude_dir / "skills" / "rogue-skill")])

    def test_exit_0_when_everything_is_managed(self):
        (self.claude_dir / "skills" / "core-skill").mkdir()

        result = self.run_cli()

        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertEqual(result.stdout.splitlines(), ["extras=known"])

    def test_exit_0_with_unknown_header_when_extras_missing(self):
        shutil.rmtree(self.repo / "packages" / "extras")
        (self.agents_dir / "maybe-extras").mkdir()

        result = self.run_cli()

        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertEqual(result.stdout.splitlines()[0], "extras=unknown")
        self.assertIn("maybe-extras", result.stdout)


if __name__ == "__main__":
    unittest.main()
