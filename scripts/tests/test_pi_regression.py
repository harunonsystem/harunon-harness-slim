"""scripts/pi-regression.py の契約テスト。"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
REGRESSION = REPO_ROOT / "scripts" / "pi-regression.py"


class PiRegressionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="pi-regression-test-")
        self.root = Path(self.temp.name)
        self.pi = self.root / "pi"
        self.pi.write_text(
            """#!/bin/sh
if [ "$1" = "--version" ]; then
  printf '%s\\n' '0.84.1'
  exit 0
fi
while IFS= read -r line; do
  case "$line" in
    *get_state*)
      printf '%s\\n' '{"id":"state","type":"response","command":"get_state","success":true,"data":{"isStreaming":false,"isCompacting":false,"pendingMessageCount":0,"autoCompactionEnabled":true}}'
      ;;
    *abort*)
      printf '%s\\n' '{"id":"abort","type":"response","command":"abort","success":true}'
      ;;
  esac
done
""",
            encoding="utf-8",
        )
        self.pi.chmod(0o755)
        self.agent_dir = self.root / ".pi" / "agent"
        self.agent_dir.mkdir(parents=True)
        (self.agent_dir / "settings.json").write_text(
            # pi-regression.py の SUBAGENT_PACKAGE と一致している必要がある
            json.dumps({"packages": ["npm:@gotgenes/pi-subagents@21.0.0"]}),
            encoding="utf-8",
        )
        self.addCleanup(self.temp.cleanup)

    def run_regression(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                str(REGRESSION),
                "--pi",
                str(self.pi),
                "--agent-dir",
                str(self.agent_dir),
                *args,
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )

    def test_providerless_rpc_contract_passes(self) -> None:
        result = self.run_regression()

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("[OK] rpc-state-response", result.stdout)
        self.assertIn("[OK] rpc-abort-response", result.stdout)
        self.assertIn("[OK] compaction-state", result.stdout)
        self.assertIn("[OK] subagent-package", result.stdout)

    def test_json_output_is_machine_readable(self) -> None:
        result = self.run_regression("--json")

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["summary"]["failures"], 0)
        self.assertEqual(
            {item["name"] for item in payload["results"]},
            {"pi-version", "rpc-state-response", "rpc-abort-response", "compaction-state", "subagent-package"},
        )

    def test_missing_subagent_package_is_warning_not_failure(self) -> None:
        (self.agent_dir / "settings.json").write_text(json.dumps({"packages": []}), encoding="utf-8")

        result = self.run_regression()

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("[WARN] subagent-package", result.stdout)


if __name__ == "__main__":
    unittest.main()
