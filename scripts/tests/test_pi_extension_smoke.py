#!/usr/bin/env python3
"""Tests for the providerless Pi extension startup smoke helper."""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "pi-extension-smoke.py"


def _load_smoke_module():
    spec = importlib.util.spec_from_file_location("pi_extension_smoke", SCRIPT_PATH)
    if spec is None or spec.loader is None:
        raise AssertionError(f"cannot load {SCRIPT_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestPiExtensionSmoke(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.smoke = _load_smoke_module()

    def test_reads_one_pinned_package_for_each_conflicting_extension(self) -> None:
        specs = self.smoke._target_package_specs(REPO_ROOT)

        self.assertEqual(len(specs), 2)
        self.assertTrue(specs[0].startswith("npm:@ff-labs/pi-fff@"))
        self.assertTrue(specs[1].startswith("npm:pi-tool-display@"))

    def test_parses_jsonl_rpc_output(self) -> None:
        messages = self.smoke._parse_rpc_output(
            '{"type":"event"}\n{"id":"state","success":true}\n'
        )

        self.assertEqual(messages[1]["id"], "state")
        self.assertTrue(messages[1]["success"])

    def test_rejects_non_json_rpc_output(self) -> None:
        with self.assertRaises(self.smoke.SmokeError):
            self.smoke._parse_rpc_output("startup warning\n")


if __name__ == "__main__":
    unittest.main()
