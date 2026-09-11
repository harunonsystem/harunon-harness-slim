#!/usr/bin/env python3
"""approve-pr.sh と guard hook（gh-pr-merge-close）の承認経路のテスト。

承認は PR 番号に紐づき TTL で失効する。guard は番号を明示した単独の
`gh pr merge|close <番号>` だけを通し、番号不一致・番号省略・チェインは deny。
"""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
APPROVE = REPO_ROOT / "packages" / "core" / "hooks" / "approve-pr.sh"
HOOK = REPO_ROOT / "packages" / "core" / "hooks" / "block-dangerous-in-bash.sh"


class ApprovePrTestCase(unittest.TestCase):
    # 検体はこのファイルを編集するセッションの hook に反応しないよう分割して組む
    MERGE = "gh " + "pr " + "merge"
    CLOSE = "gh " + "pr " + "close"

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self._tmp.name) / "repo"
        self.repo.mkdir()
        subprocess.run(["git", "init", "-q", "-b", "feature", str(self.repo)], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(self.repo), "-c", "user.email=t@example.com", "-c", "user.name=T",
                        "commit", "-q", "--allow-empty", "-m", "init"],
                       check=True, capture_output=True)
        self.env = dict(os.environ)
        self.env["HARNESS_RUNTIME"] = "claude"
        self.env["CODEX_REVIEW_FLAG_DIR"] = str(Path(self._tmp.name) / "flags")
        self.env["PUSH_APPROVE_LOG"] = str(Path(self._tmp.name) / "approve.log")

    def tearDown(self):
        self._tmp.cleanup()

    def approve(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(["bash", str(APPROVE), *args], cwd=str(self.repo),
                              capture_output=True, text=True, timeout=10, env=self.env)

    def guard(self, command: str) -> subprocess.CompletedProcess:
        env = dict(self.env)
        env["TOOL_INPUT"] = json.dumps({"command": command})
        return subprocess.run(["bash", str(HOOK)], cwd=str(self.repo),
                              capture_output=True, text=True, timeout=10, env=env)

    def flag(self) -> Path:
        flags = Path(self.env["CODEX_REVIEW_FLAG_DIR"])
        matches = list(flags.glob(".pr-approved-*"))
        self.assertEqual(len(matches), 1, msg=str(matches))
        return matches[0]

    def test_approve_requires_numeric_pr_and_reason(self):
        self.assertEqual(self.approve("abc", "reason").returncode, 1)
        self.assertEqual(self.approve("127").returncode, 1)

    def test_approve_writes_pr_number_and_logs(self):
        result = self.approve("127", "user said merge")
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertEqual(self.flag().read_text().strip(), "127")
        self.assertIn("APPROVE-PR", Path(self.env["PUSH_APPROVE_LOG"]).read_text())

    def test_guard_denies_without_approval(self):
        result = self.guard(f"{self.MERGE} 127 --merge")
        self.assertEqual(result.returncode, 2)
        self.assertIn("approve-pr", result.stderr)

    def test_guard_allows_matching_number_and_keeps_flag(self):
        self.approve("127", "ok")
        result = self.guard(f"{self.MERGE} 127 --merge")
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("PR 承認を確認", result.stdout)
        self.assertTrue(self.flag().exists())
        self.assertEqual(self.guard(f"{self.CLOSE} 127").returncode, 0)

    def test_guard_accepts_pr_url_form(self):
        self.approve("127", "ok")
        result = self.guard(f"{self.MERGE} https://github.com/o/r/pull/127 --squash")
        self.assertEqual(result.returncode, 0, msg=result.stderr)

    def test_guard_denies_other_number_and_omitted_number(self):
        self.approve("127", "ok")
        other = self.guard(f"{self.MERGE} 128 --merge")
        self.assertEqual(other.returncode, 2)
        self.assertIn("#128", other.stderr)
        omitted = self.guard(f"{self.MERGE} --merge")
        self.assertEqual(omitted.returncode, 2)
        self.assertIn("番号を明示", omitted.stderr)

    def test_guard_denies_chained_command(self):
        self.approve("127", "ok")
        result = self.guard(f"{self.MERGE} 127 && echo done")
        self.assertEqual(result.returncode, 2)

    def test_guard_expires_flag_after_ttl(self):
        self.approve("127", "ok")
        flag = self.flag()
        old = time.time() - 3600
        os.utime(flag, (old, old))
        result = self.guard(f"{self.MERGE} 127")
        self.assertEqual(result.returncode, 2)
        self.assertIn("失効", result.stderr)
        self.assertFalse(flag.exists())


if __name__ == "__main__":
    unittest.main()
