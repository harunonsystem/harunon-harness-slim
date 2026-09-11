#!/usr/bin/env python3
"""post-edit-checks.sh（runtime 中立の write/edit 後チェック）の契約テスト。"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "packages/core/hooks/post-edit-checks.sh"


def run(path: Path, env: dict | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(SCRIPT), str(path)],
        capture_output=True, text=True, check=False,
        env={**os.environ, **(env or {})},
    )


class TestPostEditChecks(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())

    def test_missing_or_unknown_file_is_silent_success(self) -> None:
        result = run(self.tmp / "nope.sh")
        self.assertEqual((result.returncode, result.stdout), (0, ""))
        ts = self.tmp / "a.ts"
        ts.write_text("const x = ;", encoding="utf-8")
        result = run(ts)
        self.assertEqual((result.returncode, result.stdout), (0, ""))

    def test_broken_json_reports_and_never_blocks(self) -> None:
        if shutil.which("jq") is None:
            self.skipTest("jq がない")
        bad = self.tmp / "bad.json"
        bad.write_text("{broken", encoding="utf-8")
        result = run(bad)
        self.assertEqual(result.returncode, 0)
        self.assertTrue(result.stdout.startswith("invalid JSON:\n"), result.stdout)
        good = self.tmp / "good.json"
        good.write_text('{"a": 1}', encoding="utf-8")
        self.assertEqual(run(good).stdout, "")

    def test_shellcheck_findings_reported(self) -> None:
        if shutil.which("shellcheck") is None:
            self.skipTest("shellcheck がない")
        sh = self.tmp / "bad.sh"
        sh.write_text("#!/bin/bash\ncd /tmp\nls\n", encoding="utf-8")
        result = run(sh)
        self.assertEqual(result.returncode, 0)
        self.assertTrue(result.stdout.startswith("shellcheck:\n"), result.stdout)
        self.assertIn("SC2164", result.stdout)

    def test_missing_checker_skips_silently(self) -> None:
        """PATH から shellcheck / jq を外すと指摘は出ず exit 0（checker 不在は黙ってスキップ）。"""
        bindir = self.tmp / "bin"
        bindir.mkdir()
        for name in ("bash", "dirname", "head", "printf"):
            real = shutil.which(name)
            if real:
                os.symlink(real, bindir / name)
        sh = self.tmp / "bad.sh"
        sh.write_text("#!/bin/bash\nrm $1\n", encoding="utf-8")
        bad = self.tmp / "bad.json"
        bad.write_text("{broken", encoding="utf-8")
        for target in (sh, bad):
            result = run(target, {"PATH": str(bindir)})
            self.assertEqual((result.returncode, result.stdout), (0, ""), result.stderr)

    def test_markdown_table_is_fixed_in_place(self) -> None:
        md = self.tmp / "doc.md"
        md.write_text("a | b\n--- | ---\n1 | 2\n", encoding="utf-8")
        result = run(md)
        self.assertEqual((result.returncode, result.stdout), (0, ""))
        self.assertEqual(md.read_text(encoding="utf-8").splitlines()[0], "| a | b |")


if __name__ == "__main__":
    unittest.main()
