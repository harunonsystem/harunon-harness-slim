#!/usr/bin/env python3
"""OpenCode optimized launcher distribution tests."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
DISTRIBUTE = REPO_ROOT / "scripts/distribute.py"


class TestOpenCodeLauncher(unittest.TestCase):
    def test_distribution_is_executable_and_sets_startup_env(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "bin"
            result = subprocess.run(
                [
                    sys.executable,
                    str(DISTRIBUTE),
                    "opencode-launcher",
                    "--push",
                    "--dest",
                    str(dest),
                    "--repo-root",
                    str(REPO_ROOT),
                ],
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            launcher = dest / "opencode"
            self.assertTrue(os.access(launcher, os.X_OK))

            real = Path(tmp) / "real-opencode"
            real.write_text('#!/bin/sh\nprintf "%s" "$OPENCODE_DISABLE_CLAUDE_CODE_SKILLS"\n')
            real.chmod(0o755)
            invoked = subprocess.run(
                [str(launcher)],
                env={**os.environ, "OPENCODE_REAL_BIN": str(real)},
                capture_output=True,
                text=True,
            )
            self.assertEqual(invoked.returncode, 0, msg=invoked.stderr)
            self.assertEqual(invoked.stdout, "1")


if __name__ == "__main__":
    unittest.main()
