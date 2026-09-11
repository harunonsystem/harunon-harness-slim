"""Offline capability-contract validation for the harness.

The capability contract deliberately describes wiring that is present in this
repository.  It does not inspect a user's live runtime, authenticate to a
service, or claim that a runtime behaves correctly under every invocation.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

from .config import target_names
from .schema import validate as schema_validate
from .validator_registry import Finding


SUPPORTED_EVIDENCE_VERDICTS = frozenset(("SUPPORTED", "PARTIAL"))
DIMENSIONS = (
    "instruction_routing",
    "deterministic_distribution",
    "workflow_state",
    "pr_create_gate",
    "pr_merge_gate",
    "review_head_binding",
    "safety_policy",
    "role_model_routing",
)


class CapabilityContractError(ValueError):
    """Raised by :func:`load_contract` for an unreadable or invalid contract."""

    def __init__(self, errors: Iterable[str]):
        self.errors = tuple(str(error) for error in errors)
        super().__init__("; ".join(self.errors))


def _finding(
    code: str,
    message: str,
    *,
    target: str | None = None,
    dimension: str | None = None,
    level: str = "error",
) -> Finding:
    """Build a stable finding in the shared validator vocabulary."""
    return Finding(
        check="capability-contract",
        level=level,
        message=message,
        code=code,
        target=target,
        dimension=dimension,
    )


def _contract_path(repo_root: Path) -> Path:
    return repo_root / "packages" / "core" / "capability-contract.json"


def _schema_path(repo_root: Path) -> Path:
    return repo_root / "schemas" / "capability-contract.schema.json"


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def load_contract(repo_root: Path) -> dict[str, Any]:
    """Load and schema-validate the comparative capability contract."""
    contract_path = _contract_path(repo_root)
    if not contract_path.is_file():
        raise CapabilityContractError([f"contract file is missing: {contract_path}"])
    try:
        contract = _read_json(contract_path)
    except (OSError, json.JSONDecodeError) as exc:
        raise CapabilityContractError([f"cannot read {contract_path}: {exc}"]) from exc
    schema_path = _schema_path(repo_root)
    if not schema_path.is_file():
        raise CapabilityContractError([f"schema file is missing: {schema_path}"])
    try:
        schema = _read_json(schema_path)
    except (OSError, json.JSONDecodeError) as exc:
        raise CapabilityContractError([f"cannot read {schema_path}: {exc}"]) from exc
    errors = schema_validate(contract, schema)
    if errors:
        raise CapabilityContractError(errors)
    return contract


def runtime_targets(repo_root: Path) -> list[str]:
    """Return runtime targets represented by instruction files, in stable order."""
    return target_names(repo_root, require_instructions=True)


def _schema_findings(repo_root: Path) -> tuple[Finding, ...]:
    try:
        contract = _read_json(_contract_path(repo_root))
    except FileNotFoundError:
        return (_finding("schema", "contract file is missing"),)
    except (OSError, json.JSONDecodeError) as exc:
        return (_finding("schema", f"cannot parse contract: {exc}"),)
    try:
        schema = _read_json(_schema_path(repo_root))
    except (OSError, json.JSONDecodeError, FileNotFoundError) as exc:
        return (_finding("schema", f"cannot parse contract schema: {exc}"),)
    return tuple(_finding("schema", error) for error in schema_validate(contract, schema))


def _path_error(
    raw_path: Any,
    repo_root: Path,
    *,
    target: str,
    dimension: str,
) -> tuple[Path | None, Finding | None]:
    if not isinstance(raw_path, str) or not raw_path:
        return None, _finding(
            "evidence-path",
            "DRIFT: evidence path must be a nonempty repo-relative string",
            target=target,
            dimension=dimension,
        )
    candidate = Path(raw_path)
    if candidate.is_absolute() or "\\" in raw_path or ".." in candidate.parts:
        return None, _finding(
            "evidence-path",
            f"DRIFT: unsafe evidence path {raw_path!r}; paths must stay repo-relative",
            target=target,
            dimension=dimension,
        )
    root = repo_root.resolve()
    resolved = (repo_root / candidate).resolve()
    try:
        resolved.relative_to(root)
    except ValueError:
        return None, _finding(
            "evidence-path",
            f"DRIFT: evidence path escapes repository: {raw_path}",
            target=target,
            dimension=dimension,
        )
    if not resolved.is_file():
        return None, _finding(
            "evidence-path",
            f"DRIFT: evidence file does not exist: {raw_path}",
            target=target,
            dimension=dimension,
        )
    return resolved, None


def _check_evidence(
    repo_root: Path,
    target: str,
    dimension: str,
    claim: Any,
) -> list[Finding]:
    if not isinstance(claim, dict):
        return []
    verdict = claim.get("verdict")
    evidence = claim.get("evidence")
    if verdict in SUPPORTED_EVIDENCE_VERDICTS and not evidence:
        return [
            _finding(
                "evidence-required",
                f"DRIFT: {verdict} claim requires nonempty evidence",
                target=target,
                dimension=dimension,
            )
        ]
    if evidence is None:
        return []
    if not isinstance(evidence, list):
        return [
            _finding(
                "evidence-path",
                "DRIFT: evidence must be an array",
                target=target,
                dimension=dimension,
            )
        ]

    findings: list[Finding] = []
    for item in evidence:
        if not isinstance(item, dict):
            findings.append(
                _finding(
                    "evidence-path",
                    "DRIFT: evidence entries must be objects",
                    target=target,
                    dimension=dimension,
                )
            )
            continue
        path, path_finding = _path_error(
            item.get("path"), repo_root, target=target, dimension=dimension
        )
        if path_finding is not None:
            findings.append(path_finding)
            continue
        tokens = item.get("contains")
        if not isinstance(tokens, list) or not tokens:
            findings.append(
                _finding(
                    "evidence-token",
                    "DRIFT: evidence contains must be a nonempty token list",
                    target=target,
                    dimension=dimension,
                )
            )
            continue
        try:
            content = path.read_text(encoding="utf-8") if path is not None else ""
        except (OSError, UnicodeDecodeError) as exc:
            findings.append(
                _finding(
                    "evidence-path",
                    f"DRIFT: cannot read evidence file {item.get('path')}: {exc}",
                    target=target,
                    dimension=dimension,
                )
            )
            continue
        for token in tokens:
            if not isinstance(token, str) or not token:
                findings.append(
                    _finding(
                        "evidence-token",
                        "DRIFT: evidence tokens must be nonempty strings",
                        target=target,
                        dimension=dimension,
                    )
                )
            elif token not in content:
                findings.append(
                    _finding(
                        "evidence-token",
                        f"DRIFT: evidence token {token!r} is absent from {item.get('path')}",
                        target=target,
                        dimension=dimension,
                    )
                )
    return findings


def _parity_findings(
    contract: dict[str, Any], expected_targets: list[str]
) -> list[Finding]:
    findings: list[Finding] = []
    dimensions = contract.get("dimensions", [])
    if dimensions != list(DIMENSIONS):
        missing = sorted(set(DIMENSIONS) - set(dimensions))
        extra = sorted(set(dimensions) - set(DIMENSIONS))
        findings.append(
            _finding(
                "dimension-parity",
                "dimension parity drift: "
                f"missing={missing}, extra={extra}, order={dimensions!r}",
            )
        )

    claims = contract.get("claims", {})
    contract_targets = sorted(claims) if isinstance(claims, dict) else []
    if contract_targets != expected_targets:
        findings.append(
            _finding(
                "runtime-target-parity",
                "runtime target parity drift: "
                f"missing={sorted(set(expected_targets) - set(contract_targets))}, "
                f"extra={sorted(set(contract_targets) - set(expected_targets))}",
            )
        )

    if not isinstance(claims, dict):
        return findings
    for target in sorted(set(expected_targets) | set(contract_targets)):
        target_claims = claims.get(target, {})
        actual = list(target_claims) if isinstance(target_claims, dict) else []
        expected = list(DIMENSIONS)
        if actual != expected:
            findings.append(
                _finding(
                    "dimension-parity",
                    f"{target} dimension parity drift: "
                    f"missing={sorted(set(expected) - set(actual))}, "
                    f"extra={sorted(set(actual) - set(expected))}",
                    target=target,
                )
            )
    return findings


def reconcile(
    repo_root: Path,
    *,
    targets: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Validate and reconcile static evidence into a deterministic report."""
    repo_root = Path(repo_root)
    expected_targets = runtime_targets(repo_root)
    schema_findings = list(_schema_findings(repo_root))
    findings: list[Finding] = schema_findings
    contract: dict[str, Any] = {}
    if not schema_findings:
        try:
            contract = load_contract(repo_root)
        except CapabilityContractError as exc:  # pragma: no cover - schema helper parity
            findings.extend(_finding("schema", error) for error in exc.errors)

    dimensions = list(contract.get("dimensions", DIMENSIONS))
    claims = contract.get("claims", {})
    if contract:
        findings.extend(_parity_findings(contract, expected_targets))
        if isinstance(claims, dict):
            for target in sorted(claims):
                target_claims = claims.get(target, {})
                if not isinstance(target_claims, dict):
                    continue
                for dimension in sorted(target_claims):
                    findings.extend(
                        _check_evidence(
                            repo_root, target, dimension, target_claims[dimension]
                        )
                    )

    selected = expected_targets
    if targets is not None:
        values = targets.split(",") if isinstance(targets, str) else targets
        requested = {str(target).strip() for target in values if str(target).strip()}
        selected = [target for target in expected_targets if target in requested]
        unknown = sorted(requested - set(expected_targets))
        if unknown:
            findings.append(
                _finding("target-filter", f"unknown runtime target(s): {', '.join(unknown)}")
            )

    selected_claims = {
        target: claims.get(target, {})
        for target in selected
        if isinstance(claims, dict)
    }
    return {
        "schemaVersion": contract.get("schemaVersion", 1),
        "mode": "offline",
        "targets": selected,
        "dimensions": dimensions,
        "claims": selected_claims,
        "findings": findings,
    }


def has_errors(report: dict[str, Any]) -> bool:
    """Return whether a report contains contract or evidence drift."""
    return bool(report.get("findings"))


def check(repo_root: Path) -> list[Finding]:
    """validate-harness 用: capability contract の違反を Finding で返す."""
    return list(reconcile(repo_root)["findings"])


__all__ = [
    "CapabilityContractError",
    "check",
    "DIMENSIONS",
    "SUPPORTED_EVIDENCE_VERDICTS",
    "has_errors",
    "load_contract",
    "reconcile",
    "runtime_targets",
]
