#!/usr/bin/env python3
"""validator が壊れた入力で traceback にならず Finding を返すことの検証。

2026-08-29 Codex 監査 P1: policy table / target config / workflow JSON が壊れている
（JSON でない・root が null や配列）と `.get()` の AttributeError で validator 全体が
止まっていた。読み込みは harness_lib.jsonio に一本化し、失敗は Finding として報告する。
"""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from harness_lib import danger_rules, hook_pipeline  # noqa: E402
from harness_lib.config import target_config_paths, target_names  # noqa: E402
from harness_lib.jsonio import JsonLoadError, load_json_object  # noqa: E402
from harness_lib.policy_kernel import TableSpec, check_table  # noqa: E402
from harness_lib.validators import CHECKS  # noqa: E402
from harness_lib.validators.context_md import check_context_target_table  # noqa: E402
from harness_lib.validators.distribution_sources import (  # noqa: E402
    check_config_schema,
    check_target_config_sources,
)
from harness_lib.validators.workflow_contract import check_core_workflow_contract  # noqa: E402


class TestLoadJsonObject(unittest.TestCase):
    def test_rejects_non_object_roots_and_broken_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            for body in ("null", "[1, 2]", '"str"', "{not json"):
                path = Path(tmp) / "t.json"
                path.write_text(body, encoding="utf-8")
                with self.assertRaises(JsonLoadError, msg=body):
                    load_json_object(path)

    def test_missing_file_is_a_load_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(JsonLoadError):
                load_json_object(Path(tmp) / "absent.json")


class TestCheckTableMalformedRoot(unittest.TestCase):
    def _spec(self):
        return TableSpec(name="demo", table_rel="table.json", validate=lambda table, root: [])

    def test_null_and_list_roots_become_findings(self):
        for body in ("null", "[]", "{broken"):
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                (root / "table.json").write_text(body, encoding="utf-8")
                findings = check_table(root, self._spec())
                self.assertEqual(len(findings), 1, body)
                self.assertEqual(findings[0].check, "demo")
                self.assertEqual(findings[0].level, "error")

    def test_danger_rules_and_hook_pipeline_survive_null_table(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for rel in (danger_rules._TABLE_PATH, hook_pipeline.TABLE_REL):
                path = root / rel
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("null", encoding="utf-8")
            self.assertTrue(danger_rules.check(root))
            self.assertTrue(hook_pipeline.check(root))


def _write_target_schema(root: Path) -> None:
    dst = root / "schemas" / "target-config.schema.json"
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(REPO_ROOT / "schemas" / "target-config.schema.json", dst)


def _write_config(root: Path, name: str, body: str) -> Path:
    path = root / "packages" / "targets" / name / "config.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


class TestTargetConfigEnumeration(unittest.TestCase):
    def test_missing_targets_dir_yields_empty_everywhere(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "CONTEXT.md").write_text("| 項目 | Codex |\n", encoding="utf-8")
            self.assertEqual(target_config_paths(root), [])
            self.assertEqual(target_names(root), [])
            self.assertEqual(check_context_target_table(root), [])
            self.assertEqual(check_target_config_sources(root), [])

    def test_malformed_target_config_is_reported_not_raised(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_target_schema(root)
            _write_config(root, "broken", "[1, 2, 3]")
            _write_config(root, "notjson", "{oops")
            (root / "CONTEXT.md").write_text("| 項目 | Codex |\n", encoding="utf-8")

            for check in (check_config_schema, check_target_config_sources, check_context_target_table):
                findings = check(root)
                self.assertEqual(
                    sorted(f.message.split(":")[0] for f in findings),
                    ["packages/targets/broken/config.json", "packages/targets/notjson/config.json"],
                    check.__name__,
                )
                self.assertTrue(all(f.level == "error" for f in findings))


class TestWorkflowContractMalformed(unittest.TestCase):
    def test_broken_workflow_json_is_a_finding(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workflows = root / "packages" / "core" / "workflows"
            policy = root / "packages" / "core" / "policy"
            workflows.mkdir(parents=True)
            policy.mkdir(parents=True)
            shutil.copy(
                REPO_ROOT / "packages" / "core" / "policy" / "workflow-contract.json",
                policy / "workflow-contract.json",
            )
            (workflows / "change.json").write_text("[]", encoding="utf-8")
            findings = check_core_workflow_contract(root)
            self.assertTrue(
                any("change.json" in f.message and "root" in f.message for f in findings),
                [f.message for f in findings],
            )

    def test_broken_contract_json_short_circuits(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workflows = root / "packages" / "core" / "workflows"
            policy = root / "packages" / "core" / "policy"
            workflows.mkdir(parents=True)
            policy.mkdir(parents=True)
            (policy / "workflow-contract.json").write_text("{", encoding="utf-8")
            (workflows / "change.json").write_text(json.dumps({"initialState": "a", "states": {"a": {}}}))
            findings = check_core_workflow_contract(root)
            self.assertEqual(len(findings), 1)
            self.assertIn("workflow-contract.json", findings[0].message)


class TestValidatorsOrder(unittest.TestCase):
    def test_no_duplicate_check_names(self):
        names = [name for name, _ in CHECKS]
        self.assertEqual(len(names), len(set(names)))


if __name__ == "__main__":
    unittest.main()
