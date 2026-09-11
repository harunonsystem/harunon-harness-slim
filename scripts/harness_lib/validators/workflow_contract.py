"""Core Workflow（packages/core/workflows/change.json）の契約検証。"""
from __future__ import annotations

from pathlib import Path

from ..validator_registry import Finding
from ._common import distribute_sources, load_json_or_finding, target_configs

WORKFLOW_CONTRACT_PATH = "packages/core/policy/workflow-contract.json"
_CHECK = "core-workflow-contract"


def check_core_workflow_contract(repo_root: Path) -> list[Finding]:
    """Core Workflow の状態遷移と必須成果物を検証する。

    target 別の必須配布 (required/gate/codex) は packages/core/policy/workflow-contract.json
    が SSOT。ここではその table を読み込み、データ駆動で照合するだけ。
    """
    workflow_path = repo_root / "packages" / "core" / "workflows" / "change.json"
    if not workflow_path.is_file():
        return []

    contract, findings = load_json_or_finding(repo_root / WORKFLOW_CONTRACT_PATH, repo_root, _CHECK)
    if contract is None:
        return findings

    for rel in contract.get("requiredFiles", []):
        path = repo_root / rel
        if not path.is_file():
            findings.append(
                Finding(check=_CHECK, level="error", message=f"必須ファイルが存在しません: {rel}")
            )

    workflow, errors = load_json_or_finding(workflow_path, repo_root, _CHECK)
    findings.extend(errors)
    if workflow is not None:
        states = workflow.get("states", {})
        if not isinstance(states, dict):
            findings.append(
                Finding(check=_CHECK, level="error", message="states はオブジェクトである必要があります")
            )
            states = {}
        initial = workflow.get("initialState")
        if initial not in states:
            findings.append(
                Finding(check=_CHECK, level="error", message=f"initialState が未定義です: {initial}")
            )
        for source, transitions in states.items():
            if not isinstance(transitions, dict):
                findings.append(
                    Finding(check=_CHECK, level="error", message=f"{source} の遷移表がオブジェクトではありません")
                )
                continue
            for event, target in transitions.items():
                if target not in states:
                    findings.append(
                        Finding(
                            check=_CHECK,
                            level="error",
                            message=f"{source}.{event} の遷移先が未定義です: {target}",
                        )
                    )

    required_distribution = contract.get("requiredDistribution", {})
    exempt_targets = set(contract.get("requiredDistributionExemptTargets", []))
    destination_overrides = contract.get("destinationOverrides", {})
    gate_distribution = contract.get("gateDistribution", {})
    codex_required = [repo_root / rel for rel in contract.get("codexRequiredFiles", [])]

    configs, config_findings = target_configs(repo_root, _CHECK)
    findings.extend(config_findings)
    for config_path, config in configs:
        distribute = config.get("distribute", {})
        if not isinstance(distribute, dict):
            distribute = {}
        target_name = config.get("name")
        if config.get("auxiliary"):
            continue
        if target_name not in exempt_targets:
            for destination, expected_source in required_distribution.items():
                destination = destination_overrides.get(target_name, {}).get(
                    destination, destination
                )
                spec = distribute.get(destination, {})
                # source は文字列と配列の両対応（rules/ 等と同じ）。配列の場合は
                # core の必須 source が含まれていれば契約を満たす。
                if isinstance(spec, dict) and expected_source in distribute_sources(spec):
                    continue
                findings.append(
                    Finding(
                        check=_CHECK,
                        level="error",
                        message=(
                            f"{config_path.relative_to(repo_root)}: {destination} は "
                            f"{expected_source} を配布する必要があります"
                        ),
                    )
                )
        if target_name == "codex":
            for path in codex_required:
                if not path.is_file():
                    findings.append(
                        Finding(
                            check=_CHECK,
                            level="error",
                            message=f"Codex plugin必須ファイルがありません: {path.relative_to(repo_root)}",
                        )
                    )
        if target_name in gate_distribution:
            gate = gate_distribution[target_name]
            destination, expected_source = gate["destination"], gate["source"]
            spec = distribute.get(destination, {})
            if not isinstance(spec, dict) or expected_source not in distribute_sources(spec):
                findings.append(
                    Finding(
                        check=_CHECK,
                        level="error",
                        message=(
                            f"{config_path.relative_to(repo_root)}: {destination} は "
                            f"Core Workflow gate {expected_source} を配布する必要があります"
                        ),
                    )
                )
    return findings


CHECKS = {_CHECK: check_core_workflow_contract}
