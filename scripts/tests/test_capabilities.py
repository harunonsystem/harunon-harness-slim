#!/usr/bin/env python3
"""Capability contract tests (written before the implementation)."""
from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPTS_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = SCRIPTS_DIR.parent


def _load_capabilities():
    sys.path.insert(0, str(SCRIPTS_DIR))
    from harness_lib import capabilities

    return capabilities


capabilities = _load_capabilities()


def _write_fixture(root: Path, *, targets: list[str] | None = None) -> None:
    targets = targets or ["claude"]
    target_dir = root / "packages" / "targets"
    for name in targets:
        path = target_dir / name
        path.mkdir(parents=True, exist_ok=True)
        (path / "config.json").write_text(
            json.dumps(
                {
                    "name": name,
                    "displayName": name,
                    "configDir": f"~/.{name}",
                    "configFile": "settings.json",
                    "instructionsFile": "AGENTS.md",
                    "auxiliary": False,
                    "distribute": {},
                }
            ),
            encoding="utf-8",
        )

    (root / "packages" / "core").mkdir(parents=True, exist_ok=True)
    (root / "packages" / "core" / "proof.md").write_text(
        "instruction routing deterministic distribution workflow state\n",
        encoding="utf-8",
    )
    (root / "schemas").mkdir(parents=True, exist_ok=True)
    (root / "schemas" / "capability-contract.schema.json").write_text(
        (REPO_ROOT / "schemas" / "capability-contract.schema.json").read_text(
            encoding="utf-8"
        ),
        encoding="utf-8",
    )
    (root / "schemas" / "target-config.schema.json").write_text(
        (REPO_ROOT / "schemas" / "target-config.schema.json").read_text(
            encoding="utf-8"
        ),
        encoding="utf-8",
    )


def _contract(targets: list[str] | None = None, dimensions: list[str] | None = None) -> dict:
    target_names = targets or ["claude"]
    dimension_names = dimensions or ["instruction_routing"]
    claim = {
        "verdict": "SUPPORTED",
        "statement": "Static wiring is present; this does not prove live behavior.",
        "evidence": [{"path": "packages/core/proof.md", "contains": ["instruction routing"]}],
    }
    return {
        "schemaVersion": 1,
        "dimensions": dimension_names,
        "claims": {target: {dimension_names[0]: claim} for target in target_names},
    }


def _copy_contract_fixture(root: Path, target: str = "claude") -> dict:
    """Copy one target's contract evidence into a small isolated repo."""
    source_contract = json.loads(
        (REPO_ROOT / "packages/core/capability-contract.json").read_text(
            encoding="utf-8"
        )
    )
    contract = dict(source_contract)
    contract["claims"] = {target: source_contract["claims"][target]}
    (root / "packages/core").mkdir(parents=True, exist_ok=True)
    (root / "schemas").mkdir(parents=True, exist_ok=True)
    shutil.copy2(
        REPO_ROOT / "schemas/capability-contract.schema.json",
        root / "schemas/capability-contract.schema.json",
    )
    target_config = REPO_ROOT / "packages/targets" / target / "config.json"
    target_config_dest = root / "packages/targets" / target / "config.json"
    target_config_dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(target_config, target_config_dest)
    copied: set[str] = set()
    for claim in contract["claims"][target].values():
        for evidence in claim.get("evidence", []):
            rel = evidence["path"]
            if rel in copied:
                continue
            copied.add(rel)
            source = REPO_ROOT / rel
            destination = root / rel
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
    (root / "packages/core/capability-contract.json").write_text(
        json.dumps(contract), encoding="utf-8"
    )
    return contract


