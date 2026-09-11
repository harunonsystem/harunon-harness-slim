"""scripts/pi-doctor.py の契約テスト。"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
DOCTOR = REPO_ROOT / "scripts" / "pi-doctor.py"


class PiDoctorTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="pi-doctor-test-")
        self.root = Path(self.temp.name)
        self.home = self.root / "home"
        self.agent_dir = self.home / ".pi" / "agent"
        self.agent_dir.mkdir(parents=True)
        self.bin_dir = self.root / "bin"
        self.bin_dir.mkdir()
        self._write_command(
            "pi",
            """#!/bin/sh
if [ "$1" = "--version" ]; then
  printf '%s\\n' '0.84.1'
  exit 0
fi
exit 0
""",
        )
        self._write_command(
            "mise",
            """#!/bin/sh
case "$1 $2 $3" in
  'ls npm:@earendil-works/pi-coding-agent ')
    printf '%s\\n' 'npm:@earendil-works/pi-coding-agent 0.84.1'
    ;;
  'which pi ')
    printf '%s\\n' "$FAKE_MISE_PI"
    ;;
  *)
    exit 1
    ;;
esac
""",
        )

        self._write_settings(
            [
                "npm:@narumitw/pi-subagents@0.20.0",
                "git:github.com/example/package@0123456789abcdef",
            ]
        )

        self.env = os.environ.copy()
        self.env["HOME"] = str(self.home)
        self.env["PATH"] = str(self.bin_dir)
        self.env["FAKE_MISE_PI"] = str(self.bin_dir / "pi")

        self.addCleanup(self.temp.cleanup)

    def _write_command(self, name: str, content: str) -> None:
        path = self.bin_dir / name
        path.write_text(content, encoding="utf-8")
        path.chmod(0o755)

    def _write_settings(self, packages: list[object]) -> None:
        self.agent_dir.joinpath("settings.json").write_text(
            json.dumps({"packages": packages}, ensure_ascii=False),
            encoding="utf-8",
        )

    def run_doctor(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(DOCTOR), "--agent-dir", str(self.agent_dir), *args],
            env=self.env,
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )

    def test_passes_when_mise_and_path_resolve_to_same_pi(self) -> None:
        result = self.run_doctor()

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("Pi doctor:", result.stdout)
        self.assertIn("[OK] mise-resolution", result.stdout)
        self.assertIn("全てpin済み", result.stdout)

    def test_fails_when_mise_resolution_differs(self) -> None:
        other_pi = self.root / "other-pi"
        other_pi.write_text("#!/bin/sh\nprintf 'other\\n'\n", encoding="utf-8")
        other_pi.chmod(0o755)
        self.env["FAKE_MISE_PI"] = str(other_pi)

        result = self.run_doctor()

        self.assertEqual(result.returncode, 1)
        self.assertIn("一致しません", result.stdout)

    def test_fails_for_unpinned_package(self) -> None:
        self._write_settings(["npm:unversioned-package"])

        result = self.run_doctor()

        self.assertEqual(result.returncode, 1)
        self.assertIn("pinされていないpackageが 1 件", result.stdout)

    def test_json_output_contains_status_without_credentials(self) -> None:
        self.agent_dir.joinpath("auth.json").write_text(
            '{"openai-codex":{"access":"secret-must-not-appear"}}',
            encoding="utf-8",
        )

        result = self.run_doctor("--json")

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["summary"]["failures"], 0)
        self.assertNotIn("secret-must-not-appear", result.stdout)
        self.assertIn("credential file present（内容は未読）", result.stdout)

    def test_warns_when_skill_is_installed_in_both_locations(self) -> None:
        (self.agent_dir / "skills" / "duplicate" ).mkdir(parents=True)
        (self.agent_dir / "skills" / "duplicate" / "SKILL.md").write_text("# pi\n", encoding="utf-8")
        shared = self.home / ".agents" / "skills" / "duplicate"
        shared.mkdir(parents=True)
        (shared / "SKILL.md").write_text("# shared\n", encoding="utf-8")

        result = self.run_doctor()

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("[WARN] skill-collision", result.stdout)


if __name__ == "__main__":
    unittest.main()
