"""scripts/pi-safe.sh の安全境界テスト。"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SAFE = REPO_ROOT / "scripts" / "pi-safe.sh"


class PiSafeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="pi-safe-test-")
        self.root = Path(self.temp.name)
        self.bin_dir = self.root / "bin"
        self.bin_dir.mkdir()
        for command in ("dirname", "pwd", "mkdir", "chmod"):
            source = shutil.which(command)
            if source is None:
                raise RuntimeError(f"{command} is required")
            (self.bin_dir / command).symlink_to(source)
        self._write_command("docker", """#!/bin/sh
if [ "$1" = "info" ]; then
  exit 1
fi
printf '%s\\n' "$*" >> "$PI_SAFE_DOCKER_LOG"
""")
        self._write_command("orbctl", """#!/bin/sh
if [ "$1" = "status" ]; then
  printf '%s\\n' 'Stopped'
  exit 0
fi
exit 1
""")
        self.env = os.environ.copy()
        self.env["PATH"] = str(self.bin_dir)
        self.env["PI_SAFE_DOCKER_LOG"] = str(self.root / "docker.log")
        self.addCleanup(self.temp.cleanup)

    def _write_command(self, name: str, content: str) -> None:
        path = self.bin_dir / name
        path.write_text(content, encoding="utf-8")
        path.chmod(0o755)

    def run_safe(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["/bin/bash", str(SAFE), *args],
            env=self.env,
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )

    def test_reports_stopped_orbstack_instead_of_generic_image_error(self) -> None:
        result = self.run_safe("--build", "--network", "none", "--", "pi", "--version")

        self.assertEqual(result.returncode, 2)
        self.assertIn("Docker daemonが停止しています", result.stderr)
        self.assertIn("orbctl start", result.stderr)
        self.assertFalse((self.root / "docker.log").exists())

    def test_dry_run_does_not_require_daemon(self) -> None:
        result = self.run_safe("--dry-run", "--network", "none", "--", "pi", "--version")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--network none", result.stdout)
        self.assertIn("--env PI_OFFLINE=1", result.stdout)
        self.assertFalse((self.root / "docker.log").exists())

    def test_non_tty_run_does_not_request_tty_allocation(self) -> None:
        self._write_command("docker", """#!/bin/sh
if [ "$1" = "info" ]; then
  exit 0
fi
if [ "$1" = "image" ] && [ "$2" = "inspect" ]; then
  exit 0
fi
printf '%s\\n' "$*" >> "$PI_SAFE_DOCKER_LOG"
""")

        result = self.run_safe("--network", "none", "--", "pi", "--version")

        self.assertEqual(result.returncode, 0, result.stderr)
        docker_log = (self.root / "docker.log").read_text(encoding="utf-8")
        self.assertIn("run --rm -i", docker_log)
        self.assertNotIn("run --rm -it", docker_log)

    def test_pi_options_must_follow_separator(self) -> None:
        result = self.run_safe("--version")

        self.assertEqual(result.returncode, 2)
        self.assertIn("Pi optionsは -- の後ろ", result.stderr)


if __name__ == "__main__":
    unittest.main()