class TestCapabilityContract(unittest.TestCase):
    def test_instruction_routing_uses_include_markers(self):
        marker = "<!-- include: packages/core/fragments/agents-md/routing.md -->"
        contract = json.loads(
            (REPO_ROOT / "packages/core/capability-contract.json").read_text(
                encoding="utf-8"
            )
        )
        for target in ("codex", "opencode", "pi", "omp"):
            evidence = contract["claims"][target]["instruction_routing"]["evidence"]
            tokens = [token for item in evidence for token in item["contains"]]
            self.assertIn(marker, tokens, target)

    def test_removed_routing_include_marker_is_drift(self):
        marker = "<!-- include: packages/core/fragments/agents-md/routing.md -->"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            contract = _copy_contract_fixture(root, "codex")
            agents = root / "packages/targets/codex/AGENTS.md"
            agents.write_text(agents.read_text(encoding="utf-8").replace(marker, ""), encoding="utf-8")
            findings = capabilities.reconcile(root)["findings"]
            self.assertTrue(any(f.code == "evidence-token" for f in findings))

    def test_gate_claims_include_target_wiring_and_claude_hook_registration(self):
        contract = json.loads(
            (REPO_ROOT / "packages/core/capability-contract.json").read_text(
                encoding="utf-8"
            )
        )
        expected = {
            "claude": ("hooks/", "packages/core/hooks/"),
            "opencode": ("runtime/harunon-opencode/", "packages/core/opencode-plugins/"),
            "pi": ("extensions/harness-policy.js", "packages/core/pi-extensions/harness-policy.js"),
            "omp": ("extensions/harness-policy.js", "packages/core/pi-extensions/harness-policy.js"),
        }
        for target, wiring_tokens in expected.items():
            for dimension in ("pr_create_gate", "pr_merge_gate"):
                evidence = contract["claims"][target][dimension]["evidence"]
                if target == "claude" and dimension == "pr_merge_gate":
                    self.assertEqual(
                        evidence,
                        [
                            {
                                "path": "packages/core/workflows/change.json",
                                "contains": ["pr.merge"],
                            },
                            {
                                "path": "packages/core/policy/danger-rules.json",
                                "contains": ["gh-pr-merge-close"],
                            },
                        ],
                    )
                    continue
                config_items = [
                    item
                    for item in evidence
                    if item["path"] == f"packages/targets/{target}/config.json"
                ]
                tokens = [token for item in config_items for token in item["contains"]]
                for token in wiring_tokens:
                    self.assertIn(token, tokens, f"{target}/{dimension}")
                if target == "claude" and dimension == "pr_create_gate":
                    settings_items = [
                        item
                        for item in evidence
                        if item["path"] == "packages/core/settings.json"
                    ]
                    self.assertTrue(settings_items, f"{target}/{dimension}")

    def test_removed_claude_create_hook_registration_is_drift(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _copy_contract_fixture(root, "claude")
            settings = root / "packages/core/settings.json"
            settings.write_text(
                settings.read_text(encoding="utf-8").replace(
                    "block-pr-without-codex-review.sh", ""
                ),
                encoding="utf-8",
            )
            findings = capabilities.reconcile(root)["findings"]
            self.assertTrue(any(f.code == "evidence-token" for f in findings))

    def test_removed_gate_wiring_token_is_drift(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            contract = _copy_contract_fixture(root, "opencode")
            config = root / "packages/targets/opencode/config.json"
            config.write_text(
                config.read_text(encoding="utf-8").replace("runtime/harunon-opencode/", ""),
                encoding="utf-8",
            )
            findings = capabilities.reconcile(root)["findings"]
            self.assertTrue(any(f.code == "evidence-token" for f in findings))

    def test_review_head_binding_uses_exact_head_tokens(self):
        marker = 'evidence["subjectSha"] == head'
        contract = json.loads(
            (REPO_ROOT / "packages/core/capability-contract.json").read_text(
                encoding="utf-8"
            )
        )
        for target in ("claude", "codex", "opencode", "pi", "omp"):
            evidence = contract["claims"][target]["review_head_binding"]["evidence"]
            pairs = {(item["path"], token) for item in evidence for token in item["contains"]}
            self.assertIn(("packages/core/policy/harnessctl.py", marker), pairs, target)

    def test_removed_review_head_binding_token_is_drift(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            contract = _copy_contract_fixture(root, "codex")
            policy = root / "packages/core/policy/harnessctl.py"
            policy.write_text(
                policy.read_text(encoding="utf-8").replace('evidence["subjectSha"] == head', ""),
                encoding="utf-8",
            )
            findings = capabilities.reconcile(root)["findings"]
            self.assertTrue(any(f.code == "evidence-token" for f in findings))

    def test_schema_rejects_unknown_verdict(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_fixture(root)
            contract = _contract()
            contract["claims"]["claude"]["instruction_routing"]["verdict"] = "MAYBE"
            (root / "packages" / "core" / "capability-contract.json").write_text(
                json.dumps(contract), encoding="utf-8"
            )
            findings = capabilities.reconcile(root)
            self.assertTrue(any(f.code == "schema" for f in findings["findings"]))

    def test_rejects_missing_runtime_target_and_extra_runtime_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_fixture(root, targets=["claude", "codex"])
            contract = _contract(targets=["claude"])
            (root / "packages" / "core" / "capability-contract.json").write_text(
                json.dumps(contract), encoding="utf-8"
            )
            findings = capabilities.reconcile(root)
            codes = {f.code for f in findings["findings"]}
            self.assertIn("runtime-target-parity", codes)

    def test_rejects_missing_and_extra_dimension(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_fixture(root)
            contract = _contract(dimensions=["instruction_routing", "extra"])
            (root / "packages" / "core" / "capability-contract.json").write_text(
                json.dumps(contract), encoding="utf-8"
            )
            findings = capabilities.reconcile(root)
            self.assertTrue(
                any(f.code == "dimension-parity" for f in findings["findings"])
            )

    def test_rejects_unsafe_missing_and_unreconciled_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_fixture(root)
            contract = _contract()
            claim = contract["claims"]["claude"]["instruction_routing"]
            claim["evidence"] = [
                {"path": "../outside.md", "contains": ["x"]},
                {"path": "missing.md", "contains": ["x"]},
                {"path": "packages/core/proof.md", "contains": ["not present"]},
            ]
            (root / "packages" / "core" / "capability-contract.json").write_text(
                json.dumps(contract), encoding="utf-8"
            )
            findings = capabilities.reconcile(root)
            codes = {f.code for f in findings["findings"]}
            self.assertIn("evidence-path", codes)
            self.assertIn("evidence-token", codes)

    def test_unknown_is_clean_without_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_fixture(root)
            contract = _contract(dimensions=list(capabilities.DIMENSIONS))
            contract["claims"]["claude"] = {
                dimension: {"verdict": "UNKNOWN"}
                for dimension in capabilities.DIMENSIONS
            }
            (root / "packages" / "core" / "capability-contract.json").write_text(
                json.dumps(contract), encoding="utf-8"
            )
            self.assertEqual(capabilities.reconcile(root)["findings"], [])

    def test_target_filter_and_stable_outputs(self):
        contract_path = REPO_ROOT / "packages" / "core" / "capability-contract.json"
        self.assertTrue(contract_path.is_file())
        report = capabilities.reconcile(REPO_ROOT, targets=["codex"])
        self.assertEqual(report["targets"], ["codex"])


class TestCapabilityCli(unittest.TestCase):
    def test_json_markdown_terminal_and_exit_code(self):
        cli = SCRIPTS_DIR / "capability-bench.py"
        for output_format in ("json", "markdown", "terminal"):
            result = subprocess.run(
                [sys.executable, str(cli), "--repo-root", str(REPO_ROOT), "--no-live", "--format", output_format],
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(result.stdout.strip())
            if output_format == "json":
                payload = json.loads(result.stdout)
                self.assertEqual(
                    list(payload), ["schemaVersion", "mode", "targets", "dimensions", "claims", "findings"]
                )
            elif output_format == "markdown":
                self.assertIn("| Target |", result.stdout)
            else:
                self.assertIn("Target", result.stdout)

    def test_filtered_json_contains_only_selected_claims(self):
        cli = SCRIPTS_DIR / "capability-bench.py"
        result = subprocess.run(
            [sys.executable, str(cli), "--repo-root", str(REPO_ROOT), "--targets", "codex", "--format", "json"],
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(list(payload["claims"]), ["codex"])
        self.assertEqual(list(payload["claims"]["codex"]), list(capabilities.DIMENSIONS))

    def test_drift_exits_one_in_all_formats_without_traceback(self):
        cli = SCRIPTS_DIR / "capability-bench.py"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _copy_contract_fixture(root, "claude")
            evidence_file = root / "packages/core/CLAUDE.md"
            evidence_file.write_text(
                evidence_file.read_text(encoding="utf-8").replace("rules/codex-review-policy.md", ""),
                encoding="utf-8",
            )
            for output_format in ("json", "markdown", "terminal"):
                result = subprocess.run(
                    [sys.executable, str(cli), "--repo-root", str(root), "--format", output_format],
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(result.returncode, 1, output_format)
                self.assertTrue(result.stdout.strip(), output_format)
                self.assertIn("evidence-token", result.stdout, output_format)
                self.assertNotIn("Traceback", result.stderr, output_format)

    def test_unknown_target_is_usage_error(self):
        cli = SCRIPTS_DIR / "capability-bench.py"
        result = subprocess.run(
            [sys.executable, str(cli), "--repo-root", str(REPO_ROOT), "--targets", "ghost"],
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 2)


if __name__ == "__main__":
    unittest.main()
