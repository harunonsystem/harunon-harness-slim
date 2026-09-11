"""Pi target の SoL-Pi 導入契約を固定する。"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PI_DIR = REPO_ROOT / "packages/targets/pi"
SOL_PI_NAME = "github.com/NVlabs/SoL-Pi"


class PiSolPiConfigTest(unittest.TestCase):
    def setUp(self) -> None:
        self.settings = json.loads((PI_DIR / "settings.json").read_text(encoding="utf-8"))
        self.target = json.loads((PI_DIR / "config.json").read_text(encoding="utf-8"))
        self.sol = json.loads((PI_DIR / "sol-pi.json").read_text(encoding="utf-8"))
        self.subagents = json.loads((PI_DIR / "subagents.json").read_text(encoding="utf-8"))

    def _sol_package(self) -> str:
        matches = [
            spec
            for spec in self.settings["packages"]
            if spec.startswith(f"git:{SOL_PI_NAME}@")
        ]
        self.assertEqual(len(matches), 1, matches)
        return matches[0]

    def test_sol_pi_is_exact_git_pin(self) -> None:
        spec = self._sol_package()
        sha = spec.rsplit("@", 1)[1]
        self.assertEqual(len(sha), 40)
        self.assertTrue(all(c in "0123456789abcdefABCDEF" for c in sha))

    def test_only_observation_pack_is_enabled(self) -> None:
        self.assertEqual(self.sol["version"], 1)
        self.assertTrue(self.sol["observationPack"])
        self.assertFalse(self.sol["actionFusion"])
        self.assertFalse(self.sol["evidencePreservingReducer"])
        self.assertFalse(self.sol["onlineContextCompact"])

    def test_config_files_are_distributed_to_pi_agent_root(self) -> None:
        distribute = self.target["distribute"]
        self.assertEqual(distribute["sol-pi.json"]["source"], "packages/targets/pi/sol-pi.json")
        self.assertEqual(distribute["subagents.json"]["source"], "packages/targets/pi/subagents.json")

    def test_subagent_exclusion_exactly_matches_installed_sol_pi_source(self) -> None:
        sol_spec = self._sol_package()
        excluded = self.subagents["excludedExtensionPackages"]
        self.assertIn(sol_spec, excluded)
        self.assertEqual([x for x in excluded if "NVlabs/SoL-Pi" in x], [sol_spec])


if __name__ == "__main__":
    unittest.main()
